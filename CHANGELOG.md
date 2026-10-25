# Changelog

All notable changes to the rebuild are documented here. The legacy add-on changelog
remains in [`dao/CHANGELOG.md`](dao/CHANGELOG.md) until the M4 cutover.

## Unreleased — rebuild M0

### Added

- `docs/rebuild-proposal.md`: decisions, target architecture, domain/API contracts,
  Home Assistant integration, control safety, and milestones.
- `src/daeo/`: new engine package with:
  - strict Pydantic configuration schema for NL/BE,
  - `Plan` / `Interval` / `OptimizationInput` domain contracts,
  - deterministic demo solver and synthetic demo profile,
  - SQLite persistence for config, plans, and runs,
  - FastAPI app with token auth, config CRUD/validation/export, plans, runs,
    optimize, diagnostics, and a dependency-free plan viewer.
- Live EnergyZero price provider: `prices.source = "energyzero"` fetches all-in
  consumer prices from the public EnergyZero API, with 15-minute and hourly
  intervals, timezone conversion, gap detection, and a shorter horizon before
  tomorrow's auction results are published.
- `tests/daeo/`: unit, contract, API, solver, storage, provider, and English-only
  guard tests.
- `addon/`: experimental add-on scaffold (ingress-only, no host port).
- `docker-compose.yml`: standalone demo.
- `pyproject.toml` and a dedicated CI workflow.

### Fixed — 2.1.5

- A Forecast.Solar outage or rate limit no longer blocks config saves, load-profile
  recalculation, or battery control. The engine falls back to the synthetic PV curve
  and marks the plan source as `pv: synthetic` instead of returning HTTP 502.
- Config saves only recalculate the recorder load profile when the `load` section
  actually changed. Saving unrelated fields such as the P1 grid settings no longer
  triggers a 365-day statistics scan.

### Fixed — 2.1.4

- Every integration optimize path now sends the live battery SOC. The controller
  refresh already did; the Run optimization button and `daeo.optimize` service did
  not, so they could replace a live-SOC plan with one based on the default 50%
  initial SOC.
- The engine remembers the last live SOC and reuses it for UI, config-save, and
  load-profile re-solves that do not supply a SOC.
- The controller refuses to arm when a configured SOC entity is unavailable, and
  refreshes the plan when the actual SOC diverges from the plan trajectory by more
  than 5%.
- Added live P1 zero-grid correction. When the plan targets zero grid import/export
  and the battery is covering load or absorbing PV, the controller adjusts the
  setpoint against the live net-meter power. The correction is bounded by the
  battery limits, SOC guard, deadband, and maximum step; planned grid-charge/export
  intervals are left alone. Configure it under Grid → Realtime grid control.

### Fixed — 2.1.3

- Added the missing **Load profile** card to Settings. The `load` config section
  existed in the schema/API but was omitted from the Settings UI, so recorder mode
  and its sensor lists could not be configured there.
- Added a regression test that every top-level `Config` field has a Settings card.

### Fixed — 2.1.2

- UI assets, API calls, and navigation now use ingress-relative URLs, so the plan,
  settings, and setup pages work under `/api/hassio_ingress/...` as well as directly.
- Add-on image version bumped to 2.1.2 so Supervisor pulls the fixed image.

### Added — add-on image publishing

- `.github/workflows/daeo-image.yml` builds multi-arch amd64/arm64 images and
  pushes `ghcr.io/<owner>/daeo` on `v*` tags or manual dispatch.
- Add-on README documents version/tag alignment, GHCR visibility, local build, and
  token pairing.
- Add-on publishes token-protected API port 8099 for the integration; the token is
  printed in the add-on log and stored in `/data/api_token` (0600).
- HACS release workflow creates a GitHub release on `v*` tags.
- Add-on maps `homeassistant_config:ro` for recorder load profiles.

### Added — recorder load profiles

