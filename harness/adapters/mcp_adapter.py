"""
MCP Protocol Adapter

Adapter layer for Model Context Protocol (MCP) integration.
Converts between MCP tool calls and PLCHaT's internal protocol.

Design Principles:
- Single Responsibility: Only handles protocol conversion
- Decoupled: Core tools don't depend on MCP
- Extensible: Easy to add support for other protocols
"""

import json
import logging
from typing import Any, Dict, Optional, List
from dataclasses import dataclass, asdict

from core.protocols import ToolCallRequest, ActionResponse, ActionType
from harness.routing.router import ToolRouter
from harness.routing.base import ToolType


logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """MCP tool definition."""

    name: str
    description: str
    input_schema: Dict[str, Any]


@dataclass
class MCPToolCall:
    """MCP tool call request."""

    tool_name: str
    arguments: Dict[str, Any]
    call_id: Optional[str] = None


@dataclass
class MCPToolResult:
    """MCP tool call result."""

    content: List[Dict[str, Any]]
    is_error: bool = False
    error_message: Optional[str] = None
    call_id: Optional[str] = None


class MCPAdapter:
    """
    Adapter for MCP protocol integration.

    Converts MCP tool calls into PLCHaT's ToolCallRequest,
    and converts ActionResponse back to MCP format.

    Usage:
        adapter = MCPAdapter(router)
        mcp_result = adapter.handle_call(mcp_call)
    """

    def __init__(self, router: ToolRouter):
        """
        Initialize the MCP adapter.

        Args:
            router: The PLCHaT tool router to delegate to.
        """
        self._router = router
        self._tool_mapping = self._build_tool_mapping()

    def _build_tool_mapping(self) -> Dict[str, ActionType]:
        """
        Build mapping from MCP tool names to PLCHaT action types.

        Returns:
            Dictionary mapping tool names to action types.
        """
        return {
            "smt_solve": ActionType.GENERATE,
            "dse_explore": ActionType.GENERATE,
            "random_fuzz": ActionType.GENERATE,
            "mutate_test": ActionType.GENERATE,
            "execute_test": ActionType.EXECUTE,
            "analyze_result": ActionType.ANALYZE,
            "get_coverage": ActionType.GET_COVERAGE,
        }

    def _mcp_to_plchat_tool_name(self, mcp_tool_name: str) -> str:
        """
        Map MCP tool names to PLCHaT tool names.

        Args:
            mcp_tool_name: MCP tool name.

        Returns:
            PLCHaT tool name.
        """
        mapping = {
            "smt_solve": "smt",
            "dse_explore": "dse",
            "random_fuzz": "random",
            "mutate_test": "mutation",
            "execute_test": "executor",
            "analyze_result": "analyzer",
            "get_coverage": "coverage_manager",
        }
        return mapping.get(mcp_tool_name, mcp_tool_name)

    def _mcp_to_tool_type(self, mcp_tool_name: str) -> Optional[ToolType]:
        """
        Map MCP tool names to ToolType enum.

        Args:
            mcp_tool_name: MCP tool name.

        Returns:
            ToolType or None.
        """
        mapping = {
            "smt_solve": ToolType.SMT_SOLVER,
            "dse_explore": ToolType.DSE_ENGINE,
            "random_fuzz": ToolType.RANDOM_FUZZER,
            "mutate_test": ToolType.MUTATION_ENGINE,
            "execute_test": None,  # Uses executor
            "analyze_result": None,  # Uses analyzer
            "get_coverage": None,  # Uses coverage_manager
        }
        return mapping.get(mcp_tool_name)

    def list_tools(self) -> List[MCPTool]:
        """
        List available tools in MCP format.

        Returns:
            List of MCP tool definitions.
        """
        tools = []

        # SMT Solver
        tools.append(MCPTool(
            name="smt_solve",
            description="Generate test cases using SMT solver to reach specific code locations",
            input_schema={
                "type": "object",
                "properties": {
                    "target_st_path": {"type": "string"},
                    "target_branch": {"type": "string"},
                    "max_cases": {"type": "integer", "default": 10},
                },
                "required": ["target_st_path", "target_branch"],
            }
        ))

        # DSE Explorer
        tools.append(MCPTool(
            name="dse_explore",
            description="Explore execution paths using dynamic symbolic execution",
            input_schema={
                "type": "object",
                "properties": {
                    "target_st_path": {"type": "string"},
                    "entry_point": {"type": "string"},
                    "depth": {"type": "integer", "default": 5},
                },
                "required": ["target_st_path"],
            }
        ))

        # Random Fuzzer
        tools.append(MCPTool(
            name="random_fuzz",
            description="Generate random test cases for broad exploration",
            input_schema={
                "type": "object",
                "properties": {
                    "target_st_path": {"type": "string"},
                    "num_cases": {"type": "integer", "default": 100},
                },
                "required": ["target_st_path"],
            }
        ))

        # Mutation Fuzzer
        tools.append(MCPTool(
            name="mutate_test",
            description="Mutate existing test cases using AFL-style mutations",
            input_schema={
                "type": "object",
                "properties": {
                    "base_test_id": {"type": "string"},
                    "num_mutations": {"type": "integer", "default": 10},
                },
                "required": ["base_test_id"],
            }
        ))

        # Execute Test
        tools.append(MCPTool(
            name="execute_test",
            description="Execute a specific test case and collect results",
            input_schema={
                "type": "object",
                "properties": {
                    "test_case": {"type": "object"},
                    "target_st_path": {"type": "string"},
                    "cycles": {"type": "integer", "default": 10},
                },
                "required": ["test_case", "target_st_path"],
            }
        ))

        # Get Coverage
        tools.append(MCPTool(
            name="get_coverage",
            description="Get current coverage information",
            input_schema={
                "type": "object",
                "properties": {
                    "coverage_type": {
                        "type": "string",
                        "enum": ["line", "branch", "all"],
                        "default": "all"
                    },
                },
            },
        ))

        return tools

    def handle_call(self, mcp_call: MCPToolCall) -> MCPToolResult:
        """
        Handle an MCP tool call.

        Args:
            mcp_call: The MCP tool call request.

        Returns:
            MCP tool result in MCP format.
        """
        try:
            # Convert MCP call to PLCHaT request
            request = self._convert_request(mcp_call)

            # Get tool hint for routing
            tool_hint = self._mcp_to_tool_type(mcp_call.tool_name)

            # Route through PLCHaT with tool hint
            response = self._router.route(request, tool_hint=tool_hint)

            # Convert PLCHaT response to MCP format
            return self._convert_response(response, mcp_call.call_id)

        except Exception as e:
            logger.error(f"MCP call failed: {e}")
            return MCPToolResult(
                content=[],
                is_error=True,
                error_message=str(e),
                call_id=mcp_call.call_id,
            )

    def _convert_request(self, mcp_call: MCPToolCall) -> ToolCallRequest:
        """
        Convert MCP tool call to PLCHaT request.

        Args:
            mcp_call: MCP tool call.

        Returns:
            PLCHaT ToolCallRequest.
        """
        action_type = self._tool_mapping.get(
            mcp_call.tool_name,
            ActionType.GENERATE
        )

        # Map MCP tool name to PLCHaT tool name
        plchat_tool_name = self._mcp_to_plchat_tool_name(mcp_call.tool_name)

        return ToolCallRequest(
            action_id=mcp_call.call_id or f"mcp_{mcp_call.tool_name}",
            action_type=action_type,
            tool_name=plchat_tool_name,
            parameters=mcp_call.arguments,
        )

    def _convert_response(
        self,
        response: ActionResponse,
        call_id: Optional[str] = None
    ) -> MCPToolResult:
        """
        Convert PLCHaT response to MCP format.

        Args:
            response: PLCHaT action response.
            call_id: Optional call ID for tracking.

        Returns:
            MCP tool result.
        """
        if response.status == "error":
            return MCPToolResult(
                content=[],
                is_error=True,
                error_message=response.error_message or "Unknown error",
                call_id=call_id,
            )

        # Format successful response
        content = [{
            "type": "text",
            "text": json.dumps({
                "action_id": response.action_id,
                "status": response.status,
                "data": response.data if hasattr(response, 'data') else {},
            }, indent=2)
        }]

        return MCPToolResult(
            content=content,
            is_error=False,
            call_id=call_id,
        )


__all__ = [
    "MCPTool",
    "MCPToolCall",
    "MCPToolResult",
    "MCPAdapter",
]
