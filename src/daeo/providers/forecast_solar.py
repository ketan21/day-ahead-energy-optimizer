"""Forecast.Solar PV provider.

Forecast.Solar returns a location-aware PV estimate without an API key for small
systems. The provider calls:

``GET https://api.forecast.solar/estimate/{lat}/{lon}/{tilt}/{azimuth}/{kwp}``

Forecast.Solar uses ``azimuth=0`` for south, negative for east, positive for west.
DAEO stores ``azimuth_deg`` with 180 = south, so the provider converts it. The
response contains local naive timestamps; they are attached to the configured home
timezone.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from daeo.providers.base import ProviderError

BASE_URL = "https://api.forecast.solar/estimate"


@dataclass(frozen=True)
class SolarArray:
    """One array as needed by Forecast.Solar."""

    peak_power_kwp: float
    tilt_deg: float = 35.0
    azimuth_deg: float = 180.0

    @property
    def forecast_solar_azimuth(self) -> int:
        # Forecast.Solar: 0 = south, -90 = east, +90 = west.
        return int(round(self.azimuth_deg - 180))


def _parse_local(value: str, zone: ZoneInfo) -> datetime:
    return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=zone)


def _latest_power(series: list[tuple[datetime, float]], moment: datetime) -> float:
    """Return the power at the latest sample at or before ``moment``."""
    power = 0.0
    for sample_time, sample_power in series:
        if sample_time > moment:
            break
        power = sample_power
    return power


class ForecastSolarProvider:
    """Fetch a PV forecast from Forecast.Solar."""

    name = "forecast_solar"

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client
        self._cache: dict[tuple, tuple[float, list[tuple[datetime, float]]]] = {}

    def fetch_pv(
        self,
        start: datetime,
        end: datetime,
        interval_minutes: int,
        arrays: list[SolarArray],
        *,
        latitude: float,
        longitude: float,
        timezone: str | None = None,
    ) -> list[float]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ProviderError("Forecast.Solar requires timezone-aware start and end times")
        if end <= start:
            raise ProviderError("Forecast.Solar end must be after start")
        if interval_minutes not in (15, 30, 60):
            raise ProviderError("Forecast.Solar supports 15, 30, or 60 minute intervals")
        count = self._count(start, end, interval_minutes)
        if not arrays:
            return [0.0] * count

        try:
            zone = ZoneInfo(timezone) if timezone else start.tzinfo
        except ZoneInfoNotFoundError as error:
            raise ProviderError(f"Unknown timezone for Forecast.Solar: {timezone}") from error

        total_power: list[float] = [0.0] * count
        for array in arrays:
            series = self._fetch_array(
                latitude=latitude,
                longitude=longitude,
                array=array,
                zone=zone,
            )
            for index in range(count):
                moment = start + timedelta(minutes=index * interval_minutes)
                total_power[index] += _latest_power(series, moment)

        interval_h = interval_minutes / 60
        return [
            round(max(0.0, power) * interval_h / 1000, 6)
            for power in total_power
        ]

    @staticmethod
    def _count(start: datetime, end: datetime, interval_minutes: int) -> int:
        return max(1, int(math.ceil((end - start).total_seconds() / 60 / interval_minutes)))

    def _fetch_array(
        self,
        *,
        latitude: float,
        longitude: float,
        array: SolarArray,
        zone: ZoneInfo,
    ) -> list[tuple[datetime, float]]:
        if array.peak_power_kwp <= 0:
            return []
        cache_key = (round(latitude, 4), round(longitude, 4), array)
        cached = self._cache.get(cache_key)
        if cached is not None and time.monotonic() - cached[0] < 900:
            return cached[1]
        url = (
            f"{self.base_url}/{latitude:.4f}/{longitude:.4f}/"
            f"{array.tilt_deg:.0f}/{array.forecast_solar_azimuth}/"
            f"{array.peak_power_kwp:.3f}"
        )
        owned_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            response = client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as error:
            raise ProviderError(f"Forecast.Solar request failed: {error}") from error
        finally:
            if owned_client:
                client.close()

        if response.status_code == 429:
            raise ProviderError(
                "Forecast.Solar rate limit reached (12 requests per hour per IP)"
            )
        if response.status_code != 200:
            raise ProviderError(
                f"Forecast.Solar returned HTTP {response.status_code}: {response.text[:200]}"
            )
        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError("Forecast.Solar returned invalid JSON") from error

        message = payload.get("message") or {}
        if message.get("code") not in (0, None):
            raise ProviderError(
                f"Forecast.Solar error: {message.get('text') or message.get('code')}"
            )
        result = payload.get("result") or {}
        watts = result.get("watts")
        if not isinstance(watts, dict) or not watts:
            raise ProviderError("Forecast.Solar returned no watts series")

        series: list[tuple[datetime, float]] = []
        for timestamp, value in watts.items():
            try:
                series.append((_parse_local(timestamp, zone), float(value)))
            except (TypeError, ValueError) as error:
                raise ProviderError(
                    f"Forecast.Solar returned an invalid sample: {timestamp!r}"
                ) from error
        series.sort(key=lambda item: item[0])
        self._cache[cache_key] = (time.monotonic(), series)
        return series
