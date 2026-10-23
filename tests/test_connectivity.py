import asyncio
import socket

from isee.config import ConnectivityTarget
from isee_network import connectivity


class FakeWriter:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def test_tcp_probe_reports_connection_latency_and_closes_writer(monkeypatch) -> None:
    writer = FakeWriter()

    async def open_connection(_host: str, _port: int):
        return object(), writer

    monkeypatch.setattr(connectivity.asyncio, "open_connection", open_connection)
    target = ConnectivityTarget(name="gateway", host="192.0.2.1", port=443)

    result = asyncio.run(connectivity.tcp_probe(target, 1))

    assert result.succeeded is True
    assert result.latency_ms is not None
    assert result.error is None
    assert writer.closed is True


def test_tcp_probe_reports_timeout_without_latency(monkeypatch) -> None:
    async def open_connection(_host: str, _port: int):
        raise TimeoutError

    monkeypatch.setattr(connectivity.asyncio, "open_connection", open_connection)
    target = ConnectivityTarget(name="gateway", host="192.0.2.1", port=443)

    result = asyncio.run(connectivity.tcp_probe(target, 0.01))

    assert result.succeeded is False
    assert result.latency_ms is None
    assert result.error == "timeout"


def test_tcp_probe_distinguishes_dns_resolution_failure(monkeypatch) -> None:
    async def open_connection(_host: str, _port: int):
        raise socket.gaierror("name resolution failed")

    monkeypatch.setattr(connectivity.asyncio, "open_connection", open_connection)
    target = ConnectivityTarget(name="dns", host="missing.invalid", port=443)

    result = asyncio.run(connectivity.tcp_probe(target, 1))

    assert result.succeeded is False
    assert result.latency_ms is None
    assert result.error == "dns_resolution_failed"
