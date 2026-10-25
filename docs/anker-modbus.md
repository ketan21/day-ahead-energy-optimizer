# Anker battery control over Modbus TCP

Your Anker battery at `192.168.0.41:502` should be exposed through a Home Assistant
integration, not by DAEO opening raw Modbus sockets. The DAEO control loop writes to
HA entities, so the vendor integration remains responsible for the Modbus protocol,
register safety, and reconnects.

Two supported paths:

## Official Anker Solix integration (recommended)

Repository: <https://github.com/anker-charging/ha-anker-solix-official>

1. Enable Modbus TCP in the Anker app:
   **Device → Settings → Third-Party Control Settings → Modbus TCP**.
2. Install the integration through HACS.
3. Add **Anker Solix Official** and enter `192.168.0.41` (port 502, unit id 1).
4. In the HA entity registry, enable these control entities if they are hidden:
   - **Operating Mode** (`select`)
   - **Grid Flow** (`select`)
   - **Power Control** (`number`)
   - **Battery SOC** (`sensor`)
5. Note the actual entity IDs. They depend on the device name; search for the names
   above. The patterns are:

```text
sensor.<anker_device>_battery_soc
select.<anker_device>_operating_mode
select.<anker_device>_grid_flow
number.<anker_device>_power_control
```

### Detected device (this installation)

A read-only Modbus probe on `192.168.0.41:502`, unit id 1, returned:

- model string `A17E2`
- serial product code `DMWH` → **Anker SOLIX Solarbank Max AC**
- firmware `1.0.2.23`
- rated energy register 10250 = 72 with gain 10 → **7.2 kWh**
- max charge / discharge registers = **1200 W** each
- battery SOC = **19%**
- work mode 10064 = **3** (`third_party_control`)
- battery power ≈ **−180 W** (charging)

The official integration's product mapping explicitly maps `DMWH` to Solarbank Max
AC. The battery is already in third-party control mode, so do not arm DAEO until the
official integration is installed and its entities are stable. At 19% SOC the DAEO
SOC guard will refuse discharge once the configured minimum is reached.

### Exact entities for this installation

The official integration creates these IDs:

```text
sensor.anker_solix_solarbank_max_ac_241_soc
select.anker_solix_solarbank_max_ac_241_operating_mode_device_runs_by_command_in_third_party_controlled
select.anker_solix_solarbank_max_ac_241_grid_flow
number.anker_solix_solarbank_max_ac_241_target_grid_power
```

The official integration's control model is:

- `Operating Mode` must be `third_party_control`.
- `Grid Flow` is `charge` or `discharge`.
- `Target Grid Power` is a **positive magnitude** in W (0–10000); the direction comes
  from `Grid Flow`.

### Disable the existing Anker automations first

This installation has a large set of automations that also drive the battery:
`anker_solix_zero_grid_power`, `anker_solix_price_aware_zero_export*`,
`v2_*`, `v3_*`, `v4_*`, `v5_0_anker_solix_pure_x_y_arbitrage...`, and
`v4_0_6_anker_solix_dynamic_demand_2dp_price_arbitrage`.

**Disable all of them before arming DAEO.** Otherwise they will fight the controller
for the Operating Mode and the setpoint. Keep them disabled, or convert their logic
into DAEO automations after the cutover.

Configure the DAEO battery as follows (Settings → Batteries; values from your
datasheet):

