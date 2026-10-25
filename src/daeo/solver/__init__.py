"""Solver backends and the pure solve boundary."""

from daeo.solver.base import Solver, SolverError
from daeo.solver.cbc import CbcSolver
from daeo.solver.demo import DemoSolver, build_inputs

__all__ = ["CbcSolver", "DemoSolver", "Solver", "SolverError", "build_inputs"]
