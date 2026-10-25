"""Recorder load-profile tests."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from daeo.api.app import create_app
from daeo.api.settings import Settings
from daeo.config.models import Config, LoadConfig
from daeo.domain.enums import LoadSource
from daeo.providers.recorder import LoadProfileSet, RecorderError, RecorderLoadReader

TZ = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 3, 15, 12, 0, tzinfo=TZ)


def _timestamp(day: int, hour: int) -> float:
    return datetime(2026, 3, day, hour, tzinfo=TZ).timestamp()


def create_db(path) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
    connection.execute(
        """
        CREATE TABLE statistics_meta (
            id INTEGER PRIMARY KEY,
            statistic_id TEXT UNIQUE,
            source TEXT,
            unit_of_measurement TEXT,
            has_mean BOOLEAN,
            has_sum BOOLEAN,
            name TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE statistics (
            id INTEGER PRIMARY KEY,
            created_ts REAL,
            start_ts REAL,
            mean REAL,
            min REAL,
            max REAL,
            last_reset REAL,
            state REAL,
            sum REAL,
            metadata_id INTEGER
        )
        """
    )
    return connection


def add_sensor(connection, metadata_id, statistic_id, unit, has_mean, has_sum, rows):
    connection.execute(
        """
        INSERT INTO statistics_meta
            (id, statistic_id, source, unit_of_measurement, has_mean, has_sum, name)
        VALUES (?, ?, 'recorder', ?, ?, ?, ?)
        """,
        (metadata_id, statistic_id, unit, has_mean, has_sum, statistic_id),
    )
    for start_ts, mean, total in rows:
        connection.execute(
            """
            INSERT INTO statistics
                (created_ts, start_ts, mean, min, max, last_reset, state, sum, metadata_id)
            VALUES (?, ?, ?, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (start_ts, start_ts, mean, total, metadata_id),
        )


def config(path, **overrides) -> LoadConfig:
    values = {
        "source": LoadSource.RECORDER,
        "database_url": str(path),
        "lookback_days": 365,
        "grid_import_sensors": ["sensor.p1_import"],
        "grid_export_sensors": ["sensor.p1_export"],
        "solar_production_sensors": ["sensor.pv"],
        "battery_charge_sensors": ["sensor.battery_charge"],
        "battery_discharge_sensors": ["sensor.battery_discharge"],
    }
    values.update(overrides)
    return LoadConfig(**values)


def test_energy_sensors_produce_month_hour_profile(tmp_path) -> None:
    path = tmp_path / "home-assistant_v2.db"
    connection = create_db(path)
    import_rows = [
        (_timestamp(10, 9), None, 100.0),
        (_timestamp(10, 10), None, 101.0),
        (_timestamp(10, 11), None, 102.0),
        (_timestamp(10, 12), None, 103.0),
        (_timestamp(11, 9), None, 103.0),
        (_timestamp(11, 10), None, 105.0),
        (_timestamp(11, 11), None, 107.0),
        (_timestamp(11, 12), None, 109.0),
    ]
    export_rows = [
        (start, None, 10.0 + index * 0.3)
        for index, (start, _, _) in enumerate(import_rows)
    ]
    solar_rows = [
        (start, None, 5.0 + index * 0.5)
        for index, (start, _, _) in enumerate(import_rows)
    ]
    charge_rows = [
        (start, None, 2.0 + index * 0.1)
        for index, (start, _, _) in enumerate(import_rows)
    ]
    discharge_rows = [
        (start, None, 1.0 + index * 0.05)
        for index, (start, _, _) in enumerate(import_rows)
    ]
    add_sensor(connection, 1, "sensor.p1_import", "kWh", 0, 1, import_rows)
    add_sensor(connection, 2, "sensor.p1_export", "kWh", 0, 1, export_rows)
    add_sensor(connection, 3, "sensor.pv", "kWh", 0, 1, solar_rows)
    add_sensor(connection, 4, "sensor.battery_charge", "kWh", 0, 1, charge_rows)
    add_sensor(connection, 5, "sensor.battery_discharge", "kWh", 0, 1, discharge_rows)
    connection.commit()
    connection.close()

    profile = RecorderLoadReader(config(path), "Europe/Amsterdam").read(now=NOW)
    # Import: 1.5 kWh/h, export 0.3, PV 0.5, charge 0.1, discharge 0.05.
    assert profile.profiles[3][10] == pytest.approx(1.65)
    assert profile.profiles[3][11] == pytest.approx(1.65)
    assert profile.profiles[3][12] == pytest.approx(1.65)
    assert profile.sensor_counts["sensor.p1_import"] == 8


def test_power_sensor_uses_mean_and_interval(tmp_path) -> None:
    path = tmp_path / "home-assistant_v2.db"
    connection = create_db(path)
    rows = [
        (_timestamp(10, 10), 1000.0, None),
        (_timestamp(10, 11), 500.0, None),
        (_timestamp(10, 12), 0.0, None),
    ]
    add_sensor(connection, 1, "sensor.p1_import", "W", 1, 0, rows)
    connection.commit()
    connection.close()

    profile = RecorderLoadReader(
        config(
            path,
            grid_export_sensors=[],
            solar_production_sensors=[],
            battery_charge_sensors=[],
            battery_discharge_sensors=[],
        ),
        "Europe/Amsterdam",
    ).read(now=NOW)
    assert profile.profiles[3][10] == pytest.approx(1.0)
    assert profile.profiles[3][11] == pytest.approx(0.5)


def test_energy_reset_is_skipped(tmp_path) -> None:
    path = tmp_path / "home-assistant_v2.db"
    connection = create_db(path)
    rows = [
        (_timestamp(10, 9), None, 5.0),
        (_timestamp(10, 10), None, 1.0),  # reset: negative delta skipped
        (_timestamp(10, 11), None, 3.0),  # +2
    ]
    add_sensor(connection, 1, "sensor.p1_import", "kWh", 0, 1, rows)
    connection.commit()
    connection.close()

    profile = RecorderLoadReader(
        config(
            path,
            grid_export_sensors=[],
            solar_production_sensors=[],
            battery_charge_sensors=[],
            battery_discharge_sensors=[],
        ),
        "Europe/Amsterdam",
    ).read(now=NOW)
    assert profile.profiles[3][10] == pytest.approx(0.0)
    assert profile.profiles[3][11] == pytest.approx(2.0)


def test_missing_database_is_reported(tmp_path) -> None:
    with pytest.raises(RecorderError, match="not found"):
        RecorderLoadReader(
            config(tmp_path / "missing.db"), "Europe/Amsterdam"
        ).read(now=NOW)


def test_non_sqlite_url_is_reported(tmp_path) -> None:
    with pytest.raises(RecorderError, match="Only SQLite"):
        RecorderLoadReader(
            config("mysql://user:pass@host/db"), "Europe/Amsterdam"
        ).read(now=NOW)


def test_empty_statistics_is_reported(tmp_path) -> None:
    path = tmp_path / "home-assistant_v2.db"
    connection = create_db(path)
    connection.commit()
    connection.close()
    with pytest.raises(RecorderError, match="No recorder statistics"):
        RecorderLoadReader(config(path), "Europe/Amsterdam").read(now=NOW)


def test_load_profile_roundtrip() -> None:
    profile = LoadProfileSet(
        profiles={month: [1.0] * 24 for month in range(1, 13)},
        generated_at=NOW,
        start=NOW,
        end=NOW,
        sensor_counts={"sensor.p1_import": 10},
        warnings=["test"],
    )
    restored = LoadProfileSet.from_dict(profile.to_dict())
    assert restored == profile


def test_recorder_source_requires_sensors() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="grid import or export"):
        LoadConfig(source=LoadSource.RECORDER)


