"""Home Assistant integration tests for the DAEO scaffold."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.daeo.const import CONF_TOKEN, CONF_URL, DOMAIN

BASE = "http://engine.local"
NOW = datetime(2026, 1, 1, 12, 10, tzinfo=UTC)


def plan_payload() -> dict:
    start = NOW.replace(minute=0, second=0, microsecond=0)
    intervals = []
    for index in range(4):
        interval_start = start + timedelta(minutes=15 * index)
        intervals.append(
            {
                "start": interval_start.isoformat(),
                "end": (interval_start + timedelta(minutes=15)).isoformat(),
                "price_import_eur_kwh": 0.2 + index * 0.01,
                "price_export_eur_kwh": 0.05,
                "load_kwh": 0.1,
                "pv_kwh": 0.0,
                "battery_charge_kwh": 1.0 if index == 1 else 0.0,
                "battery_discharge_kwh": 1.0 if index == 2 else 0.0,
                "soc_pct": 50.0 + index,
                "ev_kwh": 2.0 if index in (1, 2) else 0.0,
                "boiler_kwh": 0.0,
                "heat_pump_kwh": 0.0,
                "machine_kwh": 0.0,
                "grid_import_kwh": 0.2,
                "grid_export_kwh": 0.0,
                "cost_eur": 0.04,
                "reason": "idle",
                "explanation": "test",
            }
        )
    return {
        "id": "plan_test",
        "created_at": NOW.isoformat(),
        "horizon_start": intervals[0]["start"],
        "horizon_end": intervals[-1]["end"],
        "interval_minutes": 15,
        "currency": "EUR",
        "intervals": intervals,
        "summary": {
            "cost_eur": 1.5,
            "baseline_cost_eur": 2.0,
            "savings_eur": 0.5,
            "import_kwh": 2.0,
            "export_kwh": 0.0,
            "pv_kwh": 1.2,
            "load_kwh": 0.4,
            "battery_cycles": 0.1,
            "terminal_soc_value_eur": 0.0,
        },
        "solver": {
            "name": "demo",
            "status": "optimal",
            "runtime_ms": 1,
            "objective_eur": 1.5,
            "mip_gap": 0.0,
        },
        "config_hash": "a" * 64,
        "sources": {"prices": "energyzero", "pv": "forecast_solar"},
    }


@pytest.mark.asyncio
async def test_config_flow_creates_entry(hass, aioclient_mock) -> None:
    aioclient_mock.get(
        f"{BASE}/api/v1/health",
        json={
            "status": "ok",
            "version": "2.0.0",
            "demo": True,
            "auth_required": False,
            "plan_available": False,
            "config_hash": "a" * 64,
        },
    )
    aioclient_mock.get(f"{BASE}/api/v1/config", json={"strategy": {"objective": "minimize_cost"}})
    aioclient_mock.get(f"{BASE}/api/v1/plan/latest", status=404)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
    )
    assert result["type"] == "form"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: BASE, CONF_TOKEN: "test-token"},
    )
    assert result["type"] == "create_entry"
    assert result["data"] == {CONF_URL: BASE, CONF_TOKEN: "test-token"}


@pytest.mark.asyncio
async def test_config_flow_reports_auth_error(hass, aioclient_mock) -> None:
    aioclient_mock.get(f"{BASE}/api/v1/config", status=401)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": "user"},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_URL: BASE, CONF_TOKEN: "bad"},
    )
    assert result["errors"] == {"base": "invalid_auth"}


@pytest.mark.asyncio
async def test_setup_entry_creates_entities_and_services(
    hass, aioclient_mock
) -> None:
    plan = plan_payload()
    config = {"strategy": {"objective": "minimize_cost"}}
    aioclient_mock.get(
        f"{BASE}/api/v1/health",
        json={
            "status": "ok",
            "version": "2.0.0",
            "demo": True,
            "auth_required": False,
            "plan_available": True,
            "config_hash": "a" * 64,
        },
    )
    aioclient_mock.get(f"{BASE}/api/v1/config", json=config)
    aioclient_mock.get(f"{BASE}/api/v1/plan/latest", json=plan)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE, CONF_TOKEN: "test-token"},
        unique_id=BASE,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    registry = er.async_get(hass)
    sensor_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_price_now"
    )
    assert sensor_id is not None
    state = hass.states.get(sensor_id)
    assert state is not None
    assert state.state != STATE_UNAVAILABLE

    assert hass.services.has_service(DOMAIN, "optimize")
    assert hass.services.has_service(DOMAIN, "set_strategy")
    assert hass.services.has_service(DOMAIN, "export_plan")
    assert hass.services.has_service(DOMAIN, "arm_control")
    assert hass.services.has_service(DOMAIN, "disarm_control")
    assert hass.services.has_service(DOMAIN, "apply_now")

    switch_id = registry.async_get_entity_id(
        "switch", DOMAIN, f"{entry.entry_id}_battery_control"
    )
    assert switch_id is not None
    switch_state = hass.states.get(switch_id)
    assert switch_state is not None
    assert switch_state.state == "off"


@pytest.mark.asyncio
async def test_control_loop_applies_current_battery_setpoint(
    hass, aioclient_mock
) -> None:
    now = dt_util.now()
    start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    plan = {
        "id": "plan_control",
        "created_at": now.isoformat(),
        "horizon_start": start.isoformat(),
        "horizon_end": (start + timedelta(minutes=15)).isoformat(),
        "interval_minutes": 15,
        "currency": "EUR",
        "intervals": [
            {
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=15)).isoformat(),
                "price_import_eur_kwh": 0.2,
                "price_export_eur_kwh": 0.05,
                "load_kwh": 0.0,
                "pv_kwh": 0.0,
                "battery_charge_kwh": 1.0,
                "battery_discharge_kwh": 0.0,
                "soc_pct": 55.0,
                "ev_kwh": 0.0,
                "boiler_kwh": 0.0,
                "heat_pump_kwh": 0.0,
                "machine_kwh": 0.0,
                "grid_import_kwh": 1.0,
                "grid_export_kwh": 0.0,
                "cost_eur": 0.2,
                "reason": "price_low",
                "explanation": "test",
            }
        ],
        "summary": {
            "cost_eur": 0.2,
            "baseline_cost_eur": 0.2,
            "savings_eur": 0.0,
            "import_kwh": 1.0,
            "export_kwh": 0.0,
            "pv_kwh": 0.0,
            "load_kwh": 0.0,
            "battery_cycles": 0.1,
            "terminal_soc_value_eur": 0.0,
        },
        "solver": {
            "name": "cbc",
            "status": "optimal",
            "runtime_ms": 1,
            "objective_eur": 0.2,
            "mip_gap": 0.0,
        },
        "config_hash": "a" * 64,
        "sources": {"prices": "test", "pv": "test"},
    }
    config = {
        "batteries": [
            {
                "name": "Battery",
                "setpoint_entity": "input_number.battery_setpoint",
                "mode_entity": "input_select.battery_mode",
                "mode_charge": "charge",
                "mode_discharge": "discharge",
                "mode_idle": "idle",
            }
        ]
    }
    aioclient_mock.get(
        f"{BASE}/api/v1/health",
        json={
            "status": "ok",
            "version": "2.0.0",
            "demo": True,
            "auth_required": False,
            "plan_available": True,
            "config_hash": "a" * 64,
        },
    )
    aioclient_mock.get(f"{BASE}/api/v1/config", json=config)
    aioclient_mock.get(f"{BASE}/api/v1/plan/latest", json=plan)

    hass.states.async_set("input_number.battery_setpoint", "0")
    hass.states.async_set("input_select.battery_mode", "idle")
    calls: list[ServiceCall] = []

    async def set_value(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

    async def select_option(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set(call.data["entity_id"], call.data["option"])

    hass.services.async_register("input_number", "set_value", set_value)
    hass.services.async_register("input_select", "select_option", select_option)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE, CONF_TOKEN: "test-token"},
        unique_id=BASE,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(DOMAIN, "arm_control", {}, blocking=True)
    await hass.async_block_till_done()

    assert any(
        call.data.get("value") == 4000 for call in calls
    )
    assert any(
        call.data.get("option") == "charge" for call in calls
    )
    assert hass.states.get("input_number.battery_setpoint").state == "4000.0"
    assert hass.states.get("input_select.battery_mode").state == "charge"

    registry = er.async_get(hass)
    status_id = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_control_status"
    )
    assert status_id is not None
    assert hass.states.get(status_id).state == "applied"
    active_id = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_control_active"
    )
    assert active_id is not None
    assert hass.states.get(active_id).state == "on"


@pytest.mark.asyncio
async def test_control_loop_unsigned_direction_and_operating_mode(
    hass, aioclient_mock
) -> None:
    now = dt_util.now()
    start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    plan = {
        "id": "plan_anker",
        "created_at": now.isoformat(),
        "horizon_start": start.isoformat(),
        "horizon_end": (start + timedelta(minutes=15)).isoformat(),
        "interval_minutes": 15,
        "currency": "EUR",
        "intervals": [
            {
                "start": start.isoformat(),
                "end": (start + timedelta(minutes=15)).isoformat(),
                "price_import_eur_kwh": 0.2,
                "price_export_eur_kwh": 0.05,
                "load_kwh": 0.0,
                "pv_kwh": 0.0,
                "battery_charge_kwh": 1.0,
                "battery_discharge_kwh": 0.0,
                "soc_pct": 55.0,
                "ev_kwh": 0.0,
                "boiler_kwh": 0.0,
                "heat_pump_kwh": 0.0,
                "machine_kwh": 0.0,
                "grid_import_kwh": 1.0,
                "grid_export_kwh": 0.0,
                "cost_eur": 0.2,
                "reason": "price_low",
                "explanation": "test",
            }
        ],
        "summary": {
            "cost_eur": 0.2,
            "baseline_cost_eur": 0.2,
            "savings_eur": 0.0,
            "import_kwh": 1.0,
            "export_kwh": 0.0,
            "pv_kwh": 0.0,
            "load_kwh": 0.0,
            "battery_cycles": 0.1,
            "terminal_soc_value_eur": 0.0,
        },
        "solver": {
            "name": "cbc",
            "status": "optimal",
            "runtime_ms": 1,
            "objective_eur": 0.2,
            "mip_gap": 0.0,
        },
        "config_hash": "a" * 64,
        "sources": {"prices": "test", "pv": "test"},
    }
    config = {
        "batteries": [
            {
                "name": "Anker",
                "setpoint_entity": "input_number.anker_power",
                "mode_entity": "input_select.anker_direction",
                "mode_charge": "charge",
                "mode_discharge": "discharge",
                "control_mode_entity": "input_select.anker_operating_mode",
                "control_mode_value": "third_party_control",
                "control_mode_fallback": "self_consumption",
                "setpoint_is_unsigned": True,
                "max_charge_pct": 100,
            }
        ]
    }
    aioclient_mock.get(
        f"{BASE}/api/v1/health",
        json={
            "status": "ok",
            "version": "2.0.0",
            "demo": True,
            "auth_required": False,
            "plan_available": True,
            "config_hash": "a" * 64,
        },
    )
    aioclient_mock.get(f"{BASE}/api/v1/config", json=config)
    aioclient_mock.get(f"{BASE}/api/v1/plan/latest", json=plan)

    hass.states.async_set("input_number.anker_power", "0")
    hass.states.async_set("input_select.anker_direction", "idle")
    hass.states.async_set("input_select.anker_operating_mode", "self_consumption")
    calls: list[ServiceCall] = []

    async def set_value(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set(call.data["entity_id"], str(call.data["value"]))

    async def select_option(call: ServiceCall) -> None:
        calls.append(call)
        hass.states.async_set(call.data["entity_id"], call.data["option"])

    hass.services.async_register("input_number", "set_value", set_value)
    hass.services.async_register("input_select", "select_option", select_option)

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_URL: BASE, CONF_TOKEN: "test-token"},
        unique_id=BASE,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call(DOMAIN, "arm_control", {}, blocking=True)
    await hass.async_block_till_done()

    assert hass.states.get("input_select.anker_operating_mode").state == "third_party_control"
    assert hass.states.get("input_select.anker_direction").state == "charge"
    assert float(hass.states.get("input_number.anker_power").state) == 4000

    await hass.services.async_call(DOMAIN, "disarm_control", {}, blocking=True)
    await hass.async_block_till_done()

    assert float(hass.states.get("input_number.anker_power").state) == 0
    assert hass.states.get("input_select.anker_operating_mode").state == "self_consumption"
