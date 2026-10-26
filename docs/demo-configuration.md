# Configure the M0 demo

The engine has a schema-driven **Settings** page (`/settings`), a **Guided setup**
wizard (`/setup`), and a JSON API. This page shows both the UI path and the API path,
and what the demo can and cannot do today.

## What the demo uses today

| Area | Used by the demo? | Notes |
|---|---|---|
| Battery capacity, power, efficiency, SOC limits | Yes | The demo solver uses the **first** battery only. |
| Solar peak power | Yes | Sum of all enabled arrays drives the synthetic PV curve. |
| EV capacity, max power, target SOC, ready-by | Yes | Current SOC is assumed to be 40%. |
| Boiler volume, power, COP, target temperature | Yes | Scheduled in the cheapest window. |
| Heat-pump stages | Yes | A fixed demo heat demand is scheduled. |
| Machine power, duration, window | Yes | Scheduled in the cheapest window. |
| Grid import/export limits | Yes | Import/export is clamped. |
| Fixed import/export price | Yes | `prices.source = "fixed"` uses these values. |
| EnergyZero all-in prices | Yes | `prices.source = "energyzero"` fetches live consumer prices from the EnergyZero public API. |
| Forecast.Solar PV | Yes | `forecast.solar_source = "forecast_solar"` fetches a location-aware PV forecast. |
| Dynamic prices (ENTSO-E, Nordpool, Tibber, HA sensor) | **No** | The values are stored, but the demo uses a synthetic curve. |
| Existing HA PV forecast entity | **No** | The integration scaffold is in place, but the entity path is not wired yet. |
| HA recorder load profiles | Yes | `load.source = "recorder"` reads P1/PV/battery statistics from the HA recorder database (add-on SQLite). |
| `soc_entity`, `setpoint_entity`, `mode_entity` | **No** | Stored for the future HA integration; nothing is read or written. |
| Scheduler entries | **No** | Stored only. Use the **Run optimization** button or `POST /api/v1/optimize`. |
| Legacy `options.json` | **No** | No importer yet. |

In short: you can shape the *demo plan* to your hardware, use a flat tariff, or use
live EnergyZero prices and a live Forecast.Solar PV forecast. You cannot yet run it
against your own sensors or control devices.

## Use the settings UI

Open <http://localhost:8099/settings> for the full schema-driven form, or
<http://localhost:8099/setup> for the five-step wizard. The wizard edits the first
solar array, battery, and EV; use Settings for multiple devices and advanced tariff
fields.

The settings UI writes the same API used in the JSON examples below.

## 1. Fetch the current configuration

```bash
curl -s http://localhost:8099/api/v1/config -o my-config.json
```

The demo runs without a token. If you set `DAEO_DEMO=0`, add:

```bash
TOKEN=$(docker compose exec -T daeo cat /data/api_token)
curl -s -H "Authorization: Bearer $TOKEN" http://localhost:8099/api/v1/config -o my-config.json
```

## 2. Edit the values

Edit `my-config.json` in any editor, or use `jq`:

```bash
jq '
  .home.latitude = 52.09
| .home.longitude = 4.30
| .prices.source = "fixed"
| .prices.fixed_import_price_eur_kwh = 0.28
| .prices.fixed_export_price_eur_kwh = 0.05
| .batteries[0].capacity_kwh = 15
| .batteries[0].max_charge_kw = 6
| .batteries[0].max_discharge_kw = 6
| .batteries[0].efficiency = 0.95
| .solar[0].peak_power_wp = 6000
| .electric_vehicles[0].capacity_kwh = 77
| .electric_vehicles[0].max_charge_kw = 11
| .electric_vehicles[0].target_soc_pct = 90
| .electric_vehicles[0].ready_by = "06:30:00"
' my-config.json > my-config.new.json
```

The most useful fields for a first pass:

| Field | Meaning |
|---|---|
| `home.latitude`, `home.longitude`, `home.timezone`, `home.country` | Location and market. Country is `NL` or `BE`. |
| `prices.source` | Use `"fixed"` to make the demo follow your flat tariff. |
| `prices.fixed_import_price_eur_kwh` | All-in import price in EUR/kWh. |
| `prices.fixed_export_price_eur_kwh` | Export/feed-in price in EUR/kWh. |
| `strategy.grid_mode` | `"self_consumption"` (default, zero P1 while the battery can balance) or `"arbitrage"` (allow planned grid charging/export). |
| `strategy.interval` | `"quarter_hour"` or `"hour"`. |
| `strategy.reserve_soc_pct` | Battery reserve used by the demo heuristic. |
| `strategy.cycle_cost_eur_kwh` | Battery cycle cost. |
| `grid.max_import_kw`, `grid.max_export_kw` | Grid limits. |
| `solar[].peak_power_wp` | Total Wp of the array. |
| `batteries[].capacity_kwh` | Usable capacity. |
| `batteries[].max_charge_kw`, `max_discharge_kw` | Inverter limits. |
| `batteries[].efficiency` | One-way efficiency (0.95 ≈ 90% round trip). |
| `batteries[].min_soc_pct`, `max_soc_pct` | SOC limits. |
| `electric_vehicles[].ready_by` | Departure time, `HH:MM:SS`. |
| `electric_vehicles[].target_soc_pct` | Target SOC at departure. |
| `boiler.enabled`, `boiler.volume_l`, `boiler.power_kw`, `boiler.cop` | Boiler model. |
| `heat_pump.enabled`, `heat_pump.stages` | Heat-pump stages (`max_power_kw`, `cop`). |

