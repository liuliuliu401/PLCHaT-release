"""
Tool Registry

Central registry for managing available tools.
Provides tool lookup and lifecycle management.

Design Principles:
- Single Responsibility: Only manages tool registration/lookup
- Thread-Safe: Uses locking for concurrent access
"""

from typing import Dict, Optional, Type, List
from threading import Lock
import logging

from .base import BaseTool, ToolType


logger = logging.getLogger(__name__)


class ToolRegistry:
    """
    Central registry for tool implementations.

    Maintains a mapping of ToolType to concrete tool classes,
    and manages tool instantiation.
    """

    _instance: Optional["ToolRegistry"] = None
    _lock = Lock()

    def __new__(cls):
        """Singleton pattern to ensure single registry."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """Initialize the registry."""
        if self._initialized:
            return

        self._tools: Dict[ToolType, Type[BaseTool]] = {}
        self._instances: Dict[ToolType, BaseTool] = {}
        self._benchmark_root: Optional[str] = None
        self._initialized = True

    def register(
        self,
        tool_type: ToolType,
        tool_class: Type[BaseTool]
    ) -> None:
        """
        Register a tool implementation.

        Args:
            tool_type: The tool type identifier.
            tool_class: The tool implementation class.

        Raises:
            TypeError: If tool_class doesn't inherit BaseTool.
        """
        if not issubclass(tool_class, BaseTool):
            raise TypeError(
                f"Tool class must inherit BaseTool, got {tool_class}"
            )

        self._tools[tool_type] = tool_class
        logger.info(f"Registered tool: {tool_type.value} -> {tool_class.__name__}")

    def get_tool_class(self, tool_type: ToolType) -> Optional[Type[BaseTool]]:
        """
        Get a tool class by type.

        Args:
            tool_type: The tool type to look up.

        Returns:
            The tool class if found, None otherwise.
        """
        return self._tools.get(tool_type)

    def get_tool(self, tool_type: ToolType) -> Optional[BaseTool]:
        """
        Get a tool instance by type.

        Creates a singleton instance per tool type on first access.

        Args:
            tool_type: The tool type to get.

        Returns:
            The tool instance if found and configured, None otherwise.
        """
        if tool_type in self._instances:
            return self._instances[tool_type]

        tool_class = self._tools.get(tool_type)
        if tool_class is None:
            return None

        if self._benchmark_root is None:
            logger.warning("Benchmark root not set, cannot instantiate tool")
            return None

        try:
            instance = tool_class(self._benchmark_root)
            self._instances[tool_type] = instance
            return instance
        except Exception as e:
            logger.error(f"Failed to instantiate {tool_type.value}: {e}")
            return None

    def set_benchmark_root(self, path: str) -> None:
        """
        Set the benchmark root path for tool instantiation.

        Args:
            path: Path to the benchmark directory.
        """
        self._benchmark_root = path
        # Clear existing instances since they may have old path
        self._instances.clear()

    def list_tools(self) -> List[ToolType]:
        """List all registered tool types."""
        return list(self._tools.keys())

    def is_registered(self, tool_type: ToolType) -> bool:
        """Check if a tool type is registered."""
        return tool_type in self._tools


# Global registry instance
_registry = ToolRegistry()


def register_tool(tool_type: ToolType, tool_class: Type[BaseTool]) -> None:
    """Register a tool with the global registry."""
    _registry.register(tool_type, tool_class)


def get_tool(tool_type: ToolType) -> Optional[BaseTool]:
    """Get a tool instance from the global registry."""
    return _registry.get_tool(tool_type)


def set_benchmark_root(path: str) -> None:
    """Set benchmark root for the global registry."""
    _registry.set_benchmark_root(path)


def list_tools() -> List[ToolType]:
    """List all registered tools in the global registry."""
    return _registry.list_tools()


__all__ = [
    "ToolRegistry",
    "register_tool",
    "get_tool",
    "set_benchmark_root",
    "list_tools",
]
