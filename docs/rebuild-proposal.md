# Day Ahead Energy Optimizer — Rebuild Proposal

**Status:** Draft for implementation
**Scope:** UI, configuration, Home Assistant integration, runtime, language
**Decision owner:** repository owner
**Last updated:** 2026-10

---

## 1. Summary

The Day Ahead Energy Optimizer (DAEO) has a strong optimization core and a weak product
shell. This proposal keeps the domain logic and rebuilds everything a user touches:
configuration, onboarding, the plan dashboard, the Home Assistant surface, the job
runtime, documentation, and the language of the product.

The rebuild is deliberately **not** a solver rewrite. The existing MILP model, tariff
logic, weather/solar pipeline, and scenario suite are the most valuable assets in the
repository. They stay. The accidental complexity around them is replaced.

**One-line target:** install DAEO, connect what you already have in Home Assistant, see
tomorrow's plan, arm control, and let it run.

### Decision log

| # | Decision | Status |
|---|---|---|
| D1 | Standalone Docker is an exploration, debugging, and demo surface. The Home Assistant add-on is the production product. | Confirmed |
| D2 | No backward compatibility is required for configuration keys, entity IDs, database schema, API, or Python package layout. | Confirmed |
| D3 | The first market scope is the Netherlands and Belgium (ENTSO-E bidding zones NL/BE, EUR, NL/BE tariff presets). | Confirmed |
| D4 | The project is English-only: code, UI, logs, documentation, metadata, and release notes. No Dutch product strings. | Confirmed |
| D5 | The solver is isolated behind a pure `solve(inputs) -> Plan` boundary. Applying a plan is a separate, safety-gated step. | Proposed |
| D6 | A thin HACS companion integration provides native HA entities, services, calendar, diagnostics, and config flow. The add-on remains the engine. | Recommended, pending sign-off |
| D7 | Configuration is schema-driven. One Pydantic model generates forms, validation, docs, and the API contract. | Proposed |
| D8 | SQLite is the only storage backend. Long-term statistics are imported into Home Assistant instead of reading the recorder database. | Proposed |
| D9 | The new code lives in `src/daeo/`; the legacy implementation stays in `dao/` until the cutover milestone (M4). | Proposed |

---

## 2. Why rebuild

The current repository is mature: roughly 35k lines of Python, 224 configuration
fields, an active release history, and a scenario suite that is better than most
hobby projects. The problems are concentrated in the product layer.

### 2.1 Configuration is the largest barrier

- The settings page is a raw JSON editor (`dao/webserver/app/templates/v2/config.html`).
- A fresh install starts from a 201-line `options_start.json`; a full example is 591 lines.
- Users must understand keys such as `"entity balance switch"`, `"upper limit"`, and
  `"electric vehicle"` before they can add a battery.
- The 224-field schema already contains 223 `x-help`, 209 `x-ui-section`,
  60 `x-ui-widget-filter`, and 14 `x-ui-rules` hints, but nothing renders them.

### 2.2 The product is split in two

- v1 and v2 UIs coexist. v2 has both “Reports” and “Reports V2”.
- Charts are pre-rendered matplotlib PNGs; the “Charts” page is an image viewer.
- `reports-v2.html` is 900 lines with inline JavaScript.
- The plan is not exposed as structured data, so it cannot be explained, tested,
  filtered, exported, or rendered by a native HA card.

### 2.3 The HA integration is shallow

- The add-on uses `hassapi` (the AppDaemon client) over synchronous REST.
- Reports read the Home Assistant recorder `statistics` tables directly.
- DAEO itself has no config flow, services, entities, calendar, diagnostics, or repairs.
- The add-on exposes port 5000 directly, which bypasseses HA authentication.
- The web app has no authentication of its own and a hard-coded Flask secret key.

### 2.4 The runtime carries avoidable complexity

- `calc_optimum` spans roughly 5,200 lines and mixes fetching, solving, entity writes,
  plotting, and database writes.
- Tasks are subprocesses whose progress is inferred by scraping log files and polling
  a JSON state file.
- `watchdog.sh` restarts the scheduler and reloads gunicorn when `options.json` changes.
- The config is a process-global singleton shared by gunicorn workers.

### 2.5 Language and documentation are fragmented

- README, DOCS, CHANGELOG, wiki, task names, log messages, report headers, and period
  tokens are Dutch; schema help and much of v2 are English.
- The add-on is named `刀 Day Ahead Optimizer`; the description is copied from a
  community-add-ons template.
- Documentation lives in README, DOCS.md, DEVELOP.md, SETTINGS.md, and a Dutch wiki.

### 2.6 What is already good

- The MILP model and 15-minute support.
- Price, weather, solar, baseload, and device logic.
- Pydantic configuration models and generated schema.
- The scenario suite (invariants, expectations, objective baselines).
- CI, dev containers, migration tooling, and release images.

The rebuild should not put any of this at risk.

---

## 3. Goals and non-goals

### Goals

