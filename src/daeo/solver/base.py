"""Solver boundary."""

from __future__ import annotations

from typing import Protocol

from daeo.domain.inputs import OptimizationInput
from daeo.domain.plan import Plan


class SolverError(RuntimeError):
    """Raised when a solve cannot produce a plan."""


class Solver(Protocol):
    """A pure optimization backend."""

    name: str

    def solve(self, inputs: OptimizationInput) -> Plan:
        """Return a plan for the given inputs without side effects."""
        ...
