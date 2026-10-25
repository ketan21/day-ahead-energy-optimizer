# Load profiles from the HA recorder

DAEO can build household load profiles from the Home Assistant recorder instead of
using the synthetic demo load. This is the recommended production setup: the plan is
then driven by your P1 meter, PV production, battery, and optional device meters.

## How it works

The add-on reads the HA SQLite recorder tables `statistics` and `statistics_meta`
**read-only**. It aggregates the configured sensors over `lookback_days` and produces
a 12×24 matrix: average kWh per hour-of-day for each month.

The base-load formula is:

```text
load = grid_import - grid_export
     + pv_production
     - battery_charge
     + battery_discharge
     - ev_charge
     - boiler
     - heat_pump
     - machine
```

All sensors can be cumulative energy (kWh/Wh/MWh) or power (W/kW). Energy sensors use
the delta of the recorder `sum` column; power sensors use the recorder `mean` and the
statistics interval. Negative deltas (sensor resets) are skipped.

The plan uses the profile for the current month. Missing month/hour cells fall back to
the all-year average for that hour.

## Add-on requirements

- HA OS with the default **SQLite** recorder at `/config/home-assistant_v2.db`.
- The new add-on maps `homeassistant_config: ro`, so the file appears inside the
  add-on as `/homeassistant/home-assistant_v2.db`.
- MariaDB/PostgreSQL recorder databases are **not** supported by this reader yet;
  `database_url` must be a SQLite path.
- The sensors must have Home Assistant long-term statistics (`state_class` set). P1
  and Envoy energy sensors normally do.

For standalone Docker, mount the HA config directory read-only:

```yaml
volumes:
  - daeo-data:/data
  - /path/to/homeassistant:/homeassistant:ro
```

## Configure

Settings → **Load profile**:

- `source`: `recorder`
- `database_url`: `/homeassistant/home-assistant_v2.db`
- `lookback_days`: `365`
- Grid import/export sensors, PV, battery, and optional device sensors.

With the entities from this installation:

```json
{
  "load": {
    "source": "recorder",
    "database_url": "/homeassistant/home-assistant_v2.db",
    "lookback_days": 365,
    "grid_import_sensors": ["sensor.p1_meter_energy_import"],
    "grid_export_sensors": ["sensor.p1_meter_energy_export"],
    "solar_production_sensors": [
      "sensor.envoy_122325114155_lifetime_energy_production"
    ],
    "battery_charge_sensors": [
      "sensor.anker_solix_solarbank_max_ac_241_battery_charging_energy"
    ],
    "battery_discharge_sensors": [
      "sensor.anker_solix_solarbank_max_ac_241_battery_discharge_energy"
    ],
    "ev_charge_sensors": [],
    "boiler_sensors": [],
    "heat_pump_sensors": [],
    "machine_sensors": []
  }
}
```

If the smart plug is a controllable device, add
`sensor.anker_solix_smart_plug_gen_2_031_cumulative_energy` to `machine_sensors`.

## Import example

A complete configuration for this installation is in
[`examples/anker-solarbank-max-ac.json`](examples/anker-solarbank-max-ac.json).
Import it in the engine Settings → **Import JSON**, then adjust the location, solar
peak power, tilt, and azimuth to your roof. The load profile will calculate on save
when the add-on can read the recorder database.

## Recalculate

- The profile is calculated on startup when `source` is `recorder`.
- **Settings → Recalculate load profile** re-reads the recorder and re-optimizes.
- `PUT /api/v1/config` also recalculates when the source is `recorder`.
- API:

```bash
curl -s -X POST http://homeassistant.local:8099/api/v1/load-profile/calculate
curl -s http://homeassistant.local:8099/api/v1/load-profile
```

The plan footer shows `load: recorder` when the profile is in use.

## Limitations

- No weekday/weekend split yet: each month/hour cell is averaged over all days.
- The P1 meter's **total** import/export sensors are used; tariff-specific sensors are
  not combined.
- If no PV sensor is supplied, `load` is net of PV. If no battery sensors are
  supplied, battery flows remain in the load.
- Statistics are read-only; the engine never writes to the HA recorder database.
- The reader uses long-term statistics, not raw `states`. If a sensor lacks
  statistics, it is skipped with a warning.
