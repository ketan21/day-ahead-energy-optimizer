"""Config flow for the DAEO integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import DaeoApi, DaeoApiError, DaeoAuthError, DaeoConnectionError
from .const import CONF_TOKEN, CONF_URL, DEFAULT_URL, DOMAIN, NAME


class DaeoConfigFlow(ConfigFlow, domain=DOMAIN):
    """Connect Home Assistant to a DAEO engine."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            token = user_input[CONF_TOKEN].strip()
            api = DaeoApi(async_get_clientsession(self.hass), url, token)
            try:
                await api.async_get_config()
            except DaeoAuthError:
                errors["base"] = "invalid_auth"
            except DaeoConnectionError:
                errors["base"] = "cannot_connect"
            except DaeoApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(url)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=NAME,
                    data={CONF_URL: url, CONF_TOKEN: token},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_URL, default=DEFAULT_URL): str,
                    vol.Required(CONF_TOKEN): str,
                }
            ),
            errors=errors,
        )
