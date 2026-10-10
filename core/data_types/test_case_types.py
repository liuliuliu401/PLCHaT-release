"""
PLCHaT Test Case Types
Data structures for PLC test cases and execution traces.

Migrated from: LLM-PLC-FuzzGen/FuzzGen/core/test_case_types.py
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Union
from enum import Enum

from core.data_types.base_types import BaseType


class StoredTestCaseType(str, Enum):
    """Enumeration for different types of stored test cases."""
    UNIT_FUNCTION = "UNIT_FUNCTION"
    IO_PAIR = "IO_PAIR"


# ---------------------- Dataclasses and Enums ----------------------

@dataclass
class PLCVarState:
    """A snapshot of PLC variables grouped by section."""
    VAR_INPUT: Dict[str, Any] = field(default_factory=dict)
    VAR_OUTPUT: Dict[str, Any] = field(default_factory=dict)
    VAR_INTERNAL: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PLCCycle:
    """A single PLC cycle with before/after snapshots."""
    cycle: int
    before_execution: PLCVarState = field(default_factory=PLCVarState)
    after_execution: PLCVarState = field(default_factory=PLCVarState)


@dataclass
class PLCParsedTestCaseSummary:
    """Summary for a single parsed test case."""
    total_cycles: int = 0
    final_state: PLCVarState = field(default_factory=PLCVarState)


# ----------------------- Main Classes ----------------------

@dataclass
class PLCTestCase:
    """
    The execution-oriented representation of a test case.

    This dataclass holds the full, cycle-by-cycle execution trace and
    is a direct output of the PLC simulator. It is not designed to be
    created manually for a test plan.
    """
    test_case_name: str
    cycles: List[PLCCycle] = field(default_factory=list)
    summary: PLCParsedTestCaseSummary = field(default_factory=PLCParsedTestCaseSummary)


@dataclass
class IOPair(BaseType):
    """
    Represents a single step in a multi-round I/O pair test.
    """
    round: int
    inputs: Dict[str, Any]
    expected_outputs: Dict[str, Any]
    notes: Optional[List[str]] = field(default_factory=list)
    force_vars: Dict[str, Any] = field(default_factory=dict)
