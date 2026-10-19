from pathlib import Path

import pytest
from pydantic import ValidationError

from isee.config import (
    CollectionSettings,
    ConnectivityTarget,
    RouterSettings,
    Settings,
    load_settings,
)


def test_settings_have_localhost_defaults() -> None:
    settings = Settings()

    assert settings.server.host == "127.0.0.1"
    assert settings.server.port == 8000
    assert settings.logging.level == "INFO"


def test_load_settings_reads_toml(tmp_path: Path) -> None:
    config_file = tmp_path / "settings.toml"
    config_file.write_text(
        '[server]\nhost = "localhost"\nport = 9000\n'
        '[logging]\nlevel = "DEBUG"\n'
        '[router]\nhost = "router.lan"\nusername = "isee-monitor"\n',
        encoding="utf-8",
    )

    settings = load_settings(config_file)

    assert settings.server.host == "localhost"
    assert settings.server.port == 9000
    assert settings.logging.level == "DEBUG"
    assert settings.router is not None
    assert settings.router.host == "router.lan"
    assert settings.router.username == "isee-monitor"


@pytest.mark.parametrize(
    "document",
    [
        {"server": {"port": 0}},
        {"server": {"port": 65536}},
        {"logging": {"level": "TRACE"}},
        {"unexpected": True},
        {"collection": {"interfaces": ["ether1"]}},
        {
            "collection": {
                "targets": [{"name": "public", "host": "1.1.1.1", "port": 443}]
            }
        },
    ],
)
def test_settings_reject_invalid_values(document: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate(document)


def test_explicit_missing_config_path_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "missing.toml")


def test_configured_interfaces_are_allowed_with_router() -> None:
    settings = Settings.model_validate(
        {
            "router": {"host": "router.lan", "username": "monitor"},
            "collection": {"interfaces": ["ether1"]},
        }
    )

    assert settings.router is not None
    assert settings.collection.interfaces == ["ether1"]


def test_router_settings_validate_target_and_timeout() -> None:
    settings = RouterSettings(
        host="router.lan",
        username="isee-monitor",
        timeout_seconds=3.5,
    )

    assert settings.host == "router.lan"
    assert settings.port == 443
    assert settings.timeout_seconds == 3.5


@pytest.mark.parametrize(
    "document",
    [
        {"host": "", "username": "monitor"},
        {"host": "router.lan", "username": ""},
        {"host": "https://router.lan", "username": "monitor"},
        {"host": "router.lan", "username": "monitor", "port": 70000},
        {"host": "router.lan", "username": "monitor", "timeout_seconds": 0},
    ],
)
def test_router_settings_reject_invalid_values(document: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        RouterSettings.model_validate(document)


def test_collection_settings_defaults_and_connectivity_target() -> None:
    settings = CollectionSettings(
        targets=[ConnectivityTarget(name="gateway", host="192.168.88.1", port=443)]
    )

    assert settings.interval_seconds == 10
    assert settings.database_path == Path("data/isee.sqlite3")
    assert settings.interfaces == []
    assert settings.targets[0].name == "gateway"


@pytest.mark.parametrize(
    "document",
    [
        {"interval_seconds": 0},
        {"probes_per_target": 11},
        {"interfaces": ["ether1", "ether1"]},
        {"database_path": ":memory:"},
        {
            "targets": [
                {"name": "wan", "host": "1.1.1.1", "port": 443},
                {"name": "wan", "host": "example.net", "port": 443},
            ]
        },
        {"targets": [{"name": "wan", "host": "https://example.net", "port": 443}]},
    ],
)
def test_collection_settings_reject_invalid_values(document: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        CollectionSettings.model_validate(document)
