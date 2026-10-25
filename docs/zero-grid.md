# Live P1 zero-grid correction

The plan is built from forecast load. The actual household load will differ, so a
plan-following controller alone can import or export more than intended. The
optional zero-grid correction closes that gap using the live net-meter power.

## What it does

For each plan interval, the controller checks whether the plan targets **zero grid
import and zero grid export** and has a non-zero battery action. That is the normal
"battery covers the house load" or "battery absorbs PV" case.

In those intervals, every 30-second control tick:

```text
corrected_power = planned_battery_power - actual_grid_power
```

The result is clamped to the battery charge/discharge limits, the SOC guard, and the
configured maximum step. It is written through the same verified Anker setpoint path
as the plan.

The correction is **not** applied to intervals where the plan deliberately imports
or exports, such as cheap-rate grid charging or export arbitrage. Those intervals
keep their planned setpoint.

## Configure

Settings → **Grid** → **Realtime grid control**:

- **Power sensor entity**: your P1/net-meter **power** sensor in watts, for example
  `sensor.p1_meter_power`. This is not the cumulative kWh sensor.
- **Power sensor invert**: enable only if the sensor reports export as positive and
  import as negative.
- **Zero grid deadband W**: ignore meter errors inside this band. Default `30`.
- **Zero grid max step W**: maximum battery setpoint change per tick. Default `1000`.
  Set `0` to disable the ramp limit.

The sensor must report positive for import and negative for export, unless inverted.
The correction is disabled when the entity is not configured.

## Safety

- The battery SOC guard still applies.
- If the configured SOC entity is unavailable, the controller refuses to apply.
- If the meter entity is unavailable, the controller keeps the plan setpoint; it does
  not invent a grid value.
- The control switch remains the master arm/disarm.
- The plan is still refreshed when the SOC drifts from the plan or the plan ages.

## Limitations

- The P1 sensor must be instantaneous power in W; cumulative energy sensors are not
  used.
- Battery response and meter latency can cause small overshoots; the deadband and
  maximum step limit hunting.
- This is a proportional correction, not a full PID loop.
- The correction only targets zero. Planned grid-charge/export intervals follow the
  plan.
