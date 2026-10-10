"""
PLCHaT ST Types
Core data structures for ST program testing and stored test cases.
"""

from dataclasses import dataclass, asdict, is_dataclass, field
from typing import List, Dict, Any, Optional, Literal, Set, Union
from datetime import datetime
from enum import Enum
import uuid
import json
import os

from core.data_types.base_types import BaseType
from core.data_types.test_case_types import StoredTestCaseType, PLCVarState, PLCCycle, PLCParsedTestCaseSummary, PLCTestCase, IOPair
from core.data_types.execution_coverage import STExecutionResult, CoverageData, InitialState
from core.data_types.plan_types import PlanPayload


# ==================== Note on ExpUnifiedIR ====================
# ExpUnifiedIR is defined in core/exp_types.py to maintain modularity.
# It can be imported from there when needed.
# from core.exp_types import ExpUnifiedIR


# ---------------------------- Planning ----------------------------
@dataclass
class Plan(BaseType):
    """
    Represents a plan with a goal, target execution strategy, and notes.

    Attributes:
        goal (str): The main objective or purpose of the plan.
        target_execution_strategy (List[str]): A list of specific, executable strategies describing the path to achieve the goal.
        target_branch (Optional[str]): The name of the branch in a version control system (e.g., Git)
                    that this plan is intended to affect or operate on.
        notes (Optional[str]): Additional notes, comments, or context about the plan.
        target_type (Optional[str]): [Legacy Compat] Bridges the gap with newer PlanPayload.
        target_details (Optional[str]): [Legacy Compat] Detailed context for the target type.
    """
    goal: str
    target_execution_strategy: List[str]
    notes: Optional[str] = None
    target_branch: Optional[str] = None
    # [Fix] Add backward compatibility fields to prevent old deserializers from throwing unexpected keyword argument
    target_type: Optional[str] = None
    target_details: Optional[str] = None
    # [Fix-Agent] Fully compatible with all new fields of PlanPayload
    action_routing: Optional[Any] = None
    diagnosis: Optional[Any] = None
    intent: Optional[Any] = None
    diagnostic_notes: Optional[str] = None

    def to_dict(self):
        """Convert Plan instance to a dictionary for JSON serialization."""
        result = asdict(self)
        # Handle datetime serialization if any
        for key, value in result.items():
            if isinstance(value, datetime):
                result[key] = value.isoformat()

        return result


# -------------------- Config and State: for Logging --------------------
@dataclass
class LoopConfig(BaseType):
    outputs_dir: str = "outputs"
    # When provided, all outputs will be written to: <repo_root>/output/{tag}/...
    tag: Optional[str] = None
    max_iterations: int = 10
    stagnation_rounds: int = 3
    window_size: int = 5
    generator_num_cases: int = 2
    seed_cases: Optional[List[Dict[str, Any]]] = None  # JSON-style seeds (st_code_path, io_pairs, ...)


@dataclass
class LoopState(BaseType):
    iteration: int = 0
    global_covered_ids: Set[str] = field(default_factory=set)
    recent_covered_snapshots: List[Set[str]] = field(default_factory=list)
    no_progress_rounds: int = 0


