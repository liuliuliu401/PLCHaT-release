"""
Routing Types - Tool routing and policy data types.

Migrated from harness/routing/ to centralize data type definitions.
These types are used by the routing system to select and dispatch tools.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum


class RoutingStrategy(str, Enum):
    """Available routing strategies."""

    COVERAGE_GUIDED = "coverage"    # Route based on coverage stagnation
    PROTOTYPE_AWARE = "prototype"   # Route based on task archetype
    ROUND_ROBIN = "round_robin"    # Simple round-robin
    PRIORITY = "priority"          # Based on tool priority
    MANUAL = "manual"              # Explicit tool selection
    LLM = "llm"                    # LLM-based intelligent routing


@dataclass
class RoutingContext:
    """
    Context information for routing decisions.

    Used by routing policies to select the appropriate tool
    based on current state and history.
    """

    # Coverage information
    current_coverage: float = 0.0
    coverage_history: List[float] = None
    stagnation_cycles: int = 0

    # Task information
    task_archetype: Optional[str] = None
    target_branches: Optional[List[str]] = None

    # Tool performance
    tool_performance: Dict[str, float] = None

    # Execution constraints
    max_execution_time: Optional[int] = None
    require_symbolic: bool = False

    def __post_init__(self):
        if self.coverage_history is None:
            self.coverage_history = []
        if self.tool_performance is None:
            self.tool_performance = {}


@dataclass
class LLMRoutingContext:
    """
    Extended context for LLM-based routing.

    Combines RoutingContext with goal information for LLM reasoning.
    Reuses core types where possible (ActionExecutionResult from core.protocols).
    """

    goal: str = ""
    execution_result: Optional[Any] = None  # ActionExecutionResult from core.protocols.feedback_protocol
    stagnation_cycles: int = 0
    iteration: int = 0
    tool_performance: Dict[str, float] = None

    def __post_init__(self):
        if self.tool_performance is None:
            self.tool_performance = {}
        if self.execution_result is None:
            # Create empty execution result if not provided
            # Import here to avoid circular dependency
            from core.protocols.feedback_protocol import ActionExecutionResult
            self.execution_result = ActionExecutionResult(
                test_case_id="",
                execution_status="pending"
            )

    @property
    def current_coverage(self) -> float:
        """Get current coverage percentage from execution result."""
        if self.execution_result and hasattr(self.execution_result, 'coverage_summary'):
            coverage = self.execution_result.coverage_summary
            if coverage:
                # Try to get line coverage as default
                return coverage.get("line", 0.0)
        return 0.0

    @property
    def uncovered_lines(self) -> List[int]:
        """Get uncovered lines from execution result."""
        if self.execution_result and hasattr(self.execution_result, 'uncovered_lines'):
            return self.execution_result.uncovered_lines or []
        return []

    @property
    def uncovered_branches(self) -> List[str]:
        """Get uncovered branches from execution result."""
        if self.execution_result and hasattr(self.execution_result, 'uncovered_branches'):
            return self.execution_result.uncovered_branches or []
        return []

    def to_routing_context(self) -> RoutingContext:
        """Convert to standard RoutingContext."""
        return RoutingContext(
            current_coverage=self.current_coverage,
            stagnation_cycles=self.stagnation_cycles,
            tool_performance=self.tool_performance,
        )


__all__ = [
    "RoutingStrategy",
    "RoutingContext",
    "LLMRoutingContext",
]
