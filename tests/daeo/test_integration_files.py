"""Contract tests for the Home Assistant integration scaffold."""

from __future__ import annotations

import ast
import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INTEGRATION = ROOT / "custom_components" / "daeo"


def _load_plan_module():
    spec = importlib.util.spec_from_file_location("daeo_integration_plan", INTEGRATION / "plan.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_manifest_and_hacs_metadata() -> None:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "daeo"
    assert manifest["config_flow"] is True
    assert manifest["version"]
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert hacs["name"] == "Day Ahead Energy Optimizer"


def test_all_integration_files_parse() -> None:
    for path in INTEGRATION.glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    assert "config" in strings
    translations = json.loads(
        (INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert translations == strings


def test_plan_helpers() -> None:
    plan_module = _load_plan_module()
    now = datetime(2026, 1, 1, 12, 10, tzinfo=UTC)
    plan = {
        "id": "plan_test",
        "created_at": "2026-01-01T12:00:00+00:00",
        "config_hash": "a" * 64,
        "intervals": [
            {
                "start": "2026-01-01T12:00:00+00:00",
                "end": "2026-01-01T12:15:00+00:00",
                "battery_charge_kwh": 1.0,
                "battery_discharge_kwh": 0.0,
                "ev_kwh": 2.0,
                "soc_pct": 50.0,
            },
            {
                "start": "2026-01-01T12:15:00+00:00",
                "end": "2026-01-01T12:30:00+00:00",
                "battery_charge_kwh": 0.0,
                "battery_discharge_kwh": 0.0,
                "ev_kwh": 3.0,
                "soc_pct": 50.0,
            },
            {
                "start": "2026-01-01T12:30:00+00:00",
                "end": "2026-01-01T12:45:00+00:00",
                "battery_charge_kwh": 0.0,
                "battery_discharge_kwh": 1.0,
                "ev_kwh": 0.0,
                "soc_pct": 50.0,
            },
        ],
    }

    interval = plan_module.current_interval(plan, now)
    assert interval is not None
    assert interval["start"] == "2026-01-01T12:00:00+00:00"
    assert plan_module.battery_action(interval) == "charging"

    windows = plan_module.ev_windows(plan)
    assert len(windows) == 1
    assert windows[0]["kwh"] == 5.0
    assert windows[0]["start"] == datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert windows[0]["end"] == datetime(2026, 1, 1, 12, 30, tzinfo=UTC)

    assert plan_module.plan_age_seconds(plan, now) == 600
    assert plan_module.plan_is_valid(plan, "a" * 64, now) is True
    assert plan_module.plan_is_valid(plan, "b" * 64, now) is False
    assert (
        plan_module.plan_is_valid(
            plan,
            "a" * 64,
            now + timedelta(hours=30),
        )
        is False
    )
