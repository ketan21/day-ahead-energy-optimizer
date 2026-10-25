"""Pure helpers for the Home Assistant integration.

This module deliberately has no Home Assistant imports so it can be unit-tested
without the HA test harness.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def parse_datetime(value: str) -> datetime:
    """Parse an engine ISO timestamp."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def current_interval(plan: dict[str, Any] | None, now: datetime) -> dict[str, Any] | None:
    """Return the plan interval containing ``now``, if any."""
    if not plan:
        return None
    for interval in plan.get("intervals", []):
        start = parse_datetime(interval["start"])
        end = parse_datetime(interval["end"])
        if start <= now < end:
            return interval
    return None


def battery_action(interval: dict[str, Any] | None) -> str:
    """Describe the battery action for one interval."""
    if interval is None:
        return "unknown"
    if interval.get("battery_charge_kwh", 0) > 0:
        return "charging"
    if interval.get("battery_discharge_kwh", 0) > 0:
        return "discharging"
    return "idle"


def plan_expected_soc(
    plan: dict[str, Any] | None,
    battery: dict[str, Any] | None,
    now: datetime,
) -> float | None:
    """Estimate the plan's SOC at ``now`` for mismatch detection.

    The plan stores the SOC at the end of each interval. The first interval's
    initial SOC is reconstructed from its AC charge/discharge and the battery
    efficiency, then the current interval is interpolated linearly.
    """
    if not plan or not battery:
        return None
    intervals = plan.get("intervals") or []
    capacity = float(battery.get("capacity_kwh") or 0)
    if not intervals or capacity <= 0:
        return None
    efficiency = float(battery.get("efficiency", 1.0))
    charge_eff = efficiency * float(battery.get("dc_to_bat_efficiency", 1.0))
    discharge_eff = efficiency * float(battery.get("bat_to_dc_efficiency", 1.0))
    if charge_eff <= 0 or discharge_eff <= 0:
        return None
    first = intervals[0]
    initial = float(first.get("soc_pct", 0.0)) - (
        float(first.get("battery_charge_kwh", 0.0)) * charge_eff
        - float(first.get("battery_discharge_kwh", 0.0)) / discharge_eff
    ) / capacity * 100
    for index, interval in enumerate(intervals):
        start = parse_datetime(interval["start"])
        end = parse_datetime(interval["end"])
        if not (start <= now < end):
            continue
        start_soc = (
            initial
            if index == 0
            else float(intervals[index - 1].get("soc_pct", initial))
        )
        end_soc = float(interval.get("soc_pct", start_soc))
        fraction = (now - start).total_seconds() / (end - start).total_seconds()
        fraction = min(1.0, max(0.0, fraction))
        return start_soc + (end_soc - start_soc) * fraction
    return None


def plan_age_seconds(plan: dict[str, Any] | None, now: datetime) -> float | None:
    """Age of the plan in seconds."""
    if not plan or not plan.get("created_at"):
        return None
    return (now - parse_datetime(plan["created_at"])).total_seconds()


def ev_windows(plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Merge contiguous EV charging intervals into calendar windows."""
    if not plan:
        return []
    windows: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for interval in plan.get("intervals", []):
        energy = float(interval.get("ev_kwh", 0))
        start = parse_datetime(interval["start"])
        end = parse_datetime(interval["end"])
        if energy <= 0:
            if current is not None:
                windows.append(current)
                current = None
            continue
        if current is not None and current["end"] == start:
            current["end"] = end
            current["kwh"] += energy
        else:
            if current is not None:
                windows.append(current)
            current = {"start": start, "end": end, "kwh": energy}
    if current is not None:
        windows.append(current)
    return windows


def plan_is_valid(
    plan: dict[str, Any] | None,
    config_hash: str | None,
    now: datetime,
    max_age_seconds: int = 26 * 3600,
) -> bool:
    """A plan is valid when it matches the engine config and is recent enough."""
    age = plan_age_seconds(plan, now)
    if plan is None or age is None or config_hash is None:
        return False
    if plan.get("config_hash") != config_hash:
        return False
    return -60 <= age <= max_age_seconds
