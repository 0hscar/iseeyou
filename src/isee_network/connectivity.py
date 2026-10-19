from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass

from isee.config import ConnectivityTarget


@dataclass(frozen=True)
class ProbeResult:
    succeeded: bool
    latency_ms: float | None
    error: str | None


async def tcp_probe(
    target: ConnectivityTarget,
    timeout_seconds: float,
) -> ProbeResult:
    started = time.perf_counter()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(target.host, target.port),
            timeout=timeout_seconds,
        )
    except TimeoutError:
        return ProbeResult(False, None, "timeout")
    except socket.gaierror:
        return ProbeResult(False, None, "dns_resolution_failed")
    except OSError:
        return ProbeResult(False, None, "connection_failed")

    latency_ms = (time.perf_counter() - started) * 1000
    writer.close()
    try:
        await writer.wait_closed()
    except (ConnectionError, OSError):
        pass
    return ProbeResult(True, latency_ms, None)