1. A new user can configure prices, solar, a battery, and an EV **without editing JSON**.
2. The UI shows an explainable 24-hour plan, not a static image.
3. Home Assistant users get native entities, services, a calendar, diagnostics, and a
   config flow.
4. Control of real devices is explicit, armed, auditable, and safe by default.
5. Every shipped string, document, and metadata field is English.
6. The system runs as one process with a clear job model and structured logs.
7. NL/BE work end-to-end with presets, existing HA sensors, and no mandatory API key.

### Non-goals (this rebuild)

- Rewriting the MILP model or replacing CBC.
- Supporting markets outside NL/BE.
- A mobile app.
- Multi-tenant or cloud hosting.
- Migrating old configurations, entity IDs, or databases.
- Replacing pandas or matplotlib in the export path.

---

## 4. Users and journeys

### 4.1 First run (HA add-on)

1. Install the add-on. Open ingress.
2. The wizard detects location, timezone, country, and currency from Home Assistant.
3. Choose a price input:
   - an existing price sensor (`sensor.*`), or
   - ENTSO-E / Nordpool / Tibber, or
   - a fixed tariff.
4. Choose a solar/weather input:
   - an existing PV forecast entity, or
   - Open-Meteo (no key), or
   - Meteoserver/KNMI.
5. Add devices with entity pickers and live state preview:
   battery, boiler, heat pump, EV, machines.
6. Choose an objective and reserve SoC.
7. Preview a dry-run plan. Nothing is written to a device yet.
8. Arm control explicitly, per device, when satisfied.

### 4.2 Daily use

- Open the dashboard: current price, next action, plan cost/savings, plan freshness.
- Open the plan: price, load, PV, battery, EV/boiler schedule, and a “why” panel per
  interval.
- Confirm or override the next action.
- Use native HA entities and automations for everything else.

### 4.3 Advanced use

- Edit the raw JSON through an “Advanced” tab.
- Import/export configuration.
- Capture a run and replay it.
- Download a diagnostics bundle.
- Use the REST API or the `daeo.*` services.

### 4.4 Standalone exploration

- `docker compose up` starts the engine with a bundled demo configuration.
- The UI immediately shows a complete synthetic plan.
- No Home Assistant and no API keys are required.
- The same core is used; only the HA adapter is replaced by a simulator.

---

## 5. Architecture

```
┌────────────────────────── Home Assistant ──────────────────────────┐
│  custom_components/daeo (HACS)                                     │
│  config flow · coordinator · entities · services · calendar        │
│  diagnostics · repairs · device registry · statistics import       │
└───────────────────────────▲────────────────────────────────────────┘
                            │ authenticated REST + WebSocket
┌───────────────────────────┴────────────────────────────────────────┐
│  DAEO engine (add-on or standalone container)                      │
│                                                                    │
│  api/          FastAPI, auth, jobs, SSE, error contract             │
│  web/          ingress UI: dashboard, plan, settings, diagnostics   │
│  solver/       Solver protocol + CBC adapter (wraps existing core)  │
│  domain/       pure Plan, Interval, OptimizationInput, reasons      │
│  providers/    prices, weather, solar forecast, HA sensor input     │
│  storage/      SQLite (WAL), plan snapshots, run history            │
│  ha/           Supervisor client, control loop, audit log           │
│  config/       Pydantic schema, loader, secrets, presets            │
└────────────────────────────────────────────────────────────────────┘
```

### Responsibilities

- **Domain** has no IO. It defines validated values and the plan output.
- **Solver** receives an `OptimizationInput` and returns a `Plan`. It never writes to
  Home Assistant, never plots, and never reads files.
- **Providers** fetch and normalize external data. They are replaceable and testable
  with fixtures. EnergyZero is implemented for live NL all-in prices; ENTSO-E,
  Nordpool, Tibber, and HA sensors follow in M2.
- **Storage** persists configuration, plans, and run records. It does not contain
  business logic.
- **API** owns authentication, jobs, errors, and serialization.
- **Web** is a client of the API. It does not read the database directly.
- **HA adapter** owns entity reads and writes, control safety, and the audit trail.
- **Integration** owns the HA-native surface and calls the engine API. It does not
  duplicate the optimizer.

### Deployment

| Target | Purpose | HA features |
|---|---|---|
| HA add-on (Supervisor) | production | ingress, Supervisor API, discovery, add-on options |
| Standalone container | demo, development, debugging | optional token-based HA REST/WS |
| HACS integration | native HA surface | config flow, entities, services, calendar |

The standalone container is explicitly best-effort. The add-on is the supported
production path.

---

## 6. Domain contract

### 6.1 Plan

