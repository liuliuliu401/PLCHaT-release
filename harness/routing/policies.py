"""
Routing Policies

Defines strategies for selecting tools based on context.
Implements coverage-guided, prototype-aware, and round-robin routing.

Design Principles:
- Single Responsibility: Only handles tool selection logic
- Strategy Pattern: Pluggable routing strategies
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
import random

from .base import ToolType

# Import routing types from core - use direct import to avoid Enum conflicts
from core.data_types.routing_types import (
    RoutingStrategy,
    RoutingContext
)


class BaseRoutingPolicy(ABC):
    """Abstract base for routing policies."""

    @abstractmethod
    def select_tool(
        self,
        available_tools: List[ToolType],
        context: RoutingContext
    ) -> Optional[ToolType]:
        """
        Select a tool based on the policy.

        Args:
            available_tools: List of available tool types.
            context: Current routing context.

        Returns:
            Selected tool type, or None if no tool should be used.
        """
        pass


class CoverageGuidedPolicy(BaseRoutingPolicy):
    """
    Route tools based on coverage stagnation.

    Strategy:
    - If coverage is stagnant (no growth for N cycles), switch tools
    - Prefer tools that have historically improved coverage
    """

    def __init__(self, stagnation_threshold: int = 3):
        """
        Initialize the coverage-guided policy.

        Args:
            stagnation_threshold: Cycles of stagnation before switching.
        """
        self.stagnation_threshold = stagnation_threshold

    def select_tool(
        self,
        available_tools: List[ToolType],
        context: RoutingContext
    ) -> Optional[ToolType]:
        """Select tool based on coverage analysis."""
        if not available_tools:
            return None

        # If coverage is growing, continue with current approach
        if len(context.coverage_history) >= 2:
            recent_growth = context.coverage_history[-1] - context.coverage_history[-2]
            if recent_growth > 0:
                context.stagnation_cycles = 0
                # Return the tool that performed best
                return self._best_performing_tool(available_tools, context)

        # Check for stagnation
        if context.stagnation_cycles >= self.stagnation_threshold:
            # Switch to a different tool
            context.stagnation_cycles = 0
            return self._switch_tool(available_tools, context)

        context.stagnation_cycles += 1

        # Default: prefer SMT for white-box scenarios
        if ToolType.SMT_SOLVER in available_tools and context.require_symbolic:
            return ToolType.SMT_SOLVER

        # Otherwise, return first available
        return available_tools[0]

    def _best_performing_tool(
        self,
        available_tools: List[ToolType],
        context: RoutingContext
    ) -> Optional[ToolType]:
        """Get the tool with best historical performance."""
        best_tool = None
        best_score = -1.0

        for tool_type in available_tools:
            score = context.tool_performance.get(tool_type.value, 0.0)
            if score > best_score:
                best_score = score
                best_tool = tool_type

        return best_tool

    def _switch_tool(
        self,
        available_tools: List[ToolType],
        context: RoutingContext
    ) -> ToolType:
        """Switch to a different tool."""
        # Simple strategy: cycle through available tools
        if context.tool_performance:
            # Pick a tool that hasn't been tried recently
            for tool_type in available_tools:
                if tool_type.value not in context.tool_performance:
                    return tool_type

        # Fallback: random selection
        return random.choice(available_tools)


class PrototypeAwarePolicy(BaseRoutingPolicy):
    """
    Route tools based on task archetype/prototype.

    Strategy:
    - State machine tasks → SMT/DSE
    - Physical process tasks → Random/Mutation
    - Exploration tasks → Random/AFL
    - Deep reasoning tasks → SMT
    """

    # Archetype to tool mapping
    ARCHETYPE_MAPPING = {
        "state_machine": [ToolType.SMT_SOLVER, ToolType.DSE_ENGINE],
        "physical_process": [ToolType.RANDOM_FUZZER, ToolType.MUTATION_ENGINE],
        "exploration": [ToolType.RANDOM_FUZZER, ToolType.MUTATION_ENGINE],
        "deep_reasoning": [ToolType.SMT_SOLVER, ToolType.DSE_ENGINE],
    }

    def select_tool(
        self,
        available_tools: List[ToolType],
        context: RoutingContext
    ) -> Optional[ToolType]:
        """Select tool based on task archetype."""
        if not available_tools:
            return None

        archetype = context.task_archetype
        if not archetype:
            # Fallback to random selection
            return random.choice(available_tools)

        # Get preferred tools for archetype
        preferred_tools = self.ARCHETYPE_MAPPING.get(
            archetype,
            available_tools
        )

        # Find first available preferred tool
        for tool_type in preferred_tools:
            if tool_type in available_tools:
                return tool_type

        # Fallback to first available
        return available_tools[0]


class RoundRobinPolicy(BaseRoutingPolicy):
    """Simple round-robin routing through available tools."""

    def __init__(self):
        """Initialize the round-robin policy."""
        self._current_index = 0

    def select_tool(
        self,
        available_tools: List[ToolType],
        context: RoutingContext
    ) -> Optional[ToolType]:
        """Select next tool in round-robin fashion."""
        if not available_tools:
            return None

        tool = available_tools[self._current_index % len(available_tools)]
        self._current_index += 1
        return tool


class ManualPolicy(BaseRoutingPolicy):
    """
    Manual tool selection (tool specified in request).
    """

    def select_tool(
        self,
        available_tools: List[ToolType],
        context: RoutingContext
    ) -> Optional[ToolType]:
        """
        Select tool - returns None to indicate manual selection.

        The caller should use the tool_hint from the request.
        """
        return None  # Indicates manual selection


def create_policy(
    strategy: RoutingStrategy,
    **policy_kwargs
) -> BaseRoutingPolicy:
    """
    Factory function to create a routing policy.

    Args:
        strategy: The desired routing strategy.
        **policy_kwargs: Additional arguments for policy initialization.

    Returns:
        An instance of the corresponding policy.

    Raises:
        ValueError: If strategy is unknown.
    """
    policies = {
        RoutingStrategy.COVERAGE_GUIDED: CoverageGuidedPolicy,
        RoutingStrategy.PROTOTYPE_AWARE: PrototypeAwarePolicy,
        RoutingStrategy.ROUND_ROBIN: RoundRobinPolicy,
        RoutingStrategy.MANUAL: ManualPolicy,
    }

    # Handle LLM policy separately (requires lazy import to avoid circular dependency)
    if strategy == RoutingStrategy.LLM:
        from .llm_policy import LLMPolicy
        return LLMPolicy(**policy_kwargs)

    policy_class = policies.get(strategy)
    if policy_class is None:
        raise ValueError(f"Unknown routing strategy: {strategy}")

    return policy_class(**policy_kwargs)


__all__ = [
    "RoutingStrategy",
    "RoutingContext",
    "BaseRoutingPolicy",
    "CoverageGuidedPolicy",
    "PrototypeAwarePolicy",
    "RoundRobinPolicy",
    "ManualPolicy",
    "create_policy",
]
