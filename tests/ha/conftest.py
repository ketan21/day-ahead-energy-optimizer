"""Home Assistant integration tests (optional, HA test harness)."""

from __future__ import annotations

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable loading custom integrations in the HA test harness."""
    yield


@pytest.fixture(autouse=True)
def verify_cleanup():
    """Disable the HA thread check on macOS.

    pycares/aiodns leaves a daemon ``_run_safe_shutdown_loop`` thread behind, which
    the upstream fixture treats as a leak. The test assertions still run.
    """
    yield
