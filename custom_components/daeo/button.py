"""Buttons for the DAEO integration."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
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
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaeoCoordinator = data["coordinator"]
    controller = data["controller"]
    async_add_entities(
        DaeoButton(coordinator, controller, description) for description in BUTTONS
    )


class DaeoButton(DaeoEntity, ButtonEntity):
    """A button that triggers an engine action."""

    entity_description: ButtonEntityDescription

    def __init__(
        self,
        coordinator: DaeoCoordinator,
        controller,
        description: ButtonEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.name)
        self.controller = controller
        self.entity_description = description

    async def async_press(self) -> None:
        if self.entity_description.key == "run_optimization":
            if not await self.controller.async_optimize_live():
                raise HomeAssistantError(
                    self.controller.last_error or "Plan refresh with live SOC failed"
                )
            await self.coordinator.async_request_refresh()
