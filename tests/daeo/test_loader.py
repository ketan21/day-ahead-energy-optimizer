"""Config loader, atomic save, and secrets tests."""

from __future__ import annotations

import json
import stat

import pytest

from daeo.config.loader import (
    ConfigError,
    Secrets,
    config_hash,
    load,
    load_config,
    load_secrets,
    save_config,
    save_secrets,
    validate_payload,
)
from daeo.config.models import Config


def test_save_and_load_config(tmp_path) -> None:
    path = tmp_path / "config.json"
    config = Config.default()
    save_config(config, path)
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_config(path) == config


def test_config_hash_is_stable() -> None:
    config = Config.default()
    assert config_hash(config) == config_hash(Config.model_validate(config.model_dump()))
    assert len(config_hash(config)) == 64


def test_invalid_json_raises_config_error(tmp_path) -> None:
    path = tmp_path / "config.json"
    path.write_text("{", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_config(path)


def test_unknown_key_raises_config_error(tmp_path) -> None:
    path = tmp_path / "config.json"
    payload = Config.default().model_dump(mode="json")
    payload["surprise"] = True
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ConfigError, match="surprise"):
        load_config(path)


def test_validate_payload_reports_the_path() -> None:
    payload = Config.default().model_dump(mode="json")
    payload["batteries"] = [
        {"name": "Battery", "capacity_kwh": -1, "max_charge_kw": 5, "max_discharge_kw": 5}
    ]
    with pytest.raises(ConfigError, match="batteries"):
        validate_payload(payload)


def test_secrets_are_separate_and_owner_only(tmp_path) -> None:
    path = tmp_path / "secrets.json"
    secrets = Secrets(entsoe_api_key="super-secret")
    save_secrets(secrets, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw == {"entsoe_api_key": "super-secret"}

    loaded = load_secrets(path)
    assert loaded.entsoe_api_key is not None
    assert loaded.entsoe_api_key.get_secret_value() == "super-secret"
    assert "super-secret" not in loaded.model_dump_json()


def test_missing_secrets_file_is_empty(tmp_path) -> None:
    assert load_secrets(tmp_path / "missing.json") == Secrets()


def test_load_bundle_includes_hash(tmp_path) -> None:
    path = tmp_path / "config.json"
    save_config(Config.default(), path)
    bundle = load(path)
    assert bundle.config == Config.default()
    assert bundle.config_hash == config_hash(Config.default())
    assert bundle.secrets == Secrets()
