"""Battery control switch for the DAEO integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .control_loop import BatteryController
from .coordinator import DaeoCoordinator
from .entity import DaeoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the battery control switch."""
    data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [DaeoBatteryControlSwitch(data["coordinator"], data["controller"])]
    )


class DaeoBatteryControlSwitch(DaeoEntity, SwitchEntity):
    """Explicit arming switch for battery control."""

    _attr_name = "Battery control"
    _attr_icon = "mdi:battery-sync"

    def __init__(
        self,
        coordinator: DaeoCoordinator,
        controller: BatteryController,
    ) -> None:
        super().__init__(coordinator, "battery_control", "Battery control")
        self.controller = controller

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.controller.add_listener(self.async_write_ha_state)
        )

    @property
    def is_on(self) -> bool:
        return self.controller.armed

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "status": self.controller.status,
            "last_power_w": self.controller.last_power_w,
            "last_error": self.controller.last_error,
        }

    async def async_turn_on(self, **kwargs) -> None:
        await self.controller.async_set_armed(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        await self.controller.async_set_armed(False)
        self.async_write_ha_state()
