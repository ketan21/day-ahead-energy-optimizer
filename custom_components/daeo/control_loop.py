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
from .plan import current_interval, plan_age_seconds

_LOGGER = logging.getLogger(__name__)

TICK_INTERVAL = timedelta(seconds=30)
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
            if forced and not refreshed:
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
            last_power_w=self._last_power_w,
            max_age_seconds=max(2 * minutes * 60, 1800),
        )

        if decision.action == "apply":
            await self._apply(decision, battery)
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
        soc_pct = None
        if battery and battery.get("soc_entity"):
            state = self.hass.states.get(battery["soc_entity"])
            if state is not None and state.state not in ("unknown", "unavailable"):
                try:
                    soc_pct = float(state.state)
                except ValueError:
                    soc_pct = None
        try:
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
    ) -> None:
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
