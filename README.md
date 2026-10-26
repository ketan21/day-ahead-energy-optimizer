# Day Ahead Energy Optimizer

Plan battery, boiler, heat-pump, EV, and appliance use against dynamic day-ahead
electricity prices. Built for Home Assistant, with the Netherlands and Belgium as the
first markets.

> **Status: rebuild in progress.** The production add-on is still the legacy
> implementation in [`dao/`](dao/). The new engine lives in [`src/daeo/`](src/daeo/)
> and ships a schema-driven settings UI, a guided setup wizard, live EnergyZero
> prices, a live Forecast.Solar PV forecast, real month/hour load profiles from the
> HA recorder, a CBC MILP solver, a browser plan viewer, and a Home Assistant
> integration with opt-in, verified battery control. Device support is generic:
> signed or unsigned power setpoints, direction/mode selects, and operating-mode
> preconditions. See the [rebuild proposal](docs/rebuild-proposal.md).

## What it does

- Fetches EnergyZero all-in consumer prices (live), with ENTSO-E, Nordpool, Tibber,
  and existing HA price sensors on the M2 roadmap.
- Forecasts PV with Forecast.Solar (live, location-aware) or a synthetic demo curve.
- Builds real month/hour load profiles from the Home Assistant recorder statistics
  (P1 import/export, PV, battery, and optional device meters).
- Optimizes battery charging, boiler heating, heat-pump stages, EV charging, and
  appliance windows for the next 24 hours. The default self-consumption strategy
  keeps P1 at zero while the battery can balance, consumes PV before export or
  curtailment, and still allows profitable battery export or grid charging when the
  future price spread justifies it.
- Explains every interval: price, PV, load, battery, grid, cost, and the reason for
  the decision.
- Publishes a plan that the UI, the API, and the Home Assistant integration consume.
- Applies the current battery interval through an explicit arming switch, with
  read-back verification, SOC guards, fallback, and an audit trail.

## Quick start: standalone demo

The standalone container is for exploration, development, and debugging. It uses a
sample NL configuration and a synthetic price/solar/load profile, so it runs without
Home Assistant or API keys.

### Docker

```bash
docker compose up --build
```

Open <http://localhost:8099>.

### Local Python

Requires Python 3.12 or newer.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m daeo
```

Open <http://localhost:8099>. Use **Guided setup** for a quick configuration or
**Settings** for every field. The engine stores its SQLite database, generated API
token, and optional secrets in `.daeo-data/`.

### API

```bash
curl http://localhost:8099/api/v1/health
curl http://localhost:8099/api/v1/plan/latest
curl http://localhost:8099/api/v1/config/schema
```

In demo mode, local mutations are open. Set `DAEO_DEMO=0` (and optionally
`DAEO_API_TOKEN`) to require a bearer token. The generated token is written to
`.daeo-data/api_token` with owner-only permissions.

## Deployment

The engine add-on image is built and published by
`.github/workflows/daeo-image.yml` to `ghcr.io/ketan21/daeo` for amd64 and arm64.
The add-on `version` and the published tag must match. See
[`addon/README.md`](addon/README.md) for publishing and pairing.

## Home Assistant integration

A HACS-compatible integration scaffold lives in
[`custom_components/daeo`](custom_components/daeo/). It provides a config flow,
sensors, binary sensors, an EV charging calendar, a run button, a strategy select,
services (`daeo.optimize`, `daeo.set_strategy`, `daeo.export_plan`), and diagnostics.

The integration has a config flow, entities, services, and an opt-in battery
control loop. It is tested with the Home Assistant 2025.1 harness; device-specific
drivers and Enphase battery control are still generic. See the
[integration README](custom_components/daeo/README.md).

## Configuration status

The new engine configuration (`prices.source`, `forecast.solar_source`, device
entities, strategy, and so on) is the configuration that will become the add-on
configuration at the M4 cutover. The legacy 1.x add-on in `dao/` still uses its own
`options.json` and does not read these fields yet.

The CBC adapter optimises batteries, EVs, boiler, heat pump, machines, grid limits,
and PV curtailment. Battery charge/discharge stage curves, battery AC/DC
efficiencies, reduced-power SOC limits, minimum power, and terminal SOC targets are
ported. PV array DC coupling, EV charge stages, and heat-curve dynamics from the
legacy model are not ported yet.

## Repository layout

```
src/daeo/                 new engine (Python package)
  domain/                 Plan, Interval, OptimizationInput, enums
  config/                 strict Pydantic schema, loader, secrets
  solver/                 Solver protocol, CBC MILP solver, demo fallback
  providers/              EnergyZero prices, Forecast.Solar PV (ENTSO-E etc. follow)
  storage/                SQLite persistence
  api/                    FastAPI app, auth, error contract
  web/                    dependency-free plan viewer
tests/daeo/               unit, contract, API, solver, integration metadata tests
custom_components/daeo/   Home Assistant integration scaffold (HACS)
hacs.json                 HACS metadata
docs/rebuild-proposal.md  architecture, API, HA integration, milestones
addon/                    experimental new add-on scaffold
dao/                      legacy 1.x implementation (frozen)
```

## Development

```bash
pytest tests/daeo
ruff check src/daeo tests/daeo custom_components/daeo
```

The Home Assistant integration also has a test harness:

```bash
python3.12 -m venv .venv-ha
.venv-ha/bin/pip install -r tests/ha/requirements.txt
PYTHONPATH=. .venv-ha/bin/pytest tests/ha -q --asyncio-mode=auto
```

The legacy test suite and scenario corpus remain in `dao/tests/` and `tests/`.
They are not touched by the rebuild until the solver adapter lands.

## Language

The project is English-only: UI, documentation, metadata, logs, and code. Please do
not add Dutch product strings or documentation.

## Documentation

- [Project status and handoff](docs/status.md) — current state, live demo
  configuration, commands, and remaining work.
- [Configure the demo](docs/demo-configuration.md) — adapt the demo to your battery,
  solar, EV, boiler, and tariff via the config UI or API.
- [Anker Modbus control](docs/anker-modbus.md) — mapping the official Anker Solix
  integration and Anker X1 community integration to DAEO's battery control loop.
- [Load profiles from the HA recorder](docs/load-profile.md) — P1/PV/battery sensor
  mapping, month/hour aggregation, and recalculation.
- [Anker Solarbank Max AC example](docs/examples/anker-solarbank-max-ac.json) —
  import-ready battery, load-profile, and price configuration.
- [Live P1 zero-grid correction](docs/zero-grid.md) — correcting the battery
  setpoint against the real meter during load-covering intervals.
- [Troubleshooting](docs/troubleshooting.md) — 404/token/ingress issues and the
  difference between the legacy add-on, the new engine add-on, and the HACS
  integration.
- [Rebuild proposal](docs/rebuild-proposal.md) — decisions, architecture, API,
  Home Assistant integration, milestones.
- Legacy documentation: [`dao/DOCS.md`](dao/DOCS.md) (Dutch, archived during the
  rebuild), [`DEVELOP.md`](DEVELOP.md), [`SETTINGS.md`](SETTINGS.md).

## License

Apache License 2.0. See [LICENSE.txt](LICENSE.txt).
