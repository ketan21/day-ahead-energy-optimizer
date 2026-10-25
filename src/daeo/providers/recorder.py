"""Read month/hour load profiles from the Home Assistant recorder database.

The engine add-on mounts the HA config directory read-only. This module reads the
SQLite recorder ``statistics``/``statistics_meta`` tables and derives a gross
household load profile per month and hour of day.

P1/grid import sensors are the primary input. Optional PV, battery, EV, boiler,
heat-pump, and machine sensors remove those flows so the result is the underlying
household load. If no PV sensor is configured, the profile is net of PV.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from daeo.config.models import LoadConfig


class RecorderError(RuntimeError):
    """The recorder database cannot be read or contains no usable statistics."""


@dataclass
class LoadProfileSet:
    """Computed profiles and provenance."""

    profiles: dict[int, list[float]]
    generated_at: datetime
    start: datetime
    end: datetime
    sensor_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profiles": {str(month): hours for month, hours in self.profiles.items()},
            "generated_at": self.generated_at.isoformat(),
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "sensor_counts": self.sensor_counts,
            "warnings": self.warnings,
        }

    @classmethod
    def from_dict(cls, payload: dict) -> LoadProfileSet:
        return cls(
            profiles={
                int(month): [float(value) for value in hours]
                for month, hours in payload["profiles"].items()
            },
            generated_at=datetime.fromisoformat(payload["generated_at"]),
            start=datetime.fromisoformat(payload["start"]),
            end=datetime.fromisoformat(payload["end"]),
            sensor_counts=payload.get("sensor_counts", {}),
            warnings=payload.get("warnings", []),
        )


def _energy_factor(unit: str | None) -> float | None:
    if not unit:
        return None
    normalized = unit.strip().lower()
    if normalized == "wh":
        return 0.001
    if normalized == "kwh":
        return 1.0
    if normalized == "mwh":
        return 1000.0
    return None


def _power_factor(unit: str | None) -> float | None:
    if not unit:
        return None
    normalized = unit.strip().lower()
    if normalized == "w":
        return 0.001  # W -> kW
    if normalized == "kw":
        return 1.0
    if normalized == "mw":
        return 1000.0
    return None


class RecorderLoadReader:
    """Compute 12×24 average load profiles from recorder statistics."""

    def __init__(self, config: LoadConfig, timezone: str) -> None:
        self.config = config
        self.timezone = timezone

    def read(self, now: datetime | None = None) -> LoadProfileSet:
        try:
            zone = ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as error:
            raise RecorderError(f"Unknown timezone: {self.timezone}") from error
        now = now or datetime.now(zone)
        start = now - timedelta(days=self.config.lookback_days)
        end = now

        rows = self._load_rows(start, end)
        if not rows:
            raise RecorderError(
                "No recorder statistics found for the configured load sensors"
            )
        profiles, counts, warnings = self._aggregate(rows, zone)
        if not any(any(hours) for hours in profiles.values()):
            raise RecorderError("Recorder statistics produced an empty load profile")
        return LoadProfileSet(
            profiles=profiles,
            generated_at=now,
            start=start,
            end=end,
            sensor_counts=counts,
            warnings=warnings,
        )

    def _database_path(self) -> Path:
        value = self.config.database_url.strip()
        if value.startswith("sqlite:///"):
            value = value[len("sqlite:///") :]
        elif "://" in value:
            raise RecorderError(
                "Only SQLite recorder databases are supported; "
                "set database_url to the home-assistant_v2.db path"
            )
        return Path(value).expanduser()

    def _connect(self) -> sqlite3.Connection:
        path = self._database_path()
        if not path.exists():
            raise RecorderError(f"Recorder database not found: {path}")
        uri = f"file:{quote(str(path))}?mode=ro"
        try:
            connection = sqlite3.connect(uri, uri=True, timeout=10)
            connection.execute("PRAGMA query_only=ON")
            return connection
        except sqlite3.Error as error:
            raise RecorderError(f"Cannot open recorder database read-only: {error}") from error

    def _sensor_ids(self) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for sign, sensors in (
            (1, self.config.grid_import_sensors),
            (-1, self.config.grid_export_sensors),
            (1, self.config.solar_production_sensors),
            (-1, self.config.battery_charge_sensors),
            (1, self.config.battery_discharge_sensors),
            (-1, self.config.ev_charge_sensors),
            (-1, self.config.boiler_sensors),
            (-1, self.config.heat_pump_sensors),
            (-1, self.config.machine_sensors),
        ):
            for sensor in sensors:
                mapping[str(sensor)] = sign
        return mapping

    def _load_rows(
        self,
        start: datetime,
        end: datetime,
    ) -> list[tuple[str, str | None, int, int, float, float | None, float | None]]:
        sensor_signs = self._sensor_ids()
        if not sensor_signs:
            raise RecorderError("No load sensors are configured")
        placeholders = ",".join("?" for _ in sensor_signs)
        query = f"""
            SELECT sm.statistic_id,
                   sm.unit_of_measurement,
                   sm.has_mean,
                   sm.has_sum,
                   s.start_ts,
                   s.mean,
                   s.sum
            FROM statistics s
            JOIN statistics_meta sm ON sm.id = s.metadata_id
            WHERE sm.statistic_id IN ({placeholders})
              AND s.start_ts >= ?
              AND s.start_ts < ?
            ORDER BY sm.statistic_id, s.start_ts
        """
        try:
            connection = self._connect()
            cursor = connection.execute(
                query,
                (*sensor_signs.keys(), start.timestamp(), end.timestamp()),
            )
            rows = cursor.fetchall()
            connection.close()
        except sqlite3.Error as error:
            raise RecorderError(f"Cannot read recorder statistics: {error}") from error
        return rows

    def _aggregate(
        self,
        rows: list[tuple[str, str | None, int, int, float, float | None, float | None]],
        zone: ZoneInfo,
    ) -> tuple[dict[int, list[float]], dict[str, int], list[str]]:
        sensor_signs = self._sensor_ids()
        by_sensor: dict[str, list[tuple[float, float | None, float | None]]] = defaultdict(list)
        units: dict[str, str | None] = {}
        flags: dict[str, tuple[int, int]] = {}
        counts: dict[str, int] = defaultdict(int)
        for statistic_id, unit, has_mean, has_sum, start_ts, mean, total in rows:
            by_sensor[statistic_id].append((start_ts, mean, total))
            units[statistic_id] = unit
            flags[statistic_id] = (int(has_mean or 0), int(has_sum or 0))
            counts[statistic_id] += 1

        buckets: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0.0, set()])
        warnings: list[str] = []
        for statistic_id, series in by_sensor.items():
            sign = sensor_signs.get(statistic_id)
            if sign is None or not series:
                continue
            unit = units.get(statistic_id)
            has_mean, has_sum = flags.get(statistic_id, (0, 0))
            energy_factor = _energy_factor(unit)
            power_factor = _power_factor(unit)
            if energy_factor is not None and has_sum:
                self._add_energy_series(
                    series,
                    energy_factor,
                    sign,
                    zone,
                    buckets,
                )
            elif power_factor is not None and has_mean:
                self._add_power_series(
                    series,
                    power_factor,
                    sign,
                    zone,
                    buckets,
                )
            else:
                warnings.append(
                    f"{statistic_id}: unsupported unit/statistics type ({unit!r})"
                )

        # Average per hour-of-day within each month. Missing month/hour cells fall
        # back to the all-year hourly average.
        all_by_hour: dict[int, list[float]] = defaultdict(lambda: [0.0, set()])
        for (_month, hour), (energy, dates) in buckets.items():
            all_by_hour[hour][0] += energy
            all_by_hour[hour][1].update(dates)

        overall = [
            (all_by_hour[hour][0] / len(all_by_hour[hour][1]))
            if all_by_hour[hour][1]
            else 0.0
            for hour in range(24)
        ]
        profiles: dict[int, list[float]] = {}
        for month in range(1, 13):
            hours = []
            for hour in range(24):
                energy, dates = buckets.get((month, hour), (0.0, set()))
                value = energy / len(dates) if dates else overall[hour]
                hours.append(round(max(0.0, value), 4))
            profiles[month] = hours
        return profiles, dict(counts), warnings

    @staticmethod
    def _add_energy_series(
        series: list[tuple[float, float | None, float | None]],
        factor: float,
        sign: int,
        zone: ZoneInfo,
        buckets: dict[tuple[int, int], list[float]],
    ) -> None:
        previous: tuple[float, float | None, float | None] | None = None
        for current in series:
            if previous is not None:
                previous_total = previous[2]
                current_total = current[2]
                if previous_total is not None and current_total is not None:
                    delta = current_total - previous_total
                    if delta >= 0:
                        local = datetime.fromtimestamp(current[0], tz=UTC).astimezone(zone)
                        buckets[(local.month, local.hour)][0] += delta * factor * sign
                        buckets[(local.month, local.hour)][1].add(local.date())
            previous = current

    @staticmethod
    def _add_power_series(
        series: list[tuple[float, float | None, float | None]],
        factor: float,
        sign: int,
        zone: ZoneInfo,
        buckets: dict[tuple[int, int], list[float]],
    ) -> None:
        for index, current in enumerate(series):
            mean = current[1]
            if mean is None:
                continue
            if index + 1 < len(series):
                seconds = max(60.0, min(series[index + 1][0] - current[0], 3600.0))
            elif index > 0:
                seconds = max(60.0, min(current[0] - series[index - 1][0], 3600.0))
            else:
                seconds = 300.0
            energy = mean * factor * seconds / 3600
            local = datetime.fromtimestamp(current[0], tz=UTC).astimezone(zone)
            buckets[(local.month, local.hour)][0] += energy * sign
            buckets[(local.month, local.hour)][1].add(local.date())
