"""CBC solver tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytest.importorskip("mip")

from daeo.domain.enums import GridMode  # noqa: E402
from daeo.domain.inputs import (  # noqa: E402
    BatteryInput,
    BatteryStage,
    EVInput,
    FlexibleLoadInput,
    OptimizationInput,
    PricePoint,
    SocPowerLimit,
)
from daeo.solver.base import SolverError  # noqa: E402
from daeo.solver.cbc import CbcSolver  # noqa: E402

START = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)


def make_inputs(
    prices: list[float],
    *,
    load: list[float] | None = None,
    pv: list[float] | None = None,
    batteries: list[BatteryInput] | None = None,
    evs: list[EVInput] | None = None,
    boiler: FlexibleLoadInput | None = None,
    export_price: float | None = None,
    grid_mode: GridMode = GridMode.ARBITRAGE,
) -> OptimizationInput:
    count = len(prices)
    return OptimizationInput(
        now=START,
        interval_minutes=60,
        horizon_hours=count,
        prices=[
            PricePoint(
                start=START + timedelta(hours=index),
                import_eur_kwh=price,
                export_eur_kwh=price if export_price is None else export_price,
            )
            for index, price in enumerate(prices)
        ],
        load_kwh=load or [0.0] * count,
        pv_kwh=pv or [0.0] * count,
        batteries=batteries or [],
        evs=evs or [],
        boiler=boiler,
        grid_max_import_kw=50,
        grid_max_export_kw=50,
        grid_mode=grid_mode,
        allow_export=True,
        reserve_soc_pct=0,
        cycle_cost_eur_kwh=0.0,
        max_gap_eur=0.0,
        solver_threads=1,
        config_hash="a" * 64,
        sources={"prices": "test", "pv": "test", "grid_mode": grid_mode.value},
    )


def battery(**overrides) -> BatteryInput:
    values = {
        "name": "Battery",
        "capacity_kwh": 1,
        "max_charge_kw": 1,
        "max_discharge_kw": 1,
        "efficiency": 1.0,
        "min_soc_pct": 0,
        "max_soc_pct": 100,
        "initial_soc_pct": 0,
    }
    values.update(overrides)
    return BatteryInput(**values)


def test_battery_arbitrage() -> None:
    plan = CbcSolver().solve(
        make_inputs([0.1, 1.0], batteries=[battery()])
    )
    assert plan.solver.name == "cbc"
    assert plan.solver.status.value == "optimal"
    assert plan.intervals[0].battery_charge_kwh == pytest.approx(1.0)
    assert plan.intervals[1].battery_discharge_kwh == pytest.approx(1.0)
    assert plan.intervals[0].grid_import_kwh == pytest.approx(1.0)
    assert plan.intervals[1].grid_export_kwh == pytest.approx(1.0)
    assert plan.summary.cost_eur == pytest.approx(-0.9)
    assert plan.summary.battery_cycles == pytest.approx(1.0)
    assert plan.sources["prices"] == "test"


def test_ev_must_charge_before_departure() -> None:
    vehicle = EVInput(
        name="Car",
        capacity_kwh=2,
        max_charge_kw=1,
        current_soc_pct=0,
        target_soc_pct=100,
        ready_at=START + timedelta(hours=2),
    )
    plan = CbcSolver().solve(make_inputs([1.0, 0.1], evs=[vehicle]))
    assert plan.intervals[0].ev_kwh == pytest.approx(1.0)
    assert plan.intervals[1].ev_kwh == pytest.approx(1.0)
    assert plan.summary.cost_eur == pytest.approx(1.1)


def test_boiler_moves_to_cheapest_interval() -> None:
    boiler = FlexibleLoadInput(
        name="boiler",
        energy_kwh=1,
        max_power_kw=1,
        earliest=START,
        deadline=START + timedelta(hours=2),
    )
    plan = CbcSolver().solve(make_inputs([1.0, 0.1], boiler=boiler))
    assert plan.intervals[0].boiler_kwh == pytest.approx(0.0)
    assert plan.intervals[1].boiler_kwh == pytest.approx(1.0)
    assert plan.summary.cost_eur == pytest.approx(0.1)


def test_terminal_soc_is_preserved() -> None:
    storage = battery(initial_soc_pct=50, capacity_kwh=2)
    plan = CbcSolver().solve(make_inputs([0.1, 1.0], batteries=[storage]))
    assert plan.intervals[-1].soc_pct >= 50
    assert all(interval.soc_pct >= 0 for interval in plan.intervals)


def test_infeasible_ev_is_reported() -> None:
    vehicle = EVInput(
        name="Car",
        capacity_kwh=3,
        max_charge_kw=1,
        current_soc_pct=0,
        target_soc_pct=100,
        ready_at=START + timedelta(hours=2),
    )
    with pytest.raises(SolverError, match="cannot charge"):
        CbcSolver().solve(make_inputs([0.1, 0.1], evs=[vehicle]))


def test_grid_balance_with_load_and_pv() -> None:
    plan = CbcSolver().solve(
        make_inputs([1.0, 0.2], load=[1.0, 0.0], pv=[0.0, 1.0])
    )
    assert plan.intervals[0].grid_import_kwh == pytest.approx(1.0)
    assert plan.intervals[1].grid_export_kwh == pytest.approx(1.0)
    assert plan.summary.cost_eur == pytest.approx(0.8)


def test_charge_stage_efficiency_is_applied() -> None:
    storage = battery(
        capacity_kwh=2,
        max_charge_kw=1,
        charge_stages=[
            BatteryStage(power_kw=0, efficiency=0.5),
            BatteryStage(power_kw=1, efficiency=0.5),
        ],
    )
    plan = CbcSolver().solve(
        make_inputs([0.1, 0.1, 1.0], batteries=[storage])
    )
    assert plan.intervals[0].battery_charge_kwh == pytest.approx(1.0)
    assert plan.intervals[1].battery_charge_kwh == pytest.approx(1.0)
    assert plan.intervals[-1].battery_discharge_kwh == pytest.approx(1.0)
    assert plan.intervals[1].soc_pct == pytest.approx(50.0)
    assert plan.summary.cost_eur == pytest.approx(-0.8)


def test_dc_ac_efficiency_is_applied() -> None:
    storage = battery(
        capacity_kwh=2,
        max_charge_kw=1,
        dc_to_bat_efficiency=0.5,
        bat_to_dc_efficiency=1.0,
    )
    plan = CbcSolver().solve(
        make_inputs([0.1, 0.1, 1.0], batteries=[storage])
    )
    assert plan.intervals[1].soc_pct == pytest.approx(50.0)
    assert plan.intervals[-1].battery_discharge_kwh == pytest.approx(1.0)
    assert plan.summary.cost_eur == pytest.approx(-0.8)


def test_reduced_power_at_high_soc() -> None:
    storage = battery(
        capacity_kwh=1,
        max_charge_kw=1,
        reduce_power_high_soc=[
            SocPowerLimit(soc_pct=50, power_kw=1),
            SocPowerLimit(soc_pct=100, power_kw=0),
        ],
    )
    plan = CbcSolver().solve(make_inputs([0.1, 1.0], batteries=[storage]))
    charged = [interval for interval in plan.intervals if interval.battery_charge_kwh > 0]
    assert charged
    assert all(interval.soc_pct < 70 for interval in charged)
    assert plan.summary.cost_eur < 0


def test_self_consumption_charges_from_pv_before_curtailing() -> None:
    storage = battery(
        capacity_kwh=4,
        max_charge_kw=1,
        max_discharge_kw=1,
        min_soc_pct=10,
        initial_soc_pct=20,
    )
    plan = CbcSolver().solve(
        make_inputs(
            [0.1, 0.1, 1.0],
            load=[0.5, 0.5, 0.5],
            pv=[0.0, 2.0, 0.0],
            batteries=[storage],
            grid_mode=GridMode.SELF_CONSUMPTION,
        )
    )
    surplus = plan.intervals[1]
    assert surplus.battery_charge_kwh == pytest.approx(1.0)
    assert surplus.soc_pct > 20.0
    assert plan.intervals[2].battery_discharge_kwh > 0.0
    assert plan.sources["grid_mode"] == "self_consumption"


def test_self_consumption_exports_battery_at_high_price() -> None:
    storage = battery(
        capacity_kwh=4,
        max_charge_kw=1,
        max_discharge_kw=1,
        min_soc_pct=10,
        initial_soc_pct=50,
    )
    plan = CbcSolver().solve(
        make_inputs(
            [0.1, 1.0],
            load=[0.5, 0.5],
            pv=[0.0, 0.0],
            batteries=[storage],
            grid_mode=GridMode.SELF_CONSUMPTION,
        )
    )
    expensive = plan.intervals[1]
    assert expensive.battery_discharge_kwh == pytest.approx(1.0)
    assert expensive.grid_import_kwh == pytest.approx(0.0)
    assert expensive.grid_export_kwh == pytest.approx(0.5)


def test_self_consumption_grid_charges_before_known_arbitrage() -> None:
    storage = battery(
        capacity_kwh=4,
        max_charge_kw=1,
        max_discharge_kw=1,
        min_soc_pct=10,
        initial_soc_pct=10,
    )
    plan = CbcSolver().solve(
        make_inputs(
            [0.1, 1.0],
            load=[0.5, 0.5],
            pv=[0.0, 0.0],
            batteries=[storage],
            grid_mode=GridMode.SELF_CONSUMPTION,
        )
    )
    assert plan.intervals[0].battery_charge_kwh == pytest.approx(1.0)
    assert plan.intervals[0].grid_import_kwh == pytest.approx(1.5)
    assert plan.intervals[1].battery_discharge_kwh == pytest.approx(1.0)
