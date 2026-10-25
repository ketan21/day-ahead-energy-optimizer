"""EV charging calendar for the DAEO integration."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import DaeoCoordinator
from .entity import DaeoEntity
from .plan import ev_windows


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the EV charging calendar."""
    coordinator: DaeoCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([DaeoEvCalendar(coordinator)])


class DaeoEvCalendar(DaeoEntity, CalendarEntity):
    """Calendar with the planned EV charging windows."""

    def __init__(self, coordinator: DaeoCoordinator) -> None:
        super().__init__(coordinator, "ev_charging", "EV charging")
        self._attr_icon = "mdi:calendar-clock"

    def _events(self) -> list[CalendarEvent]:
        events = []
        for window in ev_windows(self.plan):
            events.append(
                CalendarEvent(
                    start=window["start"],
                    end=window["end"],
                    summary="EV charging",
                    description=f"{window['kwh']:.1f} kWh",
                )
            )
        return events

    @property
    def event(self) -> CalendarEvent | None:
        now = dt_util.now()
        for event in self._events():
            if event.end > now:
                return event
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        return [
            event
            for event in self._events()
            if event.start < end_date and event.end > start_date
        ]
