from datetime import datetime, timedelta, timezone

import pytest

from isee_network.metrics import CounterSample, calculate_throughput, parse_router_uptime


def sample(
    rx_bytes: int | None,
    tx_bytes: int | None,
    *,
    seconds: int = 0,
    interface_id: str | None = "*1",
    uptime_seconds: int | None = 3600,
) -> CounterSample:
    return CounterSample(
        interface_id=interface_id,
        rx_bytes=rx_bytes,
        tx_bytes=tx_bytes,
        collected_at=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=seconds),
        router_uptime_seconds=uptime_seconds,
    )


def test_throughput_uses_counter_deltas_and_bits_per_second() -> None:
    result = calculate_throughput(sample(100, 200), sample(350, 500, seconds=2))

    assert result.valid is True
    assert result.rx_bits_per_second == 1000
    assert result.tx_bits_per_second == 1200


@pytest.mark.parametrize(
    ("previous", "current", "expected_reason"),
    [
        (None, sample(10, 20), "initial_sample"),
        (sample(10, 20), sample(11, None, seconds=1), "missing_counter"),
        (sample(100, 200), sample(99, 210, seconds=1), "counter_reset"),
        (
            sample(100, 200, uptime_seconds=3600),
            sample(110, 210, seconds=1, uptime_seconds=1),
            "router_rebooted",
        ),
        (
            sample(100, 200, interface_id="*1"),
            sample(110, 210, seconds=1, interface_id="*2"),
            "interface_changed",
        ),
        (sample(100, 200), sample(110, 210, seconds=61), "sample_gap"),
    ],
)
def test_invalid_throughput_is_not_returned_as_zero(
    previous: CounterSample | None,
    current: CounterSample,
    expected_reason: str,
) -> None:
    result = calculate_throughput(previous, current)

    assert result.valid is False
    assert result.reason == expected_reason
    assert result.rx_bits_per_second is None
    assert result.tx_bits_per_second is None


def test_throughput_handles_counter_wraparound_when_near_modulus() -> None:
    modulus = 2**32
    result = calculate_throughput(
        sample(modulus - 10, modulus - 20),
        sample(10, 20, seconds=2),
        counter_modulus=modulus,
    )

    assert result.valid is True
    assert result.rx_bits_per_second == 80
    assert result.tx_bits_per_second == 160


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2w3d4h5m6s", 1483506), ("1d", 86400), ("not-uptime", None)],
)
def test_parse_router_uptime(value: str, expected: int | None) -> None:
    assert parse_router_uptime(value) == expected
