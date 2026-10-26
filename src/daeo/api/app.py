"""FastAPI application factory."""

from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Depends, FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from daeo.api.auth import ApiError, make_token_dependency
from daeo.api.settings import Settings
from daeo.config.loader import (
    ConfigError,
    Secrets,
    config_hash,
    load_secrets,
    redact,
    save_secrets,
    validate_payload,
)
from daeo.config.models import Config
from daeo.domain.enums import LoadSource, PriceSource, RunStatus, SolarForecastSource
from daeo.domain.plan import Plan
from daeo.providers.base import PriceProvider, ProviderError
from daeo.providers.energyzero import EnergyZeroProvider
from daeo.providers.forecast_solar import ForecastSolarProvider, SolarArray
from daeo.providers.recorder import LoadProfileSet, RecorderError, RecorderLoadReader
from daeo.solver.base import Solver, SolverError
from daeo.solver.cbc import CbcSolver
from daeo.solver.demo import build_inputs
from daeo.storage.sqlite import SqliteStore, StorageError
from daeo.version import __version__

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
logger = logging.getLogger(__name__)


class OptimizeRequest(BaseModel):
    """Options for a manual optimization run."""

    dry_run: bool = False
    battery_soc_pct: float | None = Field(default=None, ge=0, le=100)


def _now(config: Config) -> datetime:
    try:
        zone = ZoneInfo(config.home.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        zone = None
    return datetime.now(zone) if zone is not None else datetime.now().astimezone()


def _solve(
    store: SqliteStore,
    solver: Solver,
    config: Config,
    config_hash_value: str,
    *,
    now: datetime | None = None,
    price_provider: PriceProvider | None = None,
    pv_provider: ForecastSolarProvider | None = None,
    load_profile: LoadProfileSet | None = None,
    battery_soc_pct: float | None = None,
) -> Plan:
    now = now or _now(config)
    minutes = config.strategy.interval.minutes
    start = now.replace(
        minute=(now.minute // minutes) * minutes,
        second=0,
        microsecond=0,
    )
    prices = None
    if config.prices.source is PriceSource.ENERGYZERO:
        end = start + timedelta(hours=24)
        provider = price_provider or EnergyZeroProvider()
        prices = provider.fetch_prices(
            start,
            end,
            minutes,
            export_price_eur_kwh=config.prices.fixed_export_price_eur_kwh,
            export_price_adder_eur_kwh=config.prices.feed_in_tariff_eur_kwh,
        )
        start = prices[0].start
        end = prices[-1].start + timedelta(minutes=minutes)
        count = len(prices)
    else:
        count = 24 * 60 // minutes
        end = start + timedelta(minutes=count * minutes)

    pv_kwh = None
    if config.forecast.solar_source is SolarForecastSource.FORECAST_SOLAR:
        arrays = [
            SolarArray(
                peak_power_kwp=array.peak_power_wp / 1000,
                tilt_deg=array.tilt_deg,
                azimuth_deg=array.azimuth_deg,
            )
            for array in config.solar
            if array.enabled
        ]
        provider = pv_provider or ForecastSolarProvider()
        try:
            pv_kwh = provider.fetch_pv(
                start,
                end,
                minutes,
                arrays,
                latitude=config.home.latitude,
                longitude=config.home.longitude,
                timezone=config.home.timezone,
            )
            if len(pv_kwh) != count:
                raise ProviderError(
                    "Forecast.Solar returned a different number of intervals than prices"
                )
        except ProviderError as error:
            # A forecast provider outage/rate limit must not block config saves,
            # load-profile recalculation, or battery control. Fall back to the
            # synthetic PV curve and surface the fallback in plan sources.
            logger.warning("PV forecast failed; using synthetic PV: %s", error)
            pv_kwh = None

    load_kwh = _load_profile_for_intervals(
        load_profile,
        start,
        count,
        minutes,
        prices,
    )
    sources = {
        "prices": (
            "energyzero"
            if config.prices.source is PriceSource.ENERGYZERO
            else "fixed"
            if config.prices.source is PriceSource.FIXED
            else "synthetic"
        ),
        "pv": (
            "synthetic"
            if pv_kwh is None
            else "forecast_solar"
            if config.forecast.solar_source is SolarForecastSource.FORECAST_SOLAR
            else "synthetic"
        ),
        "load": "recorder" if load_kwh is not None else "synthetic",
        "grid_mode": config.strategy.grid_mode.value,
    }
    inputs = build_inputs(
        config,
        now=now,
        config_hash=config_hash_value,
        prices=prices,
        pv_kwh=pv_kwh,
        load_kwh=load_kwh,
        sources=sources,
    )
    if battery_soc_pct is not None and inputs.batteries:
        batteries = list(inputs.batteries)
        first = batteries[0]
        clamped = min(
            max(battery_soc_pct, first.min_soc_pct),
            first.max_soc_pct,
        )
        batteries[0] = first.model_copy(update={"initial_soc_pct": clamped})
        inputs = inputs.model_copy(update={"batteries": batteries})
    plan = solver.solve(inputs)
    store.save_plan(plan)
    return plan


def _calculate_load_profile(
    store: SqliteStore,
    config: Config,
) -> LoadProfileSet:
    """Read the HA recorder and persist the month/hour profile."""
    reader = RecorderLoadReader(config.load, config.home.timezone)
    profile = reader.read()
    store.save_load_profile(profile.to_dict(), profile.generated_at.isoformat())
    return profile


def _load_profile_for_intervals(
    profile: LoadProfileSet | None,
    start: datetime,
    count: int,
    minutes: int,
    prices,
) -> list[float] | None:
    """Expand a month/hour profile to the plan intervals."""
    if profile is None:
        return None
    if prices:
        starts = [price.start for price in prices]
    else:
        starts = [start + timedelta(minutes=index * minutes) for index in range(count)]
    return [
        round(max(0.0, profile.profiles[moment.month][moment.hour] * minutes / 60), 6)
        for moment in starts
    ]


def _secrets_presence(secrets: Secrets) -> dict[str, bool]:
    return {
        key: value is not None
        for key, value in secrets.model_dump().items()
    }


def create_app(
    settings: Settings | None = None,
    solver: Solver | None = None,
    price_provider: PriceProvider | None = None,
    pv_provider: ForecastSolarProvider | None = None,
) -> FastAPI:
    """Create the engine application.

    ``settings`` and ``solver`` are injectable for tests. Production uses
    ``Settings.from_env()`` and ``DemoSolver`` until the CBC adapter lands.
    """
    settings = settings or Settings.from_env()
    solver = solver or CbcSolver()
    price_provider = price_provider or EnergyZeroProvider()
    pv_provider = pv_provider or ForecastSolarProvider()
    require_api = make_token_dependency(
        settings.api_token,
        enabled=(not settings.demo) or settings.require_auth,
    )
    require_admin = make_token_dependency(settings.api_token, enabled=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        token_path = settings.data_dir / "api_token"
        token_content = settings.api_token + "\n"
        if not token_path.exists() or token_path.read_text(encoding="utf-8") != token_content:
            token_path.write_text(token_content, encoding="utf-8")
            os.chmod(token_path, 0o600)

        store = SqliteStore(settings.data_dir / "daeo.sqlite3")
        config = store.load_config()
        if config is None:
            config = Config.demo() if settings.demo else Config.default()
            store.save_config(config)
        hash_value = config_hash(config)
        secrets = load_secrets(settings.data_dir / "secrets.json")

        load_profile = None
        stored_profile = store.load_load_profile()
        if stored_profile is not None:
            try:
                load_profile = LoadProfileSet.from_dict(stored_profile)
            except (KeyError, ValueError) as error:
                logger.warning("Stored load profile is invalid: %s", error)
        if config.load.source is LoadSource.RECORDER:
            try:
                load_profile = _calculate_load_profile(store, config)
            except RecorderError as error:
                logger.warning("Could not calculate recorder load profile: %s", error)

        plan = store.latest_plan()
        if plan is not None and plan.config_hash != hash_value:
            plan = None
        if plan is None:
            try:
                plan = _solve(
                    store,
                    solver,
                    config,
                    hash_value,
                    price_provider=price_provider,
                    pv_provider=pv_provider,
                    load_profile=load_profile,
                )
            except (ProviderError, SolverError) as error:
                logger.warning("Initial optimization failed: %s", error)
                plan = None

        app.state.store = store
        app.state.config = config
        app.state.config_hash = hash_value
        app.state.secrets = secrets
        app.state.solver = solver
        app.state.price_provider = price_provider
        app.state.pv_provider = pv_provider
        app.state.load_profile = load_profile
        app.state.plan = plan
        app.state.last_battery_soc_pct = None
        yield

    app = FastAPI(
        title="Day Ahead Energy Optimizer",
        version=__version__,
        description="Plan battery, boiler, heat pump and EV use against dynamic prices.",
        lifespan=lifespan,
    )

    @app.exception_handler(ApiError)
    async def handle_api_error(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={"error": {"code": error.code, "message": error.message}},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Request validation failed.",
                    "details": jsonable_encoder(error.errors()),
                }
            },
        )

    @app.exception_handler(StorageError)
    async def handle_storage_error(_: Request, error: StorageError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "storage_error", "message": str(error)}},
        )

    @app.exception_handler(ProviderError)
    async def handle_provider_error(_: Request, error: ProviderError) -> JSONResponse:
        return JSONResponse(
            status_code=502,
            content={"error": {"code": "provider_error", "message": str(error)}},
        )

    @app.exception_handler(SolverError)
    async def handle_solver_error(_: Request, error: SolverError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content={"error": {"code": "solver_error", "message": str(error)}},
        )

    # Public ------------------------------------------------------------

    @app.get("/api/v1/health", tags=["meta"])
    def health(request: Request) -> dict:
        app_state = request.app.state
        return {
            "status": "ok",
            "version": __version__,
            "demo": settings.demo,
            "auth_required": (not settings.demo) or settings.require_auth,
            "plan_available": app_state.plan is not None,
            "config_hash": app_state.config_hash,
            "load_profile_available": app_state.load_profile is not None,
            "load_source": app_state.config.load.source.value,
            "last_battery_soc_pct": getattr(
                app_state, "last_battery_soc_pct", None
            ),
        }

    @app.get("/api/v1/meta", tags=["meta"])
    def meta() -> dict:
        return {
            "name": "Day Ahead Energy Optimizer",
            "version": __version__,
            "api_version": "v1",
            "countries": ["NL", "BE"],
            "price_sources": [source.value for source in PriceSource],
            "demo": settings.demo,
        }

    @app.get("/api/v1/config/schema", tags=["config"])
    def config_schema() -> dict:
        return Config.model_json_schema()

    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def index() -> str:
        return (WEB_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/settings", response_class=HTMLResponse, include_in_schema=False)
    def settings_page() -> str:
        return (WEB_DIR / "settings.html").read_text(encoding="utf-8")

    @app.get("/setup", response_class=HTMLResponse, include_in_schema=False)
    def setup_page() -> str:
        return (WEB_DIR / "setup.html").read_text(encoding="utf-8")

    @app.get(
        "/api/v1/config/demo",
        tags=["config"],
        dependencies=[Depends(require_api)],
    )
    def demo_config() -> dict:
        return Config.demo().model_dump(mode="json")

    # Configuration -----------------------------------------------------

    @app.get("/api/v1/config", tags=["config"], dependencies=[Depends(require_api)])
    def get_config(request: Request) -> dict:
        return redact(request.app.state.config)

    @app.post("/api/v1/config/validate", tags=["config"], dependencies=[Depends(require_api)])
    def validate_config(payload: dict) -> dict:
        try:
            validate_payload(payload)
        except ConfigError as error:
            raise ApiError(422, "validation_error", str(error)) from error
        return {"valid": True}

    @app.put("/api/v1/config", tags=["config"], dependencies=[Depends(require_api)])
    def update_config(payload: Config, request: Request) -> dict:
        store: SqliteStore = request.app.state.store
        previous_config = request.app.state.config
        load_changed = payload.load != previous_config.load
        hash_value = config_hash(payload)
        store.save_config(payload)
        request.app.state.config = payload
        request.app.state.config_hash = hash_value

        load_profile = request.app.state.load_profile
        load_profile_error = None
        if payload.load.source is LoadSource.RECORDER and (
            load_changed or load_profile is None
        ):
            try:
                load_profile = _calculate_load_profile(store, payload)
            except RecorderError as error:
                load_profile_error = str(error)
                logger.warning("Load profile calculation failed: %s", error)
        elif payload.load.source is not LoadSource.RECORDER:
            load_profile = None
        request.app.state.load_profile = load_profile

        plan = _solve(
            store,
            request.app.state.solver,
            payload,
            hash_value,
            price_provider=request.app.state.price_provider,
            pv_provider=request.app.state.pv_provider,
            load_profile=load_profile,
            battery_soc_pct=request.app.state.last_battery_soc_pct,
        )
        request.app.state.plan = plan
        response = {
            "config": redact(payload),
            "config_hash": hash_value,
            "plan_id": plan.id,
        }
        if load_profile_error:
            response["load_profile_error"] = load_profile_error
        return response

    @app.get("/api/v1/config/export", tags=["config"], dependencies=[Depends(require_api)])
    def export_config(request: Request) -> JSONResponse:
        content = json.dumps(request.app.state.config.model_dump(mode="json"), indent=2)
        return JSONResponse(
            content=json.loads(content),
            headers={"Content-Disposition": 'attachment; filename="daeo-config.json"'},
        )

    # Secrets -----------------------------------------------------------

    @app.get("/api/v1/secrets", tags=["secrets"], dependencies=[Depends(require_admin)])
    def get_secrets(request: Request) -> dict:
        return _secrets_presence(request.app.state.secrets)

    @app.put("/api/v1/secrets", tags=["secrets"], dependencies=[Depends(require_admin)])
    def put_secrets(payload: dict[str, str], request: Request) -> dict:
        allowed = set(Secrets.model_fields)
        unknown = set(payload) - allowed
        if unknown:
            raise ApiError(400, "unknown_secret", f"Unknown secret names: {sorted(unknown)}")
        current = {
            key: value
            for key, value in request.app.state.secrets.model_dump().items()
        }
        for key, value in payload.items():
            current[key] = value or None
        try:
            secrets = Secrets.model_validate(current)
        except ValidationError as error:
            raise ApiError(422, "validation_error", str(error)) from error
        save_secrets(secrets, settings.data_dir / "secrets.json")
        request.app.state.secrets = secrets
        return _secrets_presence(secrets)

    # Plans -------------------------------------------------------------

    @app.post("/api/v1/optimize", tags=["plan"], dependencies=[Depends(require_api)])
    def optimize(
        request: Request,
        payload: OptimizeRequest | None = None,
    ) -> dict:
        app_state = request.app.state
        store: SqliteStore = app_state.store
        run_id = store.start_run("optimize")
        soc_pct = payload.battery_soc_pct if payload is not None else None
        if soc_pct is not None:
            app_state.last_battery_soc_pct = soc_pct
        else:
            soc_pct = app_state.last_battery_soc_pct
        try:
            plan = _solve(
                store,
                app_state.solver,
                app_state.config,
                app_state.config_hash,
                price_provider=app_state.price_provider,
                pv_provider=app_state.pv_provider,
                load_profile=app_state.load_profile,
                battery_soc_pct=soc_pct,
            )
        except (ProviderError, SolverError) as error:
            store.finish_run(run_id, RunStatus.FAILED, error=str(error))
            raise
        except Exception as error:  # noqa: BLE001 - converted to a stable API error
            store.finish_run(run_id, RunStatus.FAILED, error=str(error))
            raise ApiError(500, "solve_failed", str(error)) from error
        app_state.plan = plan
        store.finish_run(run_id, RunStatus.SUCCEEDED, plan_id=plan.id)
        return {
            "run_id": run_id,
            "plan_id": plan.id,
            "dry_run": bool(payload.dry_run) if payload else False,
            "plan": plan,
        }

    @app.get("/api/v1/plan/latest", tags=["plan"], dependencies=[Depends(require_api)])
    def latest_plan(request: Request) -> Plan:
        plan = request.app.state.plan
        if plan is None:
            raise ApiError(404, "plan_not_found", "No plan has been generated yet.")
        return plan

    @app.get("/api/v1/plans", tags=["plan"], dependencies=[Depends(require_api)])
    def list_plans(request: Request, limit: int = 20) -> list[dict]:
        return [
            {
                "id": plan.id,
                "created_at": plan.created_at,
                "horizon_start": plan.horizon_start,
                "horizon_end": plan.horizon_end,
                "cost_eur": plan.summary.cost_eur,
                "savings_eur": plan.summary.savings_eur,
            }
            for plan in request.app.state.store.list_plans(limit)
        ]

    @app.get("/api/v1/plans/{plan_id}", tags=["plan"], dependencies=[Depends(require_api)])
    def get_plan(plan_id: str, request: Request) -> Plan:
        plan = request.app.state.store.get_plan(plan_id)
        if plan is None:
            raise ApiError(404, "plan_not_found", f"Unknown plan: {plan_id}")
        return plan

    # Runs --------------------------------------------------------------

    @app.get("/api/v1/runs", tags=["runs"], dependencies=[Depends(require_api)])
    def list_runs(request: Request, limit: int = 20) -> list[dict]:
        return request.app.state.store.list_runs(limit)

    @app.get("/api/v1/runs/{run_id}", tags=["runs"], dependencies=[Depends(require_api)])
    def get_run(run_id: str, request: Request) -> dict:
        run = request.app.state.store.get_run(run_id)
        if run is None:
            raise ApiError(404, "run_not_found", f"Unknown run: {run_id}")
        return run

    # Load profile ------------------------------------------------------

    @app.get("/api/v1/load-profile", tags=["load"], dependencies=[Depends(require_api)])
    def get_load_profile(request: Request) -> dict:
        profile = request.app.state.load_profile
        if profile is None:
            stored = request.app.state.store.load_load_profile()
            if stored is not None:
                try:
                    profile = LoadProfileSet.from_dict(stored)
                except (KeyError, ValueError) as error:
                    raise ApiError(
                        500, "load_profile_invalid", str(error)
                    ) from error
        return {
            "available": profile is not None,
            "profile": profile.to_dict() if profile is not None else None,
        }

    @app.post(
        "/api/v1/load-profile/calculate",
        tags=["load"],
        dependencies=[Depends(require_api)],
    )
    def calculate_load_profile(request: Request) -> dict:
        app_state = request.app.state
        if app_state.config.load.source is not LoadSource.RECORDER:
            raise ApiError(
                400,
                "load_source_not_recorder",
                "Set load.source to 'recorder' before calculating a load profile",
            )
        try:
            profile = _calculate_load_profile(app_state.store, app_state.config)
        except RecorderError as error:
            raise ApiError(422, "recorder_error", str(error)) from error
        app_state.load_profile = profile
        plan = _solve(
            app_state.store,
            app_state.solver,
            app_state.config,
            app_state.config_hash,
            price_provider=app_state.price_provider,
            pv_provider=app_state.pv_provider,
            load_profile=profile,
            battery_soc_pct=app_state.last_battery_soc_pct,
        )
        app_state.plan = plan
        return {"profile": profile.to_dict(), "plan_id": plan.id}

    # Diagnostics -------------------------------------------------------

    @app.get("/api/v1/diagnostics", tags=["meta"], dependencies=[Depends(require_admin)])
    def diagnostics(request: Request) -> dict:
        app_state = request.app.state
        plan = app_state.plan
        return {
            "version": __version__,
            "demo": settings.demo,
            "auth_required": (not settings.demo) or settings.require_auth,
            "config_hash": app_state.config_hash,
            "data_dir": str(settings.data_dir),
            "plan": plan.summary.model_dump() if plan is not None else None,
            "plan_created_at": plan.created_at if plan is not None else None,
            "run_count": len(app_state.store.list_runs(200)),
            "load_profile": (
                app_state.load_profile.to_dict()
                if app_state.load_profile is not None
                else None
            ),
        }

    return app
