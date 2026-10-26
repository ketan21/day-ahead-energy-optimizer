"""Simulate realistic self-consumption plans and the P1 control correction.

Run with:
    .venv/bin/python scripts/simulate_control_loop.py

This uses the real CBC solver and the pure grid-correction function from the HA
integration. No Home Assistant or network access is required.
"""

from __future__ import annotations

import importlib.util
import math
import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

from daeo.domain.enums import GridMode
from daeo.domain.inputs import BatteryInput, OptimizationInput, PricePoint
from daeo.solver.cbc import CbcSolver

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = types.ModuleType("daeo_grid_pkg")
PACKAGE.__path__ = [str(ROOT / "custom_components" / "daeo")]
sys.modules["daeo_grid_pkg"] = PACKAGE
for module_name in ("plan", "control"):
    spec = importlib.util.spec_from_file_location(
        f"daeo_grid_pkg.{module_name}",
        ROOT / "custom_components" / "daeo" / f"{module_name}.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"daeo_grid_pkg.{module_name}"] = module
    spec.loader.exec_module(module)
grid_corrected_power = sys.modules["daeo_grid_pkg.control"].grid_corrected_power


def price_curve(count: int) -> list[float]:
    values = []
    for index in range(count):
        hour = index / 4
        night = 0.12
        morning = 0.18 * math.exp(-((hour - 7) ** 2) / 4)
        evening = 0.38 * math.exp(-((hour - 19) ** 2) / 5)
        values.append(round(night + morning + evening + 0.015 * math.sin(hour), 5))
    return values


def load_curve(count: int, scale: float) -> list[float]:
    values = []
    for index in range(count):
        hour = index / 4
        kw = 0.28
        kw += 0.25 * math.exp(-((hour - 7) ** 2) / 2)
        kw += 0.45 * math.exp(-((hour - 19) ** 2) / 4)
        values.append(round(kw * scale * 0.25, 6))
    return values


def pv_curve(count: int, peak_kw: float) -> list[float]:
    values = []
    for index in range(count):
        hour = index / 4
        if 6.5 <= hour <= 19.5:
            fraction = math.sin(math.pi * (hour - 6.5) / 13) ** 2
        else:
            fraction = 0.0
        values.append(round(peak_kw * fraction * 0.25, 6))
    return values


def make_plan(
    *,
    peak_kw: float,
    load_scale: float,
    initial_soc: float,
) -> tuple[dict, OptimizationInput]:
    count = 96
    start = datetime(2026, 5, 15, tzinfo=UTC)
    prices = price_curve(count)
    inputs = OptimizationInput(
        now=start,
        interval_minutes=15,
        horizon_hours=24,
        prices=[
            PricePoint(
                start=start + timedelta(minutes=15 * index),
                import_eur_kwh=price,
                # EPEX-like export: market-only, can be negative.
                export_eur_kwh=round(max(-0.05, price - 0.18), 5),
            )
            for index, price in enumerate(prices)
        ],
        load_kwh=load_curve(count, load_scale),
        pv_kwh=pv_curve(count, peak_kw),
        batteries=[
            BatteryInput(
                name="Solarbank Max AC",
                capacity_kwh=7.2,
                max_charge_kw=1.2,
                max_discharge_kw=1.2,
                efficiency=0.95,
                min_soc_pct=20,
                max_soc_pct=100,
                initial_soc_pct=initial_soc,
                min_soc_end_pct=20,
                max_soc_end_pct=100,
            )
        ],
        grid_max_import_kw=17,
        grid_max_export_kw=17,
        grid_mode=GridMode.SELF_CONSUMPTION,
        allow_export=True,
        reserve_soc_pct=20,
        cycle_cost_eur_kwh=0.02,
        max_gap_eur=0.005,
        solver_threads=1,
        config_hash="simulation",
        sources={
            "prices": "synthetic",
            "pv": "synthetic",
            "load": "synthetic",
            "grid_mode": "self_consumption",
        },
    )
    return CbcSolver().solve(inputs).model_dump(mode="json"), inputs


def interval_power(interval: dict) -> tuple[float, float]:
    hours = 0.25
    battery_w = (
        interval["battery_charge_kwh"] - interval["battery_discharge_kwh"]
    ) / hours * 1000
    target_w = (
        interval["grid_import_kwh"] - interval["grid_export_kwh"]
    ) / hours * 1000
    return battery_w, target_w


def print_plan(name: str, plan: dict, inputs: OptimizationInput) -> None:
    print(f"\n=== {name} ===")
    summary = plan["summary"]
    print(
        f"status={plan['solver']['status']}  cost={summary['cost_eur']:.2f} EUR  "
        f"savings={summary['savings_eur']:.2f} EUR  "
        f"pv={summary['pv_kwh']:.1f} kWh  load={summary['load_kwh']:.1f} kWh"
    )
    print("time  price   load      pv     battery     grid    soc  source")
    for interval in plan["intervals"][::4]:
        battery_w, target_w = interval_power(interval)
        print(
            f"{interval['start'][11:16]}  {interval['price_import_eur_kwh']:.3f}  "
            f"{interval['load_kwh']:.3f}  {interval['pv_kwh']:.3f}  "
            f"{battery_w:+7.0f} W  {target_w:+7.0f} W  "
            f"{interval['soc_pct']:5.1f}%  {interval['reason']}"
        )


def print_control(name: str, interval: dict, error_w: float) -> None:
    battery_w, target_w = interval_power(interval)
    actual_w = target_w + error_w
    corrected = grid_corrected_power(
        battery_w,
        actual_w,
        target_w,
        max_charge_w=1200,
        max_discharge_w=1200,
        deadband_w=30,
        max_step_w=1000,
        last_power_w=battery_w,
    )
    print(
        f"{name:<30} target={target_w:+7.0f} W  actual={actual_w:+7.0f} W  "
        f"base={battery_w:+7.0f} W  corrected={corrected!s:>8} W"
    )


def main() -> None:
    datasets = [
        (
            "Sunny spring day, battery starts at 20%",
            4.5,
            0.9,
            20.0,
        ),
        (
            "Cloudy day, battery starts at 40%",
            1.2,
            1.2,
            40.0,
        ),
    ]
    for name, peak_kw, load_scale, initial_soc in datasets:
        plan, inputs = make_plan(
            peak_kw=peak_kw,
            load_scale=load_scale,
            initial_soc=initial_soc,
        )
        print_plan(name, plan, inputs)
        intervals = plan["intervals"]

        surplus = max(
            intervals,
            key=lambda item: item["pv_kwh"] - item["load_kwh"],
        )
        expensive = max(
            intervals,
            key=lambda item: item["price_import_eur_kwh"],
        )
        idle = next(
            (
                item
                for item in intervals
                if abs(item["battery_charge_kwh"]) < 1e-9
                and abs(item["battery_discharge_kwh"]) < 1e-9
            ),
            None,
        )

        print("control correction:")
        print_control("PV surplus / export spike", surplus, -700.0)
        print_control("Evening load spike", expensive, +500.0)
        if idle is not None:
            print(
                f"{'Explicit battery idle':<30} "
                f"target={interval_power(idle)[1]:+7.0f} W  "
                "no correction (battery marked idle)"
            )

        print("10 s closed-loop catch-up, house load steps 900 -> 700 W:")
        setpoint = 0.0
        load_w = 900.0
        for tick in range(1, 6):
            actual = load_w + setpoint
            corrected = grid_corrected_power(
                setpoint,
                actual,
                0,
                max_charge_w=1200,
                max_discharge_w=1200,
                deadband_w=30,
                max_step_w=400,
                last_power_w=setpoint,
            )
            if corrected is not None:
                setpoint = corrected
            print(
                f"  tick {tick}: load={load_w:+5.0f} W  "
                f"P1={actual:+5.0f} W  setpoint={setpoint:+7.0f} W"
            )
            if tick == 3:
                load_w = 700.0


if __name__ == "__main__":
    main()
