"""
Action Protocol - Agent → Harness
Defines the data format for requests from external agents to the harness.

This protocol decouples agent implementations from harness internals,
enabling multiple agent frameworks (LangChain, custom, etc.) to interact
with PLCHaT without tight coupling.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Literal
from enum import Enum

from core.data_types.plan_types import ExecutionStrategy


class ActionType(str, Enum):
    """Standard action types that agents can request."""
    EXECUTE = "execute"                # Execute a test case
    GENERATE = "generate"              # Generate new test cases
    ANALYZE = "analyze"                # Analyze execution results
    GET_STATE = "get_state"           # Query current harness state
    GET_COVERAGE = "get_coverage"     # Get coverage information


@dataclass
class ToolCallRequest:
    """
    Standard format for tool invocation requests from Agent to Harness.

    This replaces direct tool calls with a structured protocol.
    """
    action_id: str                     # Unique identifier for this action
    action_type: ActionType            # Type of action requested
    tool_name: str                     # Specific tool to use (e.g., "dse", "afl", "random")

    # Tool-specific parameters
    parameters: Dict[str, Any] = field(default_factory=dict)

    # Execution constraints
    timeout_sec: Optional[int] = None   # Maximum execution time
    priority: int = 0                   # Execution priority (higher = first)

    # Context for the action
    context: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecuteRequest:
    """
    Request to execute a specific test case.

    Used when agent wants to run a test and get results.
    """
    test_case_id: str
    target_st_path: str
    input_data: Dict[str, Any]          # ExpUnifiedIR.sparse_timeline format
    cycles: int = 10
    scan_cycle_ms: int = 50

    # Execution options
    collect_coverage: bool = True
    collect_trace: bool = True


@dataclass
class GenerateRequest:
    """
    Request to generate new test cases.

    Used when agent wants the harness to generate test inputs.
    """
    strategy: ExecutionStrategy
    target_st_path: str
    budget: Dict[str, Any] = field(default_factory=dict)  # e.g., {"max_cases": 10}

    # Generation constraints
    focus_branches: Optional[List[str]] = None
    focus_variables: Optional[List[str]] = None

    # Context from previous results
    context: Optional[Dict[str, Any]] = None


@dataclass
class AnalyzeRequest:
    """
    Request to analyze execution results.

    Used when agent wants detailed analysis of what happened.
    """
    execution_id: str
    analysis_type: Literal["coverage", "problems", "state_trace", "full"]

    # Analysis filters
    filters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GetStateRequest:
    """
    Request to query current harness state.

    Used when agent needs to know the current state before deciding next action.
    """
    state_type: Literal["current", "initial", "final"] = "current"

    # Optional: specific variables to query
    variables: Optional[List[str]] = None


@dataclass
class GetCoverageRequest:
    """
    Request to get coverage information.

    Used when agent wants to know coverage status.
    """
    coverage_type: Literal["line", "branch", "function", "all"] = "all"

    # Optional: focus on specific files/functions
    targets: Optional[List[str]] = None


# Factory function to create appropriate request from parameters
def create_action_request(action_type: ActionType, **kwargs) -> ToolCallRequest:
    """
    Factory function to create the appropriate request based on action type.

    Args:
        action_type: Type of action requested
        **kwargs: Parameters for the specific action

    Returns:
        ToolCallRequest with the appropriate parameters populated
    """
    if action_type == ActionType.EXECUTE:
        execute_req = ExecuteRequest(**kwargs)
        return ToolCallRequest(
            action_id=execute_req.test_case_id,
            action_type=action_type,
            tool_name="executor",
            parameters={"execute_request": execute_req},
        )
    elif action_type == ActionType.GENERATE:
        generate_req = GenerateRequest(**kwargs)
        return ToolCallRequest(
            action_id=f"gen_{generate_req.target_st_path}",
            action_type=action_type,
            tool_name=generate_req.strategy.value,
            parameters={"generate_request": generate_req},
        )
    elif action_type == ActionType.ANALYZE:
        analyze_req = AnalyzeRequest(**kwargs)
        return ToolCallRequest(
            action_id=analyze_req.execution_id,
            action_type=action_type,
            tool_name="analyzer",
            parameters={"analyze_request": analyze_req},
        )
    elif action_type == ActionType.GET_STATE:
        state_req = GetStateRequest(**kwargs)
        return ToolCallRequest(
            action_id="state_query",
            action_type=action_type,
            tool_name="state_manager",
            parameters={"state_request": state_req},
        )
    elif action_type == ActionType.GET_COVERAGE:
        cov_req = GetCoverageRequest(**kwargs)
        return ToolCallRequest(
            action_id="coverage_query",
            action_type=action_type,
            tool_name="coverage_manager",
            parameters={"coverage_request": cov_req},
        )
    else:
        raise ValueError(f"Unknown action type: {action_type}")
