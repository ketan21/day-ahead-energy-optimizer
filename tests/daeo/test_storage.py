"""SQLite storage tests."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from daeo.config.models import Config
from daeo.domain.enums import RunStatus
from daeo.solver.demo import DemoSolver, build_inputs
from daeo.storage.sqlite import SqliteStore


def _plan():
    config = Config.default()
    now = datetime(2026, 10, 25, 12, 0, tzinfo=ZoneInfo("Europe/Amsterdam"))
    return DemoSolver().solve(build_inputs(config, now=now, config_hash="a" * 64))


def test_config_roundtrip(tmp_path) -> None:
    store = SqliteStore(tmp_path / "daeo.sqlite3")
    assert store.load_config() is None
    config = Config.default()
    store.save_config(config)
    assert store.load_config() == config


def test_plans_roundtrip(tmp_path) -> None:
    store = SqliteStore(tmp_path / "daeo.sqlite3")
    plan = _plan()
    assert store.latest_plan() is None
    store.save_plan(plan)
    assert store.get_plan(plan.id) == plan
    assert store.latest_plan() == plan
    assert [item.id for item in store.list_plans()] == [plan.id]


def test_runs_roundtrip(tmp_path) -> None:
    store = SqliteStore(tmp_path / "daeo.sqlite3")
    plan = _plan()
    store.save_plan(plan)
    run_id = store.start_run("optimize")
    store.finish_run(run_id, RunStatus.SUCCEEDED, plan_id=plan.id)
    run = store.get_run(run_id)
    assert run is not None
    assert run["status"] == "succeeded"
    assert run["plan_id"] == plan.id
    assert len(store.list_runs()) == 1


def test_prune_keeps_recent_rows(tmp_path) -> None:
    store = SqliteStore(tmp_path / "daeo.sqlite3")
    plan = _plan()
    store.save_plan(plan)
    store.prune(30)
    assert store.get_plan(plan.id) == plan
