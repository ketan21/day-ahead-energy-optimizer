# Project status and handoff

**Last updated:** 2026-10-25
**Live demo:** <http://localhost:8099> (Docker Compose, `daeo-daeo-1`)
**Repository state:** working tree with the rebuild; legacy `dao/` remains in place.

## Current product state

| Area | Status |
|---|---|
| M0 foundation, domain/config contracts, API, SQLite | Complete |
| M1 schema-driven settings and guided setup | Complete |
| M2 energy prices (EnergyZero) | Complete |
| M2 PV forecast (Forecast.Solar) | Complete; 15-minute cache; rate limit 12/h per IP |
| M2 load profiles | HA recorder reader: month/hour profiles from P1 import/export, PV, battery, and optional device meters. SQLite only. |
| M2 CBC MILP solver | Complete for the supported device set |
| M2 legacy model nuances | Battery stage curves, AC/DC efficiencies, reduced-power SOC limits, minimum power, terminal SOC ported. PV array DC coupling, EV charge stages, heat-curve dynamics remain. |
| M3 integration and battery control | Config flow, coordinator, sensors, binary sensors, EV calendar, button, select, diagnostics, explicit arming switch, current-interval setpoint apply, read-back verification, SOC guard, fallback, audit/events, HA harness tests. Device-specific drivers, Supervisor WebSocket/statistics, and boiler/EV/machine control remain. |
| Deployment | Add-on image workflow builds/pushes `ghcr.io/<owner>/daeo` for amd64/arm64; add-on maps `homeassistant_config:ro` and publishes token-protected API port 8099; the token is printed in the add-on log; HACS integration remains separate. |
| M4 cutover | Not started |

## Live demo configuration

- `prices.source = energyzero` — real all-in prices, 48–49 intervals until tomorrow's auction publishes.
- `forecast.solar_source = forecast_solar` — real PV again.
- `load.source = synthetic` in the local Docker demo (no HA recorder mounted). The HA add-on can use `recorder` with the read-only HA config mount.
- `solver = cbc`, optimal, ~140 ms, gap 0.
- Plan: cost ~€0.92, baseline ~€1.31, savings ~€0.39, battery cycles 0.5.
- The local Docker demo uses synthetic load; the add-on can use HA recorder profiles.
- The demo config is stored in the `daeo-data` Docker volume.

## Key files

```
src/daeo/
  api/app.py             FastAPI app, auth, jobs, static UI
  config/models.py       strict Pydantic schema + UI hints
  config/loader.py       atomic config/secrets loading
  domain/plan.py         Plan, Interval, SolverInfo
  domain/inputs.py       OptimizationInput, battery stages, SOC limits
  providers/energyzero.py
  providers/forecast_solar.py
  solver/cbc.py          CBC MILP adapter (default)
  solver/demo.py         deterministic fallback
  solver/reasons.py      shared reason selection
  storage/sqlite.py      config, plans, runs
  web/                   plan, settings, guided setup
custom_components/daeo/  HACS integration scaffold
tests/daeo/              engine/provider/solver/API/UI-language tests
tests/ha/                Home Assistant harness tests
docs/rebuild-proposal.md architecture and milestones
docs/demo-configuration.md provider and demo configuration
```

## Environment

- `.venv` — Python 3.14, engine development and tests.
- `.venv-ha` — Python 3.12, Home Assistant 2025.1.4 + test harness.
- Docker Compose builds `addon/Dockerfile`; `cbcbox` supplies CBC.

## Commands

```bash
# Engine
.venv/bin/ruff check src/daeo tests/daeo custom_components/daeo
.venv/bin/python -m pytest tests/daeo

# Home Assistant harness
PYTHONPATH=. .venv-ha/bin/pytest tests/ha -q --asyncio-mode=auto

# Live demo
docker compose up -d --build
docker compose ps
curl -s http://localhost:8099/api/v1/plan/latest | python3 -m json.tool

# Recompute the live plan
curl -s -X POST http://localhost:8099/api/v1/optimize \
  -H 'Content-Type: application/json' -d '{}'
```

## Anker Modbus battery

The Anker battery at `192.168.0.41:502` is reached through the official Anker Solix
HA integration, not raw Modbus from DAEO. The detected IDs are documented in
[`docs/anker-modbus.md`](anker-modbus.md), including the Solarbank Max AC mapping and
the requirement to disable the existing Anker arbitrage automations before arming.

Load profiles use P1, Envoy production, and the Anker battery energy sensors; see
[`docs/load-profile.md`](load-profile.md).

## Known limitations / next work

1. **PV array DC coupling** — not modelled. `SolarConfig.dc_coupled` is stored but
   the CBC solver treats all PV as AC-coupled.
2. **EV charge stages** — only a single max power is modelled; phase switching and
   charge stage tables are not.
3. **Heat-curve dynamics** — heat pump is a flexible energy window, not the legacy
   degree-day/COP/curve model.
4. **Household load** — synthetic in the demo; no HA load sensor/history yet.
5. **Control loop** — battery arming/apply/verify/fallback/audit is implemented,
   including signed/unsigned setpoints, direction selects, operating-mode
   preconditions, and master control switches. Anker Modbus mapping is documented.
   Remaining: manual-override detection and boiler/EV/machine control.
6. **M4** — legacy `dao/` tree, Dutch docs, old UI, subprocess runner, and watchdog
   are still present but not shipped by the new add-on scope.
7. **Add-on image** — `addon/config.yaml` points at `ghcr.io/ketan21/daeo`; the
   image workflow is in place. Publish a tag and make the GHCR package public.

## Forecast.Solar note

The public API allows 12 requests/hour per IP. The provider caches per array for
15 minutes. The live config was left on `synthetic` after the limit was hit; setting
it back to `forecast_solar` triggers a real forecast and a CBC re-solve.
