"""Strategy selector for the DAEO integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, STRATEGY_OPTIONS
from .coordinator import DaeoCoordinator
from .entity import DaeoEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the strategy selector."""
    coordinator: DaeoCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([DaeoStrategySelect(coordinator)])


class DaeoStrategySelect(DaeoEntity, SelectEntity):
    """Select the optimization objective."""

    _attr_options = STRATEGY_OPTIONS
    _attr_icon = "mdi:target"

    def __init__(self, coordinator: DaeoCoordinator) -> None:
        super().__init__(coordinator, "strategy", "Strategy")

    @property
    def current_option(self) -> str | None:
        return self.config.get("strategy", {}).get("objective")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.api.async_set_strategy(option)
        await self.coordinator.async_request_refresh()
