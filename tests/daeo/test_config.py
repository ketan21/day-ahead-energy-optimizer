"""Configuration schema tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from daeo.config.models import (
    BatteryConfig,
    Config,
    PricingConfig,
    ScheduleEntry,
    SchedulerConfig,
    SolarConfig,
)
from daeo.domain.enums import PriceSource, TaskAction


def test_default_config_is_valid() -> None:
    config = Config.default()
    assert config.schema_version == 1
    assert config.home.country.value == "NL"
    assert config.strategy.interval.minutes == 15
    assert len(config.scheduler.entries) == 3


def test_default_config_roundtrips() -> None:
    config = Config.default()
    payload = config.model_dump(mode="json")
    assert Config.model_validate(payload) == config


def test_unknown_keys_are_rejected() -> None:
    with pytest.raises(ValidationError):
        Config.model_validate({"schema_version": 1, "unknown": True})


def test_battery_soc_limits_are_ordered() -> None:
    with pytest.raises(ValidationError):
        BatteryConfig(
            name="Battery",
            capacity_kwh=10,
            max_charge_kw=5,
            max_discharge_kw=5,
            min_soc_pct=80,
            max_soc_pct=20,
        )


def test_entity_id_pattern() -> None:
    with pytest.raises(ValidationError):
        SolarConfig(name="Roof", peak_power_wp=4000, forecast_entity="not-an-entity")
    solar = SolarConfig(
        name="Roof",
        peak_power_wp=4000,
        forecast_entity="sensor.solar_forecast",
    )
    assert solar.forecast_entity == "sensor.solar_forecast"


def test_device_names_are_unique() -> None:
    payload = Config.default().model_dump(mode="json")
    payload["batteries"] = [
        {
            "name": "Same",
            "capacity_kwh": 5,
            "max_charge_kw": 2,
            "max_discharge_kw": 2,
        },
        {
            "name": "Same",
            "capacity_kwh": 5,
            "max_charge_kw": 2,
            "max_discharge_kw": 2,
        },
    ]
    with pytest.raises(ValidationError, match="unique"):
        Config.model_validate(payload)


def test_scheduler_rejects_duplicate_times() -> None:
    with pytest.raises(ValidationError):
        SchedulerConfig(
            entries=[
                ScheduleEntry(at="14:00", action=TaskAction.OPTIMIZE),
                ScheduleEntry(at="14:00", action=TaskAction.FETCH_PRICES),
            ]
        )


def test_price_source_requires_fields() -> None:
    with pytest.raises(ValidationError):
        PricingConfig(source=PriceSource.HA_SENSOR)
    with pytest.raises(ValidationError):
        PricingConfig(source=PriceSource.FIXED)


def test_schema_contains_ui_hints() -> None:
    schema = Config.model_json_schema()
    assert schema["type"] == "object"
    assert "batteries" in schema["properties"]
    battery = schema["$defs"]["BatteryConfig"]
    assert battery["properties"]["capacity_kwh"]["x-ui-section"] == "Battery"
    assert "x-help" in battery["properties"]["setpoint_entity"]
    assert schema["$defs"]["HomeConfig"]["properties"]["country"]["x-ui-section"] == "Home"
