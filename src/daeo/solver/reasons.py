"""Shared plan reason selection and explanations."""

from __future__ import annotations

from daeo.domain.enums import Reason

REASON_EXPLANATIONS: dict[Reason, str] = {
    Reason.PRICE_LOW: "Charging because the import price is in the cheapest part of the horizon.",
    Reason.PRICE_HIGH: "Discharging because the import price is in the most expensive part of the horizon.",
    Reason.PV_SURPLUS: "Charging from PV surplus instead of exporting at a low price.",
    Reason.SOC_MIN: "The reserve state of charge prevents further discharge.",
    Reason.SOC_MAX: "The battery is full; no further charging is possible.",
    Reason.EV_DEADLINE: "Charging the EV in its cheapest window before departure.",
    Reason.BOILER_DEMAND: "Heating the boiler in its cheapest window.",
    Reason.HEAT_DEMAND: "Running the heat pump in its cheapest window.",
    Reason.MACHINE_DEADLINE: "Running the machine inside its allowed window.",
    Reason.GRID_LIMIT: "The grid connection limit constrains this interval.",
    Reason.IDLE: "No controllable load or price incentive in this interval.",
}


def pick_reason(
    *,
    has_battery: bool,
    ev_kwh: float,
    boiler_kwh: float,
    heat_kwh: float,
    machine_kwh: float,
    charge_kwh: float,
    discharge_kwh: float,
    pv_kwh: float,
    load_kwh: float,
    price: float,
    low: float,
    high: float,
    soc_pct: float,
    min_soc: float,
    max_soc: float,
) -> Reason:
    """Pick the dominant reason for one interval."""
    if ev_kwh > 1e-9:
        return Reason.EV_DEADLINE
    if boiler_kwh > 1e-9:
        return Reason.BOILER_DEMAND
    if heat_kwh > 1e-9:
        return Reason.HEAT_DEMAND
    if machine_kwh > 1e-9:
        return Reason.MACHINE_DEADLINE
    if charge_kwh > 1e-9 and pv_kwh > load_kwh:
        return Reason.PV_SURPLUS
    if charge_kwh > 1e-9 and price <= low:
        return Reason.PRICE_LOW
    if discharge_kwh > 1e-9 and price >= high:
        return Reason.PRICE_HIGH
    if has_battery and soc_pct >= max_soc - 1e-6:
        return Reason.SOC_MAX
    if has_battery and soc_pct <= min_soc + 1e-6:
        return Reason.SOC_MIN
    return Reason.IDLE
