from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

from isee_network.metrics import CounterSample


SCHEMA_VERSION = 1


class SQLiteStore:
    def __init__(self, database_path: Path) -> None:
        self.path = database_path.expanduser()
        if str(self.path) == ":memory:":
            raise ValueError("database_path must refer to a persistent file")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            descriptor = os.open(
                self.path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version > SCHEMA_VERSION:
                raise RuntimeError(
                    f"Database schema version {version} is newer than supported "
                    f"version {SCHEMA_VERSION}"
                )
            if version == 0:
                connection.executescript(
                    """
                    BEGIN IMMEDIATE;

                    CREATE TABLE IF NOT EXISTS collection_runs (
                        id INTEGER PRIMARY KEY,
                        started_at TEXT NOT NULL,
                        completed_at TEXT NOT NULL,
                        router_sampled_at TEXT,
                        router_status TEXT NOT NULL CHECK (router_status IN ('ok', 'error')),
                        router_error TEXT,
                        uptime TEXT,
                        uptime_seconds INTEGER,
                        cpu_load_percent INTEGER,
                        free_memory_bytes INTEGER,
                        total_memory_bytes INTEGER
                    );

                    CREATE TABLE IF NOT EXISTS interface_samples (
                        run_id INTEGER NOT NULL REFERENCES collection_runs(id),
                        interface_name TEXT NOT NULL,
                        router_interface_id TEXT,
                        interface_type TEXT NOT NULL,
                        running INTEGER,
                        rx_bytes INTEGER,
                        tx_bytes INTEGER,
                        rx_packets INTEGER,
                        tx_packets INTEGER,
                        rx_errors INTEGER,
                        tx_errors INTEGER,
                        rate_valid INTEGER NOT NULL CHECK (rate_valid IN (0, 1)),
                        rate_reason TEXT,
                        rx_bits_per_second REAL,
                        tx_bits_per_second REAL,
                        PRIMARY KEY (run_id, interface_name)
                    );

                    CREATE INDEX IF NOT EXISTS interface_samples_by_name
                        ON interface_samples (interface_name, run_id);

                    CREATE TABLE IF NOT EXISTS connectivity_samples (
                        run_id INTEGER NOT NULL REFERENCES collection_runs(id),
                        target_name TEXT NOT NULL,
                        target_host TEXT NOT NULL,
                        target_port INTEGER NOT NULL,
                        probes_sent INTEGER NOT NULL CHECK (probes_sent > 0),
                        probes_succeeded INTEGER NOT NULL CHECK (
                            probes_succeeded >= 0 AND probes_succeeded <= probes_sent
                        ),
                        probe_failure_percent REAL NOT NULL CHECK (
                            probe_failure_percent >= 0 AND probe_failure_percent <= 100
                        ),
                        latency_ms REAL,
                        error TEXT,
                        PRIMARY KEY (run_id, target_name)
                    );

                    PRAGMA user_version = 1;
                    COMMIT;
                    """
                )

    def latest_interface_samples(
        self,
        interface_names: list[str],
    ) -> dict[str, CounterSample]:
        if not interface_names:
            return {}
        placeholders = ",".join("?" for _ in interface_names)
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                f"""
                SELECT s.*, r.router_sampled_at, r.uptime_seconds
                FROM interface_samples AS s
                JOIN collection_runs AS r ON r.id = s.run_id
                WHERE s.interface_name IN ({placeholders})
                  AND s.rx_bytes IS NOT NULL
                  AND s.tx_bytes IS NOT NULL
                  AND r.router_status = 'ok'
                  AND r.id = (
                    SELECT MAX(previous.run_id)
                    FROM interface_samples AS previous
                    JOIN collection_runs AS previous_run ON previous_run.id = previous.run_id
                    WHERE previous.interface_name = s.interface_name
                      AND previous.rx_bytes IS NOT NULL
                      AND previous.tx_bytes IS NOT NULL
                      AND previous_run.router_status = 'ok'
                  )
                """,
                interface_names,
            ).fetchall()
        return {
            row["interface_name"]: CounterSample(
                interface_id=row["router_interface_id"],
                rx_bytes=row["rx_bytes"],
                tx_bytes=row["tx_bytes"],
                collected_at=_parse_timestamp(row["router_sampled_at"]),
                router_uptime_seconds=row["uptime_seconds"],
            )
            for row in rows
        }

    def save_cycle(
        self,
        *,
        started_at: str,
        completed_at: str,
        router_sampled_at: str | None,
        router_status: str,
        router_error: str | None,
        system: dict[str, Any] | None,
        interfaces: list[dict[str, Any]],
        connectivity: list[dict[str, Any]],
    ) -> None:
        uptime_seconds = system.get("uptime_seconds") if system is not None else None
        with closing(self._connect()) as connection, connection:
            cursor = connection.execute(
                """
                INSERT INTO collection_runs (
                    started_at, completed_at, router_sampled_at, router_status,
                    router_error, uptime, uptime_seconds, cpu_load_percent,
                    free_memory_bytes, total_memory_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    started_at,
                    completed_at,
                    router_sampled_at,
                    router_status,
                    router_error,
                    system.get("uptime") if system is not None else None,
                    uptime_seconds,
                    system.get("cpu_load_percent") if system is not None else None,
                    system.get("free_memory_bytes") if system is not None else None,
                    system.get("total_memory_bytes") if system is not None else None,
                ),
            )
            run_id = cursor.lastrowid
            connection.executemany(
                """
                INSERT INTO interface_samples (
                    run_id, interface_name, router_interface_id, interface_type, running,
                    rx_bytes, tx_bytes, rx_packets, tx_packets, rx_errors, tx_errors,
                    rate_valid, rate_reason, rx_bits_per_second, tx_bits_per_second
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        sample["interface_name"],
                        sample["router_interface_id"],
                        sample["interface_type"],
                        _optional_bool(sample["running"]),
                        sample["rx_bytes"],
                        sample["tx_bytes"],
                        sample["rx_packets"],
                        sample["tx_packets"],
                        sample["rx_errors"],
                        sample["tx_errors"],
                        int(sample["rate_valid"]),
                        sample["rate_reason"],
                        sample["rx_bits_per_second"],
                        sample["tx_bits_per_second"],
                    )
                    for sample in interfaces
                ],
            )
            connection.executemany(
                """
                INSERT INTO connectivity_samples (
                    run_id, target_name, target_host, target_port, probes_sent,
                    probes_succeeded, probe_failure_percent, latency_ms, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        sample["target_name"],
                        sample["target_host"],
                        sample["target_port"],
                        sample["probes_sent"],
                        sample["probes_succeeded"],
                        sample["probe_failure_percent"],
                        sample["latency_ms"],
                        sample["error"],
                    )
                    for sample in connectivity
                ],
            )


def _optional_bool(value: bool | None) -> int | None:
    return None if value is None else int(value)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)
