"""Forecast.Solar provider tests."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from daeo.providers.base import ProviderError
from daeo.providers.forecast_solar import ForecastSolarProvider, SolarArray

TZ = ZoneInfo("Europe/Amsterdam")
START = datetime(2026, 11, 15, 11, 0, tzinfo=TZ)
END = datetime(2026, 11, 15, 13, 0, tzinfo=TZ)


def _payload(watts: dict | None = None) -> dict:
    return {
        "result": {
            "watts": watts
            if watts is not None
            else {
                "2026-11-15 10:00:00": 0,
                "2026-11-15 11:00:00": 1000,
                "2026-11-15 12:00:00": 2000,
            }
        },
        "message": {"code": 0, "type": "success", "text": ""},
    }


def _provider(payload: dict, status_code: int = 200, check=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if check is not None:
            check(request)
        return httpx.Response(status_code, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return ForecastSolarProvider(client=client)


def test_fetch_pv_returns_kwh_per_interval() -> None:
    def check(request: httpx.Request) -> None:
        assert request.url.path == "/estimate/52.3700/4.8900/35/0/5.000"

    provider = _provider(_payload(), check=check)
    pv = provider.fetch_pv(
        START,
        END,
        60,
        [SolarArray(peak_power_kwp=5, tilt_deg=35, azimuth_deg=180)],
        latitude=52.37,
        longitude=4.89,
        timezone="Europe/Amsterdam",
    )
    assert pv == [1.0, 2.0]


def test_fetch_pv_uses_latest_sample_for_subhourly_intervals() -> None:
    provider = _provider(_payload())
    pv = provider.fetch_pv(
        datetime(2026, 11, 15, 11, 30, tzinfo=TZ),
        datetime(2026, 11, 15, 13, 30, tzinfo=TZ),
        60,
        [SolarArray(peak_power_kwp=5)],
        latitude=52.37,
        longitude=4.89,
        timezone="Europe/Amsterdam",
    )
    assert pv == [1.0, 2.0]


def test_multiple_arrays_are_summed() -> None:
    provider = _provider(_payload())
    pv = provider.fetch_pv(
        START,
        END,
        60,
        [
            SolarArray(peak_power_kwp=5, tilt_deg=35, azimuth_deg=180),
            SolarArray(peak_power_kwp=5, tilt_deg=35, azimuth_deg=180),
        ],
        latitude=52.37,
        longitude=4.89,
        timezone="Europe/Amsterdam",
    )
    assert pv == [2.0, 4.0]


def test_rate_limit_is_reported() -> None:
    provider = _provider({"message": {"code": 0}}, status_code=429)
    with pytest.raises(ProviderError, match="rate limit"):
        provider.fetch_pv(
            START,
            END,
            60,
            [SolarArray(peak_power_kwp=5)],
            latitude=52.37,
            longitude=4.89,
        )


def test_error_message_is_reported() -> None:
    provider = _provider({"message": {"code": 1, "text": "bad location"}})
    with pytest.raises(ProviderError, match="bad location"):
        provider.fetch_pv(
            START,
            END,
            60,
            [SolarArray(peak_power_kwp=5)],
            latitude=52.37,
            longitude=4.89,
        )


def test_missing_watts_is_reported() -> None:
    provider = _provider({"result": {}, "message": {"code": 0}})
    with pytest.raises(ProviderError, match="no watts series"):
        provider.fetch_pv(
            START,
            END,
            60,
            [SolarArray(peak_power_kwp=5)],
            latitude=52.37,
            longitude=4.89,
        )


def test_no_arrays_returns_zeros() -> None:
    provider = _provider(_payload())
    pv = provider.fetch_pv(
        START,
        END,
        60,
        [],
        latitude=52.37,
        longitude=4.89,
    )
    assert pv == [0.0, 0.0]
