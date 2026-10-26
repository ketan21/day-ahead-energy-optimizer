"""Battery control loop for the DAEO integration.

The engine plans; this controller applies the current interval's battery power to
Home Assistant entities, with explicit arming, verification, fallback, and audit.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .control import (
    ControlDecision,
    clamp_power_for_soc,
    decide_control,
    desired_mode,
    setpoint_write_value,
)
from .coordinator import DaeoCoordinator
from .plan import (
    current_interval,
    parse_datetime,
    plan_age_seconds,
    plan_expected_soc,
)

_LOGGER = logging.getLogger(__name__)

TICK_INTERVAL = timedelta(seconds=10)
REFRESH_THROTTLE = timedelta(minutes=5)
POWER_TOLERANCE_W = 10.0


class ControlError(RuntimeError):
    """A control write or verification failed."""


class BatteryController:
    """Apply the current plan interval to the configured battery entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry,
        coordinator: DaeoCoordinator,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._armed = False
        self._status = "disarmed"
        self._last_power_w: float | None = None
        self._last_plan_power_w: float | None = None
        self._last_mode: str | None = None
        self._last_interval_start: datetime | None = None
        self._last_apply: datetime | None = None
        self._last_error: str | None = None
        self._last_refresh: datetime | None = None
        self._force_refresh = False
        self._fallback_applied = False
        self._last_fallback_reason: str | None = None
        self._audit: list[dict[str, Any]] = []
        self._listeners: list[Callable[[], None]] = []
        self._lock = asyncio.Lock()

    @property
    def armed(self) -> bool:
        return self._armed

    @property
    def status(self) -> str:
        return self._status

    @property
    def active(self) -> bool:
        return self._armed and self._status == "applied"

    @property
    def last_power_w(self) -> float | None:
        return self._last_power_w

    @property
    def last_mode(self) -> str | None:
        return self._last_mode

    @property
    def last_apply(self) -> datetime | None:
        return self._last_apply

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def audit(self) -> list[dict[str, Any]]:
        return list(self._audit)

    def add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return remove

    def _notify(self) -> None:
        for listener in list(self._listeners):
            try:
                listener()
            except Exception:  # noqa: BLE001 - listener may be removed
                _LOGGER.debug("Control listener failed", exc_info=True)

    def _battery(self) -> dict[str, Any] | None:
        if not self.coordinator.data:
            return None
        batteries = self.coordinator.data.config.get("batteries") or []
        return batteries[0] if batteries else None

    def _live_soc_pct(self, battery: dict[str, Any] | None) -> float | None:
        """Read the configured battery SOC; raise when configured but unavailable."""
        if not battery:
            return None
        soc_entity = battery.get("soc_entity")
        if not soc_entity:
            return None
        state = self.hass.states.get(soc_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            raise ControlError(f"SOC entity {soc_entity} is unavailable")
        try:
            return float(state.state)
        except ValueError as error:
            raise ControlError(f"SOC entity {soc_entity} is not numeric") from error

    def _zero_grid_adjustment(
        self,
        base_power_w: float,
        interval: dict[str, Any] | None,
        battery: dict[str, Any],
    ) -> float | None:
        """Return a setpoint corrected to the interval's planned grid target.

        The plan's own grid target is used, so self-consumption intervals target
        zero while arbitrage intervals follow their planned import/export. A
        battery explicitly marked idle (no charge/discharge) is never corrected.
        """
        if not interval:
            return None
        if (
            float(interval.get("battery_charge_kwh", 0.0)) <= 1e-6
            and float(interval.get("battery_discharge_kwh", 0.0)) <= 1e-6
        ):
            # Explicitly idle: do not invent battery activity.
            return None
        config = self.coordinator.data.config if self.coordinator.data else {}
        grid = config.get("grid") or {}
        entity_id = grid.get("power_sensor_entity")
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            grid_w = float(state.state)
        except ValueError:
            return None
        if grid.get("power_sensor_invert"):
            grid_w = -grid_w

        start = parse_datetime(interval["start"])
        end = parse_datetime(interval["end"])
        hours = max((end - start).total_seconds() / 3600, 1e-6)
        target_w = (
            float(interval.get("grid_import_kwh", 0.0))
            - float(interval.get("grid_export_kwh", 0.0))
        ) / hours * 1000

        deadband = float(grid.get("zero_grid_deadband_w", 30.0))
        error_w = grid_w - target_w
        if abs(error_w) <= deadband:
            return None

        max_charge_w = float(battery.get("max_charge_kw", 0.0)) * 1000
        max_discharge_w = float(battery.get("max_discharge_kw", 0.0)) * 1000
        adjusted = base_power_w - error_w
        adjusted = max(-max_discharge_w, min(max_charge_w, adjusted))

        max_step = float(grid.get("zero_grid_max_step_w", 1000.0))
        if max_step > 0 and self._last_power_w is not None:
            delta = adjusted - self._last_power_w
            delta = max(-max_step, min(max_step, delta))
            adjusted = self._last_power_w + delta

        minimum = float(battery.get("minimum_power_kw", 0.0)) * 1000
        if abs(adjusted) < max(minimum, 1.0):
            adjusted = 0.0
        if self._last_power_w is not None and abs(adjusted - self._last_power_w) < deadband:
            return None
        return round(adjusted, 1)

    def _plan_soc_mismatch(
        self,
        plan: dict[str, Any] | None,
        battery: dict[str, Any] | None,
        now: datetime,
    ) -> bool:
        """True when the actual SOC no longer matches the plan's SOC trajectory."""
        if not plan or not battery or not battery.get("soc_entity"):
            return False
        actual = self._live_soc_pct(battery)
        expected = plan_expected_soc(plan, battery, now)
        if actual is None or expected is None:
            return False
        return abs(actual - expected) > 5.0

    def _audit_add(
        self,
        action: str,
        *,
        reason: str,
        power_w: float | None,
        mode: str | None,
    ) -> None:
        now = dt_util.now()
        plan = self.coordinator.data.plan if self.coordinator.data else None
        entry = {
            "at": now.isoformat(),
            "action": action,
            "reason": reason,
            "power_w": power_w,
            "mode": mode,
            "plan_id": plan.get("id") if plan else None,
            "interval_start": (
                self._last_interval_start.isoformat()
                if self._last_interval_start
                else None
            ),
        }
        self._audit.append(entry)
        del self._audit[:-50]
        self.hass.bus.async_fire(f"{DOMAIN}_control_{action}", entry)

    async def async_set_armed(self, armed: bool) -> None:
        async with self._lock:
            if armed == self._armed:
                return
            self._armed = armed
            self._last_fallback_reason = None
            if not armed:
                await self._fallback("disarmed")
            else:
                self._fallback_applied = False
                self._force_refresh = bool(
                    self._battery() and self._battery().get("soc_entity")
                )
                self._status = "waiting"
                self._notify()
                await self._async_tick()

    async def async_tick(self, _now: datetime | None = None) -> None:
        async with self._lock:
            await self._async_tick()

    async def _async_tick(self) -> None:
        if not self._armed:
            if not self._fallback_applied:
                await self._fallback("disarmed")
            return

        if not self.coordinator.data:
            self._status = "no_data"
            self._notify()
            return

        data = self.coordinator.data
        plan = data.plan
        battery = self._battery()
        if battery is None or not battery.get("setpoint_entity"):
            self._status = "not_configured"
            self._notify()
            return

        now = dt_util.now()
        try:
            if self._plan_soc_mismatch(plan, battery, now):
                self._force_refresh = True
        except ControlError as error:
            self._last_error = str(error)
            self._status = "error"
            _LOGGER.error("Battery SOC check failed: %s", error)
            await self._fallback("soc_unavailable")
            self._armed = False
            self._notify()
            return

        age = plan_age_seconds(plan, now)
        minutes = int((plan or {}).get("interval_minutes", 15))
        forced = self._force_refresh
        self._force_refresh = False
        if forced:
            self._last_refresh = None
        needs_refresh = (
            forced
            or plan is None
            or age is None
            or age > max(minutes * 60, 900)
            or current_interval(plan, now) is None
        )
        if needs_refresh:
            refreshed = await self._refresh(now)
            data = self.coordinator.data
            plan = data.plan if data else None
            if not refreshed:
                await self._fallback("refresh_failed")
                self._armed = False
                self._notify()
                return

        decision = decide_control(
            plan,
            data.health if data else None,
            data.config if data else None,
            now,
            armed=self._armed,
            last_interval_start=self._last_interval_start,
            last_power_w=self._last_plan_power_w,
            max_age_seconds=max(2 * minutes * 60, 1800),
        )

        interval = current_interval(plan, now)
        adjusted = None
        if decision.action in ("apply", "none"):
            try:
                adjusted = self._zero_grid_adjustment(
                    decision.power_w, interval, battery
                )
            except ControlError as error:
                self._last_error = str(error)
                self._status = "error"
                _LOGGER.error("Zero-grid correction failed: %s", error)
                await self._fallback("grid_control_failed")
                self._armed = False
                self._notify()
                return

        if decision.action == "apply":
            await self._apply(
                decision,
                battery,
                power_w=adjusted if adjusted is not None else decision.power_w,
                plan_power_w=decision.power_w,
            )
        elif decision.action == "none" and adjusted is not None:
            await self._apply(
                decision,
                battery,
                power_w=adjusted,
                plan_power_w=decision.power_w,
                record_plan=False,
            )
        elif decision.action == "fallback":
            if (
                not self._fallback_applied
                or self._last_fallback_reason != decision.reason
            ):
                await self._fallback(decision.reason)
        elif decision.action == "blocked":
            self._status = f"blocked:{decision.reason}"
            self._notify()
        else:
            self._status = "applied" if self._last_apply else "waiting"
            self._notify()

    async def _refresh(self, now: datetime) -> bool:
        if self._last_refresh and now - self._last_refresh < REFRESH_THROTTLE:
            return True
        self._last_refresh = now
        battery = self._battery()
        try:
            soc_pct = self._live_soc_pct(battery)
            await self.coordinator.api.async_optimize(battery_soc_pct=soc_pct)
            await self.coordinator.async_request_refresh()
            self._last_error = None
            return True
        except Exception as error:  # noqa: BLE001 - control must keep running
            self._last_error = str(error)
            self._status = "refresh_failed"
            self._notify()
            _LOGGER.warning("Plan refresh failed: %s", error)
            return False

    def _apply_soc_guard(
        self,
        decision: ControlDecision,
        battery: dict[str, Any],
    ) -> ControlDecision:
        soc_entity = battery.get("soc_entity")
        if not soc_entity:
            return decision
        state = self.hass.states.get(soc_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            raise ControlError(f"SOC entity {soc_entity} is unavailable")
        try:
            soc_pct = float(state.state)
        except ValueError as error:
            raise ControlError(f"SOC entity {soc_entity} is not numeric") from error
        power = clamp_power_for_soc(
            decision.power_w,
            soc_pct,
            float(battery.get("min_soc_pct", 0)),
            float(battery.get("max_soc_pct", 100)),
        )
        if power == decision.power_w:
            return decision
        return ControlDecision(
            action="apply",
            power_w=power,
            mode=desired_mode(battery, power),
            reason="soc_limit",
            interval_start=decision.interval_start,
        )

    async def _apply(
        self,
        decision: ControlDecision,
        battery: dict[str, Any],
        *,
        power_w: float | None = None,
        plan_power_w: float | None = None,
        record_plan: bool = True,
    ) -> None:
        if power_w is not None and abs(power_w - decision.power_w) > 1e-6:
            decision = ControlDecision(
                action="apply",
                power_w=power_w,
                mode=desired_mode(battery, power_w),
                reason="zero_grid",
                interval_start=decision.interval_start,
            )
        try:
            decision = self._apply_soc_guard(decision, battery)
            await self._write_and_verify(decision, battery)
        except Exception as error:  # noqa: BLE001 - convert any write failure
            self._last_error = str(error)
            self._status = "error"
            self._audit_add(
                "failed",
                reason=str(error),
                power_w=decision.power_w,
                mode=decision.mode,
            )
            _LOGGER.error("Battery control failed: %s", error)
            self._armed = False
            await self._fallback("write_failed")
            self._notify()
            return

        self._last_interval_start = decision.interval_start
        self._last_power_w = round(decision.power_w, 1)
        if record_plan:
            self._last_plan_power_w = (
                decision.power_w if plan_power_w is None else plan_power_w
            )
        self._last_mode = decision.mode
        self._last_apply = dt_util.now()
        self._last_error = None
        self._fallback_applied = False
        self._status = "applied"
        self._audit_add(
            "applied",
            reason=decision.reason,
            power_w=self._last_power_w,
            mode=self._last_mode,
        )
        self._notify()

    async def _write_and_verify(
        self,
        decision: ControlDecision,
        battery: dict[str, Any],
    ) -> None:
        mode_entity = battery.get("mode_entity")
        setpoint_entity = battery.get("setpoint_entity")
        feedback_entity = battery.get("setpoint_feedback_entity")
        power = round(decision.power_w, 1)
        mode = decision.mode if mode_entity else None
        write_power = setpoint_write_value(
            power,
            unsigned=bool(battery.get("setpoint_is_unsigned")),
            invert=bool(battery.get("invert_setpoint")),
        )

        await self._ensure_control_mode(battery)
        if setpoint_entity:
            await self._wait_for_available(setpoint_entity)
        if mode_entity:
            await self._wait_for_available(mode_entity)

        for attempt in range(2):
            if abs(power) > 1:
                if mode:
                    await self._set_mode(mode_entity, mode)
                await self._set_power(setpoint_entity, write_power)
            else:
                await self._set_power(setpoint_entity, 0)
                if mode:
                    await self._set_mode(mode_entity, mode)

            await asyncio.sleep(0.2)
            try:
                await self._verify(
                    feedback_entity or setpoint_entity,
                    write_power,
                    mode_entity,
                    mode,
                )
                return
            except ControlError:
                if attempt == 0:
                    await asyncio.sleep(0.4)
                    continue
                raise

    async def async_optimize_live(self) -> bool:
        """Force a plan refresh using the live battery SOC."""
        async with self._lock:
            self._last_refresh = None
            return await self._refresh(dt_util.now())

    async def _ensure_control_mode(self, battery: dict[str, Any]) -> None:
        switch_entity = battery.get("control_switch_entity")
        if switch_entity:
            state = self.hass.states.get(switch_entity)
            if state is None or state.state != "on":
                await self._set_switch(switch_entity, True)
                await asyncio.sleep(0.2)
                state = self.hass.states.get(switch_entity)
                if state is None or state.state != "on":
                    raise ControlError(f"{switch_entity} did not turn on")

        entity_id = battery.get("control_mode_entity")
        value = battery.get("control_mode_value")
        if not entity_id or not value:
            return
        state = self.hass.states.get(entity_id)
        if state is not None and state.state == value:
            return
        await self._set_mode(entity_id, value)
        await asyncio.sleep(0.2)
        state = self.hass.states.get(entity_id)
        if state is None or state.state != value:
            raise ControlError(
                f"{entity_id} reported {state.state if state else 'missing'}, "
                f"expected {value!r}"
            )

    async def _wait_for_available(
        self,
        entity_id: str,
        timeout: float = 10.0,
    ) -> None:
        """Wait for vendor entities that only become available after a mode change."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            state = self.hass.states.get(entity_id)
            if state is not None and state.state not in ("unknown", "unavailable"):
                return
            await asyncio.sleep(0.5)
        raise ControlError(f"{entity_id} did not become available")

    async def _set_switch(self, entity_id: str, on: bool) -> None:
        domain = entity_id.split(".", 1)[0]
        if domain not in ("switch", "input_boolean"):
            raise ControlError(
                f"Unsupported control switch domain {domain!r}; "
                "use a switch or input_boolean entity"
            )
        await self.hass.services.async_call(
            domain,
            "turn_on" if on else "turn_off",
            {"entity_id": entity_id},
            blocking=True,
        )

    async def _set_power(self, entity_id: str | None, power_w: float) -> None:
        if not entity_id:
            raise ControlError("Battery setpoint entity is not configured")
        domain = entity_id.split(".", 1)[0]
        if domain not in ("input_number", "number"):
            raise ControlError(
                f"Unsupported setpoint entity domain {domain!r}; "
                "use a number or input_number entity"
            )
        await self.hass.services.async_call(
            domain,
            "set_value",
            {"entity_id": entity_id, "value": round(power_w, 1)},
            blocking=True,
        )

    async def _set_mode(self, entity_id: str, mode: str) -> None:
        domain = entity_id.split(".", 1)[0]
        if domain not in ("input_select", "select"):
            raise ControlError(
                f"Unsupported mode entity domain {domain!r}; "
                "use a select or input_select entity"
            )
        await self.hass.services.async_call(
            domain,
            "select_option",
            {"entity_id": entity_id, "option": mode},
            blocking=True,
        )

    async def _verify(
        self,
        setpoint_entity: str,
        power_w: float,
        mode_entity: str | None,
        mode: str | None,
    ) -> None:
        state = self.hass.states.get(setpoint_entity)
        if state is None or state.state in ("unknown", "unavailable"):
            raise ControlError(f"{setpoint_entity} is unavailable")
        try:
            actual = float(state.state)
        except ValueError as error:
            raise ControlError(f"{setpoint_entity} is not numeric") from error
        tolerance = max(POWER_TOLERANCE_W, abs(power_w) * 0.05)
        if abs(actual - power_w) > tolerance:
            raise ControlError(
                f"{setpoint_entity} reported {actual} W, expected {power_w} W"
            )
        if mode_entity and mode:
            mode_state = self.hass.states.get(mode_entity)
            if mode_state is None or mode_state.state != mode:
                raise ControlError(
                    f"{mode_entity} reported {mode_state.state if mode_state else 'missing'}, "
                    f"expected {mode!r}"
                )

    async def _fallback(self, reason: str) -> None:
        if self._fallback_applied and self._last_fallback_reason == reason:
            return
        self._fallback_applied = True
        self._last_fallback_reason = reason
        self._last_interval_start = None
        self._last_power_w = 0.0
        self._last_plan_power_w = None
        self._last_mode = None
        battery = self._battery()
        if battery is not None and battery.get("setpoint_entity"):
            try:
                await self._set_power(battery.get("setpoint_entity"), 0)
                if battery.get("mode_entity") and battery.get("mode_idle"):
                    await self._set_mode(
                        battery["mode_entity"], battery["mode_idle"]
                    )
                if battery.get("control_mode_entity") and battery.get(
                    "control_mode_fallback"
                ):
                    await self._set_mode(
                        battery["control_mode_entity"],
                        battery["control_mode_fallback"],
                    )
                if battery.get("control_switch_entity"):
                    await self._set_switch(battery["control_switch_entity"], False)
            except Exception as error:  # noqa: BLE001 - fallback must not raise
                _LOGGER.warning("Battery fallback failed: %s", error)
                self._last_error = str(error)
        self._status = f"fallback:{reason}"
        self._audit_add("fallback", reason=reason, power_w=0, mode=None)
        self._notify()

    async def async_shutdown(self) -> None:
        async with self._lock:
            if self._armed or self._last_power_w not in (None, 0):
                await self._fallback("shutdown")
            self._armed = False
            self._notify()
