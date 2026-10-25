"""Diagnostics for the DAEO integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_TOKEN, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return redacted diagnostics."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    controller = data.get("controller")
    entry_data = dict(entry.data)
    entry_data[CONF_TOKEN] = "**REDACTED**"
    control = None
    if controller is not None:
        control = {
            "armed": controller.armed,
            "status": controller.status,
            "last_power_w": controller.last_power_w,
            "last_mode": controller.last_mode,
            "last_apply": (
                controller.last_apply.isoformat() if controller.last_apply else None
            ),
            "last_error": controller.last_error,
            "audit": controller.audit,
        }
    return {
        "entry": entry_data,
        "health": coordinator.data.health if coordinator.data else None,
        "plan": coordinator.data.plan if coordinator.data else None,
        "config": coordinator.data.config if coordinator.data else None,
        "control": control,
    }