```python
class Plan:
    id: str
    created_at: datetime
    horizon_start: datetime
    horizon_end: datetime
    interval_minutes: int
    currency: str
    intervals: list[Interval]
    summary: PlanSummary
    solver: SolverInfo
    config_hash: str

class Interval:
    start: datetime
    end: datetime
    price_import_eur_kwh: float
    price_export_eur_kwh: float
    load_kwh: float
    pv_kwh: float
    battery_charge_kwh: float
    battery_discharge_kwh: float
    soc_pct: float
    ev_kwh: float
    boiler_kwh: float
    heat_pump_kwh: float
    machine_kwh: float
    grid_import_kwh: float
    grid_export_kwh: float
    cost_eur: float
    reason: Reason
    explanation: str | None

class PlanSummary:
    cost_eur: float
    baseline_cost_eur: float
    savings_eur: float
    import_kwh: float
    export_kwh: float
    pv_kwh: float
    load_kwh: float
    battery_cycles: float
    terminal_soc_value_eur: float   # value of energy left in the battery

class SolverInfo:
    name: str
    status: str
    runtime_ms: int
    objective_eur: float | None
    mip_gap: float | None
```

`Reason` is a closed enum (`price_low`, `price_high`, `pv_surplus`, `soc_min`,
`soc_max`, `ev_deadline`, `boiler_demand`, `heat_demand`, `machine_deadline`,
`grid_limit`, `idle`). Every interval may carry one reason and one human-readable
explanation. The UI uses this for the “why” panel; the API exposes it unchanged.

`savings_eur` compares the optimized cost with the baseline and includes the value of
energy left in the battery at the end of the horizon (`terminal_soc_value_eur`).
Without that term a plan that ends with a full battery would look artificially
expensive.

### 6.2 Input

```python
class OptimizationInput:
    now: datetime
    interval_minutes: int
    horizon_hours: int
    prices: list[PricePoint]      # import/export price per interval
    load_kwh: list[float]         # forecast baseline load per interval
    pv_kwh: list[float]           # forecast PV per interval
    solar: list[SolarInput]
    batteries: list[BatteryInput]
    evs: list[EVInput]
    boiler: FlexibleLoadInput | None
    heat_pump: FlexibleLoadInput | None
    machines: list[FlexibleLoadInput]
    grid_max_import_kw: float
    grid_max_export_kw: float
    strategy: StrategyConfig
```

The solver boundary is the only place where the old `DaCalc` code is wrapped. The
adapter builds `OptimizationInput` from config, providers, and HA state; the existing
model runs; the adapter converts solver variables into `Plan` intervals and reasons.
No entity writes happen inside the adapter.

### 6.3 Apply

`apply(plan)` is a separate operation:

1. Check that the plan is fresh and matches the current config hash.
2. Check that control is armed for each device.
3. Write only the current interval's setpoints.
4. Read back and verify.
5. Record an audit entry.
6. On failure or stale data, fall back to the configured safe state.

---

## 7. Configuration

### 7.1 Principles

- Canonical keys are `snake_case` English.
- No legacy aliases, no migration registry, no date-keyed tax tables as the only model.
- `extra="forbid"`: unknown keys are errors, not silently preserved.
- Secrets are separate from configuration and never returned by the API.
- UI metadata lives in the model (`json_schema_extra`) and is the only source of form
  behavior, labels, help, units, and conditional visibility.
- One schema version, starting at `1`. Breaking changes bump it deliberately.

### 7.2 Root shape

```json
{
  "schema_version": 1,
  "home": {
    "name": "Home",
    "latitude": 52.37,
    "longitude": 4.89,
    "timezone": "Europe/Amsterdam",
    "country": "NL",
    "currency": "EUR"
  },
  "prices": {
    "source": "ha_sensor",
    "price_sensor": "sensor.electricity_price",
    "preset": "nl",
    "vat_pct": 21,
    "supplier_markup_import_eur_kwh": 0.02,
    "energy_tax_import_eur_kwh": 0.11,
    "feed_in_tariff_eur_kwh": 0.0,
    "tax_refund": true
  },
  "strategy": {
    "objective": "minimize_cost",
    "interval": "quarter_hour",
    "allow_export": true,
    "reserve_soc_pct": 20,
    "cycle_cost_eur_kwh": 0.02,
    "max_gap_eur": 0.005
  },
  "grid": {"max_import_kw": 17, "max_export_kw": 17},
  "solar": [
    {"name": "Roof", "peak_power_wp": 5000, "dc_coupled": false,
     "forecast_entity": "sensor.solar_forecast"}
  ],
  "batteries": [
    {"name": "Home battery", "capacity_kwh": 10, "max_charge_kw": 5,
     "max_discharge_kw": 5, "efficiency": 0.95,
     "min_soc_pct": 20, "max_soc_pct": 100,
     "soc_entity": "sensor.battery_soc",
     "setpoint_entity": "number.battery_setpoint"}
  ],
  "electric_vehicles": [],
  "machines": [],
  "boiler": null,
  "heat_pump": null,
  "scheduler": {
    "enabled": true,
    "entries": [
      {"at": "13:55", "action": "fetch_prices"},
      {"at": "14:05", "action": "fetch_weather"},
      {"at": "14:15", "action": "optimize"}
    ]
  },
  "storage": {"data_dir": "/data", "retention_days": 30}
}
```