# ---------------------- StoredTestCase: absolute top-level class ----------------------
@dataclass
class StoredTestCase(BaseType):
    """
    StoredTestCase is designed as an absolute top-level class to store test cases, including sources, target code,
    test case itself, execution result and **single** coverage.
    (Single coverage means it only stores the coverage from one execution of this test case.
    It does NOT accumulate coverage over multiple test case executions.)
    Design:
    1. current test case metadata: id, project, module, function, test_type, st_code_content, created timestamp
    2. original st code info: st_code_path, benchmark_dir
    3. test case content: io_pairs (list of IOPair), test_notes
    4. execution and coverage results(optional): execution_result (STExecutionResult), coverage (CoverageData)
    Usage:
    It is NOT used for execution. Use PLCTestCase for execution purposes.
    StoredTestCase is meant to be easily serializable to/from JSON and text formats,
    and to be stored in databases or files.  It holds metadata about the test case, its origin,
    and a list of IOPairs representing the test inputs and expected outputs.

    # TODO: Add a method to directly explain StoredTestCase in natural language using LLM.
    """
    # --- Required fields declared first ---
    project: str
    module: str
    function: str
    st_path: str
    st_code_content: str

    # --- All optional fields with default values come after ---
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    test_type: StoredTestCaseType = StoredTestCaseType.IO_PAIR
    benchmark_dir: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    requirement: Optional[str] = None
    io_pairs: List[IOPair] = field(default_factory=list)
    test_notes: List[str] = field(default_factory=list)
    plan: Optional[Plan] = None
    execution_result: Optional[STExecutionResult] = None
    coverage: Optional[CoverageData] = None

    def __post_init__(self):
        """Load code content from st_path if not provided."""
        if self.st_code_content is None:
            try:
                # Note: This function needs to be implemented or replaced
                # self.st_code_content = _load_plc_code(self.st_path)
                self.st_code_content = ""
            except Exception:
                self.st_code_content = ""

    def _to_plc_test_case(self) -> "PLCTestCase":
        """Internal method: Converts this StoredTestCase to a PLCTestCase (lossy, no cycles)."""
        name = self.id or self.function or f"{self.module}.{self.function}"
        return PLCTestCase(
            test_case_name=name,
            cycles=[],
            summary=PLCParsedTestCaseSummary(total_cycles=0, final_state=PLCVarState()),
        )

    def _to_json(self, include_metadata: bool = True, as_string: bool = False, indent: int = 2) -> Union[Dict[str, Any], str]:
        """Internal method: Converts this StoredTestCase to a JSON-ready dict or string."""
        if self.io_pairs:
            io_pairs_data = [asdict(io) for io in self.io_pairs]
        else:
            io_pairs_data = []
            if self.st_code_content:
                try:
                    parsed = json.loads(self.st_code_content)
                    for pair in parsed if isinstance(parsed, list) else []:
                        io_pairs_data.append({
                            "round": pair.get("round", 0),
                            "inputs": pair.get("inputs", {}),
                            "expected_outputs": pair.get("expected_outputs", {}),
                            "notes": pair.get("notes", []),
                            "force_vars": pair.get("force_vars", {}),
                        })
                except Exception:
                    io_pairs_data = []

        data: Dict[str, Any] = {
            "st_code_path": self.st_path,
            "benchmark_dir": self.benchmark_dir,
            "test_notes": self.test_notes or [],
            "io_pairs": io_pairs_data,
        }

        if include_metadata:
            data.update({
                "id": self.id,
                "project": self.project,
                "module": self.module,
                "function": self.function,
                "tags": list(self.tags) if self.tags else [],
                "test_type": self.test_type.value,
                "created_at": self.created_at,
            })

        return json.dumps(data, indent=indent) if as_string else data

    def _to_txt(self, input_order: Optional[List[str]] = None, array_format: str = "python") -> str:
        """Internal method: Converts this StoredTestCase to PLC test input .txt format."""
        if not self.io_pairs or len(self.io_pairs) == 0:
            return ""
        if input_order is None:
            input_order = list(self.io_pairs[0].inputs.keys())
        lines = []
        for pair in self.io_pairs:
            vals = []
            for k in input_order:
                v = pair.inputs.get(k, 0)
                if isinstance(v, list):
                    if array_format == "python":
                        vals.append(str(v))
                    else:
                        vals.extend(str(x) for x in v)
                else:
                    vals.append(str(v))
            lines.append(" ".join(vals))
        return "\n".join(lines)

    @staticmethod
    def _from_io_pairs(io_pairs: List["IOPair"], st_code_path: str, **kwargs) -> "StoredTestCase":
        """Internal static method: create StoredTestCase from io_pairs."""
        stored_test_case = StoredTestCase(
            id=kwargs.get("id", str(uuid.uuid4())),
            project=kwargs.get("project", "UnknownProject"),
            module=kwargs.get("module", "UnknownModule"),
            function=kwargs.get("function", "UnknownFunction"),
            st_path=st_code_path,
            benchmark_dir=kwargs.get("benchmark_dir", ""),
            test_type=StoredTestCaseType.IO_PAIR,
            st_code_content=json.dumps([asdict(io) for io in io_pairs], indent=2),
            io_pairs=io_pairs,
            test_notes=kwargs.get("test_notes", []),
            tags=kwargs.get("tags", []),
        )
        stored_test_case.__post_init__()
        return stored_test_case

    @staticmethod
    def _from_json(json_data: Dict[str, Any]) -> "StoredTestCase":
        # 1. Map st_code_path → st_path
        st_path = json_data.get("st_code_path", "unknown_path")

        # 2. Reconstruct st_code_content
        io_pairs_raw = json_data.get("io_pairs", [])
        if io_pairs_raw:
            try:
                st_code_content = json.dumps(io_pairs_raw, indent=2)
            except Exception:
                st_code_content = ""
        else:
            st_code_content = ""

        # 3. Inject required fields into json_data
        json_data["st_path"] = st_path
        json_data["st_code_content"] = st_code_content

        # 4. Infer missing metadata if needed
        json_data.setdefault("project", st_path.split('/')[-3] if len(st_path.split('/')) > 2 else "UnknownProject")
        json_data.setdefault("module", st_path.split('/')[-2] if len(st_path.split('/')) > 1 else "UnknownModule")
        json_data.setdefault("function", os.path.basename(st_path).replace('.st', '') if st_path else "UnknownFunction")

        # 5. Remove incompatible keys (e.g., st_code_path is not a field)
        json_data.pop("st_code_path", None)

        # 6. Delegate to _from_dict (which calls cls(**...))
        return StoredTestCase._from_dict(json_data)

    def _from_plc_test_case(self, plc_test_case: PLCTestCase, st_code_path: str,
                            project: str = "UnknownProject", module: str = "UnknownModule", function: str = "UnknownFunction") -> "StoredTestCase":
        """Internal method: Converts this PLCTestCase to a new StoredTestCase (lossy, single round)."""
        final_cycle = plc_test_case.cycles[-1] if plc_test_case.cycles else None

        io_pair = IOPair(
            round=1,
            inputs=final_cycle.after_execution.VAR_OUTPUT if final_cycle else {},
            expected_outputs={},
            notes=["Generated from a previous execution trace."]
        )

        return self._from_io_pairs(
            io_pairs=[io_pair],
            st_code_path=st_code_path,
            id=f"fuzz_gen_{datetime.utcnow().timestamp()}",
            project=project,
            module=module,
            function=function,
            test_notes=[
                f"Generated from execution trace for '{plc_test_case.test_case_name}'."
            ]
        )


