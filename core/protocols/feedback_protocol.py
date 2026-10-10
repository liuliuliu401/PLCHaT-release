"""
Feedback Protocol - Harness → Agent
Defines the data format for responses from the harness to external agents.

This protocol provides structured feedback that agents can use to
inform their next decisions.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal
from datetime import datetime


@dataclass
class ActionResponse:
    """
    Standard response format for action requests.

    All harness responses should conform to this structure.
    """
    action_id: str                     # Matches the request's action_id
    status: Literal["success", "failed", "timeout", "error"]

    # Response data (varies by action type)
    data: Optional[Dict[str, Any]] = None

    # Error information (if status is not success)
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    # Execution metadata
    execution_time_ms: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)

    # Additional metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActionExecutionResult:
    """
    API-layer execution result data (populates ActionResponse.data for EXECUTE actions).

    This is a simplified format for Agent-Harness communication.
    For internal complete data, use STExecutionResult from core.data_types.
    """
    test_case_id: str
    execution_status: str

    # Output variables
    final_state: Dict[str, Any] = field(default_factory=dict)
    state_trace: List[Dict[str, Any]] = field(default_factory=list)

    # Coverage data
    coverage_summary: Optional[Dict[str, Any]] = None
    uncovered_branches: Optional[List[str]] = None
    uncovered_lines: Optional[List[int]] = None

    # Problem detection
    problems: List[Dict[str, Any]] = field(default_factory=list)

    # Raw outputs
    stdout: Optional[str] = None
    stderr: Optional[str] = None


@dataclass
class ActionGenerationResult:
    """
    API-layer generation result data (populates ActionResponse.data for GENERATE actions).

    This is a simplified format for Agent-Harness communication.
    """
    strategy_used: str
    generated_cases: List[Dict[str, Any]] = field(default_factory=list)

    # Generation statistics
    total_generated: int = 0
    valid_cases: int = 0
    generation_time_ms: Optional[int] = None

    # Quality indicators
    diversity_score: Optional[float] = None
    expected_coverage_gain: Optional[Dict[str, float]] = None


@dataclass
class ActionAnalysisResult:
    """
    API-layer analysis result data (populates ActionResponse.data for ANALYZE actions).

    This is a simplified format for Agent-Harness communication.
    For internal complete data, use AnalysisReport from core.data_types.
    """
    analysis_type: str
    findings: List[Dict[str, Any]] = field(default_factory=list)

    # Detailed analysis
    coverage_analysis: Optional[Dict[str, Any]] = None
    problem_analysis: Optional[Dict[str, Any]] = None
    state_analysis: Optional[Dict[str, Any]] = None

    # Recommendations
    suggestions: List[str] = field(default_factory=list)
    next_actions: List[str] = field(default_factory=list)


@dataclass
class ActionStateResult:
    """
    API-layer state result data (populates ActionResponse.data for GET_STATE actions).

    This is a simplified format for Agent-Harness communication.
    """
    state_type: str
    variables: Dict[str, Any] = field(default_factory=dict)

    # State metadata
    cycle: Optional[int] = None
    timestamp: Optional[datetime] = None


@dataclass
class ActionCoverageResult:
    """
    API-layer coverage result data (populates ActionResponse.data for GET_COVERAGE actions).

    This is a simplified format for Agent-Harness communication.
    For internal complete data, use CoverageReport from core.data_types.
    """
    coverage_type: str
    summary: Dict[str, float] = field(default_factory=dict)

    # Detailed breakdown
    line_coverage: Optional[Dict[str, Any]] = None
    branch_coverage: Optional[Dict[str, Any]] = None
    function_coverage: Optional[Dict[str, Any]] = None

    # Uncovered targets
    uncovered_lines: List[int] = field(default_factory=list)
    uncovered_branches: List[str] = field(default_factory=list)
    uncovered_functions: List[str] = field(default_factory=list)


# Factory function to create appropriate response
def create_action_response(
    action_id: str,
    status: Literal["success", "failed", "timeout", "error"],
    data: Optional[Dict[str, Any]] = None,
    error_message: Optional[str] = None,
    **kwargs
) -> ActionResponse:
    """
    Factory function to create a standardized action response.

    Args:
        action_id: ID of the action being responded to
        status: Status of the action execution
        data: Response data (varies by action type)
        error_message: Error message if status is not success
        **kwargs: Additional metadata fields

    Returns:
        ActionResponse with all fields populated
    """
    return ActionResponse(
        action_id=action_id,
        status=status,
        data=data,
        error_message=error_message,
        **kwargs
    )