### 7.3 Sections

| Section | Contents |
|---|---|
| `home` | name, location, timezone, country, currency |
| `prices` | source (EnergyZero, ENTSO-E, Nordpool, Tibber, HA sensor, fixed), area, price sensor, tariff preset/components, feed-in |
| `strategy` | objective, interval, export, reserve, cycle cost, MIP gap |
| `grid` | import/export limits |
| `solar` | arrays, peak power, coupling, forecast/production entities |
| `batteries` | capacity, power, efficiency, SOC limits, control entities |
| `electric_vehicles` | capacity, power, phases, SOC, target, ready-by |
| `machines` | power, duration, window, control entity |
| `boiler` | volume, power, COP, temperatures, entities |
| `heat_pump` | stages, COP, heating curve, entities |
| `scheduler` | enabled, time/action entries |
| `storage` | data directory, retention |

### 7.4 HA entity references

Entity IDs are validated with a strict `domain.object_id` pattern and carry
`x-ui-widget-filter` hints so the UI can offer filtered pickers:

```python
EntityId = Annotated[str, StringConstraints(pattern=ENTITY_ID_PATTERN)]
soc_entity: EntityId | None = Field(
    None,
    json_schema_extra={"x-ui-widget-filter": "sensor", "x-unit": "%"},
)
```

### 7.5 Secrets

Configuration contains no credentials. A separate `secrets.json` (mode `0600`) holds:

```json
{
  "entsoe_api_key": "...",
  "tibber_token": "...",
  "meteoserver_key": "..."
}
```

The API returns only `has_value` flags. The settings UI writes secrets through a
dedicated endpoint that never echoes them back. Environment variables override file
secrets for container deployments.

### 7.6 NL/BE presets

The `prices.preset` field seeds the tariff components. Presets are data, not code:

- `nl`: energy tax, VAT, supplier markup, feed-in, tax refund.
- `be`: injection tariff, VAT, supplier markup, capacity tariff placeholder.
- `custom`: all components explicit.

Presets are editable after selection; the UI shows a diff from the preset. Market
rules live in one module with tests, not scattered through reports and charts.

---

## 8. API contract

Base path: `/api/v1`. JSON only. Errors use one shape:

```json
{"error": {"code": "validation_error", "message": "…", "details": []}}
```

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/health` | no | version, status, plan availability, auth mode |
| GET | `/config/schema` | no | JSON Schema with `x-ui-*` hints |
| GET | `/config` | read | current config (secrets redacted) |
| PUT | `/config` | write | validate, persist atomically, reload |
| POST | `/config/validate` | write | validate without saving |
| POST | `/config/import` | write | import a config document |
| GET | `/config/export` | read | download a config document |
| GET | `/secrets` | admin | list secret names and presence |
| PUT | `/secrets` | admin | write secrets (write-only) |
| GET | `/plan/latest` | read | latest plan |
| GET | `/plans` | read | plan history |
| GET | `/plans/{id}` | read | one plan |
| POST | `/optimize` | write | run a solve and store the plan |
| GET | `/runs` | read | run history |
| GET | `/runs/{id}` | read | run details |
| GET | `/runs/{id}/events` | read | SSE progress and logs |
| GET | `/diagnostics` | admin | redacted diagnostics bundle |
| GET | `/meta` | no | capabilities, providers, versions |

Authentication: `Authorization: Bearer <token>` or `X-DAEO-Token`. The engine
generates a token on first start, stores it in the data directory with mode `0600`,
and displays it in the add-on UI for pairing. Read-only endpoints are open in demo
mode only; mutations are always authenticated outside explicit demo mode.

Job model: `POST /optimize` returns `202` with a run ID and a location. Progress is
streamed over SSE; the plan is fetched from `/plans/{id}`. Long solves do not block
the event loop.

Versioning: additive changes within `/api/v1`; breaking changes create `/api/v2`.
The integration pins the API version it supports and reports incompatible engines as
a repair issue.

---

## 9. Home Assistant integration

### 9.1 Split

The add-on is the engine. The integration is the native surface. This is the
recommended pattern for heavy Python workloads: dependencies stay out of Home
Assistant Core, and the integration stays small and stable.

### 9.2 Integration responsibilities

- Config flow: discover or accept the engine URL and pairing token.
- Coordinator: poll `/plan/latest` and `/health`, subscribe to events.
- Entities: create the `daeo_*` sensor/binary sensor/calendar surface.
- Services: call the engine API and return responses.
- Diagnostics: collect redacted config, provider status, last run, versions.
- Repairs: stale data, invalid entity, provider failure, version mismatch.
- Statistics: import DAEO cost/savings/energy series with stable statistic IDs.
- Device registry: one DAEO device, plus optional per-physical-device entries.

### 9.3 Entity surface

| Entity | Type | Notes |
|---|---|---|
| `sensor.daeo_price_now` | sensor | EUR/kWh, `state_class=measurement` |
| `sensor.daeo_price_next_cheapest_window` | sensor | timestamp/attributes |
| `sensor.daeo_plan_cost` | sensor | EUR, `state_class=total` |
| `sensor.daeo_expected_savings` | sensor | EUR, `state_class=total` |
| `sensor.daeo_pv_forecast_today` | sensor | kWh |
| `sensor.daeo_battery_target_soc` | sensor | % |
| `sensor.daeo_next_battery_action` | sensor | enum |
| `sensor.daeo_plan_age` | sensor | seconds |
| `binary_sensor.daeo_plan_valid` | binary sensor | freshness and config hash |
| `binary_sensor.daeo_control_armed` | binary sensor | per device attribute |
| `binary_sensor.daeo_data_stale` | binary sensor | problem |
| `calendar.daeo_ev_charging` | calendar | EV windows |
| `button.daeo_run_optimization` | button | service proxy |
| `switch.daeo_control` | switch | global arm/disarm |
| `select.daeo_strategy` | select | objective |

### 9.4 Services

- `daeo.optimize` — run now, optional `dry_run`.
- `daeo.apply_plan` — apply a stored plan (explicit).
- `daeo.pause_control` — disarm for a duration.
- `daeo.set_strategy` — change objective.
- `daeo.export_plan` — return the plan as a response variable.
- `daeo.capture` — create a replay snapshot.

### 9.5 Events

- `daeo_plan_updated`
- `daeo_control_applied`
- `daeo_control_failed`
- `daeo_data_stale`
- `daeo_provider_error`

### 9.6 Discovery and pairing

1. The engine advertises `_daeo._tcp.local.` via zeroconf.
2. The integration discovers the engine and pre-fills the URL.
3. The add-on UI shows a short pairing code or token.
4. The user confirms in the config flow.
5. The engine issues a long-lived integration token; the add-on stores only its hash.

Fallback: manual URL + token. The engine URL is reachable only through an
authenticated API; the web UI itself remains ingress-only in the add-on.

### 9.7 Why not MQTT discovery only

MQTT discovery can create entities without an integration, but cannot provide
services, a config flow, a calendar, diagnostics, repairs, or statistics imports. It
is an acceptable interim or fallback, not the target.

---

## 10. Control safety

Device control is the highest-risk part of the product. The rebuild treats it as a
separate, auditable subsystem.

Rules:

1. **Dry-run by default.** A new installation writes nothing.
2. **Per-device arming.** A battery, boiler, EV, or machine can be controlled
   independently.
3. **Freshness gate.** A plan older than its validity window is never applied.
4. **Config hash gate.** A plan produced for a different config is never applied.
5. **Current interval only.** Apply the current interval; never replay the whole plan.
6. **Read-back verification.** Every write is verified against the target entity.
7. **Audit log.** Entity, old value, new value, plan ID, timestamp, result.
8. **Fallback.** Stale data, provider failure, or repeated write failure disarms
   control and restores the configured safe state.
9. **Manual override detection.** If a user changes a controlled entity, control
   pauses for a configurable window.
10. **Kill switch.** One HA switch and one UI button stop all writes immediately.

The UI shows control state permanently: `Control OFF`, `Armed for battery`, or
`Paused until 14:30`.

---

## 11. UI

### 11.1 Information architecture

```
Dashboard      current price, next action, savings, plan freshness, control state
Plan           price + load + PV + battery + EV/boiler + grid, per interval
  └ Why        marginal price, binding constraints, forecast inputs, solver gap
