"""Constants for the Day Ahead Energy Optimizer integration."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "daeo"
NAME = "Day Ahead Energy Optimizer"
MANUFACTURER = "DAEO"
VERSION = "2.1.4"

CONF_URL = "url"
CONF_TOKEN = "token"

DEFAULT_URL = "http://homeassistant.local:8099"
DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)
PLAN_STALE_SECONDS = 6 * 3600
PLAN_MAX_AGE_SECONDS = 26 * 3600

PLATFORMS = ["sensor", "binary_sensor", "calendar", "button", "select", "switch"]

STRATEGY_OPTIONS = ["minimize_cost", "minimize_import"]
