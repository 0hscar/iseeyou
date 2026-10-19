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


def test_sqlite_store_migrates_schema_version_one_to_two(tmp_path: Path) -> None:
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
    assert version == 2
    assert index == ("connectivity_samples_by_target",)
