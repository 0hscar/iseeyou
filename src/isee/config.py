import os
import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FilePath, field_validator


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


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: ServerSettings = Field(default_factory=ServerSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    router: RouterSettings | None = None


def load_settings(config_path: Path | None = None) -> Settings:
    configured_path = config_path or Path(os.environ.get("ISEE_CONFIG", "config.toml"))
    if not configured_path.exists():
        if config_path is not None or "ISEE_CONFIG" in os.environ:
            raise FileNotFoundError(f"Configuration file not found: {configured_path}")
        return Settings()

    with configured_path.open("rb") as config_file:
        document = tomllib.load(config_file)
    return Settings.model_validate(document)
