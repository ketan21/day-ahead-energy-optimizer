# Live P1 grid-target correction

The plan is built from forecast load. The actual household load will differ, so a
plan-following controller alone can import or export more than intended. The live
correction closes that gap using the net-meter power.

## Self-consumption default

The default strategy is **self-consumption**:

- keep P1 at zero while the battery can physically balance,
- charge from PV surplus before exporting or curtailing,
- discharge to cover load, including expensive periods,
- prefer importing only when the battery cannot cover the load,
- export or curtail PV only when the battery is full and the load is covered.

This is not a hard zero-exchange rule. The solver keeps a cost signal:

- curtailment has a large penalty, so free PV is stored before it is wasted,
- grid exchange has a small penalty, so zero P1 wins when no spread justifies trading,
- the normal price objective can still discharge the battery **above** the house load
  during expensive intervals and export the surplus,
- and it can charge from the grid ahead of a known cheap-to-expensive spread.

So the plan first prefers self-consumption, then takes profitable arbitrage when the
future prices justify it.

## What the controller does

The plan contains a **planned grid target** for every interval. The controller reads
P1 every 10 seconds and corrects the battery to that target:

```text
corrected_power = planned_battery_power + planned_grid_power - actual_grid_power
```

For self-consumption intervals the planned grid target is zero. For an optional
arbitrage plan it is the planned import/export, so the controller follows that too.

The correction is clamped to the battery limits, SOC guard, deadband, and maximum
step. It is written through the verified Anker setpoint path.

If the plan explicitly marks the battery idle (no charge or discharge), the
controller does not invent battery activity. That happens when the battery is at a
limit or cannot help.

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

## Arbitrage mode

Set `strategy.grid_mode` to `arbitrage` to remove the small self-consumption
preference and optimise cost directly. The controller follows the plan's grid target
in both modes.

The default `self_consumption` mode still allows profitable export and grid charging;
it just prefers zero exchange when the price spread does not justify trading.

## Limitations

- The P1 sensor must be instantaneous power in W; cumulative energy sensors are not
  used.
- Battery response and meter latency can cause small overshoots; the deadband and
  maximum step limit hunting.
- This is a proportional correction, not a full PID loop.
- Self-consumption is a soft priority: avoid curtailment and unnecessary exchange,
  then use profitable arbitrage when the prices justify it. Arbitrage mode removes
  the preference entirely.
