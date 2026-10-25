"""CBC-backed MILP solver.

This is the first production adapter. It optimises the supported subset of the
legacy model:

- multiple batteries with one-way efficiency, SOC limits, power limits, cycle cost,
  and a terminal SOC constraint,
- multiple EVs with a required energy before departure,
- boiler, heat-pump, and machine energy inside their allowed windows,
- grid import/export limits and PV curtailment,
- cost minimisation or import minimisation.

Battery charge/discharge stage curves, battery AC/DC efficiencies, reduced-power SOC
limits, minimum power, and terminal SOC targets are ported. PV array DC coupling, EV
charge stages, and heat-curve dynamics from the legacy model are not ported yet. The
interface is the same `solve(inputs) -> Plan` boundary, so those constraints can be
added without changing the API or UI.
"""

from __future__ import annotations

import math
import time
import uuid
from datetime import timedelta

from mip import BINARY, CBC, CONTINUOUS, Model, OptimizationStatus, minimize, xsum

from daeo.domain.enums import Objective, PlanStatus
from daeo.domain.inputs import FlexibleLoadInput, OptimizationInput
from daeo.domain.plan import Interval, Plan, PlanSummary, SolverInfo
from daeo.solver.base import SolverError
from daeo.solver.reasons import REASON_EXPLANATIONS, pick_reason


def _normalise_stages(
    stages: list,
    max_power_kw: float,
    fallback_efficiency: float,
) -> list[tuple[float, float]]:
    """Return a sorted, deduplicated (power_kw, efficiency) stage curve."""
    points: dict[float, float] = {0.0: fallback_efficiency}
    for stage in sorted(stages, key=lambda item: item.power_kw):
        power = min(max(0.0, stage.power_kw), max_power_kw)
        points[power] = stage.efficiency
    ordered = sorted(points.items())
    if ordered[-1][0] < max_power_kw:
        ordered.append((max_power_kw, ordered[-1][1]))
    if len(ordered) == 1:
        ordered.append((max_power_kw, ordered[0][1]))
    return ordered


def _allocation(energy: float, power_kw: float, dt: float, indices: list[int]) -> dict[int, float]:
    """Allocate energy to the earliest available intervals (baseline only)."""
    allocation: dict[int, float] = {}
    remaining = energy
    for index in indices:
        if remaining <= 1e-9:
            break
        amount = min(power_kw * dt, remaining)
        if amount > 0:
            allocation[index] = amount
            remaining -= amount
    return allocation


def _baseline_cost(inputs: OptimizationInput) -> float:
    """Cost of running flexible loads as early as possible, with no battery."""
    demand = list(inputs.load_kwh)
    dt = inputs.interval_minutes / 60

    for vehicle in inputs.evs:
        required = vehicle.capacity_kwh * (
            vehicle.target_soc_pct - vehicle.current_soc_pct
        ) / 100
        indices = [
            index
            for index, price in enumerate(inputs.prices)
            if price.start < vehicle.ready_at
        ]
        for index, amount in _allocation(
            required, vehicle.max_charge_kw, dt, indices
        ).items():
            demand[index] += amount

    loads: list[FlexibleLoadInput | None] = [
        inputs.boiler,
        inputs.heat_pump,
        *inputs.machines,
    ]
    for item in loads:
        if item is None or item.energy_kwh <= 0:
            continue
        indices = [
            index
            for index, price in enumerate(inputs.prices)
            if item.earliest <= price.start < item.deadline
        ]
        for index, amount in _allocation(
            item.energy_kwh, item.max_power_kw, dt, indices
        ).items():
            demand[index] += amount

    cost = 0.0
    for index, price in enumerate(inputs.prices):
        net = demand[index] - inputs.pv_kwh[index]
        import_kwh = max(0.0, net)
        export_kwh = max(0.0, -net) if inputs.allow_export else 0.0
        export_kwh = min(export_kwh, inputs.grid_max_export_kw * dt)
        cost += (
            import_kwh * price.import_eur_kwh
            - export_kwh * price.export_eur_kwh
        )
    return cost


