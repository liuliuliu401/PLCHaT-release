"""
Base Tool Interface

Defines the abstract interface for all testing tools in PLCHaT.
This is the core abstraction that all concrete tools must implement.

Design Principles:
- Single Responsibility: Only defines tool execution contract
- Interface Segregation: Minimal method set
- Protocol Agnostic: Works with ToolCallRequest/ActionResponse
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass


class ToolType(str, Enum):
    """Enumeration of all tool types in PLCHaT."""

    SMT_SOLVER = "smt"              # τsmt: Symbolic execution
    DSE_ENGINE = "dse"              # τdse: Dynamic Symbolic Execution
    RANDOM_FUZZER = "random"        # τrand: Random fuzzing
    MUTATION_ENGINE = "mutation"    # τmut: AFL-style mutation
    EXECUTION_PARSER = "parser"     # τparse: Execution analysis


@dataclass
class ToolMetadata:
    """Metadata about a tool's capabilities."""

    name: str
    description: str
    version: str = "1.0.0"
    requires_coverage: bool = False
    max_execution_time: int = 300  # seconds
    supports_batch: bool = False


class BaseTool(ABC):
    """
    Abstract base class for all testing tools.

    All concrete tools (SMT, DSE, AFL, Random) must inherit from this class
    and implement the execute() method.

    The interface is intentionally minimal to keep it flexible:
    - execute(): Main entry point for tool invocation
    - metadata: Tool metadata (name, description, capabilities)
    """

    def __init__(self, benchmark_root: str):
        """
        Initialize the tool.

        Args:
            benchmark_root: Path to the benchmark directory containing ST programs.
        """
        self._benchmark_root = benchmark_root
        self._metadata: Optional[ToolMetadata] = None

    @abstractmethod
    def execute(
        self,
        request: "ToolCallRequest",
        context: Optional[Dict[str, Any]] = None
    ) -> "ActionResponse":
        """
        Execute the tool with the given request.

        Args:
            request: The tool call request from an agent.
            context: Additional execution context (coverage, state, etc.).

        Returns:
            ActionResponse: Standardized response with execution results.

        Raises:
            ToolExecutionError: If tool execution fails.
            ValidationError: If request parameters are invalid.
        """
        pass

    @property
    @abstractmethod
    def tool_type(self) -> ToolType:
        """Return the tool type identifier."""
        pass

    @property
    def metadata(self) -> ToolMetadata:
        """Return tool metadata."""
        if self._metadata is None:
            self._metadata = ToolMetadata(
                name=self.tool_type.value,
                description=f"PLCHaT {self.tool_type.value} tool"
            )
        return self._metadata

    def validate_request(self, request: "ToolCallRequest") -> bool:
        """
        Validate the tool call request.

        Default implementation checks tool name match.
        Override for custom validation logic.

        Args:
            request: The request to validate.

        Returns:
            True if valid, False otherwise.
        """
        return request.tool_name == self.tool_type.value

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(type={self.tool_type})"


class ToolExecutionError(Exception):
    """Exception raised when tool execution fails."""

    def __init__(self, tool_type: ToolType, message: str):
        self.tool_type = tool_type
        self.message = message
        super().__init__(f"[{tool_type.value}] {message}")


class ValidationError(Exception):
    """Exception raised when request validation fails."""

    def __init__(self, tool_type: ToolType, field: str, message: str):
        self.tool_type = tool_type
        self.field = field
        self.message = message
        super().__init__(f"[{tool_type.value}] {field}: {message}")


__all__ = [
    "ToolType",
    "ToolMetadata",
    "BaseTool",
    "ToolExecutionError",
    "ValidationError",
]