- `load` configuration section with `source: recorder`.
- Read-only HA SQLite recorder reader for `statistics`/`statistics_meta`.
- P1 import/export, PV, battery, EV, boiler, heat-pump, and machine sensors aggregated
  into 12×24 month/hour profiles.
- `GET /api/v1/load-profile`, `POST /api/v1/load-profile/calculate`.
- Startup and config-save recalculation; Settings button; plan `load: recorder` source.
- Add-on `homeassistant_config:ro` map and compose mount example.
- Recorder tests for energy/power sensors, resets, missing DB, and API integration.

### Added — Anker Modbus / vendor control mapping

- Battery control supports unsigned magnitude setpoints with a separate
  charge/discharge direction select (official Anker Solix integration: Power Control +
  Grid Flow).
- Operating-mode precondition and fallback (`third_party_control` /
  `self_consumption`), and an optional master control switch.
- Setpoint inversion and optional setpoint feedback entity for signed vendor
  conventions (Anker X1 community integration).
- `docs/anker-modbus.md` with exact entity mappings and a safety checklist.

### Added — battery control loop

- Opt-in `switch` arming for the first battery, plus `arm_control`,
  `disarm_control`, and `apply_now` services.
- Current-interval signed AC power setpoint with optional charge/discharge/idle mode.
- Read-back verification with one retry; disarms and falls back to idle after failure.
- Stale/mismatched plan fallback and automatic plan refresh while armed.
- SOC guard that blocks charging at the top and discharging at the bottom.
- `control_status`, `control_active`, and `battery_setpoint` entities.
- Audit trail and `daeo_control_*` events; diagnostics include the control state.
- HA harness tests for arming and applying a setpoint.

### Added — CBC adapter

- CBC MILP solver (`daeo.solver.cbc`) is now the default engine solver:
  - multiple batteries with efficiency, SOC limits, power limits, cycle cost, and
    terminal SOC,
  - multiple EVs with departure deadlines,
  - boiler, heat pump, and machine windows,
  - grid import/export exclusivity, limits, and PV curtailment,
  - battery charge/discharge stage curves with SOS2 interpolation,
  - battery AC/DC conversion efficiencies,
  - reduced-power SOC limits, minimum power, and configurable terminal SOC,
  - cost or import minimisation, MIP gap, and CBC runtime reporting.
- `mip` and `cbcbox` dependencies; Docker image builds with the CBC library.
- Forecast.Solar provider cache (15 minutes) to reduce rate-limit pressure.
- Plan table shows flexible load (EV, boiler, heat pump, machine) per interval.
- CBC unit tests for arbitrage, EV deadlines, boiler scheduling, terminal SOC,
  infeasibility, and grid balance.

### Added — M1/M2/M3

- Schema-driven Settings page and five-step Guided setup wizard.
- Live Forecast.Solar PV provider with timezone conversion, rate-limit handling, and
  per-array configuration.
- Plan `sources` metadata (prices/PV) in the API and UI.
- Home Assistant integration scaffold in `custom_components/daeo`: config flow,
  coordinator, sensors, binary sensors, EV charging calendar, run button, strategy
  select, services (`optimize`, `set_strategy`, `export_plan`), diagnostics, and
  HACS metadata.
- Integration contract tests for metadata and pure plan helpers.
- Home Assistant test-harness coverage for config flow, token errors, and full entry
  setup (sensors, binary sensors, calendar, button, select, services).

### Changed

- Root README is now English and describes the rebuild and the standalone demo.
- Legacy add-on metadata is English; the `刀` prefix is removed.
- Legacy add-on is ingress-only (host port 5000 removed), admin-only in the sidebar,
  and mounts the Home Assistant config directory read-only.
- Repository metadata points at the fork and the new project name.

### Security

- Removed the unauthenticated host-port exposure from both legacy add-on manifests.
- New engine requires a bearer token outside explicit demo mode.
- New secrets file is written with owner-only permissions and never returned by the
  API.
