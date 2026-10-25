"""Binary sensors for the DAEO integration."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PLAN_MAX_AGE_SECONDS, PLAN_STALE_SECONDS
from .control_loop import BatteryController
from .coordinator import DaeoCoordinator
from .entity import DaeoEntity
from .plan import plan_age_seconds, plan_is_valid

BINARY_SENSORS: tuple[BinarySensorEntityDescription, ...] = (
    BinarySensorEntityDescription(
        key="plan_valid",
        name="Plan valid",
        icon="mdi:check-decagram-outline",
    ),
    BinarySensorEntityDescription(
        key="data_stale",
        name="Data stale",
        device_class=BinarySensorDeviceClass.PROBLEM,
        icon="mdi:alert-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DAEO binary sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaeoCoordinator = data["coordinator"]
    controller: BatteryController = data["controller"]
    async_add_entities(
        [
            *(DaeoBinarySensor(coordinator, description) for description in BINARY_SENSORS),
            DaeoControlActiveBinarySensor(coordinator, controller),
        ]
    )


class DaeoBinarySensor(DaeoEntity, BinarySensorEntity):
    """Plan validity and staleness."""

    entity_description: BinarySensorEntityDescription

    def __init__(
        self,
        coordinator: DaeoCoordinator,
        description: BinarySensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.name)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        plan = self.plan
        now = dt_util.now()
        if self.entity_description.key == "plan_valid":
            return plan_is_valid(
                plan,
                self.health.get("config_hash"),
                now,
                PLAN_MAX_AGE_SECONDS,
            )
        age = plan_age_seconds(plan, now)
        return plan is None or age is None or age > PLAN_STALE_SECONDS

    @property
    def extra_state_attributes(self) -> dict:
        plan = self.plan
        return {
            "plan_id": plan.get("id") if plan else None,
            "plan_age_seconds": plan_age_seconds(plan, dt_util.now()),
            "config_hash": plan.get("config_hash") if plan else None,
        }


class DaeoControlActiveBinarySensor(DaeoEntity, BinarySensorEntity):
    """Whether the controller is armed and the current plan is applied."""

    _attr_name = "Control active"
    _attr_icon = "mdi:battery-lock-open"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        coordinator: DaeoCoordinator,
        controller: BatteryController,
    ) -> None:
        super().__init__(coordinator, "control_active", "Control active")
        self.controller = controller

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.controller.add_listener(self.async_write_ha_state)
        )

    @property
    def is_on(self) -> bool:
        return self.controller.active

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "status": self.controller.status,
            "last_error": self.controller.last_error,
        }
