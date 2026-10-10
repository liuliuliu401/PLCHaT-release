"""
DSE Engine - Dynamic Symbolic Execution Core Engine

Migrated from: baselines/dse/engine.py

Universal DSE Engine that handles:
- Queue scheduling
- Z3 solving
- Fork control
- Coverage recording
- Test case export

Completely decoupled from PLC-specific logic - logic is provided via external function.
"""

import sys
import time
import z3
from pathlib import Path
from typing import List, Tuple, Callable, Dict, Any
import logging

from .state import DSEState

logger = logging.getLogger(__name__)


class DSEEngine:
    """
    Universal Dynamic Symbolic Execution Engine.

    Only responsible for: queue scheduling, Z3 solving, fork control,
    coverage recording, and test case export.
    Contains NO PLC-specific business logic.
    """
    def __init__(
        self,
        task_name: str,
        schema_dict: Dict[str, Any],
        max_depth: int = 5,
        timeout_sec: int = 120,
        debug_mode: bool = False
    ):
        self.task_name = task_name
        self.schema_dict = schema_dict
        self.max_depth = max_depth
        self.timeout_sec = timeout_sec

        # Initialize Z3 solver with timeout defense (avoid single complex constraint deadlock)
        self.solver = z3.Solver()
        self.solver.set("timeout", 5000)  # 5 second limit per Z3 query

        self.worklist: List[DSEState] = []
        self.covered_branches: set = set()
        self.generated_ir_cases: List[Dict[str, Any]] = []

    def is_sat(self, constraints: List[z3.ExprRef], branch_desc: str) -> Tuple[bool, Any]:
        """
        Push constraints to Z3 and solve, outputting Level 3 high-resolution trace logs.
        """
        logger.debug(f"    [Z3|Query] ├─ Probing [{branch_desc}] : PC ∧ (new condition)")
        self.solver.push()
        self.solver.add(constraints)
        res = self.solver.check()

        if res == z3.sat:
            model = self.solver.model()
            logger.debug(f"    [Z3|Result]│  └─ 🟢 [SAT] Reachable! -> Clone state and push constraint")
            self.solver.pop()
            return True, model
        else:
            logger.debug(f"    [Z3|Result]│  └─ 🔴 [UNSAT] Unreachable (logic conflict) -> Prune")
            self.solver.pop()
            return False, None

    def check_coverage_and_generate(self, branch_name: str, state: DSEState, model: z3.ModelRef):
        """
        [Rule 4 Standardized Export]
        If reaching a never-seen branch, output Level 4 coverage breakthrough log
        and construct unified IR format for archiving.
        """
        if branch_name not in self.covered_branches:
            self.covered_branches.add(branch_name)
            state.hit_new_branch_this_cycle = True  # Mark this state as contributing
            logger.info(f"    [DSE|Cov!] 🏆 Breakthrough new coverage edge: {branch_name} "
                       f"(discovered in Cycle {state.cycle})")
            logger.info(f"    [Z3|Model] └─ 🔓 Extract pass key (Z3 Model Completion):")

            timeline = {}
            for sym_record in state.input_symbols:
                c = sym_record['cycle']
                cycle_inputs = {}

                for var_name, z3_var in sym_record.items():
                    if var_name == 'cycle':
                        continue

                    # Extract concrete value (model_completion=True randomly assigns valid values
                    # to irrelevant variables that don't affect the result)
                    val = model.evaluate(z3_var, model_completion=True)

                    # Convert to Python basic types for JSON/IR generation
                    if z3.is_bool(val):
                        cycle_inputs[var_name] = "1" if z3.is_true(val) else "0"
                    elif z3.is_int(val):
                        cycle_inputs[var_name] = str(val.as_long())
                    elif z3.is_real(val):
                        # Z3 decimal conversion compatibility handling
                        cycle_inputs[var_name] = str(
                            float(val.numerator_as_long()) / float(val.denominator_as_long())
                        )
                    else:
                        cycle_inputs[var_name] = str(val)

                # Unified ExpUnifiedIR uses 0-based timeline index
                timeline[str(c - 1)] = cycle_inputs
                logger.info(f"                  ├─ Cycle {c}: {cycle_inputs}")

            ir_case = {
                "exp_id": f"DSE_{branch_name}_{len(self.generated_ir_cases)}",
                "target_st_path": self.task_name,
                "schema_path": "N/A",
                "tester_type": "DSE_Solver",
                "scan_cycle_ms": 50,
                "total_cycles": state.cycle,
                "sparse_timeline": timeline
            }
            self.generated_ir_cases.append(ir_case)

    def fork_if(
        self,
        state: DSEState,
        z3_condition: z3.BoolRef,
        branch_t_id: str,
        branch_f_id: str
    ) -> Tuple[DSEState, DSEState]:
        """
        [Rule 2 Fork Contract] Core interface.
        LLM-translated code MUST call this interface to handle all IF/ELSIF/CASE branches.
        """
        logger.debug(f"  [DSE|Fork] 🌿 Encountered conditional branch, probing bidirectional feasibility...")
        state_T, state_F = None, None

        # 1. Explore TRUE branch
        sat_T, model_T = self.is_sat(state.PC + [z3_condition], branch_t_id)
        if sat_T:
            state_T = state.clone()
            state_T.PC.append(z3_condition)
            self.check_coverage_and_generate(branch_t_id, state_T, model_T)

        # 2. Explore FALSE branch
        sat_F, model_F = self.is_sat(state.PC + [z3.Not(z3_condition)], branch_f_id)
        if sat_F:
            state_F = state.clone()
            state_F.PC.append(z3.Not(z3_condition))
            self.check_coverage_and_generate(branch_f_id, state_F, model_F)

        return state_T, state_F

    def end_cycle(self, state: DSEState):
        """
        [Rule 2 Termination Contract] Core interface.
        When a physical execution stream completes all logic in current cycle,
        call this method to push it to next cycle.
        """
        # [Pruning Defense 1] Calculate yield and starvation
        if state.hit_new_branch_this_cycle:
            state.starvation_cycles = 0
            state.yield_score += 100  # High weight reward
        else:
            state.starvation_cycles += 1
            state.yield_score -= 10   # Blind exploration penalty

        # [Pruning Defense 2] Resource-Aware Dynamic Stagnation Pruning
        # Reference KLEE/SAGE adaptive backoff strategy: dynamically calculate tolerance
        # based on current queue memory pressure
        queue_pressure = len(self.worklist) / 200.0  # Assume 200 is high pressure warning line

        # Linear interpolation mapping: empty load tolerates 8 cycles starvation
        # (good for deep state machine exploration), full load shrinks to 2 cycles (anti-explosion)
        # Formula: dynamic_limit = MAX_LIMIT - pressure * (MAX_LIMIT - MIN_LIMIT)
        dynamic_limit = int(8 - queue_pressure * 6)
        dynamic_limit = max(2, min(8, dynamic_limit))  # Clamp to [2, 8] range

        if state.starvation_cycles >= dynamic_limit:
            logger.debug(f"  [DSE|Prune] ✂️ [Queue Pressure: {queue_pressure*100:.0f}% | "
                        f"Dynamic Threshold: {dynamic_limit}] State has {state.starvation_cycles} "
                        f"cycles with no yield, executing prune!")
            return  # Refuse to push to next cycle

        if state.cycle < self.max_depth:
            logger.debug(f"  [DSE|Cycle] ⏩ Physical end reached (Score: {state.yield_score}). "
                        f"Clear input memory, push to Cycle {state.cycle + 1} queue...")
            next_state = state.clone()
            next_state.cycle += 1
            # [Rule 1 Isolation Defense] Completely clear previous cycle's transient inputs
            # to prevent pollution
            next_state.input_mem.clear()
            self.worklist.append(next_state)

    def run(self, logic_func: Callable) -> List[Dict[str, Any]]:
        """
        The pacemaker driving DSE.

        Receives LLM-precompiled logic_func, automatically executes
        breadth-first search (BFS) path traversal.
        """
        logger.info(f"\n{'='*50}\n[*] Starting Universal DSE Engine ({self.task_name})\n{'='*50}")
        logger.info(f"[DSE|Config] Max depth: {self.max_depth}, Timeout: {self.timeout_sec}s")
        start_time = time.time()

        # Push genesis state
        init_state = DSEState(cycle=1)
        self.worklist.append(init_state)
        logger.info(f"[DSE|Init] Genesis state pushed, starting BFS exploration")

        rounds = 0
        while self.worklist:
            if time.time() - start_time > self.timeout_sec:
                logger.warning("\n[!] Reached hard timeout, forcing DSE exploration termination.")
                break

            state = self.worklist.pop(0)
            rounds += 1

            logger.debug("")  # Empty separator line, keep layout elegant
            logger.debug(f"[DSE|State] 📥 Popped state (Cycle: {state.cycle} | Queue remaining: {len(self.worklist)})")
            logger.debug(f"[DSE|State] ├─ Inherited internal state: {list(state.internal_mem.keys())}")
            logger.debug(f"[DSE|State] ├─ Input symbols: {len(state.input_symbols)} registered")
            logger.debug(f"[DSE|State] └─ Current path constraints (PC) length: {len(state.PC)}")

            # Briefly hand over state machine control to LLM-generated dynamic logic
            try:
                logic_func(self, state)
            except Exception as e:
                logger.error(f"\n[!] LLM-generated code execution crashed: {e}")
                import traceback
                logger.error(traceback.format_exc())
                raise e

            # [Pruning Defense 3] Coverage-Yield Priority Queue Scheduling
            # Ensure next round pops the most exploration-potential state
            self.worklist.sort(key=lambda s: s.yield_score, reverse=True)

            # [Pruning Defense 4] Force memory explosion containment
            if len(self.worklist) > 200:
                logger.debug(f"  [DSE|Prune] 💣 Queue touched 200 water level, "
                            f"trimming low-score eliminated states...")
                self.worklist = self.worklist[:100]

        logger.info(f"\n[+] DSE exploration ended. Total {rounds} states iterated. "
                   f"Found {len(self.covered_branches)} edges.")
        logger.info(f"[+] Successfully generated and packed {len(self.generated_ir_cases)} test cases.")
        return self.generated_ir_cases


__all__ = ["DSEEngine"]
