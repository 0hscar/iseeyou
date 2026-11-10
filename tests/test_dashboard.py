import asyncio
import gzip
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from isee.app import create_app
from isee.config import Settings


def _save_sample(
    store,
    completed_at: datetime,
    *,
    probes_succeeded: int,
) -> None:
    timestamp = completed_at.isoformat(timespec="milliseconds")
    store.save_cycle(
        started_at=(completed_at - timedelta(seconds=1)).isoformat(timespec="milliseconds"),
        completed_at=timestamp,
        router_sampled_at=timestamp,
        router_status="ok",
        router_error=None,
        system={
            "uptime": "3d",
            "uptime_seconds": 259200,
            "cpu_load_percent": 17,
            "free_memory_bytes": 6_000,
            "total_memory_bytes": 10_000,
        },
        interfaces=[
            {
                "interface_name": "ether1",
                "router_interface_id": "*1",
                "interface_type": "ether",
                "running": True,
                "rx_bytes": 2_000_000,
                "tx_bytes": 1_000_000,
                "rx_packets": 100,
                "tx_packets": 80,
                "rx_errors": 0,
                "tx_errors": 0,
                "rate_valid": True,
                "rate_reason": None,
                "rx_bits_per_second": 1_500_000.0,
                "tx_bits_per_second": 250_000.0,
            }
        ],
        interface_inventory=[
            {
                "interface_name": "ether1",
                "router_interface_id": "*1",
                "interface_type": "ether",
                "comment": "WAN",
                "running": True,
                "disabled": False,
            },
            {
                "interface_name": "ether2",
                "router_interface_id": "*2",
                "interface_type": "ether",
                "comment": "Office LAN",
                "running": False,
                "disabled": False,
            },
        ],
        connected_devices=[
            {
                "mac_address": "AA:BB:CC:DD:EE:01",
                "interface_name": "lan-port",
                "bridge_name": "bridge",
                "vlan_id": 10,
                "age": "00:00:12",
                "ip_addresses": ["192.0.2.50"],
                "host_name": "workstation",
                "dhcp_server": "lan-dhcp",
            }
        ],
        connectivity=[
            {
                "target_name": "gateway",
                "target_host": "192.0.2.1",
                "target_port": 443,
                "probes_sent": 3,
                "probes_succeeded": probes_succeeded,
                "probe_failure_percent": (3 - probes_succeeded) / 3 * 100,
                "latency_ms": 12.5 if probes_succeeded else None,
                "error": None if probes_succeeded else "connection refused",
            }
        ],
    )


def test_dashboard_pages_and_local_assets_are_served(tmp_path: Path) -> None:
    application = create_app(
        Settings(collection={"database_path": tmp_path / "network.sqlite3"})
    )

    async def request_pages() -> list[httpx.Response]:
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                return await asyncio.gather(
                    client.get("/"),
                    client.get("/interfaces"),
                    client.get("/connectivity"),
                    client.get("/devices"),
                    client.get("/storage"),
                    client.get("/static/app.css"),
                    client.get("/static/storage.js"),
                    client.get("/static/vendor/uplot/uPlot.iife.min.js"),
                )

    responses = asyncio.run(request_pages())

    assert all(response.status_code == 200 for response in responses)
    assert "Overview" in responses[0].text
    assert "Interfaces" in responses[1].text
    assert "Comment" in responses[1].text
    assert "Connectivity" in responses[2].text
    assert "Connected devices" in responses[3].text
    assert "Storage" in responses[4].text
    assert "--page:" in responses[5].text
    assert "loadStorage" in responses[6].text
    assert len(responses[7].content) > 10_000


