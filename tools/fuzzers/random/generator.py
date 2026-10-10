"""
Random Case Generator - Weighted Random Test Case Generation

Core component for generating test cases using weighted random sampling:
- Static analysis of logic thresholds (magic numbers)
- Weighted sampling with boundary testing
- IEC 61131-3 type compliance checking

Migrated from: baselines/random/generator.py
"""

import signal
import random
import re
from typing import Dict, Any, Set, Tuple, Optional, List


# IEC 61131-3 Type Limits (unchanged from original)
IEC_TYPE_LIMITS = {
    "BOOL":  {"min": 0, "max": 1, "type": int},
    "BYTE":  {"min": 0, "max": 255, "type": int},
    "WORD":  {"min": 0, "max": 65535, "type": int},
    "DWORD": {"min": 0, "max": 4294967295, "type": int},
    "SINT":  {"min": -128, "max": 127, "type": int},
    "INT":   {"min": -32768, "max": 32767, "type": int},
    "DINT":  {"min": -2147483648, "max": 2147483647, "type": int},
    "UINT":  {"min": 0, "max": 65535, "type": int},
    "UDINT": {"min": 0, "max": 4294967295, "type": int},
    "REAL":  {"min": -1e37, "max": 1e37, "type": float},
    "LREAL": {"min": -1e307, "max": 1e307, "type": float}
}


class TimeoutException(Exception):
    """Exception raised when generation times out."""
    pass


def timeout_handler(signum, frame):
    """Signal handler for timeout."""
    raise TimeoutException("Generation process timed out")


