"""
Tool Router

Main routing component (R) that dispatches requests to appropriate tools.
Implements the routing interface between agents and the tool suite.

Design Principles:
- Single Responsibility: Only handles routing logic
- Delegates execution to tool implementations
- Supports multiple routing strategies
"""

import logging
from typing import Optional, Dict, Any, List

from .base import BaseTool, ToolType, ToolExecutionError, ValidationError
from .registry import get_tool, list_tools
from .policies import (
    RoutingStrategy,
    RoutingContext,
    BaseRoutingPolicy,
    create_policy,
)
from core.protocols import ToolCallRequest, ActionResponse, create_action_response


logger = logging.getLogger(__name__)


class ToolRouter:
    """
    Main router for tool dispatch (R component).

    The router receives ToolCallRequest from agents, selects the appropriate
    tool based on routing policy, and returns ActionResponse.
    """

    def __init__(
        self,
        benchmark_root: str,
        default_strategy: RoutingStrategy = RoutingStrategy.PROTOTYPE_AWARE,
    ):
        """
        Initialize the tool router.

        Args:
            benchmark_root: Path to benchmark directory.
            default_strategy: Default routing strategy to use.
        """
        self._benchmark_root = benchmark_root
        self._default_strategy = default_strategy
        self._policies: Dict[RoutingStrategy, BaseRoutingPolicy] = {}

    def route(
        self,
        request: ToolCallRequest,
        strategy: Optional[RoutingStrategy] = None,
        context: Optional[RoutingContext] = None,
        tool_hint: Optional[ToolType] = None,
    ) -> ActionResponse:
        """
        Route a tool call request to the appropriate tool.

        Args:
            request: The tool call request from an agent.
            strategy: Routing strategy to use (default: default_strategy).
            context: Routing context for decision making.
            tool_hint: Explicit tool hint (overrides routing).

        Returns:
            ActionResponse with tool execution results.

        Raises:
            ToolExecutionError: If tool execution fails.
            ValidationError: If request validation fails.
        """
        # Determine which tool to use
        tool_type = self._select_tool(
            request=request,
            strategy=strategy or self._default_strategy,
            context=context or RoutingContext(),
            tool_hint=tool_hint,
        )

        if tool_type is None:
            return create_action_response(
                action_id=request.action_id,
                status="error",
                error_message="No tool available for request",
            )

        # Get tool instance
        tool = get_tool(tool_type)
        if tool is None:
            return create_action_response(
                action_id=request.action_id,
                status="error",
                error_message=f"Tool not registered: {tool_type.value}",
            )

        # Validate request
        if not tool.validate_request(request):
            raise ValidationError(
                tool_type=tool_type,
                field="request",
                message="Request validation failed",
            )

        # Execute tool
        try:
            response = tool.execute(request, context=context if context else {})
            logger.info(f"Tool {tool_type.value} executed successfully")
            return response
        except Exception as e:
            logger.error(f"Tool {tool_type.value} execution failed: {e}")
            raise ToolExecutionError(tool_type=tool_type, message=str(e))

    def _select_tool(
        self,
        request: ToolCallRequest,
        strategy: RoutingStrategy,
        context: RoutingContext,
        tool_hint: Optional[ToolType],
    ) -> Optional[ToolType]:
        """Select appropriate tool for the request."""
        # Explicit tool hint takes precedence
        if tool_hint is not None:
            return tool_hint

        # Get policy
        if strategy not in self._policies:
            self._policies[strategy] = create_policy(strategy)

        policy = self._policies[strategy]

        # Get available tools
        available = list_tools()
        if not available:
            logger.warning("No tools registered")
            return None

        # Select based on policy
        return policy.select_tool(available, context)

    def list_available_tools(self) -> List[ToolType]:
        """List all available tool types."""
        return list_tools()

    def get_tool_info(self, tool_type: ToolType) -> Optional[Dict[str, Any]]:
        """Get metadata about a specific tool."""
        tool = get_tool(tool_type)
        if tool is None:
            return None

        return {
            "type": tool_type.value,
            "name": tool.metadata.name,
            "description": tool.metadata.description,
            "version": tool.metadata.version,
            "requires_coverage": tool.metadata.requires_coverage,
            "max_execution_time": tool.metadata.max_execution_time,
            "supports_batch": tool.metadata.supports_batch,
        }


__all__ = ["ToolRouter"]
