"""Deterministic demo solver.

This is the fallback and test solver. The production path is the CBC MILP solver in
``daeo.solver.cbc``. The demo solver remains useful for offline demos and tests that
need deterministic, fast output.
"""

from __future__ import annotations

import math
import time
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from datetime import time as dt_time

from daeo.config.models import Config
from daeo.domain.enums import Objective, PlanStatus
from daeo.domain.inputs import (
    BatteryInput,
    BatteryStage,
    EVInput,
    FlexibleLoadInput,
    OptimizationInput,
    PricePoint,
    SocPowerLimit,
    SolarInput,
)
from daeo.domain.plan import Interval, Plan, PlanSummary, SolverInfo
from daeo.solver.base import SolverError
from daeo.solver.reasons import REASON_EXPLANATIONS, pick_reason


def _floor_to_interval(moment: datetime, minutes: int) -> datetime:
    floored_minute = (moment.minute // minutes) * minutes
    return moment.replace(minute=floored_minute, second=0, microsecond=0)


def _next_ready_at(now: datetime, ready_by: dt_time) -> datetime:
    candidate = now.replace(
        hour=ready_by.hour, minute=ready_by.minute, second=0, microsecond=0
    )
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def _window(now: datetime, start: dt_time, end: dt_time) -> tuple[datetime, datetime]:
    """Return the next window, starting no earlier than now."""
    start_at = now.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    if start_at < now:
        start_at = now
    end_at = now.replace(hour=end.hour, minute=end.minute, second=0, microsecond=0)
    if end_at <= start_at:
        end_at += timedelta(days=1)
    return start_at, end_at


def _synthetic_prices(config: Config, start: datetime, count: int, minutes: int) -> list[PricePoint]:
    interval_h = minutes / 60
    vat = 1 + config.prices.vat_pct / 100
    prices: list[PricePoint] = []
    for index in range(count):
        moment = start + timedelta(minutes=index * minutes)
        hour = moment.hour + moment.minute / 60 + interval_h / 2
        spot = (
            0.16
            + 0.10 * math.exp(-((hour - 8) / 1.5) ** 2)
            + 0.38 * math.exp(-((hour - 19) / 2.0) ** 2)
            - 0.07 * math.exp(-((hour - 3) / 2.5) ** 2)
            + 0.02 * math.sin(index * 0.9)
        )
        if config.prices.source.value == "fixed" and config.prices.fixed_import_price_eur_kwh:
            import_price = config.prices.fixed_import_price_eur_kwh
        else:
            import_price = (
                spot
                + config.prices.energy_tax_import_eur_kwh
                + config.prices.supplier_markup_import_eur_kwh
            ) * vat
            import_price *= config.prices.multiplier_import
        if config.prices.fixed_export_price_eur_kwh is not None:
            export_price = config.prices.fixed_export_price_eur_kwh
        else:
            export_price = max(0.0, spot * 0.9 + config.prices.feed_in_tariff_eur_kwh)
            export_price *= config.prices.multiplier_export
        prices.append(
            PricePoint(
                start=moment,
                import_eur_kwh=round(import_price, 6),
                export_eur_kwh=round(export_price, 6),
            )
        )
    return prices


def _synthetic_load(start: datetime, minutes: int, count: int) -> list[float]:
    interval_h = minutes / 60
    values: list[float] = []
    for index in range(count):
        moment = start + timedelta(minutes=index * minutes)
        hour = moment.hour + moment.minute / 60
        kw = (
            0.35
            + 0.30 * math.exp(-((hour - 7.5) / 1.4) ** 2)
            + 0.50 * math.exp(-((hour - 19) / 2.4) ** 2)
            + 0.08 * math.sin(index * 0.5)
        )
        values.append(max(0.0, round(kw * interval_h, 6)))
    return values


def _synthetic_pv(config: Config, start: datetime, minutes: int, count: int) -> list[float]:
    peak_kw = sum(array.peak_power_wp for array in config.solar if array.enabled) / 1000
    interval_h = minutes / 60
    values: list[float] = []
    for index in range(count):
        moment = start + timedelta(minutes=index * minutes)
        hour = moment.hour + moment.minute / 60
        if 6.5 <= hour <= 19.5:
            fraction = math.sin(math.pi * (hour - 6.5) / 13) ** 2
        else:
            fraction = 0.0
        values.append(max(0.0, round(peak_kw * fraction * interval_h * 0.85, 6)))
    return values


def build_inputs(
    config: Config,
    now: datetime | None = None,
    config_hash: str = "0" * 64,
    prices: list[PricePoint] | None = None,
    pv_kwh: list[float] | None = None,
    load_kwh: list[float] | None = None,
    sources: dict[str, str] | None = None,
) -> OptimizationInput:
    """Build an optimization input from configuration.

    With ``prices`` the supplied all-in series is used and the horizon follows the
    available data (up to 24 hours). Without it, a synthetic 24-hour demo series is
    generated.
    """
    if now is None:
        now = datetime.now().astimezone()
    minutes = config.strategy.interval.minutes
    prices_supplied = prices is not None
    if prices is not None:
        if not prices:
            raise ValueError("prices must not be empty when supplied")
        start = prices[0].start
        if start.tzinfo is None:
            raise ValueError("price start must be timezone-aware")
        count = len(prices)
        horizon_hours = max(1, math.ceil(count * minutes / 60))
    else:
        start = _floor_to_interval(now, minutes)
        horizon_hours = 24
        count = horizon_hours * 60 // minutes
        prices = _synthetic_prices(config, start, count, minutes)
    if pv_kwh is not None and len(pv_kwh) != count:
        raise ValueError("pv_kwh must have the same length as prices")
    if load_kwh is not None and len(load_kwh) != count:
        raise ValueError("load_kwh must have the same length as prices")
    load = (
        list(load_kwh)
        if load_kwh is not None
        else _synthetic_load(start, minutes, count)
    )
    pv = list(pv_kwh) if pv_kwh is not None else _synthetic_pv(config, start, minutes, count)
    if sources is None:
        sources = {
            "prices": "provided" if prices_supplied else "synthetic",
            "pv": "provided" if pv_kwh is not None else "synthetic",
            "load": "provided" if load_kwh is not None else "synthetic",
        }

    batteries = [
        BatteryInput(
            name=battery.name,
            capacity_kwh=battery.capacity_kwh,
            max_charge_kw=battery.max_charge_kw,
            max_discharge_kw=battery.max_discharge_kw,
            efficiency=battery.efficiency,
            min_soc_pct=battery.min_soc_pct,
            max_soc_pct=battery.max_soc_pct,
            initial_soc_pct=max(
                battery.min_soc_pct,
                min(battery.max_soc_pct, 50.0),
            ),
            charge_stages=[
                BatteryStage(power_kw=stage.power_kw, efficiency=stage.efficiency)
                for stage in battery.charge_stages
            ],
            discharge_stages=[
                BatteryStage(power_kw=stage.power_kw, efficiency=stage.efficiency)
                for stage in battery.discharge_stages
            ],
            dc_to_bat_efficiency=battery.dc_to_bat_efficiency,
            bat_to_dc_efficiency=battery.bat_to_dc_efficiency,
            minimum_power_kw=battery.minimum_power_kw,
            reduce_power_low_soc=[
                SocPowerLimit(soc_pct=point.soc_pct, power_kw=point.power_kw)
                for point in battery.reduce_power_low_soc
            ],
            reduce_power_high_soc=[
                SocPowerLimit(soc_pct=point.soc_pct, power_kw=point.power_kw)
                for point in battery.reduce_power_high_soc
            ],
            min_soc_end_pct=battery.min_soc_end_pct,
            max_soc_end_pct=battery.max_soc_end_pct,
        )
        for battery in config.batteries
        if battery.enabled
    ]

    evs = [
        EVInput(
            name=vehicle.name,
            capacity_kwh=vehicle.capacity_kwh,
            max_charge_kw=vehicle.max_charge_kw,
            current_soc_pct=min(40.0, vehicle.target_soc_pct),
            target_soc_pct=vehicle.target_soc_pct,
            ready_at=_next_ready_at(now, vehicle.ready_by),
        )
        for vehicle in config.electric_vehicles
        if vehicle.enabled
    ]

    boiler = None
    if config.boiler is not None and config.boiler.enabled:
        energy = (
            config.boiler.volume_l
            * 4.186
            * max(0.0, config.boiler.target_temp_c - 55.0)
            / 3600
            / max(config.boiler.cop, 0.1)
        )
        boiler = FlexibleLoadInput(
            name="boiler",
            energy_kwh=round(energy, 6),
            max_power_kw=config.boiler.power_kw,
            earliest=now,
            deadline=now + timedelta(hours=24),
        )

    heat_pump = None
    if config.heat_pump is not None and config.heat_pump.enabled and config.heat_pump.stages:
        max_power = max(stage.max_power_kw for stage in config.heat_pump.stages)
        heat_pump = FlexibleLoadInput(
            name="heat_pump",
            energy_kwh=round(max_power * 2, 6),
            max_power_kw=max_power,
            earliest=now,
            deadline=now + timedelta(hours=24),
        )

    machines = []
    for machine in config.machines:
        if not machine.enabled:
            continue
        earliest, deadline = _window(now, machine.earliest_start, machine.deadline)
        machines.append(
            FlexibleLoadInput(
                name=machine.name,
                energy_kwh=machine.power_kw * machine.duration_minutes / 60,
                max_power_kw=machine.power_kw,
                earliest=earliest,
                deadline=deadline,
            )
        )

    return OptimizationInput(
        now=now,
        interval_minutes=minutes,
        horizon_hours=horizon_hours,
        prices=prices,
        load_kwh=load,
        pv_kwh=pv,
        solar=[
            SolarInput(
                name=array.name,
                peak_power_kw=array.peak_power_wp / 1000,
                dc_coupled=array.dc_coupled,
            )
            for array in config.solar
            if array.enabled
        ],
        batteries=batteries,
        evs=evs,
        boiler=boiler,
        heat_pump=heat_pump,
        machines=machines,
        grid_max_import_kw=config.grid.max_import_kw,
        grid_max_export_kw=config.grid.max_export_kw,
        objective=config.strategy.objective,
        allow_export=config.strategy.allow_export,
        reserve_soc_pct=config.strategy.reserve_soc_pct,
        cycle_cost_eur_kwh=config.strategy.cycle_cost_eur_kwh,
        max_gap_eur=config.strategy.max_gap_eur,
        solver_threads=config.strategy.solver_threads,
        config_hash=config_hash,
        sources=sources,
    )


def _cheapest_indices(
    prices: list[PricePoint], indices: list[int], objective: Objective
) -> list[int]:
    def key(index: int) -> float:
        if objective is Objective.MINIMIZE_IMPORT:
            return (-(prices[index].import_eur_kwh > 0), prices[index].import_eur_kwh)
        return (prices[index].import_eur_kwh, index)

    return sorted(indices, key=key)


def _allocate(
    energy_kwh: float,
    max_power_kw: float,
    interval_h: float,
    prices: list[PricePoint],
    indices: list[int],
    objective: Objective,
) -> dict[int, float]:
    allocation: dict[int, float] = {}
    remaining = energy_kwh
    for index in _cheapest_indices(prices, indices, objective):
        if remaining <= 1e-9:
            break
        amount = min(max_power_kw * interval_h, remaining)
        if amount <= 0:
            continue
        allocation[index] = amount
        remaining -= amount
    return allocation


class DemoSolver:
    """A deterministic heuristic solver for development and demos."""

    name = "demo"

    def solve(self, inputs: OptimizationInput) -> Plan:
        started = time.perf_counter()
        if not inputs.prices:
            raise SolverError("cannot solve without prices")

        interval_h = inputs.interval_minutes / 60
        count = len(inputs.prices)
        start = inputs.prices[0].start
        end = start + timedelta(minutes=count * inputs.interval_minutes)

        sorted_prices = sorted(point.import_eur_kwh for point in inputs.prices)
        low = sorted_prices[max(0, int(len(sorted_prices) * 0.3) - 1)]
        high = sorted_prices[min(len(sorted_prices) - 1, int(len(sorted_prices) * 0.7))]

        ev_by_index: dict[int, float] = defaultdict(float)
        for vehicle in inputs.evs:
            needed = vehicle.capacity_kwh * (vehicle.target_soc_pct - vehicle.current_soc_pct) / 100
            indices = [
                index
                for index, point in enumerate(inputs.prices)
                if point.start < vehicle.ready_at
            ]
            if not indices:
                indices = list(range(min(count, 8)))
            for index, amount in _allocate(
                needed,
                vehicle.max_charge_kw,
                interval_h,
                inputs.prices,
                indices,
                inputs.objective,
            ).items():
                ev_by_index[index] += amount

        boiler_by_index: dict[int, float] = {}
        if inputs.boiler is not None:
            indices = [
                index
                for index, point in enumerate(inputs.prices)
                if inputs.boiler.earliest <= point.start < inputs.boiler.deadline
            ]
            boiler_by_index = _allocate(
                inputs.boiler.energy_kwh,
                inputs.boiler.max_power_kw,
                interval_h,
                inputs.prices,
                indices,
                inputs.objective,
            )

        heat_by_index: dict[int, float] = {}
        if inputs.heat_pump is not None:
            indices = [
                index
                for index, point in enumerate(inputs.prices)
                if inputs.heat_pump.earliest <= point.start < inputs.heat_pump.deadline
            ]
            heat_by_index = _allocate(
                inputs.heat_pump.energy_kwh,
                inputs.heat_pump.max_power_kw,
                interval_h,
                inputs.prices,
                indices,
                inputs.objective,
            )

        machine_by_index: dict[int, float] = defaultdict(float)
        for machine in inputs.machines:
            indices = [
                index
                for index, point in enumerate(inputs.prices)
                if machine.earliest <= point.start < machine.deadline
            ]
            for index, amount in _allocate(
                machine.energy_kwh,
                machine.max_power_kw,
                interval_h,
                inputs.prices,
                indices,
                inputs.objective,
            ).items():
                machine_by_index[index] += amount

        battery = inputs.batteries[0] if inputs.batteries else None
        soc_pct = float(battery.initial_soc_pct) if battery else 0.0
        intervals: list[Interval] = []
        total_charge = 0.0
        total_discharge = 0.0

        for index, point in enumerate(inputs.prices):
            load_kwh = inputs.load_kwh[index]
            pv_kwh = inputs.pv_kwh[index]
            ev_kwh = ev_by_index.get(index, 0.0)
            boiler_kwh = boiler_by_index.get(index, 0.0)
            heat_kwh = heat_by_index.get(index, 0.0)
            machine_kwh = machine_by_index.get(index, 0.0)

            demand_kwh = load_kwh + ev_kwh + boiler_kwh + heat_kwh + machine_kwh
            charge_kwh = 0.0
            discharge_kwh = 0.0
            if battery is not None:
                room_kwh = (battery.max_soc_pct - soc_pct) / 100 * battery.capacity_kwh
                # The demo never discharges below the initial SOC. This keeps the
                # savings comparison independent of energy that was already in the
                # battery before the horizon; a real optimizer uses a terminal SOC
                # value instead.
                discharge_floor = max(
                    battery.min_soc_pct,
                    inputs.reserve_soc_pct,
                    battery.initial_soc_pct,
                )
                space_kwh = (
                    soc_pct - discharge_floor
                ) / 100 * battery.capacity_kwh
                max_charge = min(battery.max_charge_kw * interval_h, max(0.0, room_kwh))
                max_discharge = min(
                    battery.max_discharge_kw * interval_h, max(0.0, space_kwh)
                )
                if (pv_kwh > load_kwh or point.import_eur_kwh <= low) and max_charge > 1e-9:
                    charge_kwh = max_charge
                    soc_pct += charge_kwh * battery.efficiency / battery.capacity_kwh * 100
                    total_charge += charge_kwh
                elif point.import_eur_kwh >= high and max_discharge > 1e-9:
                    # Do not dump battery energy into a low export price. The demo
                    # offsets local demand first; unused energy stays in the battery.
                    discharge_kwh = min(max_discharge, max(0.0, demand_kwh))
                    soc_pct -= discharge_kwh / battery.efficiency / battery.capacity_kwh * 100
                    total_discharge += discharge_kwh
                soc_pct = min(battery.max_soc_pct, max(battery.min_soc_pct, soc_pct))

            net_kwh = demand_kwh + charge_kwh - pv_kwh - discharge_kwh
            grid_import = max(0.0, net_kwh)
            grid_export = max(0.0, -net_kwh) if inputs.allow_export else 0.0
            if grid_import > inputs.grid_max_import_kw * interval_h:
                grid_import = inputs.grid_max_import_kw * interval_h
            if grid_export > inputs.grid_max_export_kw * interval_h:
                grid_export = inputs.grid_max_export_kw * interval_h

            cost = (
                grid_import * point.import_eur_kwh
                - grid_export * point.export_eur_kwh
                + (charge_kwh + discharge_kwh) * inputs.cycle_cost_eur_kwh / 2
            )
            reason = pick_reason(
                has_battery=battery is not None,
                ev_kwh=ev_kwh,
                boiler_kwh=boiler_kwh,
                heat_kwh=heat_kwh,
                machine_kwh=machine_kwh,
                charge_kwh=charge_kwh,
                discharge_kwh=discharge_kwh,
                pv_kwh=pv_kwh,
                load_kwh=load_kwh,
                price=point.import_eur_kwh,
                low=low,
                high=high,
                soc_pct=soc_pct,
                min_soc=battery.min_soc_pct if battery else 0.0,
                max_soc=battery.max_soc_pct if battery else 0.0,
            )
            intervals.append(
                Interval(
                    start=point.start,
                    end=point.start + timedelta(minutes=inputs.interval_minutes),
                    price_import_eur_kwh=point.import_eur_kwh,
                    price_export_eur_kwh=point.export_eur_kwh,
                    load_kwh=round(load_kwh, 6),
                    pv_kwh=round(pv_kwh, 6),
                    battery_charge_kwh=round(charge_kwh, 6),
                    battery_discharge_kwh=round(discharge_kwh, 6),
                    soc_pct=round(soc_pct, 3),
                    ev_kwh=round(ev_kwh, 6),
                    boiler_kwh=round(boiler_kwh, 6),
                    heat_pump_kwh=round(heat_kwh, 6),
                    machine_kwh=round(machine_kwh, 6),
                    grid_import_kwh=round(grid_import, 6),
                    grid_export_kwh=round(grid_export, 6),
                    cost_eur=round(cost, 6),
                    reason=reason,
                    explanation=REASON_EXPLANATIONS[reason],
                )
            )

        cost_eur = sum(interval.cost_eur for interval in intervals)
        baseline = sum(
            (interval.load_kwh + interval.ev_kwh + interval.boiler_kwh + interval.heat_pump_kwh + interval.machine_kwh)
            * interval.price_import_eur_kwh
            - interval.pv_kwh * interval.price_export_eur_kwh
            for interval in intervals
        )
        cycles = total_discharge / battery.capacity_kwh if battery else 0.0
        average_price = sum(point.import_eur_kwh for point in inputs.prices) / len(inputs.prices)
        terminal_value = 0.0
        if battery is not None:
            terminal_energy_kwh = (
                (soc_pct - battery.initial_soc_pct) / 100 * battery.capacity_kwh
            )
            # Surplus energy is credited at the average price. A deficit is valued at
            # the cheapest replacement price in the horizon, because that is where it
            # could be bought back.
            terminal_price = (
                average_price
                if terminal_energy_kwh >= 0
                else min(point.import_eur_kwh for point in inputs.prices)
            )
            terminal_value = terminal_energy_kwh * terminal_price
        summary = PlanSummary(
            cost_eur=round(cost_eur, 6),
            baseline_cost_eur=round(baseline, 6),
            savings_eur=round(baseline - cost_eur + terminal_value, 6),
            terminal_soc_value_eur=round(terminal_value, 6),
            import_kwh=round(sum(i.grid_import_kwh for i in intervals), 6),
            export_kwh=round(sum(i.grid_export_kwh for i in intervals), 6),
            pv_kwh=round(sum(i.pv_kwh for i in intervals), 6),
            load_kwh=round(sum(i.load_kwh for i in intervals), 6),
            battery_cycles=round(cycles, 4),
        )
        runtime_ms = int((time.perf_counter() - started) * 1000)
        return Plan(
            id=f"plan_{uuid.uuid4().hex}",
            created_at=inputs.now,
            horizon_start=start,
            horizon_end=end,
            interval_minutes=inputs.interval_minutes,
            currency="EUR",
            intervals=intervals,
            summary=summary,
            solver=SolverInfo(
                name=self.name,
                status=PlanStatus.OPTIMAL,
                runtime_ms=runtime_ms,
                objective_eur=summary.cost_eur,
                mip_gap=0.0,
            ),
            config_hash=inputs.config_hash,
            sources=inputs.sources,
        )
