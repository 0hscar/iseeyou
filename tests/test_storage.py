from datetime import datetime, timedelta, timezone
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


def test_sqlite_store_migrates_schema_version_one_to_five(tmp_path: Path) -> None:
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
    assert version == 5
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
    with sqlite3.connect(database_path) as connection:
        completed_index = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'index' AND name = 'collection_runs_by_completed_at'
            """
        ).fetchone()
    assert completed_index == ("collection_runs_by_completed_at",)


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


def _save_storage_cycle(store: SQLiteStore, sampled_at: datetime) -> None:
    timestamp = sampled_at.isoformat(timespec="milliseconds")
    store.save_cycle(
        started_at=timestamp,
        completed_at=timestamp,
        router_sampled_at=timestamp,
        router_status="ok",
        router_error=None,
        system=None,
        interfaces=[
            {
                "interface_name": "wan",
                "router_interface_id": "id-1",
                "interface_type": "ether",
                "running": True,
                "rx_bytes": 100,
                "tx_bytes": 200,
                "rx_packets": 3,
                "tx_packets": 4,
                "rx_errors": 0,
                "tx_errors": 0,
                "rate_valid": True,
                "rate_reason": None,
                "rx_bits_per_second": 8.0,
                "tx_bits_per_second": 16.0,
            }
        ],
        connectivity=[
            {
                "target_name": "gateway",
                "target_host": "192.0.2.1",
                "target_port": 443,
                "probes_sent": 1,
                "probes_succeeded": 1,
                "probe_failure_percent": 0.0,
                "latency_ms": 1.0,
                "error": None,
            }
        ],
        interface_inventory=[
            {
                "interface_name": "wan",
                "router_interface_id": "id-1",
                "interface_type": "ether",
                "comment": "WAN",
                "running": True,
                "disabled": False,
            }
        ],
        connected_devices=[],
    )


def test_monthly_storage_usage_and_export_include_timestamped_rows(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "network.sqlite3")
    now = datetime.now(timezone.utc)
    old_sample = now - timedelta(days=45)
    recent_sample = now - timedelta(days=5)
    _save_storage_cycle(store, old_sample)
    _save_storage_cycle(store, recent_sample)

    usage = store.monthly_storage_usage()
    assert usage["database_bytes"] > 0
    months = {item["month"]: item for item in usage["months"]}
    old_month = months[old_sample.strftime("%Y-%m")]
    assert old_month["runs"] == 1
    assert old_month["interface_samples"] == 1
    assert old_month["interface_inventory"] == 1
    assert old_month["connectivity_samples"] == 1
    assert old_month["estimated_payload_bytes"] > 0

    records = list(
        store.iter_export_records(
            datetime.combine(old_sample.date(), datetime.min.time(), timezone.utc),
            datetime.combine(
                recent_sample.date() + timedelta(days=1),
                datetime.min.time(),
                timezone.utc,
            ),
        )
    )
    record_types = {record["record_type"] for record in records}
    assert {
        "metadata",
        "collection_runs",
        "interface_samples",
        "interface_inventory",
        "connectivity_samples",
        "device_inventory_snapshot",
    } <= record_types


def test_deletion_preserves_recent_history_and_blocks_recent_cutoffs(
    tmp_path: Path,
) -> None:
    store = SQLiteStore(tmp_path / "network.sqlite3")
    now = datetime.now(timezone.utc)
    old_sample = now - timedelta(days=45)
    recent_sample = now - timedelta(days=5)
    _save_storage_cycle(store, old_sample)
    _save_storage_cycle(store, recent_sample)

    result = store.delete_history_before(now - timedelta(days=30))
    assert result["collection_runs"] == 1
    assert result["interface_samples"] == 1
    assert result["interface_inventory"] == 1
    assert result["connectivity_samples"] == 1
    assert result["database_bytes_after"] > 0

    with sqlite3.connect(store.path) as connection:
        remaining = connection.execute(
            "SELECT completed_at FROM collection_runs"
        ).fetchall()
    assert len(remaining) == 1
    assert recent_sample.isoformat(timespec="milliseconds") == remaining[0][0]
    assert store.latest_connected_devices()["sampled_at"] == remaining[0][0]

    try:
        store.delete_history_before(now - timedelta(days=10))
    except ValueError as error:
        assert "30 days" in str(error)
    else:
        raise AssertionError("recent history deletion should be rejected")
