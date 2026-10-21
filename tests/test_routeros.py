import asyncio
import base64
import ssl

import httpx
import pytest

from isee.config import RouterSettings
from isee_network.routeros import (
    RouterOSAuthenticationError,
    RouterOSPermissionError,
    RouterOSRequestError,
    RouterOSRestClient,
    RouterOSResponseError,
    RouterOSUnavailableError,
)


SYSTEM_RESOURCE = {
    "uptime": "2d3h4m",
    "cpu-load": "12",
    "free-memory": "1024",
    "total-memory": "4096",
    "version": "7.22",
    "board-name": "hAP ax3",
}
INTERFACES = [
    {
        ".id": "*1",
        "name": "ether1",
        "type": "ether",
        "comment": "WAN",
        "running": "true",
        "disabled": "false",
        "rx-byte": "1000",
        "tx-byte": "2000",
        "rx-packet": "10",
        "tx-packet": "20",
        "rx-error": "0",
        "tx-error": "1",
    },
    {
        ".id": "*2",
        "name": "bridge",
        "type": "bridge",
        "comment": "LAN",
        "running": "true",
        "disabled": "false",
        "rx-byte": "3000",
        "tx-byte": "4000",
        "rx-packet": "30",
        "tx-packet": "40",
        "rx-error": "0",
        "tx-error": "0",
    },
]


def router_settings() -> RouterSettings:
    return RouterSettings(host="router.lan", username="isee-monitor")


def test_discover_reads_system_and_interface_data_using_get_only() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.scheme == "https"
        assert request.headers["authorization"] == "Basic " + base64.b64encode(
            b"isee-monitor:test-password"
        ).decode("ascii")
        if request.url.path == "/rest/system/resource":
            assert request.url.params[".proplist"] == (
                "uptime,cpu-load,free-memory,total-memory,version,board-name"
            )
            return httpx.Response(200, json=SYSTEM_RESOURCE)
        if request.url.path == "/rest/interface":
            assert request.url.params[".proplist"] == (
                ".id,name,type,comment,running,disabled,rx-byte,tx-byte,rx-packet,tx-packet,"
                "rx-error,tx-error"
            )
            return httpx.Response(200, json=INTERFACES)
        return httpx.Response(404)

    async def discover():
        async with RouterOSRestClient(
            router_settings(),
            "test-password",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.discover()

    snapshot = asyncio.run(discover())

    assert snapshot.system.uptime == "2d3h4m"
    assert snapshot.system.cpu_load_percent == 12
    assert snapshot.system.free_memory_bytes == 1024
    assert snapshot.system.total_memory_bytes == 4096
    assert snapshot.system.version == "7.22"
    assert snapshot.system.board_name == "hAP ax3"
    assert [interface.name for interface in snapshot.interfaces] == ["ether1", "bridge"]
    assert snapshot.interfaces[0].running is True
    assert snapshot.interfaces[0].disabled is False
    assert snapshot.interfaces[0].comment == "WAN"
    assert snapshot.interfaces[0].rx_bytes == 1000
    assert snapshot.interfaces[0].tx_bytes == 2000
    assert snapshot.interfaces[0].rx_errors == 0
    assert [request.method for request in requests] == ["GET", "GET"]


def test_tls_certificate_and_hostname_verification_are_enabled() -> None:
    context = RouterOSRestClient._ssl_context(router_settings())

    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [
        (401, RouterOSAuthenticationError),
        (403, RouterOSPermissionError),
    ],
)
def test_discovery_surfaces_authentication_and_permission_errors(
    status_code: int,
    error_type: type[Exception],
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"message": "router response"})

    async def discover():
        async with RouterOSRestClient(
            router_settings(),
            "test-password",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.discover()

    with pytest.raises(error_type):
        asyncio.run(discover())


def test_discovery_surfaces_network_timeouts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("connection timed out", request=request)

    async def discover():
        async with RouterOSRestClient(
            router_settings(),
            "test-password",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.discover()

    with pytest.raises(RouterOSUnavailableError, match="timed out"):
        asyncio.run(discover())


def test_discovery_surfaces_underlying_connection_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        connection_error = httpx.ConnectError("connection failed", request=request)
        connection_error.__cause__ = ssl.SSLCertVerificationError(
            1,
            "certificate verify failed: IP address mismatch",
        )
        raise connection_error

    async def discover():
        async with RouterOSRestClient(
            router_settings(),
            "test-password",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.discover()

    with pytest.raises(
        RouterOSUnavailableError,
        match=r"SSLCertVerificationError: .*IP address mismatch",
    ):
        asyncio.run(discover())


def test_discovery_includes_failed_endpoint_and_router_error_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/system/resource":
            return httpx.Response(200, json=[SYSTEM_RESOURCE])
        return httpx.Response(
            500,
            json={"detail": "std failure: not allowed (9)", "message": "Internal Server Error"},
        )

    async def discover():
        async with RouterOSRestClient(
            router_settings(),
            "test-password",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.discover()

    with pytest.raises(
        RouterOSRequestError,
        match=r"GET /interface failed with HTTP 500: std failure: not allowed \(9\)",
    ):
        asyncio.run(discover())


def test_discovery_rejects_invalid_router_metrics() -> None:
    invalid_resource = {**SYSTEM_RESOURCE, "cpu-load": "unknown"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/system/resource":
            return httpx.Response(200, json=[invalid_resource])
        return httpx.Response(200, json=INTERFACES)

    async def discover():
        async with RouterOSRestClient(
            router_settings(),
            "test-password",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.discover()

    with pytest.raises(RouterOSResponseError, match="invalid cpu-load"):
        asyncio.run(discover())


def test_discovery_rejects_empty_interface_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/rest/system/resource":
            return httpx.Response(200, json=[SYSTEM_RESOURCE])
        return httpx.Response(200, json=[])

    async def discover():
        async with RouterOSRestClient(
            router_settings(),
            "test-password",
            transport=httpx.MockTransport(handler),
        ) as client:
            return await client.discover()

    with pytest.raises(RouterOSResponseError, match="no interfaces"):
        asyncio.run(discover())


def test_interface_counter_fields_can_be_missing() -> None:
    interface = RouterOSRestClient._parse_interface(
        {".id": "*1", "name": "ether1", "type": "ether"}
    )

    assert interface.rx_bytes is None
    assert interface.tx_bytes is None
    assert interface.rx_packets is None
    assert interface.comment is None


def test_interface_counter_fields_reject_invalid_values() -> None:
    with pytest.raises(RouterOSResponseError, match="invalid rx-byte"):
        RouterOSRestClient._parse_interface(
            {
                ".id": "*1",
                "name": "ether1",
                "type": "ether",
                "rx-byte": "not-a-number",
            }
        )
