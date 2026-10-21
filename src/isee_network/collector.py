from __future__ import annotations

import asyncio
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from isee.config import CollectionSettings, ConnectivityTarget, RouterSettings
from isee_network.connectivity import ProbeResult, tcp_probe
from isee_network.metrics import (
    CounterSample,
    calculate_throughput,
    parse_router_uptime,
)
from isee_network.routeros import RouterOSRestClient, RouterOSError, RouterSnapshot
from isee_network.storage import SQLiteStore

LOGGER = logging.getLogger(__name__)


@dataclass
class CollectorHealth:
    status: str = "starting"
    last_attempt_at: str | None = None
    last_success_at: str | None = None
    last_error: str | None = None


class NetworkCollector:
    def __init__(
        self,
        router_settings: RouterSettings,
        collection_settings: CollectionSettings,
        password: str,
        store: SQLiteStore,
        health: CollectorHealth | None = None,
    ) -> None:
        if not password:
            raise ValueError("RouterOS password must not be empty")
        self.router_settings = router_settings
        self.collection_settings = collection_settings
        self.password = password
        self.store = store
        self.health = health or CollectorHealth()

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await self.collect_once()
            except sqlite3.Error as exc:
                self.health.status = "error"
                self.health.last_error = f"Database collection write failed: {exc}"
                LOGGER.exception("Unable to persist collection results")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.collection_settings.interval_seconds,
                )
            except TimeoutError:
                continue

    async def collect_once(self) -> None:
        started = datetime.now(timezone.utc)
        self.health.status = "collecting"
        self.health.last_attempt_at = _timestamp(started)

        router_snapshot: RouterSnapshot | None = None
        router_error: str | None = None
        router_sampled_at: datetime | None = None
        try:
            async with RouterOSRestClient(self.router_settings, self.password) as router:
                router_snapshot = await router.discover()
                router_sampled_at = datetime.now(timezone.utc)
        except RouterOSError as exc:
            router_error = str(exc)
            LOGGER.warning("RouterOS collection failed: %s", exc)

        connectivity_results = await self._probe_targets()
        completed = datetime.now(timezone.utc)
        interface_samples: list[dict[str, Any]] = []
        interface_inventory: list[dict[str, Any]] = []
        system: dict[str, Any] | None = None

        if router_snapshot is not None:
            assert router_sampled_at is not None
            uptime_seconds = parse_router_uptime(router_snapshot.system.uptime)
            system = {
                "uptime": router_snapshot.system.uptime,
                "uptime_seconds": uptime_seconds,
                "cpu_load_percent": router_snapshot.system.cpu_load_percent,
                "free_memory_bytes": router_snapshot.system.free_memory_bytes,
                "total_memory_bytes": router_snapshot.system.total_memory_bytes,
            }
            interface_inventory = [
                {
                    "interface_name": interface.name,
                    "router_interface_id": interface.router_id,
                    "interface_type": interface.type,
                    "comment": interface.comment,
                    "running": interface.running,
                    "disabled": interface.disabled,
                }
                for interface in router_snapshot.interfaces
            ]
            selected_interfaces = [
                interface
                for interface in router_snapshot.interfaces
                if not self.collection_settings.interfaces
                or interface.name in self.collection_settings.interfaces
            ]
            previous_samples = self.store.latest_interface_samples(
                [interface.name for interface in selected_interfaces]
            )
            for interface in selected_interfaces:
                previous = previous_samples.get(interface.name)
                current_counter = CounterSample(
                    interface_id=interface.router_id,
                    rx_bytes=interface.rx_bytes,
                    tx_bytes=interface.tx_bytes,
                    collected_at=router_sampled_at,
                    router_uptime_seconds=uptime_seconds,
                )
                throughput = calculate_throughput(
                    previous,
                    current_counter,
                    maximum_gap_seconds=self.collection_settings.interval_seconds * 5,
                )
                interface_samples.append(
                    {
                        "interface_name": interface.name,
                        "router_interface_id": interface.router_id,
                        "interface_type": interface.type,
                        "running": interface.running,
                        "rx_bytes": interface.rx_bytes,
                        "tx_bytes": interface.tx_bytes,
                        "rx_packets": interface.rx_packets,
                        "tx_packets": interface.tx_packets,
                        "rx_errors": interface.rx_errors,
                        "tx_errors": interface.tx_errors,
                        "rate_valid": throughput.valid,
                        "rate_reason": throughput.reason,
                        "rx_bits_per_second": throughput.rx_bits_per_second,
                        "tx_bits_per_second": throughput.tx_bits_per_second,
                    }
                )

        connectivity_samples = [
            self._summarize_probes(target, results)
            for target, results in connectivity_results
        ]
        router_status = "ok" if router_snapshot is not None else "error"
        self.store.save_cycle(
            started_at=_timestamp(started),
            completed_at=_timestamp(completed),
            router_sampled_at=(
                _timestamp(router_sampled_at) if router_sampled_at is not None else None
            ),
            router_status=router_status,
            router_error=router_error,
            system=system,
            interfaces=interface_samples,
            interface_inventory=interface_inventory,
            connectivity=connectivity_samples,
        )

        if router_snapshot is None:
            self.health.status = "error"
            self.health.last_error = router_error
        else:
            self.health.status = "ok"
            self.health.last_success_at = _timestamp(completed)
            self.health.last_error = None

    async def _probe_targets(self) -> list[tuple[ConnectivityTarget, list[ProbeResult]]]:
        async def probe_target(
            target: ConnectivityTarget,
        ) -> tuple[ConnectivityTarget, list[ProbeResult]]:
            results = []
            for _ in range(self.collection_settings.probes_per_target):
                results.append(
                    await tcp_probe(
                        target,
                        self.collection_settings.probe_timeout_seconds,
                    )
                )
            return target, results

        return list(
            await asyncio.gather(
                *(probe_target(target) for target in self.collection_settings.targets)
            )
        )

    @staticmethod
    def _summarize_probes(
        target: ConnectivityTarget,
        results: list[ProbeResult],
    ) -> dict[str, Any]:
        succeeded = [result for result in results if result.succeeded]
        errors = sorted({result.error for result in results if result.error})
        return {
            "target_name": target.name,
            "target_host": target.host,
            "target_port": target.port,
            "probes_sent": len(results),
            "probes_succeeded": len(succeeded),
            "probe_failure_percent": (
                100 * (len(results) - len(succeeded)) / len(results)
            ),
            "latency_ms": (
                sum(result.latency_ms or 0 for result in succeeded) / len(succeeded)
                if succeeded
                else None
            ),
            "error": ",".join(errors) if errors else None,
        }


def _timestamp(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")
