"""Pure battery-control decisions.

No Home Assistant imports, so the logic can be tested in the engine test suite.
The HA controller applies the decision to entities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .plan import current_interval, parse_datetime, plan_age_seconds


@dataclass(frozen=True)
class ControlDecision:
    """What the control loop should do next."""

    action: str  # apply | fallback | blocked | none
    power_w: float = 0.0
    mode: str | None = None
    reason: str = ""
    interval_start: datetime | None = None


def battery_power_w(interval: dict[str, Any], interval_minutes: int) -> float:
    """Convert interval energy to a signed AC power setpoint in W.

    Positive means charging, negative means discharging, matching the battery
    setpoint entity contract in the configuration.
    """
    hours = interval_minutes / 60
    charge = float(interval.get("battery_charge_kwh", 0))
    discharge = float(interval.get("battery_discharge_kwh", 0))
    return (charge - discharge) / hours * 1000


def setpoint_write_value(
    power_w: float,
    *,
    unsigned: bool,
    invert: bool,
) -> float:
    """Convert the controller's + charge / - discharge value for a vendor entity."""
    value = -power_w if invert else power_w
    return abs(value) if unsigned else value


def clamp_power_for_soc(
    power_w: float,
    soc_pct: float | None,
    min_soc_pct: float,
    max_soc_pct: float,
    tolerance: float = 0.5,
) -> float:
    """Prevent charging at the top and discharging at the bottom of the SOC range."""
    if soc_pct is None:
        return power_w
    if power_w > 1 and soc_pct >= max_soc_pct - tolerance:
        return 0.0
    if power_w < -1 and soc_pct <= min_soc_pct + tolerance:
        return 0.0
    return power_w


def desired_mode(battery: dict[str, Any], power_w: float) -> str | None:
    """Return the configured mode for a power setpoint."""
    if power_w > 1:
        return battery.get("mode_charge")
    if power_w < -1:
        return battery.get("mode_discharge")
    return battery.get("mode_idle")


def _fallback(battery: dict[str, Any] | None, reason: str) -> ControlDecision:
    return ControlDecision(
        action="fallback",
        power_w=0.0,
        mode=battery.get("mode_idle") if battery else None,
        reason=reason,
    )


def decide_control(
    plan: dict[str, Any] | None,
    health: dict[str, Any] | None,
    config: dict[str, Any] | None,
    now: datetime,
    *,
    armed: bool,
    last_interval_start: datetime | None,
    last_power_w: float | None,
    max_age_seconds: int,
) -> ControlDecision:
    """Decide whether to apply, fallback, block, or do nothing."""
    batteries = (config or {}).get("batteries") or []
    battery = batteries[0] if batteries else None
    if not armed:
        return _fallback(battery, "disarmed")
    if battery is None or not battery.get("setpoint_entity"):
        return ControlDecision(action="blocked", reason="no_setpoint")
    if plan is None:
        return _fallback(battery, "no_plan")
    age = plan_age_seconds(plan, now)
    if age is None or age > max_age_seconds:
        return _fallback(battery, "stale_plan")
    if health is None or plan.get("config_hash") != health.get("config_hash"):
        return _fallback(battery, "config_mismatch")
    interval = current_interval(plan, now)
    if interval is None:
        return _fallback(battery, "outside_plan")

    power = battery_power_w(interval, int(plan.get("interval_minutes", 15)))
    interval_start = parse_datetime(interval["start"])
    if (
        last_interval_start == interval_start
        and last_power_w is not None
        and abs(last_power_w - power) < 1
    ):
        return ControlDecision(
            action="none",
            power_w=power,
            mode=desired_mode(battery, power),
            reason="unchanged",
            interval_start=interval_start,
        )
    return ControlDecision(
        action="apply",
        power_w=power,
        mode=desired_mode(battery, power),
        reason="plan",
        interval_start=interval_start,
    )
