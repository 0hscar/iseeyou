from __future__ import annotations

import os
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from isee_network.metrics import CounterSample


SCHEMA_VERSION = 5


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
                version = 1
            if version == 1:
                connection.executescript(
                    """
                    BEGIN IMMEDIATE;

                    CREATE INDEX IF NOT EXISTS connectivity_samples_by_target
                        ON connectivity_samples (target_name, run_id);

                    PRAGMA user_version = 2;
                    COMMIT;
                    """
                )
                version = 2
            if version == 2:
                connection.executescript(
                    """
                    BEGIN IMMEDIATE;

                    CREATE TABLE IF NOT EXISTS interface_inventory (
                        run_id INTEGER NOT NULL REFERENCES collection_runs(id),
                        interface_name TEXT NOT NULL,
                        router_interface_id TEXT,
                        interface_type TEXT NOT NULL,
                        comment TEXT,
                        running INTEGER,
                        disabled INTEGER,
                        PRIMARY KEY (run_id, interface_name)
                    );

                    CREATE INDEX IF NOT EXISTS interface_inventory_by_run
                        ON interface_inventory (run_id, interface_name);

                    PRAGMA user_version = 3;
                    COMMIT;
                    """
                )
                version = 3
            if version == 3:
                connection.executescript(
                    """
                    BEGIN IMMEDIATE;

                    CREATE TABLE IF NOT EXISTS device_inventory_snapshot (
                        id INTEGER PRIMARY KEY CHECK (id = 1),
                        run_id INTEGER NOT NULL REFERENCES collection_runs(id),
                        sampled_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS connected_devices (
                        mac_address TEXT PRIMARY KEY,
                        interface_name TEXT NOT NULL,
                        bridge_name TEXT,
                        vlan_id INTEGER,
                        bridge_age TEXT,
                        host_name TEXT,
                        dhcp_server TEXT
                    );

                    CREATE TABLE IF NOT EXISTS connected_device_addresses (
                        mac_address TEXT NOT NULL REFERENCES connected_devices(mac_address)
                            ON DELETE CASCADE,
                        ip_address TEXT NOT NULL,
                        PRIMARY KEY (mac_address, ip_address)
                    );

                    PRAGMA user_version = 4;
                    COMMIT;
                    """
                )
                version = 4
            if version == 4:
                connection.executescript(
                    """
                    BEGIN IMMEDIATE;

                    CREATE INDEX IF NOT EXISTS collection_runs_by_completed_at
                        ON collection_runs (completed_at, id);

                    PRAGMA user_version = 5;
                    COMMIT;
                    """
                )

    def database_size_bytes(self) -> int:
        return sum(
            candidate.stat().st_size
            for candidate in (
                self.path,
                Path(f"{self.path}-wal"),
                Path(f"{self.path}-shm"),
            )
            if candidate.exists()
        )

    def monthly_storage_usage(self) -> dict[str, Any]:
        tables = {
            "runs": (
                "collection_runs AS t",
                "",
                (
                    "id",
                    "started_at",
                    "completed_at",
                    "router_sampled_at",
                    "router_status",
                    "router_error",
                    "uptime",
                    "uptime_seconds",
                    "cpu_load_percent",
                    "free_memory_bytes",
                    "total_memory_bytes",
                ),
            ),
            "interface_samples": (
                "interface_samples AS t",
                "JOIN collection_runs AS r ON r.id = t.run_id",
                (
                    "run_id",
                    "interface_name",
                    "router_interface_id",
                    "interface_type",
                    "running",
                    "rx_bytes",
                    "tx_bytes",
                    "rx_packets",
                    "tx_packets",
                    "rx_errors",
                    "tx_errors",
                    "rate_valid",
                    "rate_reason",
                    "rx_bits_per_second",
                    "tx_bits_per_second",
                ),
            ),
            "interface_inventory": (
                "interface_inventory AS t",
                "JOIN collection_runs AS r ON r.id = t.run_id",
                (
                    "run_id",
                    "interface_name",
                    "router_interface_id",
                    "interface_type",
                    "comment",
                    "running",
                    "disabled",
                ),
            ),
            "connectivity_samples": (
                "connectivity_samples AS t",
                "JOIN collection_runs AS r ON r.id = t.run_id",
                (
                    "run_id",
                    "target_name",
                    "target_host",
                    "target_port",
                    "probes_sent",
                    "probes_succeeded",
                    "probe_failure_percent",
                    "latency_ms",
                    "error",
                ),
            ),
        }
        months: dict[str, dict[str, int | str]] = {}
        with closing(self._connect()) as connection:
            for count_key, (table, join, columns) in tables.items():
                payload_terms = []
                for column in columns:
                    value = f't."{column}"'
                    payload_terms.append(
                        f"(CASE WHEN {value} IS NULL THEN 4 ELSE "
                        f"length(CAST({value} AS BLOB)) + "
                        f"CASE WHEN typeof({value}) = 'text' THEN 2 ELSE 0 END END)"
                    )
                json_key_overhead = sum(len(column) + 3 for column in columns)
                json_key_overhead += len(columns) + 1
                size_expression = f"{json_key_overhead} + " + " + ".join(payload_terms)
                month_expression = (
                    "substr(t.completed_at, 1, 7)"
                    if not join
                    else "substr(r.completed_at, 1, 7)"
                )
                rows = connection.execute(
                    f"""
                    SELECT {month_expression} AS month, COUNT(*) AS row_count,
                           SUM({size_expression}) AS payload_bytes
                    FROM {table}
                    {join}
                    GROUP BY month
                    """
                ).fetchall()
                for row in rows:
                    summary = months.setdefault(
                        row["month"],
                        {
                            "month": row["month"],
                            "runs": 0,
                            "interface_samples": 0,
                            "interface_inventory": 0,
                            "connectivity_samples": 0,
                            "estimated_payload_bytes": 0,
                        },
                    )
                    summary[count_key] = row["row_count"]
                    summary["estimated_payload_bytes"] += row["payload_bytes"] or 0

        return {
            "database_bytes": self.database_size_bytes(),
            "months": sorted(months.values(), key=lambda item: item["month"], reverse=True),
        }

    def iter_export_records(
        self,
        start: datetime,
        end_exclusive: datetime,
    ) -> Iterator[dict[str, Any]]:
        start_text = start.isoformat(timespec="milliseconds")
        end_text = end_exclusive.isoformat(timespec="milliseconds")
        with closing(self._connect()) as connection:
            yield {
                "record_type": "metadata",
                "format_version": 1,
                "schema_version": SCHEMA_VERSION,
                "start": start_text,
                "end_exclusive": end_text,
                "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            queries = (
                (
                    "collection_runs",
                    """
                    SELECT r.* FROM collection_runs AS r
                    WHERE r.completed_at >= ? AND r.completed_at < ?
                    ORDER BY r.id
                    """,
                ),
                (
                    "interface_samples",
                    """
                    SELECT s.* FROM interface_samples AS s
                    JOIN collection_runs AS r ON r.id = s.run_id
                    WHERE r.completed_at >= ? AND r.completed_at < ?
                    ORDER BY s.run_id, s.interface_name
                    """,
                ),
                (
                    "interface_inventory",
                    """
                    SELECT i.* FROM interface_inventory AS i
                    JOIN collection_runs AS r ON r.id = i.run_id
                    WHERE r.completed_at >= ? AND r.completed_at < ?
                    ORDER BY i.run_id, i.interface_name
                    """,
                ),
                (
                    "connectivity_samples",
                    """
                    SELECT s.* FROM connectivity_samples AS s
                    JOIN collection_runs AS r ON r.id = s.run_id
                    WHERE r.completed_at >= ? AND r.completed_at < ?
                    ORDER BY s.run_id, s.target_name
                    """,
                ),
            )
            for record_type, query in queries:
                cursor = connection.execute(query, (start_text, end_text))
                while rows := cursor.fetchmany(500):
                    for row in rows:
                        yield {"record_type": record_type, **dict(row)}

            snapshot = connection.execute(
                """
                SELECT snapshot.run_id, snapshot.sampled_at
                FROM device_inventory_snapshot AS snapshot
                JOIN collection_runs AS r ON r.id = snapshot.run_id
                WHERE snapshot.id = 1
                  AND r.completed_at >= ?
                  AND r.completed_at < ?
                """,
                (start_text, end_text),
            ).fetchone()
            if snapshot is not None:
                yield {
                    "record_type": "device_inventory_snapshot",
                    **dict(snapshot),
                }
                cursor = connection.execute(
                    """
                    SELECT device.mac_address, device.interface_name, device.bridge_name,
                           device.vlan_id, device.bridge_age, device.host_name,
                           device.dhcp_server, address.ip_address
                    FROM connected_devices AS device
                    LEFT JOIN connected_device_addresses AS address
                        ON address.mac_address = device.mac_address
                    ORDER BY device.mac_address, address.ip_address
                    """
                )
                while rows := cursor.fetchmany(500):
                    for row in rows:
                        yield {"record_type": "connected_device", **dict(row)}

    def delete_history_before(
        self,
        cutoff: datetime,
        *,
        protected_days: int = 30,
    ) -> dict[str, int]:
        if cutoff.tzinfo is None or cutoff.utcoffset() is None:
            raise ValueError("cutoff must include a timezone")
        if cutoff > datetime.now(timezone.utc) - timedelta(days=protected_days):
            raise ValueError(
                f"History newer than {protected_days} days is protected from deletion"
            )

        cutoff_text = cutoff.astimezone(timezone.utc).isoformat(timespec="seconds")
        database_bytes_before = self.database_size_bytes()
        deleted: dict[str, int] = {}
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                CREATE TEMP TABLE cleanup_candidates (
                    id INTEGER PRIMARY KEY
                )
                """
            )
            connection.execute(
                """
                INSERT INTO cleanup_candidates (id)
                SELECT id
                FROM collection_runs
                WHERE completed_at < ?
                  AND id != COALESCE(
                    (SELECT run_id FROM device_inventory_snapshot WHERE id = 1),
                    -1
                  )
                """,
                (cutoff_text,),
            )
            for table in (
                "interface_samples",
                "interface_inventory",
                "connectivity_samples",
            ):
                cursor = connection.execute(
                    f"""
                    DELETE FROM {table}
                    WHERE run_id IN (SELECT id FROM cleanup_candidates)
                    """
                )
                deleted[table] = cursor.rowcount
            cursor = connection.execute(
                """
                DELETE FROM collection_runs
                WHERE id IN (SELECT id FROM cleanup_candidates)
                """
            )
            deleted["collection_runs"] = cursor.rowcount
            connection.execute("DROP TABLE cleanup_candidates")

        if deleted["collection_runs"]:
            with closing(self._connect()) as connection:
                connection.execute("VACUUM")
        deleted["database_bytes_before"] = database_bytes_before
        deleted["database_bytes_after"] = self.database_size_bytes()
        return deleted

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

    def latest_collection_run(self) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                """
                SELECT id, completed_at, router_sampled_at, router_status, uptime,
                       cpu_load_percent, free_memory_bytes, total_memory_bytes
                FROM collection_runs
                ORDER BY id DESC
                LIMIT 1
                """
            ).fetchone()
        return dict(row) if row is not None else None

    def latest_interface_records(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT
                    inventory.interface_name,
                    inventory.router_interface_id,
                    inventory.interface_type,
                    inventory.comment,
                    inventory.running,
                    inventory.disabled,
                    inventory_run.router_sampled_at,
                    sample.rate_valid,
                    sample.rate_reason,
                    sample.rx_bits_per_second,
                    sample.tx_bits_per_second,
                    sample.rx_bytes,
                    sample.tx_bytes,
                    sample_run.router_sampled_at AS rates_sampled_at
                FROM interface_inventory AS inventory
                JOIN collection_runs AS inventory_run ON inventory_run.id = inventory.run_id
                LEFT JOIN interface_samples AS sample
                    ON sample.run_id = (
                        SELECT MAX(previous.run_id)
                        FROM interface_samples AS previous
                        WHERE previous.interface_name = inventory.interface_name
                          AND previous.router_interface_id IS inventory.router_interface_id
                    )
                   AND sample.interface_name = inventory.interface_name
                   AND sample.router_interface_id IS inventory.router_interface_id
                LEFT JOIN collection_runs AS sample_run ON sample_run.id = sample.run_id
                WHERE inventory.run_id = (
                    SELECT MAX(latest.run_id) FROM interface_inventory AS latest
                )
                ORDER BY inventory.interface_name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_connected_devices(self) -> dict[str, Any]:
        with closing(self._connect()) as connection, connection:
            snapshot = connection.execute(
                """
                SELECT sampled_at
                FROM device_inventory_snapshot
                WHERE id = 1
                """
            ).fetchone()
            rows = connection.execute(
                """
                SELECT device.mac_address, device.interface_name, device.bridge_name,
                       device.vlan_id, device.bridge_age, device.host_name,
                       device.dhcp_server, address.ip_address
                FROM connected_devices AS device
                LEFT JOIN connected_device_addresses AS address
                    ON address.mac_address = device.mac_address
                ORDER BY device.interface_name, device.mac_address, address.ip_address
                """
            ).fetchall()

        devices: dict[str, dict[str, Any]] = {}
        for row in rows:
            device = devices.setdefault(
                row["mac_address"],
                {
                    "mac_address": row["mac_address"],
                    "interface_name": row["interface_name"],
                    "bridge_name": row["bridge_name"],
                    "vlan_id": row["vlan_id"],
                    "bridge_age": row["bridge_age"],
                    "host_name": row["host_name"],
                    "dhcp_server": row["dhcp_server"],
                    "ip_addresses": [],
                },
            )
            if row["ip_address"] is not None:
                device["ip_addresses"].append(row["ip_address"])

        return {
            "sampled_at": snapshot["sampled_at"] if snapshot is not None else None,
            "devices": list(devices.values()),
        }

    def interface_history(
        self,
        interface_name: str,
        since: str,
        bucket_seconds: int,
    ) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT
                    MIN(r.router_sampled_at) AS sampled_at,
                    CAST(strftime('%s', r.router_sampled_at) AS INTEGER) / ?
                        AS bucket_number,
                    MAX(s.rate_valid) AS rate_valid,
                    AVG(CASE WHEN s.rate_valid = 1
                             THEN s.rx_bits_per_second END) AS rx_bits_per_second,
                    AVG(CASE WHEN s.rate_valid = 1
                             THEN s.tx_bits_per_second END) AS tx_bits_per_second
                FROM interface_samples AS s
                JOIN collection_runs AS r ON r.id = s.run_id
                WHERE s.interface_name = ?
                  AND r.router_sampled_at >= ?
                GROUP BY bucket_number
                ORDER BY bucket_number
                """,
                (bucket_seconds, interface_name, since),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_connectivity_records(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT c.*, r.completed_at AS sampled_at
                FROM connectivity_samples AS c
                JOIN collection_runs AS r ON r.id = c.run_id
                WHERE c.run_id = (
                    SELECT MAX(previous.run_id)
                    FROM connectivity_samples AS previous
                    WHERE previous.target_name = c.target_name
                )
                ORDER BY c.target_name
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def connectivity_history(
        self,
        target_name: str,
        since: str,
        bucket_seconds: int,
    ) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT
                    MIN(r.completed_at) AS sampled_at,
                    CAST(strftime('%s', r.completed_at) AS INTEGER) / ?
                        AS bucket_number,
                    AVG(c.latency_ms) AS latency_ms,
                    AVG(c.probe_failure_percent) AS probe_failure_percent
                FROM connectivity_samples AS c
                JOIN collection_runs AS r ON r.id = c.run_id
                WHERE c.target_name = ?
                  AND r.completed_at >= ?
                GROUP BY bucket_number
                ORDER BY bucket_number
                """,
                (bucket_seconds, target_name, since),
            ).fetchall()
        return [dict(row) for row in rows]

    def connectivity_samples_since(
        self,
        target_name: str,
        since: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT r.completed_at AS sampled_at, c.probes_sent,
                       c.probes_succeeded, c.probe_failure_percent
                FROM connectivity_samples AS c
                JOIN collection_runs AS r ON r.id = c.run_id
                WHERE c.target_name = ?
                  AND r.completed_at >= ?
                ORDER BY r.id
                LIMIT ?
                """,
                (target_name, since, limit),
            ).fetchall()
        return [dict(row) for row in rows]

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
        interface_inventory: list[dict[str, Any]] | None = None,
        connected_devices: list[dict[str, Any]] | None = None,
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
                INSERT INTO interface_inventory (
                    run_id, interface_name, router_interface_id, interface_type,
                    comment, running, disabled
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        run_id,
                        interface["interface_name"],
                        interface["router_interface_id"],
                        interface["interface_type"],
                        interface["comment"],
                        _optional_bool(interface["running"]),
                        _optional_bool(interface["disabled"]),
                    )
                    for interface in (interface_inventory or [])
                ],
            )
            if router_status == "ok":
                connection.execute("DELETE FROM connected_devices")
                connection.executemany(
                    """
                    INSERT INTO connected_devices (
                        mac_address, interface_name, bridge_name, vlan_id, bridge_age,
                        host_name, dhcp_server
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            device["mac_address"],
                            device["interface_name"],
                            device["bridge_name"],
                            device["vlan_id"],
                            device["age"],
                            device["host_name"],
                            device["dhcp_server"],
                        )
                        for device in (connected_devices or [])
                    ],
                )
                connection.executemany(
                    """
                    INSERT INTO connected_device_addresses (mac_address, ip_address)
                    VALUES (?, ?)
                    """,
                    [
                        (device["mac_address"], ip_address)
                        for device in (connected_devices or [])
                        for ip_address in device["ip_addresses"]
                    ],
                )
                connection.execute(
                    """
                    INSERT INTO device_inventory_snapshot (id, run_id, sampled_at)
                    VALUES (1, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        run_id = excluded.run_id,
                        sampled_at = excluded.sampled_at
                    """,
                    (run_id, router_sampled_at or completed_at),
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
