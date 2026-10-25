"""The plan contract.

A ``Plan`` is the only output of the solver. It is persisted, served by the API,
consumed by the UI, and used by the Home Assistant integration. It contains no
device handles and no Home Assistant objects.
"""

from __future__ import annotations

from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from daeo.domain.enums import PlanStatus, Reason


class Interval(BaseModel):
    """One optimization interval."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    start: datetime = Field(description="Interval start (timezone-aware).")
    end: datetime = Field(description="Interval end (timezone-aware).")
    price_import_eur_kwh: float = Field(description="All-in import price.")
    price_export_eur_kwh: float = Field(description="All-in export price.")
    load_kwh: float = Field(ge=0, description="Forecast baseline load.")
    pv_kwh: float = Field(ge=0, description="Forecast PV production.")
    battery_charge_kwh: float = Field(ge=0, description="Energy charged into the battery.")
    battery_discharge_kwh: float = Field(ge=0, description="Energy discharged from the battery.")
    soc_pct: float = Field(ge=0, le=100, description="Battery state of charge at interval end.")
    ev_kwh: float = Field(ge=0, description="Energy delivered to electric vehicles.")
    boiler_kwh: float = Field(ge=0, description="Energy delivered to the boiler.")
    heat_pump_kwh: float = Field(ge=0, description="Energy delivered to the heat pump.")
    machine_kwh: float = Field(ge=0, description="Energy delivered to machines.")
    grid_import_kwh: float = Field(ge=0, description="Energy imported from the grid.")
    grid_export_kwh: float = Field(ge=0, description="Energy exported to the grid.")
    cost_eur: float = Field(description="Net cost for this interval; negative means revenue.")
    reason: Reason = Field(default=Reason.IDLE, description="Primary decision reason.")
    explanation: str | None = Field(
        default=None, max_length=500, description="Human-readable explanation for the UI."
    )

    @model_validator(mode="after")
    def check_interval(self) -> Self:
        if self.end <= self.start:
            raise ValueError("interval end must be after start")
        if abs((self.end - self.start).total_seconds()) > 24 * 3600:
            raise ValueError("interval cannot be longer than 24 hours")
        if self.battery_charge_kwh > 0 and self.battery_discharge_kwh > 0:
            raise ValueError("battery cannot charge and discharge in the same interval")
        return self


class PlanSummary(BaseModel):
    """Aggregated plan values used by the dashboard and statistics."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cost_eur: float = Field(description="Total net cost of the plan.")
    baseline_cost_eur: float = Field(description="Cost without optimization.")
    savings_eur: float = Field(description="Baseline minus optimized cost.")
    import_kwh: float = Field(ge=0)
    export_kwh: float = Field(ge=0)
    pv_kwh: float = Field(ge=0)
    load_kwh: float = Field(ge=0)
    battery_cycles: float = Field(ge=0, description="Equivalent full battery cycles.")
    terminal_soc_value_eur: float = Field(
        default=0.0,
        description="Value of energy left in the battery at the end of the horizon.",
    )


class SolverInfo(BaseModel):
    """Solver provenance and quality."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(description="Solver name, e.g. 'cbc' or 'demo'.")
    status: PlanStatus = Field(description="Solver outcome.")
    runtime_ms: int = Field(ge=0)
    objective_eur: float | None = None
    mip_gap: float | None = Field(default=None, ge=0)


class Plan(BaseModel):
    """A complete, validated optimization result."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(description="Stable plan identifier.")
    created_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    interval_minutes: int = Field(ge=1, le=60)
    currency: str = Field(default="EUR", min_length=3, max_length=3)
    intervals: list[Interval] = Field(min_length=1)
    summary: PlanSummary
    solver: SolverInfo
    config_hash: str = Field(min_length=8)
    sources: dict[str, str] = Field(
        default_factory=dict,
        description="Where each input came from, for example prices=energyzero.",
    )

    @model_validator(mode="after")
    def check_plan(self) -> Self:
        if self.horizon_end <= self.horizon_start:
            raise ValueError("horizon end must be after start")
        if self.intervals[0].start != self.horizon_start:
            raise ValueError("first interval must start at horizon_start")
        if self.intervals[-1].end != self.horizon_end:
            raise ValueError("last interval must end at horizon_end")
        expected = (self.horizon_end - self.horizon_start).total_seconds() / 60
        if abs(expected - len(self.intervals) * self.interval_minutes) > 1:
            raise ValueError("interval count does not match the horizon")
        for previous, current in zip(self.intervals, self.intervals[1:], strict=False):
            if previous.end != current.start:
                raise ValueError("plan intervals must be contiguous")
        return self