class RandomCaseGenerator:
    """
    Weighted random test case generator for PLC programs.

    Uses static analysis to extract logic thresholds from ST code and applies
    weighted sampling strategies:
    - Strategy 1: Target logic-specific magic numbers (prob_magic)
    - Strategy 2: Global interest points and boundaries (prob_boundary)
    - Strategy 3: Bit pattern testing (prob_bit_pattern)
    - Strategy 4: Pure random within range (fallback)
    """

    def __init__(self, seed: Optional[int] = None, config: Optional[Dict[str, Any]] = None):
        """
        Initialize the generator.

        Args:
            seed: Random seed for reproducibility
            config: Optional configuration dict with keys:
                - prob_magic: Probability of targeting magic numbers (default 0.50)
                - prob_boundary: Probability of using boundary values (default 0.20)
                - prob_bit_pattern: Probability of bit pattern testing (default 0.10)
                - real_range: Range for REAL/LREAL types (default (-100.0, 100.0))
                - interest_points: List of global interest values
                - timeout_sec: Generation timeout in seconds (default 5)
        """
        if seed is not None:
            random.seed(seed)

        # Default configuration (unchanged from original)
        self.cfg = {
            "prob_magic": 0.50,
            "prob_boundary": 0.20,
            "prob_bit_pattern": 0.10,
            "real_range": (-100.0, 100.0),
            "interest_points": [0, 1, -1, 127, 128, 255, 256, 32767, 65535, 4294967295],
            "timeout_sec": 5
        }
        if config:
            self.cfg.update(config)

        self.power_of_two = [2**i for i in range(32)]

    def _extract_logic_thresholds(self, st_code: str) -> Tuple[Dict[str, Set[float]], Set[float]]:
        """
        Static analysis to extract logic thresholds (magic numbers) from ST code.

        Args:
            st_code: ST source code

        Returns:
            Tuple of (variable_thresholds, global_points):
                - variable_thresholds: Dict mapping variable names to their threshold values
                - global_points: Set of all numeric values found in case statements
        """
        thresholds: Dict[str, Set[float]] = {}
        # Pattern for comparisons: variable >=|<=|>|<|<>|= value
        cmp_pattern = re.compile(
            r'(\w+)\s*(?:>=|<=|>|<|<>|=)\s*([-+]?\d*\.?\d+(?:#\w+)?)',
            re.IGNORECASE
        )
        # Pattern for case statements
        case_pattern = re.compile(r'\b(\d+)\s*:', re.MULTILINE)

        for var, val in cmp_pattern.findall(st_code):
            parts = val.split('#')
            raw_val = parts[-1]
            try:
                # Handle hex literals (16#...)
                num_val = int(raw_val, 16) if len(parts) > 1 and '16' in parts[0] else float(raw_val)
                v_low = var.lower()
                if v_low not in thresholds:
                    thresholds[v_low] = set()
                thresholds[v_low].add(float(num_val))
            except (ValueError, TypeError):
                continue

        # Extract case statement values
        case_vals = case_pattern.findall(st_code)
        global_points = set(float(v) for v in case_vals)

        return thresholds, global_points

    def _weighted_sample(
        self,
        iec_type: str,
        var_thresholds: Set[float],
        global_points: Set[float]
    ) -> Any:
        """
        Core weighted sampling logic with magic number targeting.

        Args:
            iec_type: IEC 61131-3 type name
            var_thresholds: Set of threshold values specific to this variable
            global_points: Set of global interest points from case statements

        Returns:
            Generated value respecting IEC type limits
        """
        limits = IEC_TYPE_LIMITS.get(iec_type, IEC_TYPE_LIMITS["INT"])
        r = random.random()

        # Strategy 1: Target code-specific logic thresholds (Magic Numbers)
        if var_thresholds and r < self.cfg["prob_magic"]:
            base = random.choice(list(var_thresholds))
            # 50% precise hit, 50% boundary fluctuation (±1 or ±0.1)
            if random.random() < 0.5:
                val = base
            else:
                offset = random.choice([1, -1, 0.1, -0.1])
                val = base + offset

        # Strategy 2: Global interest points and boundaries
        elif r < (self.cfg["prob_magic"] + self.cfg["prob_boundary"]):
            val = random.choice(self.cfg["interest_points"] + list(global_points))

        # Strategy 3: Bit pattern testing
        elif r < (self.cfg["prob_magic"] + self.cfg["prob_boundary"] + self.cfg["prob_bit_pattern"]):
            val = random.choice(self.power_of_two)

        # Strategy 4: Pure random within range (fallback)
        else:
            if limits["type"] == int:
                val = random.randint(limits["min"], limits["max"])
            else:
                val = random.uniform(self.cfg["real_range"][0], self.cfg["real_range"][1])

        # Clamp to type limits
        final_val = max(limits["min"], min(limits["max"], val))
        return int(final_val) if limits["type"] == int else round(final_val, 4)

    def generate_case(
        self,
        st_code: str,
        schema_v2: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a single-cycle test case.

        Args:
            st_code: ST source code for static analysis
            schema_v2: Input schema dict with:
                - columns: List of column names
                - metadata: Dict mapping column names to type info

        Returns:
            Dict mapping column names to generated values, or None on failure
        """
        # Set timeout alarm (Unix only)
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(self.cfg["timeout_sec"])

        try:
            columns = schema_v2["columns"]
            metadata = schema_v2["metadata"]

            # Step 1: Static analysis for thresholds
            var_thresholds, global_points = self._extract_logic_thresholds(st_code)

            # Step 2: Build single-cycle payload
            payload: Dict[str, Any] = {}
            for col in columns:
                meta = metadata[col]
                iec_type = meta.get("iec_type", "INT")
                st_bind = meta.get("st_binding", "").lower()

                # Generate value for this column
                payload[col] = self._weighted_sample(
                    iec_type,
                    var_thresholds.get(st_bind, set()),
                    global_points
                )

            signal.alarm(0)  # Clear alarm
            return payload

        except TimeoutException:
            print(f"[Timeout] Case generation exceeded {self.cfg['timeout_sec']}s")
            return None
        except Exception as e:
            print(f"[Error] Random Generation failed: {str(e)}")
            signal.alarm(0)
            return None

    def generate_batch(
        self,
        st_code: str,
        schema_v2: Dict[str, Any],
        batch_size: int
    ) -> List[Dict[str, Any]]:
        """
        Generate multiple test cases in batch.

        Args:
            st_code: ST source code
            schema_v2: Input schema dict
            batch_size: Number of cases to generate

        Returns:
            List of generated payload dicts (may contain None values)
        """
        return [self.generate_case(st_code, schema_v2) for _ in range(batch_size)]


__all__ = [
    "RandomCaseGenerator",
    "IEC_TYPE_LIMITS",
    "TimeoutException",
]
