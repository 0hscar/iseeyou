from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Any

import httpx

from isee.config import RouterSettings


class RouterOSError(RuntimeError):
    """Base error for RouterOS discovery failures."""


class RouterOSAuthenticationError(RouterOSError):
    """RouterOS rejected the configured credentials."""


class RouterOSPermissionError(RouterOSError):
    """The RouterOS account cannot read the requested resources."""


class RouterOSUnavailableError(RouterOSError):
    """RouterOS could not be reached securely within the configured timeout."""


class RouterOSResponseError(RouterOSError):
    """RouterOS returned a response that does not match the expected schema."""


class RouterOSRequestError(RouterOSError):
    """RouterOS rejected a read request."""


@dataclass(frozen=True)
class RouterSystemInfo:
    uptime: str
    cpu_load_percent: int
    free_memory_bytes: int
    total_memory_bytes: int
    version: str | None
    board_name: str | None


@dataclass(frozen=True)
class RouterInterface:
    router_id: str | None
    name: str
    type: str
    running: bool | None
    disabled: bool | None


@dataclass(frozen=True)
class RouterSnapshot:
    system: RouterSystemInfo
    interfaces: tuple[RouterInterface, ...]


class RouterOSRestClient:
    """Read-only RouterOS REST client; requests are restricted to GET."""

    def __init__(
        self,
        settings: RouterSettings,
        password: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not password:
            raise ValueError("RouterOS password must not be empty")

        host = (
            f"[{settings.host}]"
            if ":" in settings.host and not settings.host.startswith("[")
            else settings.host
        )
        self._http = httpx.AsyncClient(
            base_url=f"https://{host}:{settings.port}/rest/",
            auth=(settings.username, password),
            verify=self._ssl_context(settings),
            timeout=httpx.Timeout(settings.timeout_seconds),
            transport=transport,
            trust_env=False,
        )

    @staticmethod
    def _ssl_context(settings: RouterSettings) -> ssl.SSLContext:
        ca_file = str(settings.ca_file) if settings.ca_file is not None else None
        return ssl.create_default_context(cafile=ca_file)

    async def __aenter__(self) -> RouterOSRestClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self._http.aclose()

    async def discover(self) -> RouterSnapshot:
        system_rows = await self._get_records(
            "system/resource",
            ("uptime", "cpu-load", "free-memory", "total-memory", "version", "board-name"),
        )
        if len(system_rows) != 1:
            raise RouterOSResponseError("RouterOS returned an unexpected system resource count")

        interface_rows = await self._get_records(
            "interface",
            (".id", "name", "type", "running", "disabled"),
        )
        if not interface_rows:
            raise RouterOSResponseError("RouterOS returned no interfaces")
        return RouterSnapshot(
            system=self._parse_system(system_rows[0]),
            interfaces=tuple(self._parse_interface(row) for row in interface_rows),
        )

    async def _get_records(self, path: str, properties: tuple[str, ...]) -> list[dict[str, Any]]:
        try:
            response = await self._http.get(
                path,
                params={".proplist": ",".join(properties)},
            )
        except httpx.TimeoutException as exc:
            raise RouterOSUnavailableError("RouterOS REST request timed out") from exc
        except httpx.RequestError as exc:
            detail = self._request_error_detail(exc)
            raise RouterOSUnavailableError(
                f"RouterOS HTTPS request failed: {detail}"
            ) from exc

        if response.status_code == 401:
            raise RouterOSAuthenticationError("RouterOS REST authentication failed")
        if response.status_code == 403:
            raise RouterOSPermissionError("RouterOS account lacks read access to a requested resource")
        if not response.is_success:
            detail = self._error_detail(response)
            message = f"RouterOS REST GET /{path} failed with HTTP {response.status_code}"
            if detail:
                message = f"{message}: {detail}"
            raise RouterOSRequestError(message)

        try:
            payload = response.json()
        except ValueError as exc:
            raise RouterOSResponseError(f"RouterOS returned invalid JSON for /{path}") from exc
        if isinstance(payload, dict):
            return [payload]
        if isinstance(payload, list) and all(isinstance(row, dict) for row in payload):
            return payload
        raise RouterOSResponseError(f"RouterOS returned an unexpected response shape for /{path}")

    @staticmethod
    def _error_detail(response: httpx.Response) -> str | None:
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, dict):
            return None

        details = [
            value.strip()
            for key in ("detail", "message")
            if isinstance((value := payload.get(key)), str) and value.strip()
        ]
        return "; ".join(details)[:500] or None

    @staticmethod
    def _request_error_detail(error: httpx.RequestError) -> str:
        pending: list[BaseException] = [error]
        seen: set[int] = set()
        details: list[str] = []
        while pending:
            current = pending.pop(0)
            if id(current) in seen:
                continue
            seen.add(id(current))
            message = str(current).strip()
            if message:
                details.append(f"{type(current).__name__}: {message}")
            if isinstance(current, BaseExceptionGroup):
                pending.extend(current.exceptions)
            if current.__cause__ is not None:
                pending.append(current.__cause__)
            if current.__context__ is not None:
                pending.append(current.__context__)
        return " -> ".join(details)[:500] or type(error).__name__

    @classmethod
    def _parse_system(cls, record: dict[str, Any]) -> RouterSystemInfo:
        cpu_load = cls._required_int(record, "cpu-load")
        if not 0 <= cpu_load <= 100:
            raise RouterOSResponseError("RouterOS returned an invalid CPU load")

        free_memory = cls._required_int(record, "free-memory")
        total_memory = cls._required_int(record, "total-memory")
        if free_memory < 0 or total_memory <= 0 or free_memory > total_memory:
            raise RouterOSResponseError("RouterOS returned invalid memory values")

        return RouterSystemInfo(
            uptime=cls._required_string(record, "uptime"),
            cpu_load_percent=cpu_load,
            free_memory_bytes=free_memory,
            total_memory_bytes=total_memory,
            version=cls._optional_string(record, "version"),
            board_name=cls._optional_string(record, "board-name"),
        )

    @classmethod
    def _parse_interface(cls, record: dict[str, Any]) -> RouterInterface:
        return RouterInterface(
            router_id=cls._optional_string(record, ".id"),
            name=cls._required_string(record, "name"),
            type=cls._required_string(record, "type"),
            running=cls._optional_bool(record, "running"),
            disabled=cls._optional_bool(record, "disabled"),
        )

    @staticmethod
    def _required_string(record: dict[str, Any], key: str) -> str:
        value = record.get(key)
        if not isinstance(value, str) or not value:
            raise RouterOSResponseError(f"RouterOS response is missing {key}")
        return value

    @classmethod
    def _required_int(cls, record: dict[str, Any], key: str) -> int:
        value = cls._required_string(record, key)
        try:
            return int(value)
        except ValueError as exc:
            raise RouterOSResponseError(f"RouterOS returned an invalid {key}") from exc

    @classmethod
    def _optional_string(cls, record: dict[str, Any], key: str) -> str | None:
        value = record.get(key)
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            raise RouterOSResponseError(f"RouterOS returned an invalid {key}")
        return value

    @classmethod
    def _optional_bool(cls, record: dict[str, Any], key: str) -> bool | None:
        value = cls._optional_string(record, key)
        if value is None:
            return None
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
        raise RouterOSResponseError(f"RouterOS returned an invalid {key}")
