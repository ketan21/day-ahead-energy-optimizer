"""Inputs to the solver boundary.

The solver receives only validated values. It does not read configuration files,
databases, Home Assistant, or the clock. Callers build these objects from providers
and configuration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from daeo.domain.enums import Objective


class PricePoint(BaseModel):
    """Import and export price for one interval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime = Field(description="Interval start (timezone-aware).")
    import_eur_kwh: float
    export_eur_kwh: float

    @model_validator(mode="after")
    def check_aware(self) -> Self:
        if self.start.tzinfo is None:
            raise ValueError("price start must be timezone-aware")
        return self


class SolarInput(BaseModel):
    """One PV array."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    peak_power_kw: float = Field(gt=0)
    dc_coupled: bool = False


class BatteryStage(BaseModel):
    """One AC-side power/efficiency point for a battery stage curve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    power_kw: float = Field(ge=0)
    efficiency: float = Field(gt=0, le=1)


class SocPowerLimit(BaseModel):
    """Maximum battery power at a given SOC."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    soc_pct: float = Field(ge=0, le=100)
    power_kw: float = Field(ge=0)


class BatteryInput(BaseModel):
    """Battery specification and initial state."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    capacity_kwh: float = Field(gt=0)
    max_charge_kw: float = Field(gt=0)
    max_discharge_kw: float = Field(gt=0)
    efficiency: float = Field(default=0.95, gt=0, le=1)
    min_soc_pct: float = Field(default=20, ge=0, le=100)
    max_soc_pct: float = Field(default=100, ge=0, le=100)
    initial_soc_pct: float = Field(default=50, ge=0, le=100)
    charge_stages: list[BatteryStage] = Field(default_factory=list)
    discharge_stages: list[BatteryStage] = Field(default_factory=list)
    dc_to_bat_efficiency: float = Field(default=1.0, gt=0, le=1)
    bat_to_dc_efficiency: float = Field(default=1.0, gt=0, le=1)
    minimum_power_kw: float = Field(default=0.0, ge=0)
    reduce_power_low_soc: list[SocPowerLimit] = Field(default_factory=list)
    reduce_power_high_soc: list[SocPowerLimit] = Field(default_factory=list)
    min_soc_end_pct: float | None = Field(default=None, ge=0, le=100)
    max_soc_end_pct: float = Field(default=100, ge=0, le=100)

    @model_validator(mode="after")
    def check_limits(self) -> Self:
        if self.min_soc_pct >= self.max_soc_pct:
            raise ValueError("min_soc_pct must be below max_soc_pct")
        if not self.min_soc_pct <= self.initial_soc_pct <= self.max_soc_pct:
            raise ValueError("initial_soc_pct must be within the configured limits")
        if (
            self.min_soc_end_pct is not None
            and self.min_soc_end_pct > self.max_soc_end_pct
        ):
            raise ValueError("min_soc_end_pct must not exceed max_soc_end_pct")
        if (
            self.minimum_power_kw > self.max_charge_kw
            or self.minimum_power_kw > self.max_discharge_kw
        ):
            raise ValueError(
                "minimum_power_kw must not exceed the charge/discharge power limits"
            )
        return self


class EVInput(BaseModel):
    """Electric vehicle charging request."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    capacity_kwh: float = Field(gt=0)
    max_charge_kw: float = Field(gt=0)
    current_soc_pct: float = Field(default=50, ge=0, le=100)
    target_soc_pct: float = Field(default=80, ge=0, le=100)
    ready_at: datetime

    @model_validator(mode="after")
    def check_target(self) -> Self:
        if self.target_soc_pct < self.current_soc_pct:
            raise ValueError("target_soc_pct must not be below current_soc_pct")
        return self


class FlexibleLoadInput(BaseModel):
    """A load that can move inside a window (boiler, heat pump, machine)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    energy_kwh: float = Field(ge=0)
    max_power_kw: float = Field(gt=0)
    earliest: datetime
    deadline: datetime
    mandatory: bool = True

    @model_validator(mode="after")
    def check_window(self) -> Self:
        if self.deadline <= self.earliest:
            raise ValueError("deadline must be after earliest")
        return self


class OptimizationInput(BaseModel):
    """Everything the solver is allowed to know."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    now: datetime
    interval_minutes: int = Field(ge=1, le=60)
    horizon_hours: int = Field(gt=0, le=168)
    prices: list[PricePoint] = Field(min_length=1)
    load_kwh: list[float] = Field(min_length=1)
    pv_kwh: list[float] = Field(min_length=1)
    solar: list[SolarInput] = Field(default_factory=list)
    batteries: list[BatteryInput] = Field(default_factory=list)
    evs: list[EVInput] = Field(default_factory=list)
    boiler: FlexibleLoadInput | None = None
    heat_pump: FlexibleLoadInput | None = None
    machines: list[FlexibleLoadInput] = Field(default_factory=list)
    grid_max_import_kw: float = Field(default=17, gt=0)
    grid_max_export_kw: float = Field(default=17, gt=0)
    objective: Objective = Objective.MINIMIZE_COST
    allow_export: bool = True
    reserve_soc_pct: float = Field(default=20, ge=0, le=100)
    cycle_cost_eur_kwh: float = Field(default=0.0, ge=0)
    max_gap_eur: float = Field(default=0.005, ge=0)
    solver_threads: int = Field(default=0, ge=0, le=64)
    config_hash: str = Field(default="0" * 64, min_length=8)
    sources: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_shape(self) -> Self:
        count = len(self.prices)
        if len(self.load_kwh) != count or len(self.pv_kwh) != count:
            raise ValueError("prices, load_kwh, and pv_kwh must have the same length")
        for moment in (self.now, self.prices[0].start):
            if moment.tzinfo is None:
                raise ValueError("datetimes must be timezone-aware")
        return self
