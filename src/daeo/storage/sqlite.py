"""SQLite persistence for configuration, plans, and runs."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from daeo.config.models import Config
from daeo.domain.enums import RunStatus
from daeo.domain.plan import Plan


class StorageError(RuntimeError):
    """Raised when persisted data cannot be read or written."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class SqliteStore:
    """A small SQLite repository.

    One connection per operation keeps the store safe across FastAPI worker threads.
    WAL mode allows concurrent readers while a plan is being written.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS config (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS plans (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    horizon_start TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS plans_created_at
                    ON plans (created_at DESC);
                CREATE TABLE IF NOT EXISTS load_profile (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    payload TEXT NOT NULL,
                    generated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    plan_id TEXT,
                    error TEXT
                );
                CREATE INDEX IF NOT EXISTS runs_started_at
                    ON runs (started_at DESC);
                """
            )

    # Configuration -----------------------------------------------------

    def save_config(self, config: Config) -> None:
        payload = config.model_dump_json(indent=2)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO config (id, payload, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (payload, _utc_now()),
            )

    def load_config(self) -> Config | None:
        with self._connect() as connection:
            row = connection.execute("SELECT payload FROM config WHERE id = 1").fetchone()
        if row is None:
            return None
        try:
            return Config.model_validate_json(row["payload"])
        except Exception as error:  # pydantic.ValidationError is not stable enough here
            raise StorageError(f"stored configuration is invalid: {error}") from error

    # Plans -------------------------------------------------------------

    def save_plan(self, plan: Plan) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO plans (id, created_at, horizon_start, payload)
                VALUES (?, ?, ?, ?)
                """,
                (
                    plan.id,
                    plan.created_at.isoformat(),
                    plan.horizon_start.isoformat(),
                    plan.model_dump_json(),
                ),
            )

    def get_plan(self, plan_id: str) -> Plan | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM plans WHERE id = ?", (plan_id,)
            ).fetchone()
        if row is None:
            return None
        return self._parse_plan(row["payload"])

    def latest_plan(self) -> Plan | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM plans ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
        if row is None:
            return None
        return self._parse_plan(row["payload"])

    def list_plans(self, limit: int = 20) -> list[Plan]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM plans ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [self._parse_plan(row["payload"]) for row in rows]

    def _parse_plan(self, payload: str) -> Plan:
        try:
            return Plan.model_validate_json(payload)
        except Exception as error:
            raise StorageError(f"stored plan is invalid: {error}") from error

    # Runs --------------------------------------------------------------

    def start_run(self, kind: str) -> str:
        run_id = f"run_{uuid.uuid4().hex}"
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO runs (id, kind, status, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (run_id, kind, RunStatus.RUNNING.value, _utc_now()),
            )
        return run_id

    def finish_run(
        self,
        run_id: str,
        status: RunStatus,
        *,
        plan_id: str | None = None,
        error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, plan_id = ?, error = ?
                WHERE id = ?
                """,
                (status.value, _utc_now(), plan_id, error, run_id),
            )

    def get_run(self, run_id: str) -> dict | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 20) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY started_at DESC, rowid DESC LIMIT ?",
                (max(1, min(limit, 200)),),
            ).fetchall()
        return [dict(row) for row in rows]

    # Load profile ------------------------------------------------------

    def save_load_profile(self, payload: dict, generated_at: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO load_profile (id, payload, generated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    generated_at = excluded.generated_at
                """,
                (json.dumps(payload), generated_at),
            )

    def load_load_profile(self) -> dict | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM load_profile WHERE id = 1"
            ).fetchone()
        if row is None:
            return None
        try:
            return json.loads(row["payload"])
        except json.JSONDecodeError as error:
            raise StorageError(f"stored load profile is invalid: {error}") from error

    # Maintenance -------------------------------------------------------

    def prune(self, retention_days: int) -> None:
        cutoff = datetime.now(UTC).timestamp() - retention_days * 86400
        cutoff_iso = datetime.fromtimestamp(cutoff, UTC).isoformat()
        with self._connect() as connection:
            connection.execute("DELETE FROM plans WHERE created_at < ?", (cutoff_iso,))
            connection.execute("DELETE FROM runs WHERE started_at < ?", (cutoff_iso,))


def config_payload(config: Config) -> str:
    """Serialize a configuration for debugging or export."""
    return json.dumps(config.model_dump(mode="json"), indent=2)
