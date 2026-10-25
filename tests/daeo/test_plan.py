"""Plan contract tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from daeo.domain.enums import PlanStatus, Reason
from daeo.domain.plan import Interval, Plan, PlanSummary, SolverInfo


def make_interval(start: datetime, **overrides) -> Interval:
    values = {
        "start": start,
        "end": start + timedelta(minutes=15),
        "price_import_eur_kwh": 0.2,
        "price_export_eur_kwh": 0.05,
        "load_kwh": 0.1,
        "pv_kwh": 0.0,
        "battery_charge_kwh": 0.0,
        "battery_discharge_kwh": 0.0,
        "soc_pct": 50.0,
        "ev_kwh": 0.0,
        "boiler_kwh": 0.0,
        "heat_pump_kwh": 0.0,
        "machine_kwh": 0.0,
        "grid_import_kwh": 0.1,
        "grid_export_kwh": 0.0,
        "cost_eur": 0.02,
        "reason": Reason.IDLE,
    }
    values.update(overrides)
    return Interval(**values)


def make_plan(intervals: list[Interval]) -> Plan:
    start = intervals[0].start
    end = intervals[-1].end
    return Plan(
        id="plan_test",
        created_at=start,
        horizon_start=start,
        horizon_end=end,
        interval_minutes=15,
        intervals=intervals,
        summary=PlanSummary(
            cost_eur=0.02,
            baseline_cost_eur=0.03,
            savings_eur=0.01,
            import_kwh=0.1,
            export_kwh=0.0,
            pv_kwh=0.0,
            load_kwh=0.1,
            battery_cycles=0.0,
        ),
        solver=SolverInfo(name="demo", status=PlanStatus.OPTIMAL, runtime_ms=1),
        config_hash="a" * 64,
    )


def test_interval_rejects_reversed_time() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="end must be after start"):
        make_interval(start, end=start)


def test_interval_rejects_charge_and_discharge() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="charge and discharge"):
        make_interval(start, battery_charge_kwh=0.5, battery_discharge_kwh=0.5)


def test_plan_roundtrips() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    plan = make_plan([make_interval(start), make_interval(start + timedelta(minutes=15))])
    assert Plan.model_validate_json(plan.model_dump_json()) == plan


def test_plan_rejects_gaps() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    with pytest.raises(ValidationError, match="contiguous"):
        make_plan(
            [
                make_interval(start, end=start + timedelta(minutes=10)),
                make_interval(
                    start + timedelta(minutes=10),
                    end=start + timedelta(minutes=20),
                ),
                make_interval(
                    start + timedelta(minutes=30),
                    end=start + timedelta(minutes=40),
                ),
                make_interval(
                    start + timedelta(minutes=50),
                    end=start + timedelta(minutes=60),
                ),
            ]
        )


def test_plan_rejects_wrong_horizon() -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    payload = make_plan(
        [make_interval(start), make_interval(start + timedelta(minutes=15))]
    ).model_dump()
    payload["horizon_end"] = start + timedelta(hours=2)
    with pytest.raises(ValidationError):
        Plan.model_validate(payload)
