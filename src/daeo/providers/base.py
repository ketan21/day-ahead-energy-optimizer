"""External price providers."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from daeo.domain.inputs import PricePoint


class ProviderError(RuntimeError):
    """Raised when an external provider cannot return usable data."""


class PriceProvider(Protocol):
    """A source of all-in prices for a time range."""

    name: str

    def fetch_prices(
        self,
        start: datetime,
        end: datetime,
        interval_minutes: int,
        *,
        export_price_eur_kwh: float = 0.0,
    ) -> list[PricePoint]:
        """Return prices covering the requested range, or raise ProviderError."""
        ...
