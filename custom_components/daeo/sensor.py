"""Sensors for the DAEO integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .control_loop import BatteryController
from .coordinator import DaeoCoordinator
from .entity import DaeoEntity
from .plan import battery_action, current_interval, plan_age_seconds

SENSORS: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="price_now",
        name="Price now",
        native_unit_of_measurement="EUR/kWh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:currency-eur",
    ),
    SensorEntityDescription(
        key="plan_cost",
        name="Plan cost",
        native_unit_of_measurement="EUR",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash",
    ),
    SensorEntityDescription(
        key="expected_savings",
        name="Expected savings",
        native_unit_of_measurement="EUR",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:piggy-bank",
    ),
    SensorEntityDescription(
        key="pv_forecast",
        name="PV forecast",
        native_unit_of_measurement="kWh",
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:solar-power",
    ),
    SensorEntityDescription(
        key="battery_target_soc",
        name="Battery target SOC",
        native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:battery",
    ),
    SensorEntityDescription(
        key="next_battery_action",
        name="Next battery action",
        device_class=SensorDeviceClass.ENUM,
        options=["charging", "discharging", "idle", "unknown"],
        icon="mdi:battery-sync",
    ),
    SensorEntityDescription(
        key="plan_age",
        name="Plan age",
        native_unit_of_measurement=UnitOfTime.SECONDS,
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        icon="mdi:timer-outline",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up DAEO sensors."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DaeoCoordinator = data["coordinator"]
    controller: BatteryController = data["controller"]
    async_add_entities(
        [
            *(DaeoSensor(coordinator, description) for description in SENSORS),
            DaeoControlStatusSensor(coordinator, controller),
            DaeoBatterySetpointSensor(coordinator, controller),
        ]
    )


class DaeoSensor(DaeoEntity, SensorEntity):
    """A sensor derived from the latest plan."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: DaeoCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        super().__init__(coordinator, description.key, description.name)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        plan = self.plan
        now = dt_util.now()
        interval = current_interval(plan, now)
        key = self.entity_description.key
        if plan is None:
            return None
        if key == "price_now":
            return round(interval["price_import_eur_kwh"], 5) if interval else None
        if key == "plan_cost":
            return plan["summary"]["cost_eur"]
        if key == "expected_savings":
            return plan["summary"]["savings_eur"]
        if key == "pv_forecast":
            return plan["summary"]["pv_kwh"]
        if key == "battery_target_soc":
            return round(interval["soc_pct"], 1) if interval else None
        if key == "next_battery_action":
            return battery_action(interval)
        if key == "plan_age":
            age = plan_age_seconds(plan, now)
            return round(age) if age is not None else None
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        plan = self.plan
        if plan is None:
            return {}
        interval = current_interval(plan, dt_util.now())
        attributes: dict[str, Any] = {
            "plan_id": plan.get("id"),
            "horizon_start": plan.get("horizon_start"),
            "horizon_end": plan.get("horizon_end"),
            "sources": plan.get("sources", {}),
        }
        if interval:
            attributes.update(
                {
                    "interval_start": interval.get("start"),
                    "interval_end": interval.get("end"),
                    "reason": interval.get("reason"),
                    "explanation": interval.get("explanation"),
                }
            )
        return attributes


class DaeoControlStatusSensor(DaeoEntity, SensorEntity):
    """Battery control status."""

    _attr_icon = "mdi:shield-check-outline"

    def __init__(
        self,
        coordinator: DaeoCoordinator,
        controller: BatteryController,
    ) -> None:
        super().__init__(coordinator, "control_status", "Control status")
        self.controller = controller

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.controller.add_listener(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> str:
        return self.controller.status

    @property
    def extra_state_attributes(self) -> dict:
        last_apply = self.controller.last_apply
        return {
            "armed": self.controller.armed,
            "last_power_w": self.controller.last_power_w,
            "last_mode": self.controller.last_mode,
            "last_apply": last_apply.isoformat() if last_apply else None,
            "last_error": self.controller.last_error,
            "audit": self.controller.audit[-5:],
        }


class DaeoBatterySetpointSensor(DaeoEntity, SensorEntity):
    """Last battery power setpoint written by the controller."""

    _attr_icon = "mdi:flash"
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_device_class = SensorDeviceClass.POWER
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: DaeoCoordinator,
        controller: BatteryController,
    ) -> None:
        super().__init__(coordinator, "battery_setpoint", "Battery setpoint")
        self.controller = controller

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            self.controller.add_listener(self.async_write_ha_state)
        )

    @property
    def native_value(self) -> float | None:
        return self.controller.last_power_w

    @property
    def extra_state_attributes(self) -> dict:
        return {
            "mode": self.controller.last_mode,
            "status": self.controller.status,
        }
