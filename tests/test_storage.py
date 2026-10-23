import sqlite3
import stat
from pathlib import Path

from isee_network.storage import SQLiteStore


def test_sqlite_store_persists_counters_and_invalid_rate_reason(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "monitoring.sqlite3"
    first_store = SQLiteStore(database_path)
    assert stat.S_IMODE(database_path.stat().st_mode) & 0o077 == 0
    first_store.save_cycle(
        started_at="2026-01-01T00:00:00+00:00",
        completed_at="2026-01-01T00:00:01+00:00",
        router_sampled_at="2026-01-01T00:00:00.500+00:00",
        router_status="ok",
        router_error=None,
        system={
            "uptime": "1h",
            "uptime_seconds": 3600,
            "cpu_load_percent": 10,
            "free_memory_bytes": 1024,
            "total_memory_bytes": 2048,
        },
        interfaces=[
            {
                "interface_name": "ether1",
                "router_interface_id": "*1",
                "interface_type": "ether",
                "running": True,
                "rx_bytes": 1234,
                "tx_bytes": 5678,
                "rx_packets": 12,
                "tx_packets": 34,
                "rx_errors": 0,
                "tx_errors": 1,
                "rate_valid": False,
                "rate_reason": "initial_sample",
                "rx_bits_per_second": None,
                "tx_bits_per_second": None,
            }
        ],
        connectivity=[],
        interface_inventory=[
            {
                "interface_name": "ether1",
                "router_interface_id": "*1",
                "interface_type": "ether",
                "comment": "WAN",
                "running": True,
                "disabled": False,
            }
        ],
    )

    reopened_store = SQLiteStore(database_path)
    latest = reopened_store.latest_interface_samples(["ether1"])["ether1"]
    with sqlite3.connect(database_path) as connection:
        row = connection.execute(
            """
            SELECT rx_bytes, tx_bytes, rate_valid, rate_reason
            FROM interface_samples
            """
        ).fetchone()

    assert row == (1234, 5678, 0, "initial_sample")
    assert latest.rx_bytes == 1234
    assert latest.tx_bytes == 5678
    assert latest.router_uptime_seconds == 3600
    assert latest.collected_at.isoformat() == "2026-01-01T00:00:00.500000+00:00"
    assert reopened_store.latest_interface_records()[0]["comment"] == "WAN"


def test_sqlite_store_migrates_schema_version_one_to_four(tmp_path: Path) -> None:
    database_path = tmp_path / "network.sqlite3"
    SQLiteStore(database_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("DROP INDEX connectivity_samples_by_target")
        connection.execute("PRAGMA user_version = 1")

    SQLiteStore(database_path)

    with sqlite3.connect(database_path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        index = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'index' AND name = 'connectivity_samples_by_target'
            """
        ).fetchone()
        inventory_table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'interface_inventory'
            """
        ).fetchone()
    assert version == 4
    assert index == ("connectivity_samples_by_target",)
    assert inventory_table == ("interface_inventory",)
    with sqlite3.connect(database_path) as connection:
        device_snapshot_table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'device_inventory_snapshot'
            """
        ).fetchone()
    assert device_snapshot_table == ("device_inventory_snapshot",)


def test_connected_device_snapshot_replaces_only_on_successful_router_poll(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "network.sqlite3")
    connected_device = {
        "mac_address": "AA:BB:CC:DD:EE:01",
        "interface_name": "lan-port",
        "bridge_name": "bridge",
        "vlan_id": 10,
        "age": "00:00:12",
        "host_name": "workstation",
        "dhcp_server": "lan-dhcp",
        "ip_addresses": ["192.0.2.50"],
    }

    def save_cycle(
        timestamp: str,
        *,
        router_status: str,
        devices: list[dict] | None = None,
    ) -> None:
        store.save_cycle(
            started_at=timestamp,
            completed_at=timestamp,
            router_sampled_at=timestamp if router_status == "ok" else None,
            router_status=router_status,
            router_error=None,
            system=None,
            interfaces=[],
            connectivity=[],
            connected_devices=devices,
        )

    save_cycle(
        "2026-01-01T00:00:00+00:00",
        router_status="ok",
        devices=[connected_device],
    )
    save_cycle("2026-01-01T00:00:10+00:00", router_status="error")

    last_successful_snapshot = store.latest_connected_devices()
    assert last_successful_snapshot["sampled_at"] == "2026-01-01T00:00:00+00:00"
    assert last_successful_snapshot["devices"][0]["host_name"] == "workstation"
    assert last_successful_snapshot["devices"][0]["ip_addresses"] == ["192.0.2.50"]

    save_cycle(
        "2026-01-01T00:00:20+00:00",
        router_status="ok",
        devices=[],
    )

    empty_successful_snapshot = store.latest_connected_devices()
    assert empty_successful_snapshot["sampled_at"] == "2026-01-01T00:00:20+00:00"
    assert empty_successful_snapshot["devices"] == []
