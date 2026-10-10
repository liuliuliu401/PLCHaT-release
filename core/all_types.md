# PLCHaT Core Types Complete Inventory

**Created:** 2026-05-29
**Last updated:** 2026-05-29
**Purpose:** Documents all core data contracts and communication protocols

---

## Table of Contents

1. [Type Overview](#type-overview)
2. [Base Types Layer (base_types.py)](#base-types-layer-basetypespy)
3. [Test Case Types (test_case_types.py)](#test-case-types-test_case_typespy)
4. [IR Types (ir_types.py)](#ir-types-irtypespy)
5. [Execution & Coverage Types (execution_coverage.py)](#execution--coverage-types-execution_coveragepy)
6. [Plan Types (plan_types.py)](#plan-types-plan_typespy)
7. [ST Types (st_types.py)](#st-types-st_typespy)
8. [Experiment Unified IR (exp_types.py)](#experiment-unified-ir-exp_typespy)
9. [Evaluation Types (eval_types.py)](#evaluation-types-eval_typespy)
10. [Agent-Harness Communication Protocol (protocols/)](#agent-harness-communication-protocol-protocols)
11. [Type Dependency Graph](#type-dependency-graph)
12. [Compatibility Migration Plan](#compatibility-migration-plan)

---

## Type Overview

### By Status

| Status | Types | Notes |
|------|------|------|
| ✅ Core | BaseType, ExpUnifiedIR, PlanPayload, STExecutionResult, EvaluationReport | Actively maintained, recommended |
| ✅ In Use | All execution, coverage, and plan-related types | Stable usage |
| ⚠️ Legacy | StoredTestCase, IOPair | Kept for compatibility, migration planned |
| 🆕 New | protocols/* | Agent-Harness communication protocol |

### By File

| File | # Classes | Main Types |
|------|--------|----------|
| base_types.py | 5 | BaseType, TestStep, OracleViolation, AnalysisReport, InitialState |
| test_case_types.py | 6 | StoredTestCaseType, PLCVarState, PLCCycle, PLCParsedTestCaseSummary, PLCTestCase, IOPair |
| ir_types.py | 2 | STVariableDecl, STPOUIR |
| execution_coverage.py | 15 | STExecutionResult, CoverageData, ValidationResult, etc. |
| plan_types.py | 13 | PlanPayload, ExecutionStrategy, VerificationPlanGraph, etc. |
| st_types.py | 7 | StoredTestCase, Plan, LoopConfig, PLCFullTestResult, etc. |
| exp_types.py | 1 | ExpUnifiedIR |
| eval_types.py | 1 | EvaluationReport |
| protocols/action_protocol.py | 7 | ActionType, ToolCallRequest, ExecuteRequest, etc. |
| protocols/feedback_protocol.py | 6 | ActionResponse, ExecutionResult, GenerationResult, etc. |

---

## Base Types Layer (base_types.py)

### BaseType
**Status:** ✅ Core base class

```python
class BaseType:
    def _to_dict() -> Dict[str, Any]      # serialize
    def _from_dict(data: Dict) -> Self    # deserialize
    def get_value(key: str) -> Any
    def set_value(key: str, value: Any)
    def update_with_dict(data: Dict)
    def delete_value(key: str)
```

**Purpose:** Base class for all data classes that need serialization

**Subclass count:** 20+ (OracleViolation, AnalysisReport, STExecutionResult, etc.)

---

### TestStep
**Status:** ✅ In use

```python
@dataclass
class TestStep:
    inputs: Dict[str, Any]
    duration: int = 1
    force_vars: Dict[str, Any] = field(default_factory=dict)
```

**Purpose:** Single-step test input definition

---

### OracleViolation
**Status:** ✅ In use

```python
@dataclass
class OracleViolation(BaseType):
    test_item_id: str
    name: str
    severity: Literal["low", "medium", "high", "critical"]
    reason: str
    evidence: Dict[str, Any]
```

**Purpose:** Oracle violation record

---

### AnalysisReport
**Status:** ✅ In use

```python
@dataclass
class AnalysisReport(BaseType):
    is_interesting: bool
    vulnerability_type: str
    details: str
    coverage_gain: Dict[str, float]
    oracle_violations: List[OracleViolation]
    suggestions: List[str]
```

**Purpose:** Analysis report aggregate

---

### InitialState
**Status:** ✅ In use

```python
@dataclass
class InitialState(BaseType):
    VAR_OUTPUT: Dict[str, Any] = field(default_factory=dict)
    VAR_INTERNAL: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_initial_state() -> "InitialState"
    def to_simple() -> "InitialState"
```

**Purpose:** State persistence for incremental simulation

**Note:** VAR_INPUT is not persisted (design decision)

---

## Test Case Types (test_case_types.py)

### StoredTestCaseType (Enum)
**Status:** ✅ In use

```python
class StoredTestCaseType(str, Enum):
    UNIT_FUNCTION = "UNIT_FUNCTION"
    IO_PAIR = "IO_PAIR"
```

---

### PLCVarState
**Status:** ✅ In use

```python
@dataclass
class PLCVarState:
    VAR_INPUT: Dict[str, Any] = field(default_factory=dict)
    VAR_OUTPUT: Dict[str, Any] = field(default_factory=dict)
    VAR_INTERNAL: Dict[str, Any] = field(default_factory=dict)
```

**Purpose:** PLC variable snapshot

---

### PLCCycle
**Status:** ✅ In use

```python
@dataclass
class PLCCycle:
    cycle: int
    before_execution: PLCVarState = field(default_factory=PLCVarState)
    after_execution: PLCVarState = field(default_factory=PLCVarState)
```

**Purpose:** Single scan-cycle record

---

### PLCParsedTestCaseSummary
**Status:** ✅ In use

```python
@dataclass
class PLCParsedTestCaseSummary:
    total_cycles: int = 0
    final_state: PLCVarState = field(default_factory=PLCVarState)
```

**Purpose:** Test case execution summary

---

### PLCTestCase
**Status:** ✅ In use

```python
@dataclass
class PLCTestCase:
    test_case_name: str
    cycles: List[PLCCycle] = field(default_factory=list)
    summary: PLCParsedTestCaseSummary = field(default_factory=PLCParsedTestCaseSummary)
```

**Purpose:** Execution-oriented test case representation (full cycle tracking)

**Note:** Not intended for manual creation; used for simulator output

---

### IOPair ⚠️
**Status:** ⚠️ Legacy - functionality overlaps with ExpUnifiedIR

```python
@dataclass
class IOPair(BaseType):
    round: int
    inputs: Dict[str, Any]
    expected_outputs: Dict[str, Any]
    notes: Optional[List[str]] = field(default_factory=list)
    force_vars: Dict[str, Any] = field(default_factory=dict)
```

**Purpose:** Single-step IO pair

**Compatibility plan:**
- Current: keep for backward compatibility
- Future: consider gradual migration to the ExpUnifiedIR.sparse_timeline format
- Priority: medium (non-blocking migration)

---

## IR Types (ir_types.py)

### STVariableDecl
**Status:** ✅ In use

```python
@dataclass
class STVariableDecl(BaseType):
    name: str
    st_type: str
    scope: str  # "VAR_INPUT", "VAR_OUTPUT", "VAR", "VAR_IN_OUT", "VAR_GLOBAL"
    py_default_value: Any
    py_size: int = 1
    st_array_bounds: Optional[tuple] = None
```

**Purpose:** ST variable declaration IR

---

### STPOUIR
**Status:** ✅ In use (but rarely used in practice)

```python
@dataclass
class STPOUIR(BaseType):
    name: str
    declarations: List[STVariableDecl] = field(default_factory=list)
    inputs: List[STVariableDecl] = field(default_factory=list)
    outputs: List[STVariableDecl] = field(default_factory=list)
    internals: List[STVariableDecl] = field(default_factory=list)
    py_logic_code: List[str] = field(default_factory=list)
```

**Purpose:** POU (Program Organization Unit) IR

**Note:** Mainly used in parsing scenarios; uncommon in the core testing flow

---

## Execution & Coverage Types (execution_coverage.py)

### ExecutionStatus (Literal)
**Status:** ✅ In use

```python
ExecutionStatus = Literal[
    "success", "failed", "error", "timeout",
    "compilation_failed", "build_failed",
    "execution_failed", "coverage_failed", "partial_success"
]
```

---

### ValidationResult
**Status:** ✅ In use

```python
@dataclass
class ValidationResult(BaseType):
    status: Literal["success", "failed", "timeout", "error"]
    return_code: Optional[int] = None
    stdout: str = ""
    stderr: str = ""
    result_file: Optional[str] = None
    message: Optional[str] = None
    details: Optional[str] = None

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ValidationResult"
```

**Purpose:** Pre-compilation validation result (Rusty compiler)

---

### ExecutionSummary
**Status:** ✅ In use

```python
@dataclass
class ExecutionSummary(BaseType):
    total_test_cases: int = 0
    total_cycles: int = 0
    expected_executions: int = 0
    input_count: int = 0
    state_count: int = 0
```

**Purpose:** Execution statistics summary

---

### STExecutionResult
**Status:** ✅ Core

```python
@dataclass
class STExecutionResult(BaseType):
    status: ExecutionStatus
    return_code: int = 0
    message: Optional[str] = None
    execution_summary: ExecutionSummary = field(default_factory=ExecutionSummary)
    test_cases: List[PLCTestCase] = field(default_factory=list)
    raw_stdout: str = ""
    raw_stderr: str = ""

    def _pick_cycle(test_case_index: int = 0, cycle_index: int = -1) -> Optional["PLCCycle"]
    def to_plc_var_state(test_case_index: int = 0, cycle_index: int = -1) -> Optional[PLCVarState]
    def to_initial_state(test_case_index: int = 0, cycle_index: int = -1) -> Optional["InitialState"]
    def to_simple(test_case_index: int = 0, cycle_index: int = -1) -> Optional["InitialState"]
```

**Purpose:** Main return type for ST code execution

**Methods:**
- `to_plc_var_state()` - extract the state of a given cycle
- `to_initial_state()` - convert to InitialState (without VAR_INPUT)
- `to_simple()` - simplified interface

---

### CoverageData
**Status:** ✅ In use

```python
@dataclass
class CoverageData:
    stmts: float = 0.0
    branches: float = 0.0
    paths: float = 0.0
    custom: Dict[str, float] = field(default_factory=dict)
```

**Note:** Not a BaseType; a simple data container

---

### CoverageBreakdown
**Status:** ✅ In use

```python
@dataclass
class CoverageBreakdown(BaseType):
    percentage: Optional[str] = None
    total: Optional[int] = None
    missed: Optional[int] = None
    covered: Optional[int] = None
    error: Optional[str] = None
```

**Purpose:** Detailed breakdown of a single coverage type

---

### CoverageSummary
**Status:** ✅ In use

```python
@dataclass
class CoverageSummary(BaseType):
    line_coverage: CoverageBreakdown = field(default_factory=CoverageBreakdown)
    function_coverage: CoverageBreakdown = field(default_factory=CoverageBreakdown)
    branch_coverage: CoverageBreakdown = field(default_factory=CoverageBreakdown)
    region_coverage: CoverageBreakdown = field(default_factory=CoverageBreakdown)
    error: Optional[str] = None
```

**Purpose:** Complete llvm-cov format coverage summary

---

### CoverageReport
**Status:** ✅ In use

```python
@dataclass
class CoverageReport(BaseType):
    case_name: str
    coverage_available: bool = False
    coverage_summary: Optional[CoverageSummary] = None
    coverage_files: List[str] = field(default_factory=list)
    error: Optional[str] = None
    merge_info: Optional[Dict[str, Any]] = None
```

**Purpose:** Complete coverage report (file list + summary)

---

### CoverageRunResult
**Status:** ✅ In use

```python
@dataclass
class CoverageRunResult(BaseType):
    status: ExecutionStatus
    return_code: int = 0
    stdout: str = ""
    stderr: str = ""
    coverage_data: Optional[CoverageReport] = None
    incremental: Optional[bool] = None
    execution_result: Optional[STExecutionResult] = None
```

**Purpose:** Coverage run result (with a link to execution data)

---

### CoverageRecord
**Status:** ✅ In use

```python
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
```

**Purpose:** Coverage record (used for tracking increments)

---

### UncoveredUnit
**Status:** ✅ In use

```python
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
```

**Purpose:** Uncovered unit record

---

### ResourceQuota
**Status:** ✅ In use

```python
@dataclass
class ResourceQuota:
    count: int
    limit: int
```

**Note:** Not a BaseType

---

### DockerResourceStatus
**Status:** ✅ In use

```python
@dataclass
class DockerResourceStatus(BaseType):
    images: Optional[ResourceQuota] = None
    containers: Optional[ResourceQuota] = None
    rusty_available: bool = False
    error: Optional[str] = None
```

**Purpose:** Docker resource status (Docker execution mode)

---

### DockerCmdResult
**Status:** ✅ In use

```python
@dataclass
class DockerCmdResult(BaseType):
    status: ExecutionStatus
    return_code: int
    stdout: str = ""
    stderr: str = ""
    message: Optional[str] = None
```

**Purpose:** Docker command execution result

---

### IncrementalSummary
**Status:** ✅ In use

```python
@dataclass
class IncrementalSummary(BaseType):
    total_rounds: int = 0
    successful_rounds: int = 0
    total_test_cases: int = 0
    total_cycles: int = 0
    cycles_per_round: int = 0
    state_continuity: bool = False
```

**Purpose:** Incremental simulation summary

---

### IncrementalSimulationResult
**Status:** ✅ In use

```python
@dataclass
class IncrementalSimulationResult(BaseType):
    status: ExecutionStatus
    rounds: List[STExecutionResult] = field(default_factory=list)
    final_state: Optional[InitialState] = None
    summary: IncrementalSummary = field(default_factory=IncrementalSummary)
    message: Optional[str] = None
```

**Purpose:** Multi-round incremental simulation result

---

## Plan Types (plan_types.py)

### TaskArchetype (Enum)
**Status:** ✅ In use

```python
class TaskArchetype(str, Enum):
    P_ALG = "P_alg"
    P_SEQ = "P_seq"
    P_TIME = "P_time"
    GENERAL = "General"
    SATURATED = "SATURATED"
    VULNERABILITY_EXPLOIT = "VULNERABILITY_EXPLOIT"
```

**Purpose:** Task archetype classification

---

### TargetAnchorType (Enum)
**Status:** ✅ In use

```python
class TargetAnchorType(str, Enum):
    CODE_SNIPPET = "code_snippet"
    FUNCTIONAL_STATE = "functional_state"
    BOUNDARY_VAR = "boundary_variable"
    GLOBAL = "global_context"
```

**Purpose:** Target anchor types

---

### SystemDirectiveType (Enum)
**Status:** ✅ In use

```python
class SystemDirectiveType(str, Enum):
    CONTINUE = "CONTINUE"
    STOP_SATURATED = "SATURATED"
    STOP_SUCCESS = "SUCCESS"
    FALLBACK_EXPLORE = "FALLBACK"
```

**Purpose:** System-level directives (Orchestrator control)

---

### TargetObservation
**Status:** ✅ In use

```python
@dataclass
class TargetObservation:
    target_identifier: str
    spatial_context: str
    temporal_context: str
    required_pre_states: List[str]
```

**Purpose:** Target observation data transfer object (DTO)

---

### ExecutionStrategy (Enum)
**Status:** ✅ In use

```python
class ExecutionStrategy(str, Enum):
    SYMBOLIC_SOLVING = "symbolic_guard_solving"
    BOUNDARY_MUTATION = "boundary_value_mutation"
    SEQUENCE_SUMMARY = "semantic_sequence_summary"
    STATE_TRACKING = "state_transition_tracking"
    RANDOM_FUZZING = "exploratory_random_fuzzing"
    EXPLORATORY_RANDOM_FUZZING = "exploratory_random_fuzzing"
    CRASH_MINIMIZATION = "crash_minimization"
    ADVERSARIAL_INJECTION = "adversarial_boundary_injection"
    CALL_FUZZING_BREAKTHROUGH = "call_fuzzing_breakthrough"
    DIRECTED_VULNERABILITY_MUTATION = "directed_vulnerability_mutation"

    @classmethod
    def safe_get(cls, strategy_name: str) -> str
```

**Purpose:** Execution strategy enum

**Methods:**
- `safe_get()` - bulletproof mechanism that matches strategy names

---

### NodeStatus (Enum)
**Status:** ✅ In use

```python
class NodeStatus(str, Enum):
    PENDING = "PENDING"
    BLOCKED = "BLOCKED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    UNSAT = "UNSAT"
```

**Purpose:** Status lifecycle of plan-graph nodes

---

### DiagnosisContext
**Status:** ✅ Core (Pydantic)

```python
class DiagnosisContext(BaseModel):
    archetype: TaskArchetype
    bottleneck_analysis: str
```

**Purpose:** Diagnosis context (LLM structured output)

---

### IntentContext
**Status:** ✅ Core (Pydantic)

```python
class IntentContext(BaseModel):
    goal_description: str
    spatial_context_summary: str
    temporal_context_summary: str
```

**Purpose:** Intent context (LLM structured output)

---

### ActionRouting
**Status:** ✅ Core (Pydantic)

```python
class ActionRouting(BaseModel):
    selected_strategy: ExecutionStrategy
    expected_cycles: int = Field(default=1)
```

**Purpose:** Action routing (LLM structured output)

---

### PlanPayload
**Status:** ✅ Core - LLM structured output contract

```python
class PlanPayload(BaseModel):
    goal: str = Field("")
    diagnosis: DiagnosisContext
    intent: IntentContext
    target_type: TargetAnchorType
    target_details: str
    action_routing: ActionRouting
    diagnostic_notes: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode='after')
    def sync_goal_attribute(self) -> 'PlanPayload'
```

**Features:**
- Pydantic model (unlike BaseType)
- Forces the LLM to output in format
- Supports Reflexion (diagnostic_notes)
- Auto-syncs the goal attribute

---

### TargetObligation
**Status:** ✅ In use

```python
@dataclass
class TargetObligation:
    id: str
    target_identifier: str
    payload: PlanPayload
    status: NodeStatus = NodeStatus.PENDING
    retry_count: int = 0
    history_logs: List[str] = field(default_factory=list)
```

**Purpose:** A node in the plan graph

---

### VerificationPlanGraph
**Status:** ✅ In use

```python
class VerificationPlanGraph:
    def add_node(target_identifier, payload) -> TargetObligation
    def add_dependency(prereq_node_id, dependent_node_id)
    def update_node_status(node_id, new_status, log_msg)
    def get_node(node_id) -> Optional[TargetObligation]
    def get_node_by_target(target_identifier) -> Optional[TargetObligation]
    def get_actionable_nodes() -> List[TargetObligation]
    def _update_graph_status()
```

**Purpose:** Maintains the DAG of multi-step plans

---

### PlannerOutput
**Status:** ✅ In use

```python
@dataclass
class PlannerOutput:
    directive: SystemDirectiveType
    actionable_nodes: List[TargetObligation]
    message: str
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Purpose:** Final structured output of the Planner Agent

---

### Plan
**Status:** ✅ In use

```python
@dataclass
class Plan(BaseType):
    goal: str
    target_execution_strategy: List[str]
    notes: Optional[str] = None
    target_branch: Optional[str] = None
    # Compatibility fields
    target_type: Optional[str] = None
    target_details: Optional[str] = None
    action_routing: Optional[Any] = None
    diagnosis: Optional[Any] = None
    intent: Optional[Any] = None
    diagnostic_notes: Optional[str] = None

    def to_dict() -> Dict[str, Any]
```

**Purpose:** Strategy plan representation

**Note:** Contains backward-compatibility fields

---

## ST Types (st_types.py)

### LoopConfig
**Status:** ✅ In use

```python
@dataclass
class LoopConfig(BaseType):
    outputs_dir: str = "outputs"
    tag: Optional[str] = None
    max_iterations: int = 10
    stagnation_rounds: int = 3
    window_size: int = 5
    generator_num_cases: int = 2
    seed_cases: Optional[List[Dict[str, Any]]] = None
```

**Purpose:** Main-loop configuration

---

### LoopState
**Status:** ✅ In use

```python
@dataclass
class LoopState(BaseType):
    iteration: int = 0
    global_covered_ids: Set[str] = field(default_factory=set)
    recent_covered_snapshots: List[Set[str]] = field(default_factory=list)
    no_progress_rounds: int = 0
```

**Purpose:** Main-loop state

---

### StoredTestCase ⚠️
**Status:** ⚠️ Legacy - gradual migration planned

```python
@dataclass
class StoredTestCase(BaseType):
    # Required fields
    project: str
    module: str
    function: str
    st_path: str
    st_code_content: str

    # Optional fields
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

    def __post_init__()
    def _to_plc_test_case() -> "PLCTestCase"
    def _to_json(...) -> Union[Dict, str]
    def _to_txt(...) -> str
    @staticmethod
    def _from_io_pairs(io_pairs, st_code_path, **kwargs) -> "StoredTestCase"
    @staticmethod
    def _from_json(json_data) -> "StoredTestCase"
    def _from_plc_test_case(plc_test_case, ...) -> "StoredTestCase"
```

**Purpose:** The absolute top-level storage class for test cases

**Compatibility plan:**
- Current: keep backward compatible
- Problem: coupled with IOPair, functionality overlaps with ExpUnifiedIR
- Priority: high (migration path needs planning)

---

### PLCFullTestResult
**Status:** ✅ In use

```python
@dataclass
class PLCFullTestResult(BaseType):
    stored_test_cases: List[StoredTestCase]
    full_coverage_data: CoverageData
```

**Purpose:** Complete test result (multiple test cases + accumulated coverage)

---

### Helper Functions (st_types.py)

| Function | Status | Purpose |
|------|------|------|
| `create_stored_io_test_case()` | ⚠️ Legacy | Create an IO test case |
| `create_stored_test_case_from_json()` | ⚠️ Legacy | Create a test case from JSON |
| `stored_to_plc_test_case()` | ⚠️ Legacy | Convert to execution format |
| `plc_to_stored_test_case()` | ⚠️ Legacy | Convert to storage format |
| `stored_test_case_to_json()` | ⚠️ Legacy | Serialize to JSON |
| `stored_test_case_to_txt()` | ⚠️ Legacy | Serialize to TXT |

---

## Experiment Unified IR (exp_types.py)

### ExpUnifiedIR
**Status:** ✅ Core - recommended test case representation

```python
@dataclass
class ExpUnifiedIR:
    exp_id: str
    target_st_path: str
    schema_path: str
    tester_type: str = "PureLLM"
    scan_cycle_ms: int = 10
    total_cycles: int = 10
    sparse_timeline: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    def _sanitize_value(value, plc_type: str) -> str
    def _resolve_type(matched_col, data) -> Optional[str]
    def _fuzzy_match(key, schema_cols) -> str
    def validate() -> Tuple[bool, List[str]]
    def to_harness_input() -> str
```

**Purpose:** Unified test case representation

**Features:**
- Sparse timeline format (space-saving)
- Physical sandbox filtering (IEC 61131-3 type compliance)
- Fuzzy variable-name matching
- Automatic value truncation and validation

**Methods:**
- `validate()` - validate input legality with smart hints
- `to_harness_input()` - serialize to the harness input format
- `_sanitize_value()` - type-safe value filtering
- `_resolve_type()` - enhanced type resolver (V1/V2 compatible)
- `_fuzzy_match()` - fuzzy variable-name matching (supports array formats)

**Relationship to IOPair:**
- IOPair: single-step IO pair
- ExpUnifiedIR: multi-cycle sparse timeline
- Conversion: IOPair list -> ExpUnifiedIR.sparse_timeline (needs an adapter layer)

---

## Evaluation Types (eval_types.py)

### EvaluationReport
**Status:** ✅ In use

```python
@dataclass
class EvaluationReport:
    test_suite_id: str
    coverage_summary: Dict[str, Any] = field(default_factory=dict)
    problems: List[Dict[str, Any]] = field(default_factory=list)
    recommendation: Dict[str, Any] = field(default_factory=dict)
    raw_execution_data: Optional[Dict[str, Any]] = None
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)

    def to_planner_context() -> Dict[str, Any]
```

**Purpose:** Evaluation report structure

**Methods:**
- `to_planner_context()` - convert to Planner context

---

## Agent-Harness Communication Protocol (protocols/)

### Action Protocol (action_protocol.py)

#### ActionType (Enum)
**Status:** 🆕 New

```python
class ActionType(str, Enum):
    EXECUTE = "execute"
    GENERATE = "generate"
    ANALYZE = "analyze"
    GET_STATE = "get_state"
    GET_COVERAGE = "get_coverage"
```

**Purpose:** Standard action types an Agent can request

---

#### ToolCallRequest
**Status:** 🆕 New

```python
@dataclass
class ToolCallRequest:
    action_id: str
    action_type: ActionType
    tool_name: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    timeout_sec: Optional[int] = None
    priority: int = 0
    context: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Purpose:** Generic tool-call request format

---

#### ExecuteRequest
**Status:** 🆕 New

```python
@dataclass
class ExecuteRequest:
    test_case_id: str
    target_st_path: str
    input_data: Dict[str, Any]
    cycles: int = 10
    scan_cycle_ms: int = 50
    collect_coverage: bool = True
    collect_trace: bool = True
```

**Purpose:** Test case execution request

---

#### GenerateRequest
**Status:** 🆕 New

```python
@dataclass
class GenerateRequest:
    strategy: ExecutionStrategy
    target_st_path: str
    budget: Dict[str, Any] = field(default_factory=dict)
    focus_branches: Optional[List[str]] = None
    focus_variables: Optional[List[str]] = None
    context: Optional[Dict[str, Any]] = None
```

**Purpose:** Test case generation request

---

#### AnalyzeRequest
**Status:** 🆕 New

```python
@dataclass
class AnalyzeRequest:
    execution_id: str
    analysis_type: Literal["coverage", "problems", "state_trace", "full"]
    filters: Dict[str, Any] = field(default_factory=dict)
```

**Purpose:** Result analysis request

---

#### GetStateRequest
**Status:** 🆕 New

```python
@dataclass
class GetStateRequest:
    state_type: Literal["current", "initial", "final"] = "current"
    variables: Optional[List[str]] = None
```

**Purpose:** State query request

---

#### GetCoverageRequest
**Status:** 🆕 New

```python
@dataclass
class GetCoverageRequest:
    coverage_type: Literal["line", "branch", "function", "all"] = "all"
    targets: Optional[List[str]] = None
```

**Purpose:** Coverage query request

---

#### create_action_request()
**Status:** 🆕 New

```python
def create_action_request(action_type: ActionType, **kwargs) -> ToolCallRequest
```

**Purpose:** Factory function that creates the appropriate request

---

### Feedback Protocol (feedback_protocol.py)

#### ActionResponse
**Status:** 🆕 New

```python
@dataclass
class ActionResponse:
    action_id: str
    status: Literal["success", "failed", "timeout", "error"]
    data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    execution_time_ms: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

**Purpose:** Standard action response format

---

#### ExecutionResult
**Status:** 🆕 New

```python
@dataclass
class ExecutionResult:
    test_case_id: str
    execution_status: str
    final_state: Dict[str, Any] = field(default_factory=dict)
    state_trace: List[Dict[str, Any]] = field(default_factory=list)
    coverage_summary: Optional[Dict[str, Any]] = None
    uncovered_branches: Optional[List[str]] = None
    uncovered_lines: Optional[List[int]] = None
    problems: List[Dict[str, Any]] = field(default_factory=list)
    stdout: Optional[str] = None
    stderr: Optional[str] = None
```

**Purpose:** Execution result data

---

#### GenerationResult
**Status:** 🆕 New

```python
@dataclass
class GenerationResult:
    strategy_used: str
    generated_cases: List[Dict[str, Any]] = field(default_factory=list)
    total_generated: int = 0
    valid_cases: int = 0
    generation_time_ms: Optional[int] = None
    diversity_score: Optional[float] = None
    expected_coverage_gain: Optional[Dict[str, float]] = None
```

**Purpose:** Generation result data

---

#### AnalysisResult
**Status:** 🆕 New

```python
@dataclass
class AnalysisResult:
    analysis_type: str
    findings: List[Dict[str, Any]] = field(default_factory=list)
    coverage_analysis: Optional[Dict[str, Any]] = None
    problem_analysis: Optional[Dict[str, Any]] = None
    state_analysis: Optional[Dict[str, Any]] = None
    suggestions: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)
```

**Purpose:** Analysis result data

---

#### StateResult
**Status:** 🆕 New

```python
@dataclass
class StateResult:
    state_type: str
    variables: Dict[str, Any] = field(default_factory=dict)
    cycle: Optional[int] = None
    timestamp: Optional[datetime] = None
```

**Purpose:** State query result

---

#### CoverageResult
**Status:** 🆕 New

```python
@dataclass
class CoverageResult:
    coverage_type: str
    summary: Dict[str, float] = field(default_factory=dict)
    line_coverage: Optional[Dict[str, Any]] = None
    branch_coverage: Optional[Dict[str, Any]] = None
    function_coverage: Optional[Dict[str, Any]] = None
    uncovered_lines: List[int] = field(default_factory=list)
    uncovered_branches: List[str] = field(default_factory=list)
    uncovered_functions: List[str] = field(default_factory=list)
```

**Purpose:** Coverage query result

---

#### create_action_response()
**Status:** 🆕 New

```python
def create_action_response(
    action_id: str,
    status: Literal["success", "failed", "timeout", "error"],
    data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    **kwargs
) -> ActionResponse
```

**Purpose:** Factory function that creates a standard response

---

## Type Dependency Graph

```
BaseType (foundation)
├── TestStep
├── OracleViolation
├── AnalysisReport
├── InitialState
├── ValidationResult
├── ExecutionSummary
├── STExecutionResult
├── CoverageBreakdown
├── CoverageSummary
├── CoverageReport
├── CoverageRunResult
├── CoverageRecord
├── UncoveredUnit
├── DockerResourceStatus
├── DockerCmdResult
├── IncrementalSummary
├── IncrementalSimulationResult
├── Plan
├── StoredTestCase
├── PLCFullTestResult
└── IOPair

Pydantic Models (plan_types.py)
├── DiagnosisContext → TaskArchetype (Enum)
├── IntentContext
├── ActionRouting → ExecutionStrategy (Enum)
└── PlanPayload → (DiagnosisContext, IntentContext, ActionRouting, TargetAnchorType)

Dataclasses (test_case_types.py)
├── PLCVarState (standalone)
├── PLCCycle → PLCVarState
├── PLCTestCase → (PLCCycle, PLCParsedTestCaseSummary)
└── IOPair → BaseType

Enums
├── StoredTestCaseType
├── TaskArchetype
├── TargetAnchorType
├── SystemDirectiveType
├── ExecutionStrategy
├── NodeStatus
└── ActionType (protocols)

Protocols (protocols/)
├── action_protocol.py
│   ├── ActionType (Enum)
│   ├── ToolCallRequest
│   ├── ExecuteRequest
│   ├── GenerateRequest → ExecutionStrategy
│   ├── AnalyzeRequest
│   ├── GetStateRequest
│   └── GetCoverageRequest
└── feedback_protocol.py
    ├── ActionResponse
    ├── ExecutionResult
    ├── GenerationResult
    ├── AnalysisResult
    ├── StateResult
    └── CoverageResult

Complex Composites
├── VerificationPlanGraph → (TargetObligation → PlanPayload)
├── TargetObligation → PlanPayload (Pydantic)
├── PlannerOutput → (SystemDirectiveType, List[TargetObligation])
└── StoredTestCase → (IOPair, Plan, STExecutionResult, CoverageData)

Independent
├── CoverageData (not a BaseType)
├── ResourceQuota (not a BaseType)
├── TargetObservation (dataclass)
└── ExpUnifiedIR (standalone, depends on constants.IEC_TYPE_LIMITS)
```

---

## Compatibility Migration Plan

### Phase 1: Keep Compatibility (current)
- ✅ All types keep their existing interfaces
- ✅ IOPair and StoredTestCase keep working
- ✅ New code prefers ExpUnifiedIR
- ✅ protocols/ added for Agent-Harness communication

### Phase 2: Add an Adapter Layer (future)
```python
# Planned conversion functions
def io_pairs_to_exp_ir(io_pairs: List[IOPair], schema_path: str) -> ExpUnifiedIR:
    """Convert an IOPair list to ExpUnifiedIR"""
    ...

def stored_test_case_to_exp_ir(st: StoredTestCase) -> ExpUnifiedIR:
    """Convert a StoredTestCase to ExpUnifiedIR"""
    ...

def protocol_to_internal(action_req: ToolCallRequest) -> Any:
    """Convert a protocol request to an internal call"""
    ...
```

### Phase 3: Gradual Replacement (long term)
- New code uses ExpUnifiedIR + protocols/
- Old code stays compatible via the adapter layer
- End state: IOPair/StoredTestCase marked Deprecated

---

## Import Recommendations

### Recommended Imports

```python
# Core data contracts
from core import (
    ExpUnifiedIR,      # test case representation
    STExecutionResult, # execution result
    CoverageData,      # coverage data
    PlanPayload,       # LLM output contract
)

# Communication protocols
from core.protocols import (
    ToolCallRequest,   # Agent → Harness
    ActionResponse,    # Harness → Agent
    create_action_request,
    create_action_response,
)

# Helper functions
from core.protocols import create_action_request  # factory function
```

---

*Document version: v2.0*
*Last updated: 2026-05-29*