def test_api_calculates_and_uses_recorder_profile(tmp_path) -> None:
    path = tmp_path / "home-assistant_v2.db"
    connection = create_db(path)
    rows = [
        (_timestamp(10, 9), None, 0.0),
        (_timestamp(10, 10), None, 1.0),
        (_timestamp(10, 11), None, 2.0),
    ]
    add_sensor(connection, 1, "sensor.p1_import", "kWh", 0, 1, rows)
    connection.commit()
    connection.close()

    payload = Config.default().model_dump(mode="json")
    payload["load"] = {
        "source": "recorder",
        "database_url": str(path),
        "lookback_days": 365,
        "grid_import_sensors": ["sensor.p1_import"],
        "grid_export_sensors": [],
        "solar_production_sensors": [],
        "battery_charge_sensors": [],
        "battery_discharge_sensors": [],
        "ev_charge_sensors": [],
        "boiler_sensors": [],
        "heat_pump_sensors": [],
        "machine_sensors": [],
    }
    settings = Settings(
        data_dir=tmp_path / "data",
        api_token="test-token",
        demo=True,
        require_auth=True,
    )
    headers = {"Authorization": "Bearer test-token"}
    with TestClient(create_app(settings)) as client:
        response = client.put("/api/v1/config", headers=headers, json=payload)
        assert response.status_code == 200, response.text
        assert "load_profile_error" not in response.json()

        profile_response = client.get("/api/v1/load-profile", headers=headers)
        assert profile_response.status_code == 200
        body = profile_response.json()
        assert body["available"] is True
        assert body["profile"]["profiles"]["3"][10] == pytest.approx(1.0)

        plan = client.get("/api/v1/plan/latest", headers=headers).json()
        assert plan["sources"]["load"] == "recorder"
        assert any(interval["load_kwh"] > 0 for interval in plan["intervals"])

        recalc = client.post(
            "/api/v1/load-profile/calculate", headers=headers
        )
        assert recalc.status_code == 200
        assert recalc.json()["profile"]["profiles"]["3"][10] == pytest.approx(1.0)
