"""
PLCHaT Execution and Coverage Types
Data structures for execution results and coverage analysis.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal, Set
from datetime import datetime
from enum import Enum

from core.data_types.base_types import BaseType, InitialState
from core.data_types.test_case_types import PLCTestCase, PLCVarState, PLCCycle

ExecutionStatus = Literal[
    "success",
    "failed",
    "error",
    "timeout",
    "compilation_failed",
    "build_failed",
    "execution_failed",
    "coverage_failed",
    "partial_success"
]


# ---------------------- Execution & Validation ----------------------

@dataclass
class ValidationResult(BaseType):
    """
    Validation is process before execution. The validation result on if structures syntax is correct or not by Rusty compiler.
    If the syntax is incorrect, try to fix it and not recommended to proceed.
    """
    status: Literal["success", "failed", "timeout", "error"]
    return_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    result_file: Optional[str] = None
    message: Optional[str] = None
    details: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ValidationResult":
        """Convert st_compile_old.py dict format to structured dataclass."""
        return cls(
            status=d.get("status", "error"),
            return_code=d.get("return_code"),
            stdout=d.get("stdout", ""),
            stderr=d.get("stderr", ""),
            result_file=d.get("result_file"),
            message=d.get("message"),
            details=d.get("details")
        )


@dataclass
class ExecutionSummary(BaseType):
    """Simple execution summary statistics message, not including detailed info."""
    total_test_cases: int = 0
    total_cycles: int = 0
    expected_executions: int = 0  # From "Expected total executions:" parsing
    input_count: int = 0          # From "Input files count:" parsing
    state_count: int = 0          # From "State files count:" parsing


@dataclass
class STExecutionResult(BaseType):
    """
    Matches st_compile_old.py._parse_execution_output() return structure exactly.
    This is the primary return type for execute_st_code() and related methods.

    Conversions (lossy):
    - to_plc_var_state(test_case_index=0, cycle_index=-1): extract the specified cycle's after_execution state.
    - to_initial_state(test_case_index=0, cycle_index=-1): reduce the extracted PLCVarState to InitialState (drops VAR_INPUT) and add provenance metadata.
    """
    status: ExecutionStatus
    return_code: int = 0
    message: Optional[str] = None
    execution_summary: ExecutionSummary = field(default_factory=ExecutionSummary)
    test_cases: List[PLCTestCase] = field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""

    def _pick_cycle(self, test_case_index: int = 0, cycle_index: int = -1) -> Optional["PLCCycle"]:
        try:
            if not self.test_cases:
                return None
            tc = self.test_cases[test_case_index]
            if not tc.cycles:
                return None
            # Normalize negative index (default -1 → last cycle)
            if cycle_index < 0:
                cycle_index = len(tc.cycles) + cycle_index
            if cycle_index < 0 or cycle_index >= len(tc.cycles):
                cycle_index = len(tc.cycles) - 1
            return tc.cycles[cycle_index]
        except Exception:
            return None

    def to_plc_var_state(self, test_case_index: int = 0, cycle_index: int = -1) -> Optional[PLCVarState]:
        c = self._pick_cycle(test_case_index, cycle_index)
        return c.after_execution if c else None

    def to_initial_state(self, test_case_index: int = 0, cycle_index: int = -1) -> Optional["InitialState"]:
        c = self._pick_cycle(test_case_index, cycle_index)
        if not c:
            return None
        state = c.after_execution
        return InitialState(
            VAR_OUTPUT=dict(state.VAR_OUTPUT),
            VAR_INTERNAL=dict(state.VAR_INTERNAL),
            metadata={
                "description": f"Extracted from test case {test_case_index}, cycle {c.cycle}",
                "source_test_case": self.test_cases[test_case_index].test_case_name if self.test_cases else None,
                "source_cycle": c.cycle,
                "lossy": True,
                "source": "STExecutionResult",
            },
        )

    def to_simple(self, test_case_index: int = 0, cycle_index: int = -1) -> Optional["InitialState"]:
        return self.to_initial_state(test_case_index, cycle_index)


# ---------------------- Coverage ----------------------

@dataclass
class CoverageData:
    stmts: float = 0.0
    branches: float = 0.0
    paths: float = 0.0
    custom: Dict[str, float] = field(default_factory=dict)


@dataclass
class CoverageBreakdown(BaseType):
    """
    Matches st_compile_old.py._parse_coverage_summary() parsing logic.
    Handles the complex TOTAL line parsing with percentages and counts.
    """
    percentage: Optional[str] = None  # e.g., "75.0%" - directly from coverage summary
    total: Optional[int] = None       # Total items (lines/functions/branches/regions)
    missed: Optional[int] = None      # Missed items
    covered: Optional[int] = None     # Covered items (calculated as total - missed)
    error: Optional[str] = None       # Parse error if any


@dataclass
class CoverageSummary(BaseType):
    """
    Matches st_compile_old.py._parse_coverage_summary() return structure.
    Supports all 4 coverage types parsed from gcov/llvm-cov TOTAL line.
    """
    line_coverage: CoverageBreakdown = field(default_factory=CoverageBreakdown)
    function_coverage: CoverageBreakdown = field(default_factory=CoverageBreakdown)
    branch_coverage: CoverageBreakdown = field(default_factory=CoverageBreakdown)
    region_coverage: CoverageBreakdown = field(default_factory=CoverageBreakdown)
    error: Optional[str] = None


@dataclass
class CoverageReport(BaseType):
    """
    Matches st_compile_old.py._extract_coverage_results() return structure exactly.
    This is what gets stored in coverage_data field of execution results.
    """
    case_name: str
    coverage_available: bool = False
    coverage_summary: Optional[CoverageSummary] = None  # From _parse_coverage_summary()
    coverage_files: List[str] = field(default_factory=list)  # From _list_coverage_files()
    error: Optional[str] = None
    merge_info: Optional[Dict[str, Any]] = None  # For incremental coverage merges


@dataclass
class CoverageRunResult(BaseType):
    """
    Return type for coverage execution methods in st_compile_old.py.
    Used by execute_st_code_with_coverage() and execute_st_code_with_incremental_coverage().
    """
    status: ExecutionStatus
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""
    coverage_data: Optional[CoverageReport] = None
    incremental: Optional[bool] = None  # True for incremental coverage mode
    # Future enhancement: link back to parsed execution results
    execution_result: Optional[STExecutionResult] = None


@dataclass
class CoverageRecord(BaseType):
    run_id: str
    test_id: str
    function: str
    lines_total: int
    lines_covered: int
    branches_total: int
    branches_covered: int
    delta_lines_covered: int
    delta_branches_covered: int
    runtime_ms: float
    evaluated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class UncoveredUnit(BaseType):
    run_id: str
    project: str
    module: str
    function: str
    missing_lines: List[int] = field(default_factory=list)
    missing_branches: List[str] = field(default_factory=list)
    predicates: List[str] = field(default_factory=list)
    identified_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------- Docker Resources/Results ----------------------

@dataclass
class ResourceQuota(BaseType):
    """Used within DockerResourceStatus for tracking Docker resource limits."""
    count: int
    limit: int


@dataclass
class DockerResourceStatus(BaseType):
    """
    Matches st_compile_old.py.get_docker_resource_status() return structure exactly.
    """
    images: Optional[ResourceQuota] = None
    containers: Optional[ResourceQuota] = None
    rusty_available: bool = False
    error: Optional[str] = None


@dataclass
class DockerCmdResult(BaseType):
    """
    REDESIGNED to match st_compile_old.py Docker execution methods exactly.

    Used by _run_docker_execution() and _run_docker_coverage_execution().
    """
    status: ExecutionStatus  # Changed from limited Literal to full ExecutionStatus
    return_code: int
    stdout: str = ""
    stderr: str = ""
    message: Optional[str] = None
    # NOTE: coverage_data is handled separately in CoverageRunResult


# ---------------------- Incremental Simulation ----------------------

@dataclass
class IncrementalSummary(BaseType):
    """
    Matches st_compile_old.py.execute_incremental_simulation() summary structure.
    """
    total_rounds: int = 0
    successful_rounds: int = 0
    total_test_cases: int = 0      # Sum across all rounds
    total_cycles: int = 0          # Sum across all rounds
    cycles_per_round: int = 0      # Expected cycles per round
    state_continuity: bool = False # Whether state was carried between rounds


@dataclass
class IncrementalSimulationResult(BaseType):
    """
    Matches st_compile_old.py.execute_incremental_simulation() return structure exactly.
    """
    status: ExecutionStatus
    rounds: List[STExecutionResult] = field(default_factory=list)  # Results from each round
    final_state: Optional["InitialState"] = None    # Final state for potential continuation
    summary: IncrementalSummary = field(default_factory=IncrementalSummary)
    message: Optional[str] = None
