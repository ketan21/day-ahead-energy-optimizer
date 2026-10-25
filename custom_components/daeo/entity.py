"""Base entity for the DAEO integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, NAME, VERSION
from .coordinator import DaeoCoordinator


class DaeoEntity(CoordinatorEntity[DaeoCoordinator]):
    """Base class with shared device information."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: DaeoCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_name = name
        health = coordinator.data.health if coordinator.data else {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model="Engine",
            sw_version=health.get("version", VERSION),
        )

    @property
    def plan(self) -> dict | None:
        return self.coordinator.data.plan if self.coordinator.data else None

    @property
    def config(self) -> dict:
        return self.coordinator.data.config if self.coordinator.data else {}

    @property
    def health(self) -> dict:
        return self.coordinator.data.health if self.coordinator.data else {}
