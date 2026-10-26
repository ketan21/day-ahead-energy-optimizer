"""Closed enums shared by the domain, configuration, and API.

All values are stable English identifiers. Display strings are produced by the UI.
"""

from enum import StrEnum


class Country(StrEnum):
    """Supported market countries."""

    NL = "NL"
    BE = "BE"


class PriceSource(StrEnum):
    """Where day-ahead prices come from."""

    ENTSOE = "entsoe"
    NORDPOOL = "nordpool"
    TIBBER = "tibber"
    ENERGYZERO = "energyzero"
    HA_SENSOR = "ha_sensor"
    FIXED = "fixed"


class LoadSource(StrEnum):
    """Where the household load profile comes from."""

    SYNTHETIC = "synthetic"
    RECORDER = "recorder"


class SolarForecastSource(StrEnum):
    """Where the PV forecast comes from."""

    SYNTHETIC = "synthetic"
    FORECAST_SOLAR = "forecast_solar"


class TariffPreset(StrEnum):
    """Tax and tariff preset."""

    NL = "nl"
    BE = "be"
    CUSTOM = "custom"


class Objective(StrEnum):
    """Optimization objective."""

    MINIMIZE_COST = "minimize_cost"
    MINIMIZE_IMPORT = "minimize_import"


class GridMode(StrEnum):
    """How the plan treats grid exchange."""

    SELF_CONSUMPTION = "self_consumption"
    ARBITRAGE = "arbitrage"


class Interval(StrEnum):
    """Optimization interval."""

    QUARTER_HOUR = "quarter_hour"
    HOUR = "hour"

    @property
    def minutes(self) -> int:
        return 15 if self is Interval.QUARTER_HOUR else 60


class TaskAction(StrEnum):
    """Scheduled engine actions."""

    FETCH_PRICES = "fetch_prices"
    FETCH_WEATHER = "fetch_weather"
    OPTIMIZE = "optimize"
    CALCULATE_BASELOAD = "calculate_baseload"
    CLEAN_DATA = "clean_data"
    TRAIN_MODELS = "train_models"


class Reason(StrEnum):
    """Why the optimizer chose an interval's setpoints."""

    PRICE_LOW = "price_low"
    PRICE_HIGH = "price_high"
    PV_SURPLUS = "pv_surplus"
    SOC_MIN = "soc_min"
    SOC_MAX = "soc_max"
    EV_DEADLINE = "ev_deadline"
    BOILER_DEMAND = "boiler_demand"
    HEAT_DEMAND = "heat_demand"
    MACHINE_DEADLINE = "machine_deadline"
    GRID_LIMIT = "grid_limit"
    IDLE = "idle"


class PlanStatus(StrEnum):
    """Solver outcome."""

    OPTIMAL = "optimal"
    FEASIBLE = "feasible"
    INFEASIBLE = "infeasible"
    UNKNOWN = "unknown"


class RunStatus(StrEnum):
    """Job lifecycle."""

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