class CbcSolver:
    """Optimise the supported DAEO device set with CBC via python-mip."""

    name = "cbc"

    def __init__(self, max_seconds: int = 120) -> None:
        self.max_seconds = max_seconds

    def solve(self, inputs: OptimizationInput) -> Plan:
        count = len(inputs.prices)
        dt = inputs.interval_minutes / 60
        started = time.perf_counter()

        try:
            model = Model(solver_name=CBC)
        except Exception as error:  # noqa: BLE001 - CBC native library may be missing
            raise SolverError(f"CBC solver is unavailable: {error}") from error
        model.verbose = 0
        model.threads = inputs.solver_threads or -1
        model.max_mip_gap_abs = inputs.max_gap_eur

        import_kwh = [
            model.add_var(
                name=f"import_{index}",
                var_type=CONTINUOUS,
                lb=0,
                ub=inputs.grid_max_import_kw * dt,
            )
            for index in range(count)
        ]
        export_ub = inputs.grid_max_export_kw * dt if inputs.allow_export else 0.0
        export_kwh = [
            model.add_var(
                name=f"export_{index}",
                var_type=CONTINUOUS,
                lb=0,
                ub=export_ub,
            )
            for index in range(count)
        ]
        import_on = [
            model.add_var(name=f"import_on_{index}", var_type=BINARY)
            for index in range(count)
        ]
        export_on = [
            model.add_var(name=f"export_on_{index}", var_type=BINARY)
            for index in range(count)
        ]
        for index in range(count):
            model += (
                import_kwh[index]
                <= inputs.grid_max_import_kw * dt * import_on[index]
            )
            model += export_kwh[index] <= export_ub * export_on[index]
            model += import_on[index] + export_on[index] <= 1

        curtail_kwh = [
            model.add_var(
                name=f"curtail_{index}",
                var_type=CONTINUOUS,
                lb=0,
                ub=inputs.pv_kwh[index],
            )
            for index in range(count)
        ]

        battery_vars: list[dict] = []
        for battery_index, battery in enumerate(inputs.batteries):
            capacity = battery.capacity_kwh
            min_energy = battery.min_soc_pct / 100 * capacity
            max_energy = battery.max_soc_pct / 100 * capacity
            initial_energy = battery.initial_soc_pct / 100 * capacity
            charge_points = _normalise_stages(
                battery.charge_stages,
                battery.max_charge_kw,
                battery.efficiency,
            )
            discharge_points = _normalise_stages(
                battery.discharge_stages,
                battery.max_discharge_kw,
                battery.efficiency,
            )
            dc_discharge_ub = battery.max_discharge_kw * dt / (
                min(efficiency for _, efficiency in discharge_points)
                * battery.bat_to_dc_efficiency
            )
            ac_charge = [
                model.add_var(
                    name=f"battery_{battery_index}_ac_charge_{index}",
                    var_type=CONTINUOUS,
                    lb=0,
                    ub=battery.max_charge_kw * dt,
                )
                for index in range(count)
            ]
            ac_discharge = [
                model.add_var(
                    name=f"battery_{battery_index}_ac_discharge_{index}",
                    var_type=CONTINUOUS,
                    lb=0,
                    ub=battery.max_discharge_kw * dt,
                )
                for index in range(count)
            ]
            dc_charge = [
                model.add_var(
                    name=f"battery_{battery_index}_dc_charge_{index}",
                    var_type=CONTINUOUS,
                    lb=0,
                    ub=battery.max_charge_kw * dt,
                )
                for index in range(count)
            ]
            dc_discharge = [
                model.add_var(
                    name=f"battery_{battery_index}_dc_discharge_{index}",
                    var_type=CONTINUOUS,
                    lb=0,
                    ub=dc_discharge_ub,
                )
                for index in range(count)
            ]
            soc = [
                model.add_var(
                    name=f"battery_{battery_index}_soc_{index}",
                    var_type=CONTINUOUS,
                    lb=min_energy,
                    ub=max_energy,
                )
                for index in range(count)
            ]
            charge_on = [
                model.add_var(
                    name=f"battery_{battery_index}_charge_on_{index}",
                    var_type=BINARY,
                )
                for index in range(count)
            ]
            discharge_on = [
                model.add_var(
                    name=f"battery_{battery_index}_discharge_on_{index}",
                    var_type=BINARY,
                )
                for index in range(count)
            ]
            charge_weights = [
                [
                    model.add_var(
                        name=f"battery_{battery_index}_charge_w_{index}_{stage}",
                        var_type=CONTINUOUS,
                        lb=0,
                        ub=1,
                    )
                    for stage in range(len(charge_points))
                ]
                for index in range(count)
            ]
            discharge_weights = [
                [
                    model.add_var(
                        name=f"battery_{battery_index}_discharge_w_{index}_{stage}",
                        var_type=CONTINUOUS,
                        lb=0,
                        ub=1,
                    )
                    for stage in range(len(discharge_points))
                ]
                for index in range(count)
            ]
            charge_samples = [power * dt for power, _ in charge_points]
            discharge_samples = [power * dt for power, _ in discharge_points]
            low_soc = sorted(battery.reduce_power_low_soc, key=lambda point: point.soc_pct)
            high_soc = sorted(
                battery.reduce_power_high_soc, key=lambda point: point.soc_pct
            )
            for index in range(count):
                model += xsum(charge_weights[index]) == 1
                model += (
                    ac_charge[index]
                    == dt
                    * xsum(
                        charge_weights[index][stage] * charge_points[stage][0]
                        for stage in range(len(charge_points))
                    )
                )
                model += (
                    dc_charge[index]
                    == dt
                    * xsum(
                        charge_weights[index][stage]
                        * charge_points[stage][0]
                        * charge_points[stage][1]
                        for stage in range(len(charge_points))
                    )
                    * battery.dc_to_bat_efficiency
                )
                model.add_sos(
                    [
                        (charge_weights[index][stage], charge_samples[stage])
                        for stage in range(len(charge_points))
                    ],
                    2,
                )

                model += xsum(discharge_weights[index]) == 1
                model += (
                    ac_discharge[index]
                    == dt
                    * xsum(
                        discharge_weights[index][stage] * discharge_points[stage][0]
                        for stage in range(len(discharge_points))
                    )
                )
                model += (
                    dc_discharge[index]
                    == dt
                    * xsum(
                        discharge_weights[index][stage]
                        * discharge_points[stage][0]
                        / discharge_points[stage][1]
                        for stage in range(len(discharge_points))
                    )
                    / battery.bat_to_dc_efficiency
                )
                model.add_sos(
                    [
                        (discharge_weights[index][stage], discharge_samples[stage])
                        for stage in range(len(discharge_points))
                    ],
                    2,
                )

                model += (
                    ac_charge[index]
                    <= battery.max_charge_kw * dt * charge_on[index]
                )
                model += (
                    ac_discharge[index]
                    <= battery.max_discharge_kw * dt * discharge_on[index]
                )
                model += charge_on[index] + discharge_on[index] <= 1
                if battery.minimum_power_kw > 0:
                    model += (
                        ac_charge[index]
                        >= battery.minimum_power_kw * dt * charge_on[index]
                    )
                    model += (
                        ac_discharge[index]
                        >= battery.minimum_power_kw * dt * discharge_on[index]
                    )

                previous = initial_energy if index == 0 else soc[index - 1]
                model += (
                    soc[index]
                    == previous
                    + dc_charge[index]
                    - dc_discharge[index]
                )

                for left, right in zip(low_soc, low_soc[1:], strict=False):
                    if right.soc_pct <= left.soc_pct:
                        continue
                    slope = (right.power_kw - left.power_kw) / (
                        right.soc_pct - left.soc_pct
                    )
                    model += dc_discharge[index] <= dt * (
                        left.power_kw
                        + slope * (soc[index] / capacity * 100 - left.soc_pct)
                    )
                for left, right in zip(high_soc, high_soc[1:], strict=False):
                    if right.soc_pct <= left.soc_pct:
                        continue
                    slope = (right.power_kw - left.power_kw) / (
                        right.soc_pct - left.soc_pct
                    )
                    model += dc_charge[index] <= dt * (
                        left.power_kw
                        + slope * (soc[index] / capacity * 100 - left.soc_pct)
                    )

            min_end = (
                battery.min_soc_end_pct
                if battery.min_soc_end_pct is not None
                else battery.initial_soc_pct
            )
            max_end = min(battery.max_soc_end_pct, battery.max_soc_pct)
            if min_end > max_end:
                raise SolverError(
                    f"Battery {battery.name} has an impossible terminal SOC range"
                )
            model += soc[-1] >= min_end / 100 * capacity
            model += soc[-1] <= max_end / 100 * capacity
            battery_vars.append(
                {
                    "battery": battery,
                    "ac_charge": ac_charge,
                    "ac_discharge": ac_discharge,
                    "dc_charge": dc_charge,
                    "dc_discharge": dc_discharge,
                    "soc": soc,
                    "initial_energy": initial_energy,
                }
            )

        ev_vars: list[list] = []
        for ev_index, vehicle in enumerate(inputs.evs):
            required = vehicle.capacity_kwh * (
                vehicle.target_soc_pct - vehicle.current_soc_pct
            ) / 100
            if required <= 1e-9:
                ev_vars.append([None] * count)
                continue
            available: list[int] = []
            variables = []
            for index, price in enumerate(inputs.prices):
                if price.start < vehicle.ready_at:
                    available.append(index)
                    ub = vehicle.max_charge_kw * dt
                else:
                    ub = 0.0
                variables.append(
                    model.add_var(
                        name=f"ev_{ev_index}_{index}",
                        var_type=CONTINUOUS,
                        lb=0,
                        ub=ub,
                    )
                )
            if not available:
                raise SolverError(
                    f"EV {vehicle.name} cannot charge before its ready time"
                )
            if len(available) * vehicle.max_charge_kw * dt + 1e-9 < required:
                raise SolverError(
                    f"EV {vehicle.name} cannot charge {required:.2f} kWh before its ready time"
                )
            model += xsum(variables) == required
            ev_vars.append(variables)

        def add_flexible(
            name: str,
            item: FlexibleLoadInput | None,
        ) -> list | None:
            nonlocal model
            if item is None or item.energy_kwh <= 1e-9:
                return None
            variables = []
            capacity = 0.0
            for index, price in enumerate(inputs.prices):
                in_window = item.earliest <= price.start < item.deadline
                ub = item.max_power_kw * dt if in_window else 0.0
                capacity += ub
                variables.append(
                    model.add_var(
                        name=f"{name}_{index}",
                        var_type=CONTINUOUS,
                        lb=0,
                        ub=ub,
                    )
                )
            if capacity + 1e-9 < item.energy_kwh:
                if item.mandatory:
                    raise SolverError(
                        f"{name} cannot deliver {item.energy_kwh:.2f} kWh inside its window"
                    )
                return variables
            if item.mandatory:
                model += xsum(variables) == item.energy_kwh
            else:
                model += xsum(variables) <= item.energy_kwh
            return variables

        boiler_vars = add_flexible("boiler", inputs.boiler)
        heat_vars = add_flexible("heat_pump", inputs.heat_pump)
        machine_vars = [
            add_flexible(f"machine_{index}", machine)
            for index, machine in enumerate(inputs.machines)
        ]

        for index in range(count):
            demand = inputs.load_kwh[index]
            supply = inputs.pv_kwh[index] - curtail_kwh[index]
            for variables in battery_vars:
                demand += variables["ac_charge"][index]
                supply += variables["ac_discharge"][index]
            for variables in ev_vars:
                if variables[index] is not None:
                    demand += variables[index]
            if boiler_vars is not None:
                demand += boiler_vars[index]
            if heat_vars is not None:
                demand += heat_vars[index]
            for variables in machine_vars:
                if variables is not None:
                    demand += variables[index]
            model += import_kwh[index] - export_kwh[index] == demand - supply

        cost_terms = [
            import_kwh[index] * price.import_eur_kwh
            - export_kwh[index] * price.export_eur_kwh
            for index, price in enumerate(inputs.prices)
        ]
        cycle_cost = xsum(
            (variables["dc_charge"][index] + variables["dc_discharge"][index])
            * inputs.cycle_cost_eur_kwh
            for variables in battery_vars
            for index in range(count)
        )
        if inputs.objective is Objective.MINIMIZE_IMPORT:
            objective = xsum(import_kwh) + 1e-6 * xsum(cost_terms)
        else:
            objective = xsum(cost_terms) + cycle_cost
        model.objective = minimize(objective)

        status = model.optimize(max_seconds=self.max_seconds)
        runtime_ms = int((time.perf_counter() - started) * 1000)
        if status not in (OptimizationStatus.OPTIMAL, OptimizationStatus.FEASIBLE):
            raise SolverError(f"CBC did not find a feasible plan: {status}")

        def value(variable) -> float:
            return float(variable.x) if variable.x is not None else 0.0

        sorted_prices = sorted(price.import_eur_kwh for price in inputs.prices)
        low = sorted_prices[max(0, int(len(sorted_prices) * 0.3) - 1)]
        high = sorted_prices[min(len(sorted_prices) - 1, int(len(sorted_prices) * 0.7))]
        total_capacity = sum(
            variables["battery"].capacity_kwh for variables in battery_vars
        )
        min_soc = min(
            (variables["battery"].min_soc_pct for variables in battery_vars),
            default=0.0,
        )
        max_soc = max(
            (variables["battery"].max_soc_pct for variables in battery_vars),
            default=100.0,
        )

        intervals: list[Interval] = []
        for index, price in enumerate(inputs.prices):
            charge = sum(
                value(variables["ac_charge"][index]) for variables in battery_vars
            )
            discharge = sum(
                value(variables["ac_discharge"][index]) for variables in battery_vars
            )
            dc_charge = sum(
                value(variables["dc_charge"][index]) for variables in battery_vars
            )
            dc_discharge = sum(
                value(variables["dc_discharge"][index]) for variables in battery_vars
            )
            soc_kwh = sum(value(variables["soc"][index]) for variables in battery_vars)
            soc_pct = (soc_kwh / total_capacity * 100) if total_capacity else 0.0
            if charge < 1e-7:
                charge = 0.0
            if discharge < 1e-7:
                discharge = 0.0
            ev_kwh = sum(
                value(variables[index])
                for variables in ev_vars
                if variables[index] is not None
            )
            boiler_kwh = value(boiler_vars[index]) if boiler_vars is not None else 0.0
            heat_kwh = value(heat_vars[index]) if heat_vars is not None else 0.0
            machine_kwh = sum(
                value(variables[index])
                for variables in machine_vars
                if variables is not None
            )
            grid_import = value(import_kwh[index])
            grid_export = value(export_kwh[index])
            cost = (
                grid_import * price.import_eur_kwh
                - grid_export * price.export_eur_kwh
                + (dc_charge + dc_discharge) * inputs.cycle_cost_eur_kwh
            )
            reason = pick_reason(
                has_battery=bool(battery_vars),
                ev_kwh=ev_kwh,
                boiler_kwh=boiler_kwh,
                heat_kwh=heat_kwh,
                machine_kwh=machine_kwh,
                charge_kwh=charge,
                discharge_kwh=discharge,
                pv_kwh=inputs.pv_kwh[index],
                load_kwh=inputs.load_kwh[index],
                price=price.import_eur_kwh,
                low=low,
                high=high,
                soc_pct=soc_pct,
                min_soc=min_soc,
                max_soc=max_soc,
            )
            intervals.append(
                Interval(
                    start=price.start,
                    end=price.start + timedelta(minutes=inputs.interval_minutes),
                    price_import_eur_kwh=price.import_eur_kwh,
                    price_export_eur_kwh=price.export_eur_kwh,
                    load_kwh=round(inputs.load_kwh[index], 6),
                    pv_kwh=round(inputs.pv_kwh[index], 6),
                    battery_charge_kwh=round(charge, 6),
                    battery_discharge_kwh=round(discharge, 6),
                    soc_pct=round(min(100.0, max(0.0, soc_pct)), 3),
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
        baseline = _baseline_cost(inputs)
        average_price = sum(price.import_eur_kwh for price in inputs.prices) / count
        final_energy = sum(
            value(variables["soc"][-1]) for variables in battery_vars
        )
        initial_energy = sum(
            variables["initial_energy"] for variables in battery_vars
        )
        terminal_energy = final_energy - initial_energy
        if terminal_energy >= 0:
            terminal_price = average_price
        else:
            terminal_price = min(price.import_eur_kwh for price in inputs.prices)
        terminal_value = terminal_energy * terminal_price
        total_discharge = sum(
            sum(value(variable) for variable in variables["dc_discharge"])
            for variables in battery_vars
        )
        summary = PlanSummary(
            cost_eur=round(cost_eur, 6),
            baseline_cost_eur=round(baseline, 6),
            savings_eur=round(baseline - cost_eur + terminal_value, 6),
            import_kwh=round(sum(interval.grid_import_kwh for interval in intervals), 6),
            export_kwh=round(sum(interval.grid_export_kwh for interval in intervals), 6),
            pv_kwh=round(sum(interval.pv_kwh for interval in intervals), 6),
            load_kwh=round(sum(interval.load_kwh for interval in intervals), 6),
            battery_cycles=round(
                total_discharge / total_capacity if total_capacity else 0.0,
                4,
            ),
            terminal_soc_value_eur=round(terminal_value, 6),
        )
        gap = getattr(model, "gap", None)
        mip_gap = (
            0.0
            if status is OptimizationStatus.OPTIMAL
            else (float(gap) if gap is not None and math.isfinite(gap) else None)
        )
        return Plan(
            id=f"plan_{uuid.uuid4().hex}",
            created_at=inputs.now,
            horizon_start=inputs.prices[0].start,
            horizon_end=inputs.prices[-1].start
            + timedelta(minutes=inputs.interval_minutes),
            interval_minutes=inputs.interval_minutes,
            currency="EUR",
            intervals=intervals,
            summary=summary,
            solver=SolverInfo(
                name=self.name,
                status=(
                    PlanStatus.OPTIMAL
                    if status is OptimizationStatus.OPTIMAL
                    else PlanStatus.FEASIBLE
                ),
                runtime_ms=runtime_ms,
                objective_eur=(
                    float(model.objective_value)
                    if model.objective_value is not None
                    else None
                ),
                mip_gap=mip_gap,
            ),
            config_hash=inputs.config_hash,
            sources=inputs.sources,
        )