class PLCFullTestResult(BaseType):
    stored_test_cases: List[StoredTestCase]
    full_coverage_data: CoverageData        # The coverage for the combination of all test cases:
                                            # the single coverage is stored in stored_test_case.coverage


# POU definition

# ---------------------- Helper Functions (Public Interface) ----------------------
# These functions act as a stable public interface for older code,
# delegating to the new internal class methods.

def create_stored_io_test_case(io_pairs: List[IOPair], st_code_path: str, **kwargs) -> StoredTestCase:
    """
    Converts a structured list of IOPair objects into a StoredTestCase.
    WARNING: Prefer using StoredTestCase._from_io_pairs() for new code.
    """
    return StoredTestCase._from_io_pairs(io_pairs, st_code_path, **kwargs)


def create_stored_test_case_from_json(json_data: Dict[str, Any]) -> StoredTestCase:
    """
    Fulfills an incomplete JSON dictionary into a full StoredTestCase object.
    WARNING: Prefer using StoredTestCase._from_json() for new code.
    """
    return StoredTestCase._from_json(json_data)


def stored_to_plc_test_case(st: "StoredTestCase") -> PLCTestCase:
    """
    Converts a minimal `StoredTestCase` placeholder into an execution-ready `PLCTestCase`.
    WARNING: Prefer using StoredTestCase._to_plc_test_case() for new code.
    """
    return st._to_plc_test_case()


def plc_to_stored_test_case(
    plc: PLCTestCase,
    test_type: StoredTestCaseType,
    st_code_path: str,
    project: str = "UnknownProject",
    module: str = "UnknownModule",
    function: str = "UnknownFunction",
) -> StoredTestCase:
    """
    Converts a runtime `PLCTestCase` into a new, single-round `StoredTestCase`.
    WARNING: Prefer using PLCTestCase._to_stored_test_case() for new code.
    """
    return plc._to_stored_test_case(test_type, st_code_path, project, module, function)


def stored_test_case_to_json(
    st: StoredTestCase,
    include_metadata: bool = True,
    as_string: bool = False,
    indent: int = 2,
) -> Union[Dict[str, Any], str]:
    """
    Convert a StoredTestCase into a JSON-ready dict or JSON string.
    WARNING: Prefer using StoredTestCase._to_json() for new code.
    """
    return st._to_json(include_metadata=include_metadata, as_string=as_string, indent=indent)


def stored_test_case_to_txt(
    st: StoredTestCase,
    input_order: Optional[List[str]] = None,
    array_format: str = "python",
) -> str:
    """
    Convert a StoredTestCase (IO_PAIR) into PLC test input .txt format.
    WARNING: Prefer using StoredTestCase._to_txt() for new code.
    """
    return st._to_txt(input_order=input_order, array_format=array_format)