The full schema, including descriptions and UI hints, is available at:

```bash
curl -s http://localhost:8099/api/v1/config/schema | jq '.properties'
```

## AC-coupled vs DC-coupled PV

- **AC-coupled**: the panels have their own inverter and produce AC directly. The
  battery has a separate AC-coupled inverter. Enphase IQ7/IQ8 microinverters and
  Enphase IQ Batteries are AC-coupled. The PV and battery meet at the house AC bus.
- **DC-coupled**: the panels connect to a DC bus/MPPT that is shared with the
  battery, before a hybrid inverter. A hybrid inverter with a high-voltage battery
  is the typical example. PV can charge the battery with one conversion.

The CBC solver currently treats **all** PV as AC-coupled. `SolarConfig.dc_coupled`
is stored but not used yet. For an Enphase system this is correct: set
`dc_coupled: false`, or leave it at the default.

Battery efficiency warning: `efficiency` is the fallback one-way stage efficiency
(round trip ≈ efficiency²). `dc_to_bat_efficiency` and `bat_to_dc_efficiency` are
**additional** losses on top of the stage curve. If your stage curve already
represents the inverter's AC↔DC efficiency, leave the two extra efficiencies at 1.0
to avoid counting the loss twice. For an AC-coupled battery with ~90% round trip,
`efficiency: 0.95` and both extra efficiencies at 1.0 is a good start.

Sensor caveat: `soc_entity`, `forecast_entity`, and `production_entity` are stored
for the HA integration milestone, but the engine does not read them yet. The demo
still assumes an initial battery SOC of 50%.

## Real Forecast.Solar PV

Set the forecast source to `forecast_solar` in Settings → Forecast, or via the API:

```bash
jq '.forecast.solar_source = "forecast_solar"' my-config.json > my-config.new.json
```

The engine uses your location, the array's `peak_power_wp`, `tilt_deg`, and
`azimuth_deg`. Forecast.Solar allows 12 requests per hour per IP; each plan build
makes one request per array. Household load remains synthetic.

## Real EnergyZero prices

EnergyZero publishes all-in consumer prices for the Netherlands through its public
API. The engine uses `all_in_with_vat`, which is what you actually pay, so the
configured energy tax, supplier markup, and VAT are **not** added again for this
source.

```bash
jq '
  .prices.source = "energyzero"
| .prices.fixed_export_price_eur_kwh = 0.05
' my-config.json > my-config.new.json
```

Then validate and save as shown below. The API has no feed-in price, so
`fixed_export_price_eur_kwh` (or `feed_in_tariff_eur_kwh`) supplies the export price.

Before the day-ahead auction publishes tomorrow's prices (roughly 13:00 CET), the
EnergyZero API only returns prices up to midnight. The engine then produces a plan
for the remaining hours of today instead of a full 24-hour horizon. Run the
optimization again after publication for a full day.

Load can be real when `load.source` is `recorder`; see
[`docs/load-profile.md`](load-profile.md). Otherwise it is synthetic. PV can be real
via Forecast.Solar.

## 3. Validate and save

Always validate first:

```bash
curl -s -X POST http://localhost:8099/api/v1/config/validate \
  -H 'Content-Type: application/json' \
  -d @my-config.new.json
```

A valid document returns `{"valid": true}`. Then save it:

```bash
curl -s -X PUT http://localhost:8099/api/v1/config \
  -H 'Content-Type: application/json' \
  -d @my-config.new.json
```

The API validates the document, writes it atomically to SQLite, recomputes the demo
plan, and returns the new `plan_id`. Refresh the UI or call:

```bash
curl -s http://localhost:8099/api/v1/plan/latest | jq '.summary'
```

With auth enabled, add `-H "Authorization: Bearer $TOKEN"` to every call.

## Reset to the demo configuration

The compose file stores data in the `daeo-data` volume. To wipe the configuration,
plans, and API token and reseed the demo:

```bash
docker compose down -v
docker compose up -d
```

`docker compose down` without `-v` keeps your configuration.

## Notes and current limitations

- Only the **first** battery is used by the demo solver. Multiple batteries are
  accepted by the schema but not simulated separately.
- The EV starts at 40% SOC. There is no `current_soc` config field yet; the
  `soc_entity` value is not read.
- Dynamic prices other than EnergyZero are not fetched. Setting `prices.source` to
  `entsoe`, `nordpool`, `tibber`, or `ha_sensor` validates, but the demo still uses
  the synthetic price curve. Use `"fixed"` for a predictable demo or
  `"energyzero"` for live NL prices.
- The scheduler is configuration only. Run a solve with the button or
  `POST /api/v1/optimize`.
- No device is controlled. `setpoint_entity`, `mode_entity`, and the other control
  entities are stored for the M3 integration.
- There is no legacy `options.json` importer. The schemas are different.

M1 is implemented. M2 now has a CBC MILP adapter for the supported device set
(batteries, EVs, boiler, heat pump, machines, grid, PV curtailment), including
battery stage curves, AC/DC efficiencies, reduced-power SOC limits, minimum power,
and terminal SOC. PV array DC coupling, EV charge stages, and heat-curve dynamics
are not ported yet, and household load remains synthetic. M3 is an integration
scaffold (entities, services, calendar, diagnostics); device control is not
implemented.
