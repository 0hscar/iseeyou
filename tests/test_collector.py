import asyncio
import sqlite3
from pathlib import Path

from isee.config import CollectionSettings, ConnectivityTarget, RouterSettings
from isee_network import collector as collector_module
from isee_network.collector import CollectorHealth, NetworkCollector
from isee_network.connectivity import ProbeResult
from isee_network.routeros import (
    RouterConnectedDevice,
    RouterInterface,
    RouterSnapshot,
    RouterSystemInfo,
    RouterOSUnavailableError,
)
from isee_network.storage import SQLiteStore


def snapshot(
    rx_bytes: int,
    tx_bytes: int,
    uptime: str,
) -> RouterSnapshot:
    return RouterSnapshot(
        system=RouterSystemInfo(
            uptime=uptime,
            cpu_load_percent=12,
            free_memory_bytes=1024,
            total_memory_bytes=2048,
            version="7.22",
            board_name="hAP ax3",
        ),
        interfaces=(
            RouterInterface(
                router_id="*1",
                name="ether1",
                type="ether",
                running=True,
                disabled=False,
                comment="WAN",
                rx_bytes=rx_bytes,
                tx_bytes=tx_bytes,
                rx_packets=10,
                tx_packets=20,
                rx_errors=0,
                tx_errors=0,
            ),
            RouterInterface(
                router_id="*2",
                name="ether2",
                type="ether",
                running=False,
                disabled=False,
                comment="Office LAN",
                rx_bytes=500,
                tx_bytes=600,
                rx_packets=5,
                tx_packets=6,
                rx_errors=0,
                tx_errors=0,
            ),
        ),
        connected_devices=(
            RouterConnectedDevice(
                mac_address="AA:BB:CC:DD:EE:01",
                interface_name="ether2",
                bridge_name="bridge",
                vlan_id=None,
                age="00:00:03",
                ip_addresses=("192.0.2.50",),
                host_name="workstation",
                dhcp_server="lan-dhcp",
            ),
        ),
    )


def test_collector_persists_rates_and_tcp_probe_loss(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshots = [snapshot(1000, 2000, "1h0m0s"), snapshot(2000, 3000, "1h0m1s")]

    class FakeRouter:
        def __init__(self, *_args) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            pass

        async def discover(self) -> RouterSnapshot:
            return snapshots.pop(0)

    probe_number = 0

    async def fake_probe(_target, _timeout) -> ProbeResult:
        nonlocal probe_number
        probe_number += 1
        return (
            ProbeResult(True, 5.0, None)
            if probe_number % 2
            else ProbeResult(False, None, "timeout")
        )

    monkeypatch.setattr(collector_module, "RouterOSRestClient", FakeRouter)
    monkeypatch.setattr(collector_module, "tcp_probe", fake_probe)
    database_path = tmp_path / "network.sqlite3"
    settings = CollectionSettings(
        database_path=database_path,
        interfaces=["ether1"],
        probes_per_target=2,
        targets=[ConnectivityTarget(name="https", host="1.1.1.1", port=443)],
    )
    health = CollectorHealth()
    collector = NetworkCollector(
        RouterSettings(host="router.lan", username="monitor"),
        settings,
        "test-password",
        SQLiteStore(database_path),
        health,
    )

    async def collect_twice() -> None:
        await collector.collect_once()
        await collector.collect_once()

    asyncio.run(collect_twice())

    with sqlite3.connect(database_path) as connection:
        rates = connection.execute(
            """
            SELECT rate_valid, rate_reason, rx_bits_per_second
            FROM interface_samples ORDER BY run_id
            """
        ).fetchall()
        inventory = connection.execute(
            """
            SELECT interface_name, comment
            FROM interface_inventory
            WHERE run_id = (SELECT MAX(run_id) FROM interface_inventory)
            ORDER BY interface_name
            """
        ).fetchall()
        connectivity = connection.execute(
            """
            SELECT probes_sent, probes_succeeded, probe_failure_percent, latency_ms
            FROM connectivity_samples ORDER BY run_id
            """
        ).fetchall()
    devices = collector.store.latest_connected_devices()

    assert rates[0] == (0, "initial_sample", None)
    assert rates[1][0] == 1
    assert rates[1][1] is None
    assert rates[1][2] is not None and rates[1][2] > 0
    assert inventory == [("ether1", "WAN"), ("ether2", "Office LAN")]
    assert devices["devices"][0]["host_name"] == "workstation"
    assert devices["devices"][0]["interface_name"] == "ether2"
    assert connectivity == [(2, 1, 50.0, 5.0), (2, 1, 50.0, 5.0)]
    assert health.status == "ok"
    assert health.last_success_at is not None


def test_router_failure_is_stored_without_erasing_connectivity_samples(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class UnavailableRouter:
        def __init__(self, *_args) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            pass

        async def discover(self) -> RouterSnapshot:
            raise RouterOSUnavailableError("router request timed out")

    async def successful_probe(_target, _timeout) -> ProbeResult:
        return ProbeResult(True, 2.0, None)

    monkeypatch.setattr(collector_module, "RouterOSRestClient", UnavailableRouter)
    monkeypatch.setattr(collector_module, "tcp_probe", successful_probe)
    database_path = tmp_path / "network.sqlite3"
    collector = NetworkCollector(
        RouterSettings(host="router.lan", username="monitor"),
        CollectionSettings(
            database_path=database_path,
            probes_per_target=1,
            targets=[ConnectivityTarget(name="public", host="1.1.1.1", port=443)],
        ),
        "test-password",
        SQLiteStore(database_path),
    )

    asyncio.run(collector.collect_once())

    with sqlite3.connect(database_path) as connection:
        run = connection.execute(
            "SELECT router_status, router_error, uptime FROM collection_runs"
        ).fetchone()
        connectivity = connection.execute(
            "SELECT probes_succeeded, probe_failure_percent, latency_ms "
            "FROM connectivity_samples"
        ).fetchone()

    assert run == ("error", "router request timed out", None)
    assert connectivity == (1, 0.0, 2.0)
    assert collector.health.status == "error"
