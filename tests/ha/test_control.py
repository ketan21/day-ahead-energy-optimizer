"""Battery control decision tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from custom_components.daeo.control import (
    battery_power_w,
    clamp_power_for_soc,
    decide_control,
    desired_mode,
    setpoint_write_value,
)
from custom_components.daeo.plan import parse_datetime

NOW = datetime(2026, 1, 1, 12, 10, tzinfo=UTC)


def plan_payload() -> dict:
    return {
        "id": "plan_test",
        "created_at": "2026-01-01T12:00:00+00:00",
        "config_hash": "a" * 64,
        "interval_minutes": 15,
        "intervals": [
            {
                "start": "2026-01-01T12:00:00+00:00",
                "end": "2026-01-01T12:15:00+00:00",
                "battery_charge_kwh": 1.0,
                "battery_discharge_kwh": 0.0,
                "soc_pct": 50.0,
            }
        ],
    }


def battery_config() -> dict:
    return {
        "batteries": [
            {
                "name": "Battery",
                "setpoint_entity": "number.battery_setpoint",
                "mode_entity": "select.battery_mode",
                "mode_charge": "charge",
                "mode_discharge": "discharge",
                "mode_idle": "idle",
            }
        ]
    }


def health(config_hash: str = "a" * 64) -> dict:
    return {"config_hash": config_hash}


def test_battery_power_and_mode() -> None:
    interval = plan_payload()["intervals"][0]
    assert battery_power_w(interval, 15) == 4000
    assert battery_power_w(
        {"battery_charge_kwh": 0, "battery_discharge_kwh": 0.5}, 15
    ) == -2000
    battery = battery_config()["batteries"][0]
    assert desired_mode(battery, 4000) == "charge"
    assert desired_mode(battery, -2000) == "discharge"
    assert desired_mode(battery, 0) == "idle"


def test_disarmed_falls_back() -> None:
    decision = decide_control(
        plan_payload(),
        health(),
        battery_config(),
        NOW,
        armed=False,
        last_interval_start=None,
        last_power_w=None,
        max_age_seconds=1800,
    )
    assert decision.action == "fallback"
    assert decision.reason == "disarmed"
    assert decision.power_w == 0
    assert decision.mode == "idle"


def test_missing_setpoint_is_blocked() -> None:
    config = battery_config()
    config["batteries"][0]["setpoint_entity"] = None
    decision = decide_control(
        plan_payload(),
        health(),
        config,
        NOW,
        armed=True,
        last_interval_start=None,
        last_power_w=None,
        max_age_seconds=1800,
    )
    assert decision.action == "blocked"
    assert decision.reason == "no_setpoint"


def test_stale_plan_falls_back() -> None:
    decision = decide_control(
        plan_payload(),
        health(),
        battery_config(),
        NOW + timedelta(hours=1),
        armed=True,
        last_interval_start=None,
        last_power_w=None,
        max_age_seconds=1800,
    )
    assert decision.action == "fallback"
    assert decision.reason == "stale_plan"


def test_config_hash_mismatch_falls_back() -> None:
    decision = decide_control(
        plan_payload(),
        health("b" * 64),
        battery_config(),
        NOW,
        armed=True,
        last_interval_start=None,
        last_power_w=None,
        max_age_seconds=1800,
    )
    assert decision.action == "fallback"
    assert decision.reason == "config_mismatch"


def test_outside_plan_falls_back() -> None:
    decision = decide_control(
        plan_payload(),
        health(),
        battery_config(),
        NOW + timedelta(minutes=10),
        armed=True,
        last_interval_start=None,
        last_power_w=None,
        max_age_seconds=1800,
    )
    assert decision.action == "fallback"
    assert decision.reason == "outside_plan"


def test_apply_then_unchanged() -> None:
    first = decide_control(
        plan_payload(),
        health(),
        battery_config(),
        NOW,
        armed=True,
        last_interval_start=None,
        last_power_w=None,
        max_age_seconds=1800,
    )
    assert first.action == "apply"
    assert first.power_w == 4000
    assert first.mode == "charge"
    assert first.interval_start == parse_datetime("2026-01-01T12:00:00+00:00")

    second = decide_control(
        plan_payload(),
        health(),
        battery_config(),
        NOW,
        armed=True,
        last_interval_start=first.interval_start,
        last_power_w=first.power_w,
        max_age_seconds=1800,
    )
    assert second.action == "none"
    assert second.reason == "unchanged"


def test_soc_guard() -> None:
    assert clamp_power_for_soc(4000, 99.8, 20, 100) == 0
    assert clamp_power_for_soc(-4000, 20.1, 20, 100) == 0
    assert clamp_power_for_soc(4000, 50, 20, 100) == 4000
    assert clamp_power_for_soc(-4000, 50, 20, 100) == -4000
    assert clamp_power_for_soc(4000, None, 20, 100) == 4000


def test_setpoint_write_value() -> None:
    assert setpoint_write_value(4000, unsigned=False, invert=False) == 4000
    assert setpoint_write_value(-4000, unsigned=False, invert=True) == 4000
    assert setpoint_write_value(4000, unsigned=True, invert=False) == 4000
    assert setpoint_write_value(-4000, unsigned=True, invert=False) == 4000
    assert setpoint_write_value(0, unsigned=True, invert=True) == 0
