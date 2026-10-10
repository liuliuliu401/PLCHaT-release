"""
PLCHaT Core Module
Unified type export and management interface

This module provides a unified interface for accessing:
- Type Registry: Type metadata and querying
- Data Types: Internal data structures (core.data_types)
- Protocols: Agent-Harness communication protocols (core.protocols)
- Converters: Conversion between protocol and data layers

Architecture:
┌─────────────────────────────────────────────────────────┐
│                      core/                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  │
│  │ type_registry│  │  converters  │  │   protocols  │  │
│  └──────────────┘  └──────────────┘  └──────────────┘  │
│  ┌──────────────────────────────────────────────────┐  │
│  │              data_types/                          │  │
│  │  base_types, test_case_types, execution_coverage │  │
│  │  plan_types, st_types, exp_types, ir_types        │  │
│  └──────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘

Usage Examples:
    # Import types from data layer
    from core import STExecutionResult, PlanPayload

    # Import protocol types
    from core import ActionExecutionResult, ActionResponse

    # Use type registry
    from core import TypeRegistry
    TypeRegistry.get_all_types()

    # Use converters
    from core import ExecutionConverter
    api_result = ExecutionConverter.to_action_response(st_result)
"""

# =============================================================================
# Type Registry
# =============================================================================
from core.type_registry import (
    TypeRegistry,
    get_all_types,
    get_type_by_name,
    is_base_type,
    get_base_type_subclasses,
)

# =============================================================================
# Protocol Layer (API Layer - Agent-Harness Communication)
# =============================================================================
from core.protocols import (
    # Action Protocol
    ActionType,
    ToolCallRequest,
    ExecuteRequest,
    GenerateRequest,
    AnalyzeRequest,
    GetStateRequest,
    GetCoverageRequest,
    create_action_request,
    # Feedback Protocol
    ActionResponse,
    ActionExecutionResult,
    ActionGenerationResult,
    ActionAnalysisResult,
    ActionStateResult,
    ActionCoverageResult,
    create_action_response,
)

# =============================================================================
# Data Layer (Internal Data Structures)
# =============================================================================
from core.data_types import (
    # Base types
    BaseType,
    TestStep,
    OracleViolation,
    AnalysisReport,
    InitialState,
    # Test case types
    StoredTestCaseType,
    PLCVarState,
    PLCCycle,
    PLCParsedTestCaseSummary,
    PLCTestCase,
    IOPair,
    # IR types
    STVariableDecl,
    STPOUIR,
    # Evaluation types
    EvaluationReport,
    # Execution and coverage types
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
    # Plan and strategy types
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
    # ST types
    Plan,
    LoopConfig,
    LoopState,
    StoredTestCase,
    PLCFullTestResult,
    # Helper functions from st_types
    create_stored_io_test_case,
    create_stored_test_case_from_json,
    stored_to_plc_test_case,
    plc_to_stored_test_case,
    stored_test_case_to_json,
    stored_test_case_to_txt,
    # Experimental Unified IR
    ExpUnifiedIR,
)

# =============================================================================
# Converters (Protocol ↔ Data Layer Conversion)
# =============================================================================
from core.converters import (
    ExecutionConverter,
    CoverageConverter,
    AnalysisConverter,
)

# =============================================================================
# Public API
# =============================================================================
__all__ = [
    # === Type Registry ===
    "TypeRegistry",
    "get_all_types",
    "get_type_by_name",
    "is_base_type",
    "get_base_type_subclasses",

    # === Protocol Layer (Action Protocol) ===
    "ActionType",
    "ToolCallRequest",
    "ExecuteRequest",
    "GenerateRequest",
    "AnalyzeRequest",
    "GetStateRequest",
    "GetCoverageRequest",
    "create_action_request",

    # === Protocol Layer (Feedback Protocol) ===
    "ActionResponse",
    "ActionExecutionResult",
    "ActionGenerationResult",
    "ActionAnalysisResult",
    "ActionStateResult",
    "ActionCoverageResult",
    "create_action_response",

    # === Data Layer - Base Types ===
    "BaseType",
    "TestStep",
    "OracleViolation",
    "AnalysisReport",
    "InitialState",

    # === Data Layer - Test Case Types ===
    "StoredTestCaseType",
    "PLCVarState",
    "PLCCycle",
    "PLCParsedTestCaseSummary",
    "PLCTestCase",
    "IOPair",

    # === Data Layer - IR Types ===
    "STVariableDecl",
    "STPOUIR",

    # === Data Layer - Evaluation Types ===
    "EvaluationReport",

    # === Data Layer - Execution and Coverage Types ===
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

    # === Data Layer - Plan and Strategy Types ===
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

    # === Data Layer - ST Types ===
    "Plan",
    "LoopConfig",
    "LoopState",
    "StoredTestCase",
    "PLCFullTestResult",

    # === Data Layer - ST Helper Functions ===
    "create_stored_io_test_case",
    "create_stored_test_case_from_json",
    "stored_to_plc_test_case",
    "plc_to_stored_test_case",
    "stored_test_case_to_json",
    "stored_test_case_to_txt",

    # === Data Layer - Experimental Unified IR ===
    "ExpUnifiedIR",

    # === Converters ===
    "ExecutionConverter",
    "CoverageConverter",
    "AnalysisConverter",
]

# =============================================================================
# Module Metadata
# =============================================================================
__version__ = "1.0.0"
__author__ = "PLCHaT Team"

# Module documentation
"""
PLCHaT Core Module Architecture:

Layer 1: Type Registry (type_registry.py)
    - TypeRegistry: Central registry for all data types
    - Query types by name, check inheritance, get metadata

Layer 2: Protocol Layer (protocols/)
    - Agent → Harness: ActionType, ToolCallRequest, *Request
    - Harness → Agent: ActionResponse, Action*Result
    - Purpose: Simplified API format for Agent-Harness communication

Layer 3: Data Layer (data_types/)
    - Complete internal data structures
    - base_types.py: BaseType, TestStep, OracleViolation, AnalysisReport, InitialState
    - test_case_types.py: IOPair, PLCTestCase, PLCVarState
    - execution_coverage.py: STExecutionResult, CoverageData, CoverageReport
    - plan_types.py: PlanPayload, ExecutionStrategy
    - st_types.py: StoredTestCase, Plan
    - exp_types.py: ExpUnifiedIR

Layer 4: Converters (converters.py)
    - ExecutionConverter: STExecutionResult ↔ ActionExecutionResult
    - CoverageConverter: CoverageReport ↔ ActionCoverageResult
    - AnalysisConverter: AnalysisReport ↔ ActionAnalysisResult
"""
