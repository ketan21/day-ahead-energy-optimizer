"""Configuration loading, saving, secrets, and hashing."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from daeo.config.models import Config


class ConfigError(ValueError):
    """Raised when configuration cannot be loaded or validated."""


class Secrets(BaseModel):
    """Credentials kept outside the configuration document."""

    model_config = ConfigDict(extra="forbid")

    entsoe_api_key: SecretStr | None = None
    tibber_token: SecretStr | None = None
    meteoserver_key: SecretStr | None = None


@dataclass(frozen=True)
class ConfigBundle:
    """A configuration document plus its secrets."""

    config: Config
    secrets: Secrets
    path: Path
    config_hash: str


def _format_validation_error(error: ValidationError) -> str:
    lines = ["Configuration validation failed:"]
    for item in error.errors():
        location = " -> ".join(str(part) for part in item["loc"])
        lines.append(f"  - {location}: {item['msg']}")
    return "\n".join(lines)


def validate_payload(payload: dict) -> Config:
    """Validate a raw configuration document."""
    try:
        return Config.model_validate(payload)
    except ValidationError as error:
        raise ConfigError(_format_validation_error(error)) from error


def load_config(path: Path) -> Config:
    """Load and validate a configuration file."""
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(f"Configuration file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise ConfigError(f"Configuration file is not valid JSON: {error}") from error
    return validate_payload(payload)


def load_secrets(path: Path) -> Secrets:
    """Load secrets, returning empty secrets when the file does not exist."""
    if not path.exists():
        return Secrets()
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except json.JSONDecodeError as error:
        raise ConfigError(f"Secrets file is not valid JSON: {error}") from error
    try:
        return Secrets.model_validate(payload)
    except ValidationError as error:
        raise ConfigError(_format_validation_error(error)) from error


def load(path: Path, secrets_path: Path | None = None) -> ConfigBundle:
    """Load a configuration bundle and the hash of the configuration."""
    config = load_config(path)
    secrets = load_secrets(secrets_path or path.parent / "secrets.json")
    return ConfigBundle(
        config=config,
        secrets=secrets,
        path=path,
        config_hash=config_hash(config),
    )


def load_or_default(path: Path) -> ConfigBundle:
    """Load a configuration file or return the default NL preset."""
    if path.exists():
        return load(path)
    config = Config.default()
    return ConfigBundle(
        config=config,
        secrets=Secrets(),
        path=path,
        config_hash=config_hash(config),
    )


def _atomic_write(path: Path, content: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(handle.name, mode)
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)


def save_config(config: Config, path: Path) -> None:
    """Validate and atomically write a configuration document."""
    _atomic_write(path, json.dumps(config.model_dump(mode="json"), indent=2) + "\n")


def save_secrets(secrets: Secrets, path: Path) -> None:
    """Write the secrets file with owner-only permissions."""
    payload = {
        key: value.get_secret_value()
        for key, value in secrets.model_dump().items()
        if value is not None
    }
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")


def config_hash(config: Config) -> str:
    """Return a stable hash of the normalized configuration."""
    payload = json.dumps(
        config.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def redact(config: Config) -> dict:
    """Return a configuration dict safe to send to a client."""
    return config.model_dump(mode="json")
