"""EnergyZero provider tests."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from daeo.providers.base import ProviderError
from daeo.providers.energyzero import EnergyZeroProvider

TZ = ZoneInfo("Europe/Amsterdam")
START = datetime(2026, 11, 15, 12, 0, tzinfo=TZ)
END = datetime(2026, 11, 15, 12, 45, tzinfo=TZ)


def _entry(start: str, end: str, value: str) -> dict:
    return {"start": start, "end": end, "price": {"value": value}}


def _payload(series_key: str = "all_in_with_vat") -> dict:
    return {
        "interval": "RESPONSE_INTERVAL_QUARTER",
        "range": {
            "start": "2026-11-14T23:00:00Z",
            "end": "2026-11-15T23:00:00Z",
        },
        series_key: [
            _entry(
                "2026-11-15T10:45:00Z",
                "2026-11-15T11:00:00Z",
                "9.99",
            ),
            _entry(
                "2026-11-15T11:00:00Z",
                "2026-11-15T11:15:00Z",
                "0.31",
            ),
            _entry(
                "2026-11-15T11:15:00Z",
                "2026-11-15T11:30:00Z",
                "0.32",
            ),
            _entry(
                "2026-11-15T11:30:00Z",
                "2026-11-15T11:45:00Z",
                "0.33",
            ),
        ],
    }


def _provider(payload: dict, status_code: int = 200, check=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if check is not None:
            check(request)
        return httpx.Response(status_code, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    return EnergyZeroProvider(client=client)


def test_fetch_prices_parses_all_in_values() -> None:
    def check(request: httpx.Request) -> None:
        assert request.url.params["date"] == "15-11-2026"
        assert request.url.params["interval"] == "INTERVAL_QUARTER"
        assert request.url.params["energyType"] == "ENERGY_TYPE_ELECTRICITY"

    provider = _provider(_payload(), check=check)
    prices = provider.fetch_prices(START, END, 15, export_price_eur_kwh=0.05)

    assert [point.import_eur_kwh for point in prices] == [0.31, 0.32, 0.33]
    assert [point.export_eur_kwh for point in prices] == [0.05, 0.05, 0.05]
    assert prices[0].start == START
    assert prices[0].start.utcoffset().total_seconds() == 3600
    assert prices[1].start == START.replace(minute=15)


def test_fallback_to_all_in_without_vat() -> None:
    provider = _provider(_payload("all_in"))
    prices = provider.fetch_prices(START, END, 15)
    assert [point.import_eur_kwh for point in prices] == [0.31, 0.32, 0.33]


def test_http_error_is_reported() -> None:
    provider = _provider(
        {"code": 5, "message": "prices do not span the whole requested date"},
        status_code=404,
    )
    with pytest.raises(ProviderError, match="HTTP 404"):
        provider.fetch_prices(START, END, 15)


def test_missing_series_is_reported() -> None:
    provider = _provider({"interval": "RESPONSE_INTERVAL_QUARTER"})
    with pytest.raises(ProviderError, match="did not return a price series"):
        provider.fetch_prices(START, END, 15)


def test_gap_is_reported() -> None:
    payload = _payload()
    payload["all_in_with_vat"] = [
        payload["all_in_with_vat"][0],
        payload["all_in_with_vat"][1],
        payload["all_in_with_vat"][3],
    ]
    provider = _provider(payload)
    with pytest.raises(ProviderError, match="gap"):
        provider.fetch_prices(START, END, 15)


def test_unsupported_interval_is_reported() -> None:
    provider = _provider(_payload())
    with pytest.raises(ProviderError, match="15-minute or hourly"):
        provider.fetch_prices(START, END, 30)


def test_naive_datetime_is_reported() -> None:
    provider = _provider(_payload())
    with pytest.raises(ProviderError, match="timezone-aware"):
        provider.fetch_prices(
            START.replace(tzinfo=None),
            END.replace(tzinfo=None),
            15,
        )
