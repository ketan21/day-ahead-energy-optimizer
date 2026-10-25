"""Buttons for the DAEO integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DaeoCoordinator
from .entity import DaeoEntity

BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(
        key="run_optimization",
        name="Run optimization",
        icon="mdi:play",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DAEO buttons."""
    coordinator: DaeoCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(DaeoButton(coordinator, description) for description in BUTTONS)


class DaeoButton(DaeoEntity, ButtonEntity):
    """A button that triggers an engine action."""

    entity_description: ButtonEntityDescription

    def __init__(
        self,
        coordinator: DaeoCoordinator,
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.name)
        self.entity_description = description

    async def async_press(self) -> None:
        if self.entity_description.key == "run_optimization":
            await self.coordinator.api.async_optimize()
            await self.coordinator.async_request_refresh()
