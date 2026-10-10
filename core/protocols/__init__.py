"""
Protocols Module - Agent-Harness Communication

Defines the standard protocols for communication between
external agents and the harness:

Action Protocol (Agent → Harness):
- ActionType: Standard action types
- ToolCallRequest: Generic tool invocation request
- ExecuteRequest: Test case execution request
- GenerateRequest: Test case generation request
- AnalyzeRequest: Result analysis request
- GetStateRequest: State query request
- GetCoverageRequest: Coverage query request

Feedback Protocol (Harness → Agent):
- ActionResponse: Standard response format
- ActionExecutionResult: Execution result data (renamed from ExecutionResult)
- ActionGenerationResult: Generation result data (renamed from GenerationResult)
- ActionAnalysisResult: Analysis result data (renamed from AnalysisResult)
- ActionStateResult: State query result data (renamed from StateResult)
- ActionCoverageResult: Coverage query result data (renamed from CoverageResult)
"""

from core.protocols.action_protocol import (
    ActionType,
    ToolCallRequest,
    ExecuteRequest,
    GenerateRequest,
    AnalyzeRequest,
    GetStateRequest,
    GetCoverageRequest,
    create_action_request,
)

from core.protocols.feedback_protocol import (
    ActionResponse,
    ActionExecutionResult,
    ActionGenerationResult,
    ActionAnalysisResult,
    ActionStateResult,
    ActionCoverageResult,
    create_action_response,
)

__all__ = [
    # Action Protocol
    "ActionType",
    "ToolCallRequest",
    "ExecuteRequest",
    "GenerateRequest",
    "AnalyzeRequest",
    "GetStateRequest",
    "GetCoverageRequest",
    "create_action_request",

    # Feedback Protocol
    "ActionResponse",
    "ActionExecutionResult",
    "ActionGenerationResult",
    "ActionAnalysisResult",
    "ActionStateResult",
    "ActionCoverageResult",
    "create_action_response",
]
