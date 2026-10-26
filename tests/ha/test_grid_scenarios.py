"""Exhaustive pure grid-target correction scenarios."""

from __future__ import annotations

import pytest

from custom_components.daeo.control import grid_corrected_power

BASE = {
    "max_charge_w": 1200.0,
    "max_discharge_w": 1200.0,
    "deadband_w": 30.0,
    "max_step_w": 1000.0,
}


@pytest.mark.parametrize(
    ("name", "kwargs", "expected"),
    [
        (
            "load spike: extra discharge, clamped at battery limit",
            {
                "base_power_w": -600,
                "actual_grid_w": 900,
                "target_grid_w": 0,
                "last_power_w": -600,
            },
            -1200.0,
        ),
        (
            "load drop: reduce discharge",
            {
                "base_power_w": -600,
                "actual_grid_w": -200,
                "target_grid_w": 0,
                "last_power_w": -600,
            },
            -400.0,
        ),
        (
            "PV surplus: increase charge instead of exporting",
            {
                "base_power_w": 800,
                "actual_grid_w": -700,
                "target_grid_w": 0,
                "last_power_w": 800,
                "max_charge_w": 1200.0,
            },
            1200.0,
        ),
        (
            "high-price planned export: follow negative grid target",
            {
                "base_power_w": -1000,
                "actual_grid_w": 200,
                "target_grid_w": -800,
                "last_power_w": -1000,
            },
            -1200.0,
        ),
        (
            "cheap planned grid charge: follow positive target",
            {
                "base_power_w": 1000,
                "actual_grid_w": 1200,
                "target_grid_w": 600,
                "last_power_w": 1000,
            },
            400.0,
        ),
        (
            "deadband: no write inside 30 W",
            {
                "base_power_w": -600,
                "actual_grid_w": 50,
                "target_grid_w": 40,
                "last_power_w": -600,
            },
            None,
        ),
        (
            "ramp limit: only 300 W change this tick",
            {
                "base_power_w": -600,
                "actual_grid_w": 1000,
                "target_grid_w": 0,
                "last_power_w": -600,
                "max_step_w": 300.0,
            },
            -900.0,
        ),
        (
            "minimum power: 60 W request is rounded to zero",
            {
                "base_power_w": -20,
                "actual_grid_w": 40,
                "target_grid_w": 0,
                "last_power_w": None,
                "minimum_power_w": 100.0,
            },
            0.0,
        ),
        (
            "charge limit: cannot absorb the full export",
            {
                "base_power_w": 500,
                "actual_grid_w": -1000,
                "target_grid_w": 0,
                "last_power_w": 500,
            },
            1200.0,
        ),
        (
            "discharge limit: cannot cover the full import",
            {
                "base_power_w": -600,
                "actual_grid_w": 2000,
                "target_grid_w": 0,
                "last_power_w": -600,
            },
            -1200.0,
        ),
    ],
)
def test_grid_correction_scenarios(name, kwargs, expected) -> None:
    assert grid_corrected_power(**{**BASE, **kwargs}) == expected, name


def test_control_catches_up_with_a_physical_load_and_battery() -> None:
    """The battery mirrors a load drop once P1 has been driven to zero."""
    setpoint = 0.0
    load_w = 900.0
    history = []

    for _ in range(4):
        actual = load_w + setpoint
        corrected = grid_corrected_power(
            setpoint,
            actual,
            0,
            **{**BASE, "max_step_w": 400.0},
            last_power_w=setpoint,
        )
        if corrected is not None:
            setpoint = corrected
        history.append((actual, setpoint))

    # House load drops by 200 W after the meter has reached zero.
    load_w = 700.0
    actual = load_w + setpoint
    corrected = grid_corrected_power(
        setpoint,
        actual,
        0,
        **{**BASE, "max_step_w": 400.0},
        last_power_w=setpoint,
    )
    if corrected is not None:
        setpoint = corrected
    history.append((actual, setpoint))

    assert history == [
        (900.0, -400.0),
        (500.0, -800.0),
        (100.0, -900.0),
        (0.0, -900.0),
        (-200.0, -700.0),
    ]