```json
{
  "name": "Anker",
  "enabled": true,
  "capacity_kwh": 7.2,
  "max_charge_kw": 1.2,
  "max_discharge_kw": 1.2,
  "efficiency": 0.95,
  "min_soc_pct": 20,
  "max_soc_pct": 100,
  "soc_entity": "sensor.anker_solix_solarbank_max_ac_241_soc",
  "setpoint_entity": "number.anker_solix_solarbank_max_ac_241_target_grid_power",
  "setpoint_is_unsigned": true,
  "mode_entity": "select.anker_solix_solarbank_max_ac_241_grid_flow",
  "mode_charge": "charge",
  "mode_discharge": "discharge",
  "control_mode_entity": "select.anker_solix_solarbank_max_ac_241_operating_mode_device_runs_by_command_in_third_party_controlled",
  "control_mode_value": "third_party_control",
  "control_mode_fallback": "self_consumption",
  "battery_charge_sensors": [
    "sensor.anker_solix_solarbank_max_ac_241_battery_charging_energy"
  ],
  "battery_discharge_sensors": [
    "sensor.anker_solix_solarbank_max_ac_241_battery_discharge_energy"
  ],
  "dc_to_bat_efficiency": 1.0,
  "bat_to_dc_efficiency": 1.0
}
```

What DAEO does:

1. Sets `Operating Mode` to `third_party_control`.
2. Sets `Grid Flow` to `charge` or `discharge`.
3. Writes `abs(power)` to `Target Grid Power` (positive W).
4. Verifies the entity states.
5. On disarm, stale plan, or write failure: writes 0 W and returns `Operating Mode`
   to `self_consumption`.

Keep `dc_to_bat_efficiency` and `bat_to_dc_efficiency` at 1.0 if `efficiency`
already represents the battery inverter's round trip; otherwise the loss is counted
twice.

## Anker SOLIX X1 (community integration)

The official integration currently lists the X1 as out of active scope. The X1 has
community Modbus integrations:

- <https://github.com/afewyards/anker-x1-ha>
- <https://github.com/SasMei/AnkerSolixX1ModbusTCP>

Enable Modbus TCP in the Anker **Professional** app, then install one of them. The
X1 control model is different:

- `number.<device>_battery_setpoint` is **signed**: positive = discharge,
  negative = charge.
- `sensor.<device>_battery_setpoint` reads back the written setpoint.
- `switch.<device>_modbus_control` must be ON (VPP/third-party mode).

Configure DAEO like this:

```json
{
  "soc_entity": "sensor.<x1_device>_soc",
  "setpoint_entity": "number.<x1_device>_battery_setpoint",
  "setpoint_feedback_entity": "sensor.<x1_device>_battery_setpoint",
  "invert_setpoint": true,
  "control_switch_entity": "switch.<x1_device>_modbus_control",
  "dc_to_bat_efficiency": 1.0,
  "bat_to_dc_efficiency": 1.0
}
```

`invert_setpoint: true` converts DAEO's **positive = charge** convention into the
X1's **positive = discharge** convention. DAEO turns the Modbus Control switch on
when armed and off on disarm/fallback, which hands control back to the Anker app.

## Import-ready configuration

[`examples/anker-solarbank-max-ac.json`](examples/anker-solarbank-max-ac.json)
contains the battery control mapping, the P1/Envoy/Anker load sensors, and the
Solarbank Max AC limits detected from the device. Import it in Settings → **Import
JSON** and adjust the location and solar array fields.

## Safety checklist

- Start with `switch.daeo_battery_control` **off**.
- Confirm the SOC, Operating Mode/Grid Flow/Power Control entities are correct.
- Arm control and watch `sensor.daeo_control_status`; it should become `applied`.
- If the status becomes `fallback:*`, control is idle and the switch may be off.
- The Anker inverter watchdog should revert to its safe/app mode if Home Assistant
  stops polling; verify this behavior before relying on it.
- Do not set `minimum_power_kw` on the official integration unless the inverter
  accepts it; `Power Control` supports 0.
- The control loop accepts only `number`/`input_number` setpoints and
  `select`/`input_select` modes. If the vendor exposes only a mode/reserve selector
  and no power setpoint, this generic loop cannot drive it yet.

## Why not raw Modbus in DAEO?

The official integration already handles model detection, register maps, scaling,
reconnects, alarms, and vendor-specific write protection. Duplicating that in DAEO
would add risk and break when Anker changes firmware. DAEO stays at the planning
layer and writes through the vendor integration.
