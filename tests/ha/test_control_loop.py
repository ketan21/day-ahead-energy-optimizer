"""Battery controller live-SOC tests."""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from homeassistant.core import ServiceCall
from homeassistant.util import dt as dt_util

from custom_components.daeo.control_loop import BatteryController


def battery_config() -> dict:
    return {
        "name": "Battery",
        "capacity_kwh": 7.2,
        "max_charge_kw": 1.2,
        "max_discharge_kw": 1.2,
        "efficiency": 0.95,
        "min_soc_pct": 20.0,
        "max_soc_pct": 100.0,
        "soc_entity": "sensor.battery_soc",
        "setpoint_entity": "input_number.battery_setpoint",
        "mode_entity": "input_select.battery_mode",
        "mode_charge": "charge",
        "mode_discharge": "discharge",
        "mode_idle": "idle",
    }


def plan_payload(
    soc_pct: float,
    *,
    now=None,
    grid_import_kwh: float = 0.0,
    grid_export_kwh: float = 0.0,
    battery_discharge_kwh: float = 0.143,
) -> dict:
    now = now or dt_util.now()
    start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    return {
        "id": "plan_soc_test",
        "created_at": now.isoformat(),
        "horizon_start": start.isoformat(),
        "horizon_end": (start + timedelta(minutes=15)).isoformat(),
        "interval_minutes": 15,
        "currency": "EUR",
        "intervals": [
            {
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=15)).isoformat(),
                "price_import_eur_kwh": 0.25,
                "price_export_eur_kwh": 0.0,
                "load_kwh": 0.143,
                "pv_kwh": 0.0,
                "battery_charge_kwh": 0.0,
                "battery_discharge_kwh": battery_discharge_kwh,
                "soc_pct": soc_pct,
                "ev_kwh": 0.0,
                "boiler_kwh": 0.0,
                "heat_pump_kwh": 0.0,
                "machine_kwh": 0.0,
                "grid_import_kwh": grid_import_kwh,
                "grid_export_kwh": grid_export_kwh,
                "cost_eur": 0.0,
                "reason": "idle",
                "explanation": "test",
            }
        ],
        "summary": {
            "cost_eur": 0.0,
            "baseline_cost_eur": 0.0,
            "savings_eur": 0.0,
            "import_kwh": 0.0,
            "export_kwh": 0.0,
            "pv_kwh": 0.0,
            "load_kwh": 0.143,
            "battery_cycles": 0.01,
            "terminal_soc_value_eur": 0.0,
        },
        "solver": {
            "name": "cbc",
            "status": "optimal",
            "runtime_ms": 1,
            "objective_eur": 0.0,
            "mip_gap": 0.0,
        },
        "config_hash": "a" * 64,
        "sources": {"prices": "test", "pv": "test", "load": "recorder"},
    }


class FakeApi:
    def __init__(self) -> None:
        self.soc_values: list[float | None] = []

    async def async_optimize(self, battery_soc_pct: float | None = None) -> dict:
        self.soc_values.append(battery_soc_pct)
        return {}


class FakeCoordinator:
    def __init__(self, plan: dict, live_plan: dict, grid: dict | None = None) -> None:
        config = {"batteries": [battery_config()]}
        if grid:
            config["grid"] = grid
        self.data = SimpleNamespace(
            plan=plan,
            health={"config_hash": "a" * 64},
            config=config,
        )
        self.live_plan = live_plan
        self.api = FakeApi()

    async def async_request_refresh(self) -> None:
        self.data.plan = self.live_plan


@pytest.mark.asyncio
async def test_arm_forces_live_soc_plan_when_plan_soc_is_from_default(hass) -> None:
    """A plan built with the default 50% SOC must be replaced before applying."""
    now = dt_util.now()
    old_plan = plan_payload(47.9, now=now)  # implies ~50% initial SOC
    live_plan = plan_payload(27.0, now=now)  # 29% initial minus 0.143 kWh
    coordinator = FakeCoordinator(old_plan, live_plan)

    hass.states.async_set("sensor.battery_soc", "29")
    hass.states.async_set("input_number.battery_setpoint", "0")
    hass.states.async_set("input_select.battery_mode", "idle")

    async def set_value(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

    async def select_option(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], call.data["option"])

    hass.services.async_register("input_number", "set_value", set_value)
    hass.services.async_register("input_select", "select_option", select_option)

    controller = BatteryController(hass, None, coordinator)
    await controller.async_set_armed(True)

    assert coordinator.api.soc_values == [29.0]
    assert controller.armed is True
    assert controller.status == "applied"
    assert controller.last_power_w == -572.0
    assert hass.states.get("input_number.battery_setpoint").state == "-572.0"
    assert hass.states.get("input_select.battery_mode").state == "discharge"


