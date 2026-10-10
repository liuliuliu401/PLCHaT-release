"""
PLCHaT Data Types Module
Core data structures for PLC testing and execution.

This module contains all internal data types used by PLCHaT:
- Base types and common utilities
- Test case representations
- Execution and coverage data
- Planning and strategy types
- ST program types and IR
"""

# Base types
from core.data_types.base_types import (
    BaseType,
    TestStep,
    OracleViolation,
    AnalysisReport,
    InitialState,
)

# Test case types
from core.data_types.test_case_types import (
    StoredTestCaseType,
    PLCVarState,
    PLCCycle,
    PLCParsedTestCaseSummary,
    PLCTestCase,
    IOPair,
)

# IR types
from core.data_types.ir_types import (
    STVariableDecl,
    STPOUIR,
)

# Evaluation types
from core.data_types.eval_types import (
    EvaluationReport,
)

# Execution and coverage types
from core.data_types.execution_coverage import (
    ExecutionStatus,
    ValidationResult,
    ExecutionSummary,
    STExecutionResult,
    CoverageData,
    CoverageBreakdown,
    CoverageSummary,
    CoverageReport,
    CoverageRunResult,
    CoverageRecord,
    UncoveredUnit,
    ResourceQuota,
    DockerResourceStatus,
    DockerCmdResult,
    IncrementalSummary,
    IncrementalSimulationResult,
)

# Plan and strategy types
from core.data_types.plan_types import (
    TaskArchetype,
    TargetAnchorType,
    SystemDirectiveType,
    TargetObservation,
    ExecutionStrategy,
    NodeStatus,
    DiagnosisContext,
    IntentContext,
    ActionRouting,
    PlanPayload,
    TargetObligation,
    VerificationPlanGraph,
    PlannerOutput,
)

# ST types
from core.data_types.st_types import (
    Plan,
    LoopConfig,
    LoopState,
    StoredTestCase,
    PLCFullTestResult,
    # Helper functions
    create_stored_io_test_case,
    create_stored_test_case_from_json,
    stored_to_plc_test_case,
    plc_to_stored_test_case,
    stored_test_case_to_json,
    stored_test_case_to_txt,
)

# Experimental Unified IR
from core.data_types.exp_types import (
    ExpUnifiedIR,
)

# Workflow types
from core.data_types.workflow_types import (
    WorkflowConfig,
    WorkflowState,
    WorkflowResult,
    create_session_dir,
)

# Test analysis types
from core.data_types.test_analysis_types import (
    TestIntent,
    AssertionDef,
    StateTransition,
    AssertionFailure,
    DistilledTrace,
    CompressedSegment,
    StateChange,
    CyclePattern,
    TestCaseReport,
)

__all__ = [
    # Base types
    "BaseType",
    "TestStep",
    "OracleViolation",
    "AnalysisReport",
    "InitialState",

    # Test case types
    "StoredTestCaseType",
    "PLCVarState",
    "PLCCycle",
    "PLCParsedTestCaseSummary",
    "PLCTestCase",
    "IOPair",

    # IR types
    "STVariableDecl",
    "STPOUIR",

    # Evaluation types
    "EvaluationReport",

    # Execution and coverage types
    "ExecutionStatus",
    "ValidationResult",
    "ExecutionSummary",
    "STExecutionResult",
    "CoverageData",
    "CoverageBreakdown",
    "CoverageSummary",
    "CoverageReport",
    "CoverageRunResult",
    "CoverageRecord",
    "UncoveredUnit",
    "ResourceQuota",
    "DockerResourceStatus",
    "DockerCmdResult",
    "IncrementalSummary",
    "IncrementalSimulationResult",

    # Plan and strategy types
    "TaskArchetype",
    "TargetAnchorType",
    "SystemDirectiveType",
    "TargetObservation",
    "ExecutionStrategy",
    "NodeStatus",
    "DiagnosisContext",
    "IntentContext",
    "ActionRouting",
    "PlanPayload",
    "TargetObligation",
    "VerificationPlanGraph",
    "PlannerOutput",
    "Plan",

    # ST types
    "LoopConfig",
    "LoopState",
    "StoredTestCase",
    "PLCFullTestResult",
    "create_stored_io_test_case",
    "create_stored_test_case_from_json",
    "stored_to_plc_test_case",
    "plc_to_stored_test_case",
    "stored_test_case_to_json",
    "stored_test_case_to_txt",

    # Experimental Unified IR
    "ExpUnifiedIR",

    # Workflow types
    "WorkflowConfig",
    "WorkflowState",
    "WorkflowResult",
    "create_session_dir",

    # Test analysis types
    "TestIntent",
    "AssertionDef",
    "StateTransition",
    "AssertionFailure",
    "DistilledTrace",
    "CompressedSegment",
    "StateChange",
    "CyclePattern",
    "TestCaseReport",
]
