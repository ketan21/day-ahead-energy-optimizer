"""DAEO engine integration for Home Assistant."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval

from .api import DaeoApi
from .const import (
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    PLATFORMS,
    STRATEGY_OPTIONS,
)
from .control_loop import TICK_INTERVAL, BatteryController
from .coordinator import DaeoCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_OPTIMIZE = "optimize"
SERVICE_SET_STRATEGY = "set_strategy"
SERVICE_EXPORT_PLAN = "export_plan"
SERVICE_ARM_CONTROL = "arm_control"
SERVICE_DISARM_CONTROL = "disarm_control"
SERVICE_APPLY_NOW = "apply_now"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a DAEO engine config entry."""
    api = DaeoApi(
        async_get_clientsession(hass),
        entry.data[CONF_URL],
        entry.data[CONF_TOKEN],
    )
    coordinator = DaeoCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    controller = BatteryController(hass, entry, coordinator)

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "api": api,
        "coordinator": coordinator,
        "controller": controller,
    }
    entry.async_on_unload(
        async_track_time_interval(hass, controller.async_tick, TICK_INTERVAL)
    )
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _async_register_services(hass)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a DAEO config entry."""
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if data and data.get("controller"):
        await data["controller"].async_shutdown()
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            for service in (
                SERVICE_OPTIMIZE,
                SERVICE_SET_STRATEGY,
                SERVICE_EXPORT_PLAN,
                SERVICE_ARM_CONTROL,
                SERVICE_DISARM_CONTROL,
                SERVICE_APPLY_NOW,
            ):
                hass.services.async_remove(DOMAIN, service)
            hass.data.pop(DOMAIN, None)
    return unloaded


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


def _entry_data(hass: HomeAssistant) -> dict[str, Any]:
    entries = hass.data.get(DOMAIN)
    if not entries:
        raise HomeAssistantError("No DAEO engine is configured")
    return next(iter(entries.values()))


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_OPTIMIZE):
        return

    async def async_optimize(call: ServiceCall) -> None:
        data = _entry_data(hass)
        controller = data["controller"]
        if not await controller.async_optimize_live():
            raise HomeAssistantError(
                controller.last_error or "Plan refresh with live SOC failed"
            )
        await data["coordinator"].async_request_refresh()

    async def async_set_strategy(call: ServiceCall) -> None:
        objective = call.data["objective"]
        if objective not in STRATEGY_OPTIONS:
            raise HomeAssistantError(
                f"Unknown objective {objective!r}; expected one of {STRATEGY_OPTIONS}"
            )
        data = _entry_data(hass)
        await data["api"].async_set_strategy(objective)
        await data["coordinator"].async_request_refresh()

    async def async_export_plan(call: ServiceCall) -> ServiceResponse:
        data = _entry_data(hass)
        plan = await data["api"].async_export_plan()
        return ServiceResponse(data={"plan": plan})

    async def async_arm_control(call: ServiceCall) -> None:
        controller = _entry_data(hass)["controller"]
        await controller.async_set_armed(True)

    async def async_disarm_control(call: ServiceCall) -> None:
        controller = _entry_data(hass)["controller"]
        await controller.async_set_armed(False)

    async def async_apply_now(call: ServiceCall) -> None:
        controller = _entry_data(hass)["controller"]
        await controller.async_tick()

    hass.services.async_register(DOMAIN, SERVICE_OPTIMIZE, async_optimize)
    hass.services.async_register(DOMAIN, SERVICE_SET_STRATEGY, async_set_strategy)
    hass.services.async_register(
        DOMAIN,
        SERVICE_EXPORT_PLAN,
        async_export_plan,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(DOMAIN, SERVICE_ARM_CONTROL, async_arm_control)
    hass.services.async_register(DOMAIN, SERVICE_DISARM_CONTROL, async_disarm_control)
    hass.services.async_register(DOMAIN, SERVICE_APPLY_NOW, async_apply_now)
