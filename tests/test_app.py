import asyncio
import sys
from pathlib import Path

import httpx
import pytest

from isee.app import create_app
from isee.config import RouterSettings, Settings
from isee.main import main


def test_health_endpoint_reports_application_status() -> None:
    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(Settings()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {"service": "iSeeYou", "status": "ok"}


def test_collector_health_is_separate_and_unknown_without_router() -> None:
    async def request_health() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(Settings()))
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/health/collector")

    response = asyncio.run(request_health())

    assert response.status_code == 200
    assert response.json() == {
        "status": "not_configured",
        "last_attempt_at": None,
        "last_success_at": None,
        "last_error": None,
    }


def test_configured_router_requires_password_at_application_startup(monkeypatch) -> None:
    monkeypatch.delenv("ISEE_ROUTER_PASSWORD", raising=False)
    application = create_app(
        Settings(router=RouterSettings(host="router.lan", username="monitor"))
    )

    async def start_application() -> None:
        async with application.router.lifespan_context(application):
            pass

    with pytest.raises(RuntimeError, match="ISEE_ROUTER_PASSWORD"):
        asyncio.run(start_application())


def test_application_lifespan_starts_and_stops_collector(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ISEE_ROUTER_PASSWORD", "test-password")

    class FakeCollector:
        def __init__(self, *_args) -> None:
            self.health = _args[-1]

        async def run(self, stop_event: asyncio.Event) -> None:
            self.health.status = "ok"
            await stop_event.wait()

    monkeypatch.setattr("isee.app.NetworkCollector", FakeCollector)
    application = create_app(
        Settings(
            router=RouterSettings(host="router.lan", username="monitor"),
            collection={"database_path": tmp_path / "network.sqlite3"},
        )
    )

    async def exercise_lifespan() -> None:
        async with application.router.lifespan_context(application):
            await asyncio.sleep(0)
            assert application.state.collector_health.status == "ok"
        assert application.state.collector_health.status == "ok"

    asyncio.run(exercise_lifespan())


def test_cli_reports_configuration_validation_errors_without_traceback(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    config_file = tmp_path / "invalid.toml"
    config_file.write_text(
        '[collection]\ninterfaces = ["ether1"]\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("ISEE_CONFIG", str(config_file))
    monkeypatch.setattr(sys, "argv", ["isee"])

    with pytest.raises(SystemExit) as error:
        main()

    assert error.value.code == 2
    assert "Configuration error:" in capsys.readouterr().err
