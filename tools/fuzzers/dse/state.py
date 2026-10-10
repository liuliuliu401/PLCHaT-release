"""
DSE State - Dynamic Symbolic Execution State Management

Migrated from: baselines/dse/state.py

Represents a single state during DSE traversal of ST-CFCG (Control Flow Graph).
Strictly separates:
- Internal memory (cross-cycle PLC state: timers, counters, static variables)
- Input memory (current cycle physical inputs)
- Path constraints (Z3 constraints accumulated along the path)
"""

import z3
import logging

logger = logging.getLogger(__name__)


class DSEState:
    """
    Represents a single moment in DSE traversal of ST-CFCG.

    Strictly separates current cycle physical inputs from cross-cycle PLC internal state.
    """
    def __init__(self, cycle: int = 1):
        self.cycle: int = cycle          # Current scan cycle depth
        self.PC: list = []               # Path Constraints (accumulated along path)

        # [Core Isolation Rule 1]
        self.internal_mem: dict = {}     # Cross-cycle internal state (timers, counters, static vars)
        self.input_mem: dict = {}        # Current cycle physical inputs (cleared on cycle advance)

        # Records all input symbols from cycle 1 to current for Z3 model completion
        # Format: [{'cycle': 1, 'sensor': z3.Bool('sensor_c1')}, {'cycle': 2, ...}]
        self.input_symbols: list = []

        # [Explosion Defense: Heuristic Scheduling & Pruning]
        self.yield_score: int = 0             # Coverage yield score (KLEE Coverage-Optimized Search)
        self.starvation_cycles: int = 0       # Coverage starvation cycles (reactive system stagnation detection)
        self.hit_new_branch_this_cycle: bool = False  # Whether this state triggered new coverage this cycle

    def clone(self) -> 'DSEState':
        """
        Core mechanism of State Forking.

        Deep copies state containers, ensuring Z3 expression references transfer
        and memory dictionaries are independent.
        """
        new_state = DSEState(self.cycle)
        new_state.PC = list(self.PC)
        new_state.internal_mem = dict(self.internal_mem)
        new_state.input_mem = dict(self.input_mem)

        # input_symbols contains dicts, shallow copy each to prevent reference pollution
        new_state.input_symbols = [dict(sym_record) for sym_record in self.input_symbols]

        # Inherit scores, reset this cycle's trigger flag
        new_state.yield_score = self.yield_score
        new_state.starvation_cycles = self.starvation_cycles
        new_state.hit_new_branch_this_cycle = False

        return new_state

    def add_input_symbol(self, var_name: str, z3_var: z3.ExprRef):
        """
        Helper: Register a physical input symbol for current cycle.

        Automatically mounts to both input_mem and input_symbols history.
        """
        logger.debug(f"  [DSE|Symb] Injecting current cycle physical symbol: [{var_name}]")
        self.input_mem[var_name] = z3_var

        # Ensure input_symbols list's last element corresponds to current cycle
        if not self.input_symbols or self.input_symbols[-1].get('cycle') != self.cycle:
            self.input_symbols.append({'cycle': self.cycle})

        self.input_symbols[-1][var_name] = z3_var

    def __repr__(self):
        return (f"<DSEState Cycle={self.cycle} | PC={len(self.PC)} | "
                f"Internal={list(self.internal_mem.keys())} | Input={list(self.input_mem.keys())}>")


__all__ = ["DSEState"]
