"""
Z3 Backend - Symbolic Execution Solver
Provides Z3 constraint solving capabilities for test case generation.
"""

from typing import Dict, Any, Optional
import sys

# Runtime check for Z3 availability
try:
    from z3 import *
    Z3_AVAILABLE = True
except ImportError:
    Z3_AVAILABLE = False


class Z3Engine:
    """
    [Conquer Module]
    Responsible for executing the symbolic model with concrete state injection.

    This engine takes Z3 constraint scripts and solves them to generate
    concrete test inputs that satisfy the constraints.
    """

    def __init__(self):
        """Initialize the Z3 Engine."""
        self.available = Z3_AVAILABLE

    def solve_with_snapshot(self, script: str, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute Z3 script with concrete state injection.

        Args:
            script: Python code string that defines Z3 constraints
            snapshot: Dictionary of concrete variable values to inject

        Returns:
            Standardized dictionary with keys:
            - status: "SAT"|"UNSAT"|"ERROR"
            - inputs: Dictionary of solved input variable values
            - reason: Error message if status is ERROR or UNSAT
        """
        if not self.available:
            return {"status": "ERROR", "inputs": {}, "reason": "Z3 not installed."}

        # 1. Sandbox Setup (expecting separated inputs and states)
        local_scope = {"s": None, "z3_inputs": None, "z3_states": None}
        global_scope = self._get_z3_globals()

        try:
            # 2. Logic Construction
            exec(script, global_scope, local_scope)

            solver = local_scope.get("s")
            z3_inputs = local_scope.get("z3_inputs", {})
            z3_states = local_scope.get("z3_states", {})

            if not solver or (not z3_inputs and not z3_states):
                return {
                    "status": "ERROR",
                    "inputs": {},
                    "reason": "Script did not define 's' or 'z3_inputs'/'z3_states'."
                }

            if not isinstance(z3_inputs, dict) or not isinstance(z3_states, dict):
                return {
                    "status": "ERROR",
                    "inputs": {},
                    "reason": "z3_inputs or z3_states is not a dictionary. Invalid structure."
                }

            # 3. State Injection - ONLY inject snapshot values into z3_states
            # z3_inputs remain free to be solved
            self._inject_snapshot(solver, z3_states, snapshot)

            # 4. Solving
            print(f"[DEBUG] [Z3Backend] Solver Assertions: {solver.assertions()}")
            check_result = solver.check()

            if check_result == sat:
                inputs = self._extract_solution(solver.model(), z3_inputs)
                return {"status": "SAT", "inputs": inputs, "reason": ""}
            else:
                return {"status": "UNSAT", "inputs": {}, "reason": str(solver.assertions())}

        except Exception as e:
            import traceback
            error_msg = f"{e}\n{traceback.format_exc()}"
            return {"status": "ERROR", "inputs": {}, "reason": error_msg}

    def _inject_snapshot(self, solver, z3_states, snapshot):
        """
        Bind symbolic variables to concrete values from the trace snapshot.
        ONLY for states, not inputs.
        """
        print(f"[DEBUG] [Z3Backend] Injecting Snapshot into States: {snapshot}")
        for name, value in snapshot.items():
            if name in z3_states:
                z3_var = z3_states[name]
                # Enforce: The state variable IS the value from the snapshot
                if isinstance(value, bool):
                    solver.add(z3_var == value)
                elif isinstance(value, (int, float)):
                    solver.add(z3_var == value)

    def _extract_solution(self, model, z3_inputs):
        """
        Extract only the solved input variables.
        Supports Int, Bool, Real (Float) types.
        """
        result = {}
        for name, var in z3_inputs.items():
            val = model[var]
            if val is not None:
                if is_true(val):
                    result[name] = True
                elif is_false(val):
                    result[name] = False
                elif isinstance(val, IntNumRef):
                    result[name] = val.as_long()
                elif isinstance(val, RatNumRef):
                    # Z3 Real type is extracted as Rational
                    result[name] = val.numerator_as_long() / val.denominator_as_long()
                elif hasattr(val, 'approx') and callable(getattr(val, 'approx')):
                    # Fallback for algebraic numbers
                    approx_val = val.approx(10)
                    if isinstance(approx_val, RatNumRef):
                        result[name] = approx_val.numerator_as_long() / approx_val.denominator_as_long()
        return result

    def _get_z3_globals(self):
        """Return global scope for Z3 script execution."""
        return {
            "Solver": Solver,
            "Int": Int,
            "Bool": Bool,
            "Real": Real,
            "Array": Array,
            "IntSort": IntSort,
            "BoolSort": BoolSort,
            "RealSort": RealSort,
            "RatNumRef": RatNumRef,
            "AlgebraicNumRef": AlgebraicNumRef,
            "And": And,
            "Or": Or,
            "Not": Not,
            "If": If,
            "Implies": Implies,
            "sat": sat,
            "unsat": unsat,
            "Select": Select,
            "Store": Store
        }


__all__ = ["Z3Engine", "Z3_AVAILABLE"]
