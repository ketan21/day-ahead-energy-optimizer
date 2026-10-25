"""Demo solver tests."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from daeo.config.loader import config_hash
from daeo.config.models import (
    BatteryConfig,
    BoilerConfig,
    Config,
    EVConfig,
    SolarConfig,
)
from daeo.domain.inputs import PricePoint
from daeo.solver.demo import DemoSolver, build_inputs

NOW = datetime(2026, 10, 25, 12, 7, tzinfo=ZoneInfo("Europe/Amsterdam"))


def config_with_devices() -> Config:
    config = Config.default()
    config.batteries = [
        BatteryConfig(
            name="Home",
            capacity_kwh=10,
            max_charge_kw=5,
            max_discharge_kw=5,
            efficiency=0.95,
            min_soc_pct=20,
            max_soc_pct=100,
        )
    ]
    config.solar = [SolarConfig(name="Roof", peak_power_wp=5000)]
    config.electric_vehicles = [
        EVConfig(
            name="Car",
            capacity_kwh=60,
            max_charge_kw=11,
            target_soc_pct=80,
            ready_by=time(18, 0),
        )
    ]
    config.boiler = BoilerConfig(
        enabled=True,
        volume_l=180,
        power_kw=1.5,
        cop=1.0,
        target_temp_c=60,
    )
    return config


def solve(config: Config, now: datetime = NOW):
    inputs = build_inputs(config, now=now, config_hash=config_hash(config))
    return DemoSolver().solve(inputs)


def test_plan_shape_and_hash() -> None:
    config = config_with_devices()
    plan = solve(config)
    assert len(plan.intervals) == 96
    assert plan.interval_minutes == 15
    assert plan.horizon_start == NOW.replace(minute=0, second=0, microsecond=0)
    assert plan.config_hash == config_hash(config)
    assert plan.solver.name == "demo"


def test_soc_stays_inside_limits() -> None:
    plan = solve(config_with_devices())
    assert all(20 <= interval.soc_pct <= 100 for interval in plan.intervals)


def test_battery_charges_and_discharges() -> None:
    plan = solve(config_with_devices())
    assert sum(i.battery_charge_kwh for i in plan.intervals) > 0
    assert sum(i.battery_discharge_kwh for i in plan.intervals) > 0
    assert plan.summary.battery_cycles > 0


def test_ev_is_charged_before_departure() -> None:
    config = config_with_devices()
    plan = solve(config)
    vehicle = config.electric_vehicles[0]
    ready_at = NOW.replace(hour=vehicle.ready_by.hour, minute=vehicle.ready_by.minute)
    ev_intervals = [i for i in plan.intervals if i.ev_kwh > 0]
    assert ev_intervals
    assert all(i.start < ready_at for i in ev_intervals)
    assert sum(i.ev_kwh for i in ev_intervals) == 24.0


def test_boiler_is_scheduled_in_its_window() -> None:
    plan = solve(config_with_devices())
    assert sum(i.boiler_kwh for i in plan.intervals) > 0


def test_no_devices_means_no_controllable_flows() -> None:
    plan = solve(Config.default())
    assert all(i.battery_charge_kwh == 0 for i in plan.intervals)
    assert all(i.battery_discharge_kwh == 0 for i in plan.intervals)
    assert all(i.ev_kwh == 0 for i in plan.intervals)
    assert all(i.boiler_kwh == 0 for i in plan.intervals)


def test_solver_is_deterministic() -> None:
    config = config_with_devices()
    first = solve(config)
    second = solve(config)
    assert first.intervals == second.intervals
    assert first.summary == second.summary


def test_summary_matches_intervals() -> None:
    plan = solve(config_with_devices())
    assert abs(plan.summary.cost_eur - sum(i.cost_eur for i in plan.intervals)) < 1e-3
    assert abs(plan.summary.import_kwh - sum(i.grid_import_kwh for i in plan.intervals)) < 1e-3
    assert abs(plan.summary.export_kwh - sum(i.grid_export_kwh for i in plan.intervals)) < 1e-3


def test_build_inputs_uses_supplied_prices() -> None:
    config = Config.default()
    start = NOW.replace(minute=0, second=0, microsecond=0)
    prices = [
        PricePoint(
            start=start + timedelta(minutes=15 * index),
            import_eur_kwh=0.30 + index * 0.01,
            export_eur_kwh=0.05,
        )
        for index in range(4)
    ]
    inputs = build_inputs(
        config,
        now=NOW,
        config_hash="a" * 64,
        prices=prices,
    )
    assert inputs.prices == prices
    assert len(inputs.load_kwh) == 4
    assert len(inputs.pv_kwh) == 4
    assert inputs.horizon_hours == 1

    plan = DemoSolver().solve(inputs)
    assert len(plan.intervals) == 4
    assert plan.horizon_start == start
    assert plan.horizon_end == start + timedelta(hours=1)
    assert plan.intervals[0].price_import_eur_kwh == pytest.approx(0.30)
    assert plan.intervals[-1].price_import_eur_kwh == pytest.approx(0.33)
