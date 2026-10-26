"""EnergyZero public price provider.

EnergyZero publishes all-in consumer electricity prices for the Netherlands:
``all_in`` (excluding VAT) and ``all_in_with_vat`` (what a consumer pays). The
provider uses ``all_in_with_vat`` by default. The API does not publish a feed-in
price, so the caller supplies the export price.

Endpoint: ``GET https://public.api.energyzero.nl/public/v1/prices``
Query: ``date=dd-mm-yyyy``, ``interval=INTERVAL_QUARTER|INTERVAL_HOUR``,
``energyType=ENERGY_TYPE_ELECTRICITY``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from daeo.domain.inputs import PricePoint
from daeo.providers.base import ProviderError

BASE_URL = "https://public.api.energyzero.nl/public/v1/prices"

IMPORT_SERIES_KEYS = (
    "all_in_with_vat",
    "allInWithVat",
    "all_in",
    "allIn",
)
EXPORT_SERIES_KEYS = (
    "base",
    "base_with_vat",
    "baseWithVat",
)


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _parse_price(entry: dict) -> float:
    price = entry.get("price")
    if not isinstance(price, dict):
        raise ProviderError("EnergyZero returned an entry without a price object")
    value = price.get("value")
    if value is None:
        raise ProviderError("EnergyZero returned an empty price value")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise ProviderError(f"EnergyZero returned a non-numeric price: {value!r}") from error


class EnergyZeroProvider:
    """Fetch all-in EnergyZero electricity prices."""

    name = "energyzero"

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._client = client

    def fetch_prices(
        self,
        start: datetime,
        end: datetime,
        interval_minutes: int,
        *,
        export_price_eur_kwh: float | None = None,
        export_price_adder_eur_kwh: float = 0.0,
    ) -> list[PricePoint]:
        if start.tzinfo is None or end.tzinfo is None:
            raise ProviderError("EnergyZero requires timezone-aware start and end times")
        if end <= start:
            raise ProviderError("EnergyZero end must be after start")
        if interval_minutes not in (15, 60):
            raise ProviderError("EnergyZero supports 15-minute or hourly intervals only")

        interval = (
            "INTERVAL_QUARTER" if interval_minutes == 15 else "INTERVAL_HOUR"
        )
        params = {
            "date": start.strftime("%d-%m-%Y"),
            "interval": interval,
            "energyType": "ENERGY_TYPE_ELECTRICITY",
        }
        headers = {
            "Accept": "application/json",
            "User-Agent": "daeo-engine/2.0",
        }

        owned_client = self._client is None
        client = self._client or httpx.Client(timeout=self.timeout)
        try:
            response = client.get(self.base_url, params=params, headers=headers)
        except httpx.HTTPError as error:
            raise ProviderError(f"EnergyZero request failed: {error}") from error
        finally:
            if owned_client:
                client.close()

        if response.status_code != 200:
            message = self._error_message(response)
            raise ProviderError(
                f"EnergyZero returned HTTP {response.status_code}: {message}"
            )

        try:
            payload = response.json()
        except ValueError as error:
            raise ProviderError("EnergyZero returned invalid JSON") from error

        import_series = None
        for key in IMPORT_SERIES_KEYS:
            candidate = payload.get(key)
            if isinstance(candidate, list) and candidate:
                import_series = candidate
                break
        if import_series is None:
            message = payload.get("message") if isinstance(payload, dict) else None
            raise ProviderError(
                "EnergyZero did not return a price series"
                + (f": {message}" if message else "")
            )

        export_by_start: dict[datetime, float] = {}
        for key in EXPORT_SERIES_KEYS:
            candidate = payload.get(key)
            if not isinstance(candidate, list) or not candidate:
                continue
            for entry in candidate:
                try:
                    entry_start = _parse_timestamp(entry["start"]).astimezone(
                        start.tzinfo
                    )
                    export_by_start[entry_start] = _parse_price(entry)
                except (KeyError, TypeError, ValueError):
                    continue
            if export_by_start:
                break

        points: list[PricePoint] = []
        for entry in import_series:
            try:
                entry_start = _parse_timestamp(entry["start"]).astimezone(start.tzinfo)
                _parse_timestamp(entry["end"])
            except (KeyError, TypeError, ValueError) as error:
                raise ProviderError("EnergyZero returned an invalid time range") from error
            if not (start <= entry_start < end):
                continue
            if export_price_eur_kwh is not None:
                export_price = export_price_eur_kwh
            else:
                export_price = export_by_start.get(entry_start, 0.0)
            points.append(
                PricePoint(
                    start=entry_start,
                    import_eur_kwh=_parse_price(entry),
                    export_eur_kwh=export_price + export_price_adder_eur_kwh,
                )
            )

        points.sort(key=lambda point: point.start)
        if not points:
            raise ProviderError(
                "EnergyZero returned no prices for the requested range; "
                "tomorrow's day-ahead prices may not be published yet"
            )
        self._check_contiguous(points, interval_minutes)
        return points

    @staticmethod
    def _error_message(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text[:200] or "no response body"
        if isinstance(payload, dict):
            return str(payload.get("message") or payload.get("error") or payload)[:200]
        return str(payload)[:200]

    @staticmethod
    def _check_contiguous(points: list[PricePoint], interval_minutes: int) -> None:
        step = timedelta(minutes=interval_minutes)
        for previous, current in zip(points, points[1:], strict=False):
            previous_utc = previous.start.astimezone(UTC)
            current_utc = current.start.astimezone(UTC)
            if previous_utc + step != current_utc:
                raise ProviderError(
                    "EnergyZero returned a gap in the price series "
                    f"between {previous.start.isoformat()} and {current.start.isoformat()}"
                )