Runs           run now, progress, logs, history, capture/replay
Settings       guided sections, entity pickers, validation, advanced JSON
Diagnostics    provider status, entity health, versions, download bundle
```

### 11.2 Settings

- Forms generated from the Pydantic JSON Schema.
- Sections and order from `x-ui-group`, `x-ui-section`, `x-order`.
- Visibility rules from `x-ui-rules` (JSON Forms `condition/effect/scope`).
- Entity pickers from `x-ui-widget-filter`; live state shown next to the field.
- Arrays (solar, batteries, EV, machines) rendered as repeatable cards.
- “Advanced JSON” tab for power users; same validation as the forms.
- Save is disabled while invalid; errors point at the field.
- Import/export of the whole configuration.
- Secrets are write-only and never displayed.

Recommended renderer: **JSON Forms** (vanilla renderers) on top of the existing
Vite/Bootstrap pipeline. No second SPA framework.

### 11.3 Plan

- Interactive charts (Chart.js) rendered from `Plan` JSON.
- Price bars, SoC line, charge/discharge bars, EV/boiler/machine Gantt.
- Table view with CSV download.
- Click an interval to open the “why” panel.
- No matplotlib PNGs on the critical path; PNG export remains available.

### 11.4 Accessibility and mobile

- Mobile-first layouts; the HA companion app is the primary client.
- Dark/light theme following HA.
- Keyboard navigation, focus states, semantic tables.
- No colour-only meaning: charge/discharge and import/export always have labels.

---

## 12. Data and storage

- One SQLite database per engine instance, WAL mode.
- Tables: `config` (single row), `plans`, `runs`, `audit`, `secrets_meta`.
- Plans are stored as validated JSON; large series can move to Parquet in a later
  milestone without changing the API.
- Retention is configurable; default 30 days for runs, 365 days for daily summaries.
- Long-term statistics are imported into Home Assistant with stable statistic IDs:
  `daeo:cost`, `daeo:savings`, `daeo:grid_import`, `daeo:grid_export`,
  `daeo:pv`, `daeo:battery_charge`, `daeo:battery_discharge`.
- Export: CSV and JSON per plan; a full diagnostics bundle as a zip.
- No direct reads of the HA recorder database. Use the recorder statistics API.

---

## 13. Language policy

**English only.** This applies to:

- README, docs, wiki content, release notes, changelogs.
- Add-on and integration metadata, descriptions, options, translations.
- UI labels, help, errors, toasts, confirmations, empty states.
- Log messages, notifications, service errors, diagnostics.
- Report headers, chart labels, enum display names.
- Code comments and docstrings (new code immediately; existing code as touched).

Mechanics:

- Internal tokens are stable English identifiers (`today`, `tomorrow`,
  `minimize_cost`), translated only at the presentation layer.
- All user-facing strings live in one module (`daeo/strings/en.py`) or gettext
  catalogs with a single `en` locale. No string literals scattered through templates.
- Dates, numbers, and currency use locale-aware formatting (`Intl.NumberFormat` in
  the UI, `babel` on the server if needed).
- A CI guard scans user-facing directories for Dutch stopwords and non-English
  metadata, and fails the build.
- The old Dutch wiki is archived with a banner that points to the English docs; it is
  not maintained.

---

## 14. Repository layout

```
addon/                      HA add-on packaging (thin; image built by CI)
custom_components/daeo/     HACS integration (M3)
src/daeo/
  api/                      FastAPI app, auth, jobs, SSE
  config/                   Pydantic schema, loader, secrets, presets
  domain/                   Plan, Interval, OptimizationInput, reasons
  ha/                       Supervisor client, control loop, audit
  providers/                prices, weather, solar, HA sensor input
  solver/                   Solver protocol, CBC adapter, demo solver
  storage/                  SQLite repositories
  web/                      templates, static assets, Vite entry
  strings/                  English user-facing strings
