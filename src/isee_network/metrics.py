from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class CounterSample:
    interface_id: str | None
    rx_bytes: int | None
    tx_bytes: int | None
    collected_at: datetime
    router_uptime_seconds: int | None = None


@dataclass(frozen=True)
class Throughput:
    valid: bool
    reason: str | None
    rx_bits_per_second: float | None
    tx_bits_per_second: float | None


_UPTIME_TOKEN = re.compile(r"(\d+)([wdhms])")
_UPTIME_SECONDS = {"w": 604800, "d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_router_uptime(value: str) -> int | None:
    tokens = list(_UPTIME_TOKEN.finditer(value))
    if not tokens or "".join(token.group(0) for token in tokens) != value:
        return None
    return sum(int(token.group(1)) * _UPTIME_SECONDS[token.group(2)] for token in tokens)


def calculate_throughput(
    previous: CounterSample | None,
    current: CounterSample,
    *,
    counter_modulus: int = 2**64,
    maximum_gap_seconds: float = 60.0,
) -> Throughput:
    if current.rx_bytes is None or current.tx_bytes is None:
        return _invalid("missing_counter")
    if previous is None:
        return _invalid("initial_sample")
    if previous.rx_bytes is None or previous.tx_bytes is None:
        return _invalid("missing_counter")
    if previous.interface_id != current.interface_id:
        return _invalid("interface_changed")
    if (
        previous.router_uptime_seconds is not None
        and current.router_uptime_seconds is not None
        and current.router_uptime_seconds < previous.router_uptime_seconds
    ):
        return _invalid("router_rebooted")

    elapsed = (current.collected_at - previous.collected_at).total_seconds()
    if elapsed <= 0:
        return _invalid("non_positive_elapsed")
    if elapsed > maximum_gap_seconds:
        return _invalid("sample_gap")

    rx_delta = _counter_delta(previous.rx_bytes, current.rx_bytes, counter_modulus)
    tx_delta = _counter_delta(previous.tx_bytes, current.tx_bytes, counter_modulus)
    if rx_delta is None or tx_delta is None:
        return _invalid("counter_reset")

    return Throughput(
        valid=True,
        reason=None,
        rx_bits_per_second=rx_delta * 8 / elapsed,
        tx_bits_per_second=tx_delta * 8 / elapsed,
    )


def _counter_delta(previous: int, current: int, modulus: int) -> int | None:
    if previous < 0 or current < 0 or modulus <= 0:
        return None
    if current >= previous:
        return current - previous
    if previous >= modulus * 0.9 and current <= modulus * 0.1:
        return modulus - previous + current
    return None


def _invalid(reason: str) -> Throughput:
    return Throughput(False, reason, None, None)
