"""
PLCHaT Output Parser

Parses and structures execution output from PLC programs.
Supports multiple output formats and extracts cycle-by-cycle state.

Key features:
- Parse stdout into structured cycle data
- Extract variable states per cycle
- Support multiple harness output formats
"""

import re
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field

from harness.compiler.utils import Logger, LEVEL
from core.data_types import STExecutionResult, StoredTestCase, ExpUnifiedIR


@dataclass
class CycleState:
    """Structured representation of a single PLC cycle state."""
    cycle_number: int
    variables: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None


@dataclass
class StructuredExecutionResult:
    """Structured execution result with parsed cycle data."""
    status: str
    return_code: int
    total_cycles: int = 0
    cycles: List[CycleState] = field(default_factory=list)
    final_state: Dict[str, Any] = field(default_factory=dict)
    raw_output: str = ""
    error_message: Optional[str] = None


class OutputParser:
    """
    Parser for PLC execution output.

    Handles various harness output formats:
    - Standard format: "--- Cycle N ---"
    - Key-value pairs: "VAR: value"
    - Array formats: "ARRAY: [v1, v2, ...]"
    """

    def __init__(self, logger: Optional[Logger] = None):
        self.logger = logger or Logger("/tmp/plchat", "output_parser.log", level=LEVEL.WARNING)

    def parse_execution_output(
        self,
        stdout: str,
        stderr: str = "",
        return_code: int = 0
    ) -> StructuredExecutionResult:
        """
        Parse raw execution output into structured result.

        Args:
            stdout: Standard output from execution
            stderr: Standard error from execution
            return_code: Process return code

        Returns:
            StructuredExecutionResult with parsed cycle data
        """
        result = StructuredExecutionResult(
            status="success" if return_code == 0 else "error",
            return_code=return_code,
            raw_output=stdout
        )

        if return_code != 0:
            result.error_message = stderr if stderr else "Execution failed"
            return result

        # Parse cycles from stdout
        cycles = self._extract_cycles(stdout)
        result.cycles = cycles
        result.total_cycles = len(cycles)

        # Extract final state
        if cycles:
            result.final_state = cycles[-1].outputs

        return result

    def _extract_cycles(self, output: str) -> List[CycleState]:
        """Extract cycle data from output string."""
        cycles = []

        # Split by cycle markers
        # Format: "--- Cycle N ---"
        cycle_pattern = r'---\s*Cycle\s+(\d+)\s*---'
        parts = re.split(cycle_pattern, output)

        # parts[0] is before first cycle, parts[1] is first cycle number, etc.
        for i in range(1, len(parts), 2):
            if i + 1 < len(parts):
                cycle_num = int(parts[i])
                cycle_content = parts[i + 1]
                cycle_state = self._parse_cycle_content(cycle_num, cycle_content)
                cycles.append(cycle_state)

        return cycles

    def _parse_cycle_content(self, cycle_num: int, content: str) -> CycleState:
        """Parse content of a single cycle."""
        cycle = CycleState(cycle_number=cycle_num)

        lines = content.strip().split('\n')
        for line in lines:
            line = line.strip()
            if not line or line.startswith('---'):
                continue

            # Parse key-value pairs
            # Format: "KEY: value" or "KEY: value, value2, ..."
            if ':' in line:
                key, value = line.split(':', 1)
                key = key.strip()
                value = value.strip()

                # Handle array format: "ARRAY: [v1, v2, ...]"
                if value.startswith('[') and value.endswith(']'):
                    array_value = self._parse_array(value)
                    cycle.outputs[key] = array_value
                else:
                    # Handle scalar values
                    cycle.outputs[key] = self._parse_scalar(value)

        return cycle

    def _parse_array(self, value_str: str) -> List[Any]:
        """Parse array value string."""
        # Remove brackets and split
        content = value_str.strip('[]')
        if not content:
            return []

        items = [item.strip() for item in content.split(',')]
        result = []
        for item in items:
            result.append(self._parse_scalar(item))
        return result

    def _parse_scalar(self, value_str: str) -> Any:
        """Parse scalar value string."""
        value_str = value_str.strip()

        # Try integer
        try:
            return int(value_str)
        except ValueError:
            pass

        # Try float
        try:
            return float(value_str)
        except ValueError:
            pass

        # Return as string
        return value_str

    def extract_variable_timeline(
        self,
        structured_result: StructuredExecutionResult,
        variable_name: str
    ) -> List[Tuple[int, Any]]:
        """
        Extract timeline of a specific variable across all cycles.

        Args:
            structured_result: Parsed execution result
            variable_name: Name of variable to track

        Returns:
            List of (cycle_number, value) tuples
        """
        timeline = []
        for cycle in structured_result.cycles:
            if variable_name in cycle.outputs:
                timeline.append((cycle.cycle_number, cycle.outputs[variable_name]))
        return timeline

    def compare_cycles(
        self,
        cycle1: CycleState,
        cycle2: CycleState
    ) -> Dict[str, Tuple[Any, Any]]:
        """
        Compare two cycles and find differences.

        Returns:
            Dict mapping variable names to (value_in_cycle1, value_in_cycle2)
        """
        differences = {}

        all_vars = set(cycle1.outputs.keys()) | set(cycle2.outputs.keys())
        for var in all_vars:
            val1 = cycle1.outputs.get(var)
            val2 = cycle2.outputs.get(var)
            if val1 != val2:
                differences[var] = (val1, val2)

        return differences


def convert_stored_test_case_to_exp_unified_ir(
    test_case: StoredTestCase,
    schema_path: str,
    target_st_path: str
) -> Optional['ExpUnifiedIR']:
    """
    Convert StoredTestCase to ExpUnifiedIR format.

    This is a placeholder for the full conversion logic.
    """
    # Implementation would go here
    pass
