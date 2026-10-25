"""HTTP client for the DAEO engine."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from .const import CONF_TOKEN, CONF_URL


class DaeoApiError(Exception):
    """The engine returned an error."""


class DaeoAuthError(DaeoApiError):
    """The engine rejected the token."""


class DaeoConnectionError(DaeoApiError):
    """The engine could not be reached."""


class DaeoApi:
    """Small async client for the engine API."""

    def __init__(self, session: aiohttp.ClientSession, url: str, token: str) -> None:
        self.session = session
        self.base_url = url.rstrip("/")
        self.token = token

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        allow_404: bool = False,
    ) -> Any:
        url = f"{self.base_url}{path}"
        try:
            async with asyncio.timeout(20):
                response = await self.session.request(
                    method,
                    url,
                    headers=self.headers,
                    json=payload,
                )
        except (TimeoutError, aiohttp.ClientError) as error:
            raise DaeoConnectionError(f"Cannot reach {url}: {error}") from error

        if response.status in (401, 403):
            raise DaeoAuthError("The engine rejected the API token")
        if response.status == 404 and allow_404:
            return None
        if response.status >= 400:
            text = await response.text()
            raise DaeoApiError(f"Engine returned HTTP {response.status}: {text[:200]}")
        if response.status == 204:
            return None
        return await response.json()

    async def async_get_health(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/health")

    async def async_get_config(self) -> dict[str, Any]:
        return await self._request("GET", "/api/v1/config")

    async def async_get_plan(self) -> dict[str, Any] | None:
        return await self._request("GET", "/api/v1/plan/latest", allow_404=True)

    async def async_optimize(
        self,
        battery_soc_pct: float | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if battery_soc_pct is not None:
            payload["battery_soc_pct"] = battery_soc_pct
        return await self._request("POST", "/api/v1/optimize", payload=payload)

    async def async_set_strategy(self, objective: str) -> dict[str, Any]:
        config = await self.async_get_config()
        config.setdefault("strategy", {})["objective"] = objective
        return await self._request("PUT", "/api/v1/config", payload=config)

    async def async_export_plan(self) -> dict[str, Any] | None:
        return await self.async_get_plan()


def entry_to_api(data: dict[str, Any]) -> tuple[str, str]:
    """Extract URL and token from a config entry."""
    return data[CONF_URL], data[CONF_TOKEN]
