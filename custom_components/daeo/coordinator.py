"""Data coordinator for the DAEO integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import DaeoApi, DaeoApiError, DaeoAuthError
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DaeoData:
    """Data fetched from the engine."""

    health: dict[str, Any]
    config: dict[str, Any]
    plan: dict[str, Any] | None


class DaeoCoordinator(DataUpdateCoordinator[DaeoData]):
    """Poll the engine for health, configuration, and the latest plan."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: DaeoApi,
    ) -> None:
        self.entry = entry
        self.api = api
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> DaeoData:
        try:
            health = await self.api.async_get_health()
            config = await self.api.async_get_config()
            plan = await self.api.async_get_plan()
        except DaeoAuthError as error:
            raise ConfigEntryAuthFailed(str(error)) from error
        except DaeoApiError as error:
            raise UpdateFailed(str(error)) from error
        return DaeoData(health=health, config=config, plan=plan)