tests/daeo/                 unit, contract, API, solver, e2e
docs/                       English documentation site
dao/                        legacy implementation (frozen until M4)
```

The legacy `dao/` tree is not imported by the new package. It remains the shipping
add-on until the cutover milestone.

---

## 15. Milestones

### M0 — Foundation and English metadata

- This proposal.
- New `pyproject.toml`, `src/daeo/` skeleton, domain and config contracts.
- Demo solver and a running API/UI skeleton.
- New add-on metadata (experimental, English, ingress-only).
- Immediate security fixes to the legacy add-on: remove the exposed host port,
  require admin for the panel, make the HA config mount read-only.
- English root README, repository metadata, and legacy add-on name/description.
- CI for the new package.

**Exit:** `pytest tests/daeo` passes; the skeleton runs with a demo plan; no new
Dutch strings; the legacy add-on no longer exposes an unauthenticated host port.

### M1 — Configuration and onboarding

- New config schema complete for NL/BE devices.
- Config API, atomic save, validation, import/export.
- Schema-driven settings UI with entity pickers and rules.
- Onboarding wizard.
- Secrets flow.
- NL/BE tariff presets.
- Price-sensor and Open-Meteo inputs.

**Exit:** a new user configures a battery and a price source without JSON; invalid
config never reaches disk; the schema is the single source of forms and docs.

### M2 — Plan and dashboard

- Extract the solver adapter and `Plan` conversion from `calc_optimum`.
- Plan API, persistence, run history, SSE.
- Interactive plan dashboard and “why” panel.
- CSV/JSON export; PNG becomes export-only.
- Baseline and savings calculation.

**Exit:** every run produces a validated `Plan`; the UI renders only from the API.

### M3 — Native Home Assistant

- HACS integration: config flow, coordinator, entities, services, calendar.
- Supervisor WebSocket client; no `hassapi`; no recorder DB reads.
- Statistics import; diagnostics; repairs.
- Control loop, arming, audit, fallback.

**Exit:** users get entities and services without YAML; control is opt-in and
auditable; a stale plan cannot write to a device.

### M4 — Cutover and decommission

- Delete `dao/` from the shipped image; remove v1, subprocess runner, watchdog,
  `task_state.json`, multi-dialect DB, migrations, and legacy aliases.
- English docs site generated from the schema; wiki redirect.
- One-command standalone demo.
- Release and upgrade notes.

**Exit:** one UI, one runtime, one docs source, no Dutch in shipped artifacts.

### Milestone status

| Milestone | Status |
|---|---|
| M0 | Complete: contracts, API/UI skeleton, demo solver, English metadata, legacy security fixes. |
| M1 | Complete: schema-driven Settings page, five-step Guided setup, config API, import/export, secrets, provider fields. |
| M2 | Data layer and CBC adapter complete for the supported set: EnergyZero prices, Forecast.Solar PV, HA recorder month/hour load profiles, plan `sources`, plan dashboard, CBC MILP for batteries/EVs/boiler/heat pump/machines/grid/PV curtailment, battery stage curves, AC/DC efficiencies, reduced-power SOC limits, minimum power, and terminal SOC. **Pending: PV array DC coupling, EV charge stages, heat-curve dynamics.** |
| M3 | Integration and battery control complete: config flow, coordinator, entities, calendar, services, diagnostics, arming switch, current-interval apply, read-back verification, SOC guard, fallback, audit/events, and HA harness tests. **Pending: Supervisor WebSocket client, statistics import, device-specific drivers (including Enphase), manual-override detection, boiler/EV/machine control.** |
| M4 | Not started: legacy `dao/` removal, one runtime, docs cutover. |
| M5 | Not started. |

### M5 — Reach (optional)

- Battery driver presets (Huawei, Solis, Sigenergy, Enphase, Victron, …).
- Solver abstraction evaluation (PuLP + HiGHS) to remove the CBC build path.
- More HA statistics and energy-dashboard integration.
- Additional markets.

---

## 16. Testing strategy

- **Unit:** domain validation, config presets, loader/atomic save, storage, auth.
- **Providers:** mocked HTTP tests for EnergyZero and Forecast.Solar (parsing,
  timezones, gaps, rate limits, errors).
- **Home Assistant harness:** config flow, token error, entry setup, entities,
  calendar, services, and diagnostics scaffold in `tests/ha/`.
- **Contract:** JSON Schema snapshots; API request/response snapshots; OpenAPI diff.
- **Solver:** the existing scenario suite stays. Add a `Plan` conversion test for each
  scenario and a golden-plan baseline.
- **API:** `TestClient` tests for auth, validation errors, run lifecycle, SSE.
- **UI:** Playwright for the wizard, settings save, plan rendering, control arming.
- **Integration:** HA test harness for config flow, entities, services, diagnostics.
- **Language:** CI guard for Dutch strings and metadata.
- **Security:** unauthenticated mutation attempts must return 401; stale plan apply
  must fail closed.

The scenario suite remains the regression net for the solver. Do not change its
semantics during the rebuild.

---

## 17. Security and privacy

- Ingress UI in the add-on; the integration API port 8099 is published with token
  auth (no unauthenticated host port). `demo_mode` disables auth and must only be
  used for isolated demos.
- Token auth on all mutations; constant-time comparison; tokens stored hashed.
- Per-secret write-only endpoints; secrets never returned by the API.
- `homeassistant_config` mounted read-only or removed once recorder reads are gone.
- No `eval` of user configuration; strict schema validation.
- CSRF protection for browser forms; SameSite cookies; no cross-origin API.
- Audit log for every device write.
- Diagnostics redact secrets, tokens, and entity values.
- Dependency and container scanning in CI.

---

## 18. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Control causes physical harm or cost | Dry-run default, per-device arming, freshness/config gates, read-back, fallback, kill switch |
| Solver extraction changes behaviour | Keep the model untouched; wrap it; run the scenario suite against old and new paths; golden plans |
| Scope creeps into a full rewrite | Milestones with exit criteria; legacy tree frozen; no new features in `dao/` |
| Users are disrupted by breaking changes | Deliberate major release; clear migration guide to the new config (manual import, not compatibility code) |
| Two artifacts (add-on + integration) double the release work | One repo, one tag, CI builds both; integration kept small; MQTT fallback documented |
| English-only alienates Dutch users | Market docs in English are acceptable for NL/BE; community translations can be added later without changing the core |
| HA API changes | Integration pins the API version and reports mismatches as repairs |

---

## 19. Open decisions

1. **Companion integration (D6):** confirm. If declined, M3 becomes MQTT discovery +
   Core API state publishing; services and calendar are dropped.
2. **Solver adapter:** wrap `DaCalc.calc_optimum` as-is, or extract the model into a
   pure function first? Recommendation: wrap first (M2), extract in a later
   refactor once the contract is proven.
3. **Add-on cutover:** replace `day_ahead_opt` in place, or publish a new slug
   (`daeo`) and keep the old add-on installable during the transition? Recommendation:
   new slug, old add-on deprecated after M4.
4. **Integration pairing:** zeroconf + short code, or URL + token only for the first
   release? Recommendation: URL + token for the first release; zeroconf pairing in a
   follow-up.

---

## 20. Implementation status

What exists in `src/daeo/` today:

- Strict configuration schema for home, prices, strategy, grid, solar, batteries,
  EVs, machines, boiler, heat pump, scheduler, and storage.
- Config loader with atomic writes, owner-only secrets, stable config hashing, and
  readable validation errors.
- `Plan` / `Interval` / `OptimizationInput` domain contracts with invariants.
- Deterministic demo solver (fallback) and a synthetic NL demo profile.
- CBC MILP adapter for multiple batteries, multiple EVs, boiler, heat pump, machines,
  grid import/export limits, and PV curtailment, with cycle cost, MIP gap, terminal
  SOC, battery stage curves, AC/DC efficiencies, reduced-power SOC limits, and
  minimum power.
- Home Assistant recorder load-profile reader: P1 import/export, PV, battery, and
  optional device sensors aggregated into 12×24 month/hour profiles (SQLite only).
- EnergyZero all-in price provider (live public API, 15/60-minute requests,
  `all_in_with_vat`, partial horizon before tomorrow's prices are published).
- Forecast.Solar PV provider (location, tilt, azimuth, kWp; 15/30/60-minute
  intervals; rate-limit handling).
- Schema-driven Settings page and a five-step Guided setup wizard.
- Plan `sources` (prices/PV) exposed through the API and UI.
- Home Assistant integration scaffold: config flow, coordinator, sensors, binary
  sensors, EV calendar, buttons, strategy select, services, diagnostics, HACS
  metadata.
- FastAPI app: health, meta, config schema, config CRUD/validate/export, secrets,
  plans, runs, optimize, diagnostics, and a dependency-free HTML plan viewer.
- SQLite persistence for config, plans, and runs.
- A test suite covering the schema, loader, storage, plan contract, solver output,
  API auth/validation, the demo mode, and the English-only guard.
- Experimental add-on scaffold (`addon/`) and standalone `docker-compose.yml`.
- English root README and metadata; legacy add-on security fixes (ingress only,
  admin panel, read-only HA config mount).

What is deliberately not here yet:

- The remaining legacy model nuances: PV array DC coupling, EV charge stages, and
  heat-curve dynamics.
- Supervisor WebSocket client, statistics import, device-specific drivers (including
  Enphase), manual-override detection, and boiler/EV/machine control.
- Existing HA PV forecast entity support (`SolarConfig.forecast_entity` is stored but
  not read).
- Deletion of the legacy `dao/` tree (M4).

## 21. Appendix A — API examples

### Run an optimization

```http
POST /api/v1/optimize
Authorization: Bearer <token>
Content-Type: application/json