@pytest.mark.asyncio
async def test_arm_refuses_when_configured_soc_is_unavailable(hass) -> None:
    """Never reuse the 50% default when a configured SOC entity is unavailable."""
    now = dt_util.now()
    plan = plan_payload(47.9, now=now)
    coordinator = FakeCoordinator(plan, plan)

    hass.states.async_set("sensor.battery_soc", "unavailable")
    hass.states.async_set("input_number.battery_setpoint", "0")
    hass.states.async_set("input_select.battery_mode", "idle")

    async def set_value(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

    async def select_option(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], call.data["option"])

    hass.services.async_register("input_number", "set_value", set_value)
    hass.services.async_register("input_select", "select_option", select_option)

    controller = BatteryController(hass, None, coordinator)
    await controller.async_set_armed(True)

    assert controller.armed is False
    assert controller.last_error is not None
    assert coordinator.api.soc_values == []
    assert hass.states.get("input_number.battery_setpoint").state in ("0", "0.0")


@pytest.mark.asyncio
async def test_zero_grid_correction_uses_live_p1_power(hass) -> None:
    """In a zero-grid interval, the P1 error is added to the planned setpoint."""
    now = dt_util.now()
    old_plan = plan_payload(47.9, now=now)
    live_plan = plan_payload(27.0, now=now)
    coordinator = FakeCoordinator(
        old_plan,
        live_plan,
        {
            "power_sensor_entity": "sensor.grid_power",
            "power_sensor_invert": False,
            "zero_grid_deadband_w": 30,
            "zero_grid_max_step_w": 2000,
        },
    )

    hass.states.async_set("sensor.battery_soc", "29")
    hass.states.async_set("sensor.grid_power", "500")
    hass.states.async_set("input_number.battery_setpoint", "0")
    hass.states.async_set("input_select.battery_mode", "idle")

    async def set_value(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

    async def select_option(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], call.data["option"])

    hass.services.async_register("input_number", "set_value", set_value)
    hass.services.async_register("input_select", "select_option", select_option)

    controller = BatteryController(hass, None, coordinator)
    await controller.async_set_armed(True)

    # Planned base is -572 W; 500 W live import adds another 500 W discharge.
    assert controller.last_power_w == -1072.0
    assert hass.states.get("input_number.battery_setpoint").state == "-1072.0"
    assert hass.states.get("input_select.battery_mode").state == "discharge"


@pytest.mark.asyncio
async def test_grid_correction_follows_planned_grid_target(hass) -> None:
    """A planned grid target of 800 W is followed instead of forcing zero."""
    now = dt_util.now()
    old_plan = plan_payload(47.9, now=now, grid_import_kwh=0.2)
    live_plan = plan_payload(27.0, now=now, grid_import_kwh=0.2)
    coordinator = FakeCoordinator(
        old_plan,
        live_plan,
        {
            "power_sensor_entity": "sensor.grid_power",
            "zero_grid_deadband_w": 30,
            "zero_grid_max_step_w": 2000,
        },
    )

    hass.states.async_set("sensor.battery_soc", "29")
    hass.states.async_set("sensor.grid_power", "500")
    hass.states.async_set("input_number.battery_setpoint", "0")
    hass.states.async_set("input_select.battery_mode", "idle")

    async def set_value(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

    async def select_option(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], call.data["option"])

    hass.services.async_register("input_number", "set_value", set_value)
    hass.services.async_register("input_select", "select_option", select_option)

    controller = BatteryController(hass, None, coordinator)
    await controller.async_set_armed(True)

    # Planned 0.2 kWh in a 15-minute interval is 800 W. Actual 500 W means
    # reduce discharge by 300 W: -572 + (800 - 500) = -272 W.
    assert controller.last_power_w == -272.0
    assert hass.states.get("input_number.battery_setpoint").state == "-272.0"


@pytest.mark.asyncio
async def test_grid_correction_skips_explicitly_idle_battery(hass) -> None:
    """An idle plan interval must not be turned into battery activity."""
    now = dt_util.now()
    old_plan = plan_payload(47.9, now=now, battery_discharge_kwh=0.0)
    live_plan = plan_payload(29.0, now=now, battery_discharge_kwh=0.0)
    coordinator = FakeCoordinator(
        old_plan,
        live_plan,
        {"power_sensor_entity": "sensor.grid_power"},
    )

    hass.states.async_set("sensor.battery_soc", "29")
    hass.states.async_set("sensor.grid_power", "500")
    hass.states.async_set("input_number.battery_setpoint", "0")
    hass.states.async_set("input_select.battery_mode", "idle")

    async def set_value(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

    async def select_option(call: ServiceCall) -> None:
        hass.states.async_set(call.data["entity_id"], call.data["option"])

    hass.services.async_register("input_number", "set_value", set_value)
    hass.services.async_register("input_select", "select_option", select_option)

    controller = BatteryController(hass, None, coordinator)
    await controller.async_set_armed(True)

    assert controller.last_power_w == 0.0
    assert hass.states.get("input_number.battery_setpoint").state in ("0", "0.0")