def test_dashboard_api_returns_samples_and_derived_outage_history(
    tmp_path: Path,
) -> None:
    application = create_app(
        Settings(collection={"database_path": tmp_path / "network.sqlite3"})
    )
    now = datetime.now(timezone.utc)

    async def request_dashboard() -> dict[str, httpx.Response]:
        async with application.router.lifespan_context(application):
            _save_sample(
                application.state.store,
                now - timedelta(seconds=20),
                probes_succeeded=0,
            )
            _save_sample(
                application.state.store,
                now - timedelta(seconds=10),
                probes_succeeded=3,
            )
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                responses = await asyncio.gather(
                    client.get("/api/network/overview"),
                    client.get("/api/network/devices"),
                    client.get("/api/network/interfaces/history?name=ether1&hours=24"),
                    client.get("/api/network/connectivity/history?name=gateway&hours=24"),
                    client.get("/api/network/connectivity/outages?name=gateway&hours=24"),
                    client.get("/api/network/interfaces/history?name=ether1&hours=169"),
                )
                return dict(
                    zip(
                        (
                            "overview",
                            "devices",
                            "interfaces",
                            "connectivity",
                            "outages",
                            "invalid_range",
                        ),
                        responses,
                        strict=True,
                    )
                )

    responses = asyncio.run(request_dashboard())
    overview = responses["overview"].json()
    devices = responses["devices"].json()

    assert responses["overview"].status_code == 200
    assert overview["router"]["status"] == "available"
    assert [item["name"] for item in overview["interfaces"]] == ["ether1", "ether2"]
    assert overview["interfaces"][0]["comment"] == "WAN"
    assert overview["interfaces"][0]["monitored"] is True
    assert overview["interfaces"][0]["rx_bits_per_second"] == 1_500_000.0
    assert overview["interfaces"][1]["comment"] == "Office LAN"
    assert overview["interfaces"][1]["monitored"] is False
    assert overview["interfaces"][1]["rx_bytes"] is None
    assert overview["connectivity"][0]["status"] == "reachable"
    assert len(overview["recent_outages"]) == 1
    assert overview["recent_outages"][0]["ongoing"] is False
    assert devices["status"] == "fresh"
    assert devices["devices"][0]["host_name"] == "workstation"
    assert devices["devices"][0]["ip_addresses"] == ["192.0.2.50"]
    assert responses["interfaces"].json()["points"][0]["rate_valid"] is True
    assert any(
        point["latency_ms"] == 12.5
        for point in responses["connectivity"].json()["points"]
    )
    outage_history = responses["outages"].json()
    assert len(outage_history) == 1
    assert outage_history[0]["ongoing"] is False
    assert responses["invalid_range"].status_code == 422


def test_dashboard_empty_state_does_not_invent_measurements(tmp_path: Path) -> None:
    application = create_app(
        Settings(collection={"database_path": tmp_path / "network.sqlite3"})
    )

    async def request_empty() -> tuple[httpx.Response, httpx.Response]:
        async with application.router.lifespan_context(application):
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                return tuple(
                    await asyncio.gather(
                        client.get("/api/network/overview"),
                        client.get("/api/network/devices"),
                    )
                )

    response, devices_response = asyncio.run(request_empty())
    payload = response.json()

    assert response.status_code == 200
    assert payload["router"]["status"] == "unknown"
    assert payload["router"]["cpu_load_percent"] is None
    assert payload["interfaces"] == []
    assert payload["connectivity"] == []
    assert devices_response.json() == {
        "status": "unknown",
        "sampled_at": None,
        "devices": [],
    }


def test_storage_dashboard_exports_and_protects_recent_history(tmp_path: Path) -> None:
    application = create_app(
        Settings(collection={"database_path": tmp_path / "network.sqlite3"})
    )
    now = datetime.now(timezone.utc)
    old_sample = now - timedelta(days=45)
    recent_sample = now - timedelta(days=5)

    async def request_storage():
        async with application.router.lifespan_context(application):
            _save_sample(application.state.store, old_sample, probes_succeeded=3)
            _save_sample(application.state.store, recent_sample, probes_succeeded=3)
            transport = httpx.ASGITransport(app=application)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://test",
            ) as client:
                page = await client.get("/storage")
                usage = await client.get("/api/storage/usage")
                export = await client.get(
                    "/api/storage/export",
                    params={
                        "from": old_sample.date().isoformat(),
                        "through": recent_sample.date().isoformat(),
                    },
                )
                reversed_export = await client.get(
                    "/api/storage/export",
                    params={
                        "from": now.date().isoformat(),
                        "through": old_sample.date().isoformat(),
                    },
                )
                protected_delete = await client.post(
                    "/api/storage/delete",
                    json={
                        "before": (now - timedelta(days=10)).date().isoformat(),
                        "confirmation": "DELETE",
                    },
                )
                delete = await client.post(
                    "/api/storage/delete",
                    json={
                        "before": (now - timedelta(days=30)).date().isoformat(),
                        "confirmation": "DELETE",
                    },
                )
            return page, usage, export, reversed_export, protected_delete, delete

    page, usage_response, export_response, reversed_export, protected_delete, delete = (
        asyncio.run(request_storage())
    )
    usage = usage_response.json()
    records = [
        json.loads(line)
        for line in gzip.decompress(export_response.content).splitlines()
    ]

    assert page.status_code == 200
    assert "Delete old history" in page.text
    assert usage_response.status_code == 200
    assert usage["database_bytes"] > 0
    assert sum(month["runs"] for month in usage["months"]) == 2
    assert export_response.status_code == 200
    assert export_response.headers["content-type"] == "application/gzip"
    assert any(record["record_type"] == "interface_samples" for record in records)
    assert reversed_export.status_code == 422
    assert protected_delete.status_code == 400
    assert delete.status_code == 200
    assert delete.json()["deleted_runs"] == 1