{"dry_run": true}
```

```http
202 Accepted
{"run_id": "run_01J...", "status": "queued", "events": "/api/v1/runs/run_01J.../events"}
```

### Latest plan (excerpt)

```json
{
  "id": "plan_01J...",
  "interval_minutes": 15,
  "horizon_start": "2026-10-25T00:00:00+02:00",
  "horizon_end": "2026-10-26T00:00:00+02:00",
  "summary": {
    "cost_eur": 3.42,
    "baseline_cost_eur": 5.18,
    "savings_eur": 1.76,
    "import_kwh": 18.4,
    "export_kwh": 6.1,
    "pv_kwh": 22.7,
    "load_kwh": 12.3,
    "battery_cycles": 0.71
  },
  "solver": {"name": "cbc", "status": "optimal", "runtime_ms": 640, "mip_gap": 0.004, "objective_eur": 3.42},
  "intervals": [
    {
      "start": "2026-10-25T02:00:00+02:00",
      "end": "2026-10-25T02:15:00+02:00",
      "price_import_eur_kwh": 0.18,
      "price_export_eur_kwh": 0.05,
      "load_kwh": 0.12,
      "pv_kwh": 0.0,
      "battery_charge_kwh": 0.31,
      "battery_discharge_kwh": 0.0,
      "soc_pct": 42.1,
      "grid_import_kwh": 0.43,
      "grid_export_kwh": 0.0,
      "cost_eur": 0.077,
      "reason": "price_low",
      "explanation": "Price is in the cheapest 30% of the horizon; charging is limited by the 5 kW inverter."
    }
  ]
}
```

## 22. Appendix B — Naming

- Product: **Day Ahead Energy Optimizer (DAEO)**.
- Python package: `daeo`.
- Add-on slug: `daeo`.
- Integration domain: `daeo`.
- Service prefix: `daeo.`.
- Entity prefix: `daeo_`.
- Config file: `config.json`; secrets: `secrets.json`; database: `daeo.sqlite3`.
- Repository: `day-ahead-energy-optimizer`.

---

## 23. Definition of done

The rebuild is done when a new NL/BE user can:

1. Install the add-on and the integration.
2. Complete the wizard in under five minutes with existing HA sensors.
3. See an explainable plan for tomorrow.
4. Arm control and trust that a stale or failed plan cannot write to a device.
5. Use native HA entities, services, and a calendar without YAML.
6. Read English documentation that matches the product.
7. Run the same engine locally for debugging without touching the legacy code.
