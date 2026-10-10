"""
Tool Registry - Central tool registration and discovery.

Enables runtime tool registration and LangChain integration for Agents.
Supports both BaseTool implementations (decoupled) and LangChain @tool
decorated functions (coupled).
"""

from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass
from langchain_core.tools import StructuredTool

from core.protocols.action_protocol import ToolCallRequest, ActionType


@dataclass
class ToolSpec:
    """Tool specification for registry."""
    name: str
    description: str
    tool_type: str  # "basetool" | "langchain"
    implementation: Any  # BaseTool instance or Callable
    schema: Optional[Dict] = None


class ToolRegistry:
    """
    Central registry for tools.

    Supports:
    - BaseTool implementations (decoupled)
    - LangChain @tool decorated functions (coupled)
    - Runtime registration
    - LangChain tool conversion

    Example:
        from harness.registry import registry
        from tools.solvers import SMTTool

        registry.register(
            name="smt_solver",
            tool=SMTTool(benchmark_dir),
            description="SMT constraint solving"
        )

        # Get all as LangChain tools
        langchain_tools = registry.to_langchain_tools()
    """

    _instance: Optional['ToolRegistry'] = None
    _tools: Dict[str, ToolSpec] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(
        self,
        name: str,
        tool: Any,
        description: str = "",
        tool_type: str = "auto"
    ) -> None:
        """
        Register a tool.

        Args:
            name: Tool identifier
            tool: BaseTool instance or Callable
            description: Human-readable description
            tool_type: "basetool" | "langchain" | "auto"
        """
        if tool_type == "auto":
            # Detect type automatically
            if hasattr(tool, 'execute'):
                tool_type = "basetool"
            elif callable(tool):
                tool_type = "langchain"
            else:
                raise ValueError(f"Cannot auto-detect type for {name}")

        spec = ToolSpec(
            name=name,
            description=description,
            tool_type=tool_type,
            implementation=tool
        )
        self._tools[name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        """Get tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSpec]:
        """List all registered tools."""
        return list(self._tools.values())

    def to_langchain_tools(self) -> List:
        """
        Convert all tools to LangChain format.

        For BaseTool: wraps execute() in StructuredTool
        For @tool: returns as-is

        Returns:
            List of LangChain-compatible tools
        """
        langchain_tools = []

        for spec in self._tools.values():
            if spec.tool_type == "langchain":
                # Already a LangChain tool
                langchain_tools.append(spec.implementation)
            elif spec.tool_type == "basetool":
                # Wrap BaseTool.execute() with proper closure
                def make_wrapper(tool_spec, tool_impl, self_ref):
                    """Create wrapper with closure over spec and impl."""
                    def wrapped_tool(**kwargs):
                        request = ToolCallRequest(
                            action_id=tool_spec.name,
                            action_type=ActionType.GENERATE,
                            tool_name=tool_spec.name,
                            parameters=kwargs
                        )
                        response = tool_impl.execute(request)
                        return self_ref._format_response(response)

                    wrapped_tool.__name__ = tool_spec.name
                    wrapped_tool.__doc__ = tool_spec.description
                    return wrapped_tool

                wrapped_fn = make_wrapper(spec, spec.implementation, self)
                tool = StructuredTool.from_function(
                    func=wrapped_fn,
                    name=spec.name,
                    description=spec.description
                )
                langchain_tools.append(tool)

        return langchain_tools

    def _format_response(self, response) -> Any:
        """Format ActionResponse for LLM consumption."""
        # Check if response has test_cases
        if hasattr(response, 'data') and response.data:
            if "exp_ir" in response.data:
                return [response.data["exp_ir"]]
            elif "generated_cases" in response.data:
                return response.data["generated_cases"]
            return response.data
        # Return raw response
        return response

    def unregister(self, name: str) -> bool:
        """Remove tool from registry."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def clear(self) -> None:
        """Clear all registered tools."""
        self._tools.clear()


# Global singleton instance
registry = ToolRegistry()
