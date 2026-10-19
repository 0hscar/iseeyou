from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FilePath, field_validator, model_validator


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)

    @field_validator("host")
    @classmethod
    def host_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("host must not be empty")
        return value


class LoggingSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"


class RouterSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = Field(default=443, ge=1, le=65535)
    username: str
    ca_file: FilePath | None = None
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)

    @field_validator("host")
    @classmethod
    def validate_host(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("host must not be empty")
        if any(character in value for character in "/?#@") or any(character.isspace() for character in value):
            raise ValueError("host must not contain URL delimiters or whitespace")
        return value

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("username must not be empty")
        return value


class ConnectivityTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    host: str
    port: int = Field(ge=1, le=65535)

    @field_validator("name", "host")
    @classmethod
    def values_must_not_be_empty(cls, value: str) -> str:
        value = value.strip()
        if not value or any(character.isspace() for character in value):
            raise ValueError("value must not be empty or contain whitespace")
        return value

    @field_validator("host")
    @classmethod
    def host_must_not_contain_url_delimiters(cls, value: str) -> str:
        if any(character in value for character in "/?#@"):
            raise ValueError("host must not contain URL delimiters")
        return value


class CollectionSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: int = Field(default=10, ge=5, le=3600)
    database_path: Path = Path("data/isee.sqlite3")
    interfaces: list[str] = Field(default_factory=list, max_length=128)
    probes_per_target: int = Field(default=3, ge=1, le=5)
    probe_timeout_seconds: float = Field(default=2.0, gt=0, le=10)
    targets: list[ConnectivityTarget] = Field(default_factory=list, max_length=10)

    @field_validator("database_path")
    @classmethod
    def database_path_must_be_persistent(cls, value: Path) -> Path:
        if str(value) == ":memory:":
            raise ValueError("database_path must refer to a persistent file")
        return value

    @field_validator("interfaces")
    @classmethod
    def validate_interfaces(cls, value: list[str]) -> list[str]:
        names = [name.strip() for name in value]
        if any(not name or any(character.isspace() for character in name) for name in names):
            raise ValueError("interface names must not be empty or contain whitespace")
        if len(names) != len(set(names)):
            raise ValueError("interface names must be unique")
        return names

    @model_validator(mode="after")
    def target_names_must_be_unique(self) -> CollectionSettings:
        names = [target.name for target in self.targets]
        if len(names) != len(set(names)):
            raise ValueError("connectivity target names must be unique")
        return self


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerSettings = Field(default_factory=ServerSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    router: RouterSettings | None = None
    collection: CollectionSettings = Field(default_factory=CollectionSettings)

    @model_validator(mode="after")
    def configured_collection_requires_router(self) -> Settings:
        if self.router is None and (self.collection.interfaces or self.collection.targets):
            raise ValueError(
                "Configure [router] when collection.interfaces or collection.targets is set"
            )
        return self


def load_settings(config_path: Path | None = None) -> Settings:
    configured_path = config_path or Path(os.environ.get("ISEE_CONFIG", "config.toml"))
    if not configured_path.exists():
        if config_path is not None or "ISEE_CONFIG" in os.environ:
            raise FileNotFoundError(f"Configuration file not found: {configured_path}")
        return Settings()

    with configured_path.open("rb") as config_file:
        document = tomllib.load(config_file)
    return Settings.model_validate(document)
