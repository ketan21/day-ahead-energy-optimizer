"""API contract tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from daeo.api.app import create_app
from daeo.api.settings import Settings
from daeo.config.models import Config
from daeo.domain.inputs import PricePoint
from daeo.providers.base import ProviderError
from daeo.providers.recorder import LoadProfileSet


def valid_payload() -> dict:
    payload = Config.default().model_dump(mode="json")
    payload["batteries"] = [
        {
            "name": "Home",
            "capacity_kwh": 10,
            "max_charge_kw": 5,
            "max_discharge_kw": 5,
        }
    ]
    payload["solar"] = [{"name": "Roof", "peak_power_wp": 4000}]
    return payload


def test_health_is_public(client) -> None:
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["auth_required"] is True
    assert body["plan_available"] is True


def test_protected_endpoints_require_token(client, auth_headers) -> None:
    assert client.get("/api/v1/plan/latest").status_code == 401
    response = client.get("/api/v1/plan/latest", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()["intervals"]) == 96


def test_schema_is_public_and_has_ui_hints(client) -> None:
    response = client.get("/api/v1/config/schema")
    assert response.status_code == 200
    schema = response.json()
    assert "batteries" in schema["properties"]
    assert "BatteryConfig" in schema["$defs"]


def test_config_roundtrip_and_reoptimize(client, auth_headers) -> None:
    response = client.get("/api/v1/config", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["schema_version"] == 1

    response = client.put(
        "/api/v1/config",
        headers=auth_headers,
        json=valid_payload(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["config"]["batteries"][0]["name"] == "Home"
    assert body["plan_id"].startswith("plan_")

    response = client.get("/api/v1/plan/latest", headers=auth_headers)
    assert response.status_code == 200
    assert len(response.json()["intervals"]) == 96


def test_invalid_config_returns_stable_error(client, auth_headers) -> None:
    payload = valid_payload()
    payload["batteries"][0]["capacity_kwh"] = -1
    response = client.put("/api/v1/config", headers=auth_headers, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_validate_endpoint_reports_business_error(client, auth_headers) -> None:
    response = client.post(
        "/api/v1/config/validate",
        headers=auth_headers,
        json={"schema_version": 1, "prices": {"source": "ha_sensor"}},
    )
    assert response.status_code == 422
    assert "price_sensor" in response.json()["error"]["message"]


def test_optimize_creates_plan_and_run(client, auth_headers) -> None:
    response = client.post(
        "/api/v1/optimize",
        headers=auth_headers,
        json={"dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"].startswith("run_")
    assert body["dry_run"] is True
    assert body["plan"]["solver"]["name"] == "cbc"
    assert len(body["plan"]["intervals"]) == 96

    runs = client.get("/api/v1/runs", headers=auth_headers)
    assert runs.status_code == 200
    assert any(run["id"] == body["run_id"] for run in runs.json())


def test_secrets_are_write_only(client, auth_headers, settings) -> None:
    response = client.put(
        "/api/v1/secrets",
        headers=auth_headers,
        json={"entsoe_api_key": "top-secret"},
    )
    assert response.status_code == 200
    assert response.json()["entsoe_api_key"] is True

    response = client.get("/api/v1/config", headers=auth_headers)
    assert "top-secret" not in response.text

    secrets_file = Path(settings.data_dir) / "secrets.json"
    assert secrets_file.exists()
    assert "top-secret" in secrets_file.read_text(encoding="utf-8")


def test_config_export_and_diagnostics(client, auth_headers) -> None:
    export = client.get("/api/v1/config/export", headers=auth_headers)
    assert export.status_code == 200
    assert "attachment" in export.headers["content-disposition"]
    assert json.loads(export.text)["schema_version"] == 1

    diagnostics = client.get("/api/v1/diagnostics", headers=auth_headers)
    assert diagnostics.status_code == 200
    assert "config_hash" in diagnostics.json()


def test_html_shell_is_served(client) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "Day Ahead Energy Optimizer" in response.text


def test_demo_mode_allows_local_mutation(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "demo",
        api_token="demo-token",
        demo=True,
        require_auth=False,
    )
    with TestClient(create_app(settings)) as demo_client:
        assert demo_client.get("/api/v1/plan/latest").status_code == 200
        response = demo_client.post("/api/v1/optimize", json={})
        assert response.status_code == 200


class FakeEnergyZeroProvider:
    name = "energyzero"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    def fetch_prices(
        self,
        start,
        end,
        interval_minutes,
        *,
        export_price_eur_kwh=None,
        export_price_adder_eur_kwh=0.0,
    ):
        self.calls += 1
        if self.fail:
            raise ProviderError("EnergyZero is down")
        count = int((end - start).total_seconds() / 60 / interval_minutes)
        return [
            PricePoint(
                start=start + timedelta(minutes=index * interval_minutes),
                import_eur_kwh=0.20 + index * 0.001,
                export_eur_kwh=(export_price_eur_kwh or 0.0)
                + export_price_adder_eur_kwh,
            )
            for index in range(count)
        ]


def test_energyzero_prices_are_used(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "energyzero",
        api_token="test-token",
        demo=True,
        require_auth=False,
    )
    provider = FakeEnergyZeroProvider()
    with TestClient(create_app(settings, price_provider=provider)) as client:
        payload = Config.default().model_dump(mode="json")
        payload["prices"]["source"] = "energyzero"
        payload["prices"]["fixed_export_price_eur_kwh"] = 0.05

        response = client.put("/api/v1/config", json=payload)
        assert response.status_code == 200, response.text
        plan = client.get("/api/v1/plan/latest").json()
        assert len(plan["intervals"]) == 96
        assert plan["intervals"][0]["price_import_eur_kwh"] == 0.20
        assert plan["intervals"][1]["price_import_eur_kwh"] == 0.201
        assert all(
            interval["price_export_eur_kwh"] == 0.05
            for interval in plan["intervals"]
        )
        assert provider.calls >= 1


def test_energyzero_provider_error_is_reported(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "energyzero-fail",
        api_token="test-token",
        demo=True,
        require_auth=False,
    )
    provider = FakeEnergyZeroProvider(fail=True)
    with TestClient(create_app(settings, price_provider=provider)) as client:
        payload = Config.default().model_dump(mode="json")
        payload["prices"]["source"] = "energyzero"
        response = client.put("/api/v1/config", json=payload)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "provider_error"


class FakePVProvider:
    name = "forecast_solar"

    def fetch_pv(
        self,
        start,
        end,
        interval_minutes,
        arrays,
        *,
        latitude,
        longitude,
        timezone=None,
    ):
        count = int((end - start).total_seconds() / 60 / interval_minutes)
        return [0.5] * count


def test_forecast_solar_pv_is_used(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path / "pv",
        api_token="test-token",
        demo=True,
        require_auth=False,
    )
    provider = FakePVProvider()
    with TestClient(create_app(settings, pv_provider=provider)) as client:
        payload = Config.default().model_dump(mode="json")
        payload["forecast"]["solar_source"] = "forecast_solar"
        payload["solar"] = [
            {"name": "Roof", "peak_power_wp": 5000, "tilt_deg": 35, "azimuth_deg": 180}
        ]

        response = client.put("/api/v1/config", json=payload)
        assert response.status_code == 200, response.text
        plan = client.get("/api/v1/plan/latest").json()
        assert plan["sources"]["pv"] == "forecast_solar"
        assert all(interval["pv_kwh"] == 0.5 for interval in plan["intervals"])
        assert plan["summary"]["pv_kwh"] == 48.0


def test_optimize_reuses_last_battery_soc(client, auth_headers) -> None:
    response = client.post(
        "/api/v1/optimize",
        headers=auth_headers,
        json={"battery_soc_pct": 29},
    )
    assert response.status_code == 200
    health = client.get("/api/v1/health").json()
    assert health["last_battery_soc_pct"] == 29

    # A UI-style optimize without an explicit SOC must not silently fall back to 50%.
    response = client.post("/api/v1/optimize", headers=auth_headers, json={})
    assert response.status_code == 200
    health = client.get("/api/v1/health").json()
    assert health["last_battery_soc_pct"] == 29


class FailingPvProvider:
    def fetch_pv(self, *args, **kwargs):
        raise ProviderError("Forecast.Solar rate limit reached")


def test_pv_provider_failure_falls_back_to_synthetic(settings, auth_headers) -> None:
    with TestClient(create_app(settings, pv_provider=FailingPvProvider())) as client:
        payload = Config.default().model_dump(mode="json")
        payload["forecast"]["solar_source"] = "forecast_solar"
        payload["solar"] = [
            {
                "name": "Roof",
                "peak_power_wp": 4000,
                "tilt_deg": 35,
                "azimuth_deg": 180,
            }
        ]
        response = client.put(
            "/api/v1/config",
            headers=auth_headers,
            json=payload,
        )
        assert response.status_code == 200
        plan = client.get(
            "/api/v1/plan/latest", headers=auth_headers
        ).json()
        assert plan["sources"]["pv"] == "synthetic"


def test_config_save_skips_unchanged_load_profile_recalculation(
    settings, auth_headers, monkeypatch
) -> None:
    calls = []
    now = datetime.now(UTC)
    profile = LoadProfileSet(
        profiles={month: [0.0] * 24 for month in range(1, 13)},
        generated_at=now,
        start=now - timedelta(days=365),
        end=now,
    )

    def fake_calculate(store, config):
        calls.append(config.load)
        return profile

    monkeypatch.setattr("daeo.api.app._calculate_load_profile", fake_calculate)

    with TestClient(create_app(settings)) as client:
        payload = Config.default().model_dump(mode="json")
        payload["load"] = {
            "source": "recorder",
            "database_url": "/tmp/ha.db",
            "lookback_days": 365,
            "grid_import_sensors": ["sensor.p1_import"],
            "grid_export_sensors": ["sensor.p1_export"],
            "solar_production_sensors": [],
            "battery_charge_sensors": [],
            "battery_discharge_sensors": [],
            "ev_charge_sensors": [],
            "boiler_sensors": [],
            "heat_pump_sensors": [],
            "machine_sensors": [],
        }
        response = client.put(
            "/api/v1/config", headers=auth_headers, json=payload
        )
        assert response.status_code == 200
        assert len(calls) == 1

        payload["grid"]["max_import_kw"] = 16.0
        response = client.put(
            "/api/v1/config", headers=auth_headers, json=payload
        )
        assert response.status_code == 200
        assert len(calls) == 1
