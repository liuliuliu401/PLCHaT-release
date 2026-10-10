"""
AFL Generator - Simplified wrapper for AFL++ fuzzing

Provides simplified interface for AFL++-guided test case generation.
For RQ2 experiments without full AFL++ binary requirements.
"""

import logging
import random
from typing import Dict, Any, List, Optional

from core.data_types.exp_types import ExpUnifiedIR
from ..random.generator import RandomCaseGenerator

logger = logging.getLogger(__name__)


class AFLCaseGenerator:
    """
    AFL++-inspired mutation-based test case generator.

    Simplified version that mimics AFL's mutation strategies without
    requiring the full AFL++ binary infrastructure.
    """

    def __init__(
        self,
        mutation_rate: float = 0.1,
        deterministic_cycles: int = 5,
        random_cycles: int = 20,
        debug: bool = False
    ):
        """
        Initialize AFL generator.

        Args:
            mutation_rate: Probability of mutation vs random
            deterministic_cycles: Cycles of deterministic mutations
            random_cycles: Cycles of random mutations
            debug: Enable debug logging
        """
        self.mutation_rate = mutation_rate
        self.deterministic_cycles = deterministic_cycles
        self.random_cycles = random_cycles
        self.debug = debug

        self.random_gen = RandomCaseGenerator()
        self.current_seed: Optional[Dict[str, Any]] = None

    def generate_case(
        self,
        st_code: str,
        schema_dict: Dict[str, Any],
        task_name: str = "task"
    ) -> Optional[ExpUnifiedIR]:
        """
        Generate test case using AFL-inspired mutation.

        Args:
            st_code: ST source code
            schema_dict: Input schema
            task_name: Task identifier

        Returns:
            ExpUnifiedIR test case
        """
        # Start with random seed if none exists
        if self.current_seed is None:
            seed_payload = self.random_gen.generate_case(st_code, schema_dict)
            if seed_payload:
                # Convert dict payload to simple timeline format
                self.current_seed = {"sparse_timeline": {"0": seed_payload}, "total_cycles": 10}
            else:
                self.current_seed = {"sparse_timeline": {"0": {}}, "total_cycles": 10}

        # Apply mutation
        mutated = self._mutate_seed(schema_dict)

        return ExpUnifiedIR(
            exp_id=f"afl_{task_name}_{random.randint(0, 10000)}",
            target_st_path="",
            schema_path="",
            tester_type="afl",
            total_cycles=mutated.get("total_cycles", 10),
            sparse_timeline=mutated.get("sparse_timeline", {}),
            metadata={"mutation_rate": self.mutation_rate}
        )

    def _mutate_seed(self, schema_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply AFL-style mutations to current seed.

        Mutation strategies (simplified):
        1. Bit flip
        2. Arithmetic increment/decrement
        3. Interest value replacement
        4. Dictionary insertion
        """
        if self.current_seed is None:
            return {"sparse_timeline": {"0": {}}, "total_cycles": 10}

        # Handle both ExpUnifiedIR and dict
        if hasattr(self.current_seed, 'sparse_timeline'):
            timeline = self.current_seed.sparse_timeline.copy()
        elif isinstance(self.current_seed, dict):
            timeline = self.current_seed.get("sparse_timeline", {"0": {}})
        else:
            timeline = {"0": {}}

        # Apply random mutations
        for cycle_idx, cycle_data in list(timeline.items()):
            for var_name, var_value in list(cycle_data.items()):
                if random.random() < self.mutation_rate:
                    cycle_data[var_name] = self._mutate_value(var_value, schema_dict)

        return {
            "sparse_timeline": timeline,
            "total_cycles": len(timeline)
        }

    def _mutate_value(self, value: Any, schema_dict: Dict[str, Any]) -> Any:
        """Apply mutation to a single value."""
        # Type-specific mutations
        if isinstance(value, bool):
            return not value

        if isinstance(value, int):
            # Arithmetic mutations
            mutations = [
                value + 1,
                value - 1,
                value + 16,
                value - 16,
                value ^ (1 << random.randint(0, 15)),  # Bit flip
                0,  # Interesting values
                127,
                128,
                255,
                256,
                32767,
                65535
            ]
            return random.choice(mutations)

        if isinstance(value, float):
            mutations = [
                value + 1.0,
                value - 1.0,
                value * 1.1,
                value * 0.9,
                0.0,
                1.0,
                -1.0
            ]
            return random.choice(mutations)

        # String/array mutations
        if isinstance(value, str):
            # Flip a bit
            if value:
                char_list = list(value)
                pos = random.randint(0, len(char_list) - 1)
                if char_list[pos].isdigit():
                    new_digit = str((int(char_list[pos]) + 1) % 10)
                    char_list[pos] = new_digit
                return "".join(char_list)

        return value
