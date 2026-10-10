"""
LLM-based Routing Policy

Uses LLM to intelligently select tools based on goal and context.
Compatible with MCP protocol format for tools/list and tools/call.

Design Principles:
- LLM as Router: Leverages LLM reasoning for tool selection
- MCP Compatible: Follows MCP tools/list format for tool descriptions
- Context Aware: Considers coverage, goal, and execution state
- Reuses Core Types: Uses existing types from core/protocols
"""

import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

from .base import ToolType
from .policies import BaseRoutingPolicy, RoutingContext

# Import core types for reuse
from core.protocols.feedback_protocol import ActionExecutionResult


logger = logging.getLogger(__name__)


# LLMRoutingContext is now defined in core/data_types/routing_types.py
# This avoids duplication and centralizes type definitions
from core.data_types.routing_types import LLMRoutingContext


class LLMPolicy(BaseRoutingPolicy):
    """
    LLM-based tool selection policy.

    Uses LLM reasoning to select the most appropriate tool based on:
    - Goal description
    - Current coverage state
    - Uncovered targets
    - Historical tool performance

    The LLM receives tool descriptions in MCP-compatible format.
    """

    # Tool descriptions in MCP format
    TOOL_DESCRIPTIONS = {
        ToolType.SMT_SOLVER: {
            "name": "smt",
            "description": "Symbolic execution using Z3 solver. Best for: arithmetic and logic constraints, precise boundary conditions, complex IF-conditions, state machine reasoning.",
        },
        ToolType.DSE_ENGINE: {
            "name": "dse",
            "description": "Dynamic Symbolic Execution. Best for: path exploration with concrete inputs, combining concrete and symbolic execution, complex branch conditions.",
        },
        ToolType.RANDOM_FUZZER: {
            "name": "random",
            "description": "Coverage-guided random fuzzing. Best for: rapid coverage exploration, breaking through plateaus, state space exploration, physical process simulation.",
        },
        ToolType.MUTATION_ENGINE: {
            "name": "mutation",
            "description": "AFL-style mutation engine. Best for: input mutation based testing, buffer overflow detection, format string vulnerabilities.",
        },
    }

    SYSTEM_PROMPT = """You are a Tool Selection Expert for a PLC fuzzing system.

Your task is to select the most appropriate tool for achieving a specific goal based on:
1. The goal description
2. Current coverage state
3. Tool capabilities

Available tools and their descriptions will be provided in the context.

Respond with ONLY the tool name (e.g., "smt", "dse", "random", "mutation").
No explanation, just the tool name."""

    def __init__(
        self,
        model: str = "gpt-4o-mini",
        api_key: str = None,
        base_url: str = None,
        temperature: float = 0.1
    ):
        """
        Initialize the LLM policy.

        Args:
            model: LLM model to use for routing decisions.
            api_key: OpenAI API key (defaults to config).
            base_url: API base URL (defaults to config).
            temperature: Temperature for LLM responses.
        """
        # Import config
        import sys
        from pathlib import Path

        # Project root resolution
        project_root = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(project_root))

        # Load config
        import importlib.util
        spec = importlib.util.spec_from_file_location("config", project_root / "config.py")
        config_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(config_module)

        router_model = getattr(config_module, "router_model", model)
        router_api_key = api_key or getattr(config_module, "router_api_key", None)
        router_base_url = base_url or getattr(config_module, "router_base_url", None)

        self.llm = ChatOpenAI(
            model=router_model,
            api_key=router_api_key,
            base_url=router_base_url,
            temperature=temperature,
        )

    def select_tool(
        self,
        available_tools: List[ToolType],
        context: RoutingContext
    ) -> Optional[ToolType]:
        """
        Select tool using LLM reasoning.

        Args:
            available_tools: List of available tool types.
            context: Current routing context.

        Returns:
            Selected tool type, or None if no suitable tool.
        """
        if not available_tools:
            return None

        # If only one tool available, use it
        if len(available_tools) == 1:
            return available_tools[0]

        # Build tool descriptions for available tools
        tool_descriptions = self._build_tool_descriptions(available_tools)

        # Build context string
        context_str = self._build_context_string(context)

        # Format prompt
        prompt = f"""[AVAILABLE TOOLS]
{tool_descriptions}

[CURRENT STATE]
{context_str}

Select the best tool for the current situation."""

        try:
            # Call LLM
            response = self.llm.invoke([
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ])

            # Parse response
            selected_name = response.content.strip().strip('"').strip("'").lower()

            # Map to ToolType
            return self._name_to_tool_type(selected_name, available_tools)

        except Exception as e:
            logger.error(f"LLM routing failed: {e}")
            # Fallback to first available tool
            return available_tools[0]

    def select_tool_with_goal(
        self,
        available_tools: List[ToolType],
        llm_context: LLMRoutingContext
    ) -> Optional[ToolType]:
        """
        Select tool using LLM with explicit goal information.

        This is the recommended method for goal-oriented routing.

        Args:
            available_tools: List of available tool types.
            llm_context: Extended context with goal information.

        Returns:
            Selected tool type, or None if no suitable tool.
        """
        if not available_tools:
            return None

        if len(available_tools) == 1:
            return available_tools[0]

        # Build tool descriptions
        tool_descriptions = self._build_tool_descriptions(available_tools)

        # Build context with goal
        context_str = self._build_llm_context_string(llm_context)

        prompt = f"""[AVAILABLE TOOLS]
{tool_descriptions}

[CURRENT STATE]
{context_str}

Select the best tool to achieve the goal."""

        try:
            response = self.llm.invoke([
                SystemMessage(content=self.SYSTEM_PROMPT),
                HumanMessage(content=prompt)
            ])

            selected_name = response.content.strip().strip('"').strip("'").lower()
            logger.info(f"LLM selected tool: {selected_name}")

            return self._name_to_tool_type(selected_name, available_tools)

        except Exception as e:
            logger.error(f"LLM routing with goal failed: {e}")
            return available_tools[0]

    def _build_tool_descriptions(self, available_tools: List[ToolType]) -> str:
        """Build tool descriptions in MCP format."""
        lines = []
        for tool_type in available_tools:
            desc = self.TOOL_DESCRIPTIONS.get(tool_type, {
                "name": tool_type.value,
                "description": f"{tool_type.value} tool"
            })
            lines.append(f"- {desc['name']}: {desc['description']}")
        return "\n".join(lines)

    def _build_context_string(self, context: RoutingContext) -> str:
        """Build context string from RoutingContext."""
        lines = [
            f"Current Coverage: {context.current_coverage * 100:.1f}%",
            f"Stagnation Cycles: {context.stagnation_cycles}",
        ]

        if context.task_archetype:
            lines.append(f"Task Archetype: {context.task_archetype}")

        if context.tool_performance:
            lines.append("Tool Performance:")
            for tool, score in context.tool_performance.items():
                lines.append(f"  - {tool}: {score:.2f}")

        return "\n".join(lines)

    def _build_llm_context_string(self, context: LLMRoutingContext) -> str:
        """Build context string from LLMRoutingContext."""
        lines = [
            f"Goal: {context.goal}",
            f"Current Coverage: {context.current_coverage * 100:.1f}%",
            f"Stagnation Cycles: {context.stagnation_cycles}",
            f"Iteration: {context.iteration}",
        ]

        uncovered_lines = context.uncovered_lines
        if uncovered_lines:
            lines.append(f"Uncovered Lines (first 10): {uncovered_lines[:10]}")

        uncovered_branches = context.uncovered_branches
        if uncovered_branches:
            lines.append(f"Uncovered Branches (first 5): {uncovered_branches[:5]}")

        violations = context.violations_found
        if violations > 0:
            lines.append(f"Violations Found: {violations}")

        if context.tool_performance:
            lines.append("Tool Performance:")
            for tool, score in context.tool_performance.items():
                lines.append(f"  - {tool}: {score:.2f}")

        return "\n".join(lines)

    def _name_to_tool_type(
        self,
        name: str,
        available_tools: List[ToolType]
    ) -> Optional[ToolType]:
        """Map tool name to ToolType."""
        name_lower = name.lower()
        name_to_type = {t.value: t for t in available_tools}

        # Direct match (case-insensitive)
        for tool_type in available_tools:
            if name_lower == tool_type.value.lower():
                return tool_type

        # Fuzzy match (case-insensitive)
        for tool_type in available_tools:
            if name_lower in tool_type.value.lower() or tool_type.value.lower() in name_lower:
                return tool_type

        # Default to first available
        logger.warning(f"Unknown tool name '{name}', using first available")
        return available_tools[0]

    def list_tools_mcp(self) -> List[Dict[str, Any]]:
        """
        List tools in MCP-compatible format.

        Returns a list of tool descriptors compatible with MCP tools/list response.
        """
        return [
            {
                "name": desc["name"],
                "description": desc["description"]
            }
            for desc in self.TOOL_DESCRIPTIONS.values()
        ]


__all__ = [
    "LLMPolicy",
    "LLMRoutingContext",
]
