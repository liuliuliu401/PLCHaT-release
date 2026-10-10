"""
DSE Fuzzer Tool - Dynamic Symbolic Execution

Migrated from: baselines/dse/

Components:
- DSETool: BaseTool implementation for tool routing
- DSEEngine: Core symbolic execution engine
- DSEState: State management for DSE traversal
- DSEExecutorAdapter: Integration with PLCHaT execution infrastructure
"""

from harness.routing import ToolType, register_tool
from .dse_tool import DSETool
from .engine import DSEEngine
from .state import DSEState
from .executor_adapter import DSEExecutorAdapter, SimpleLogicBuilder
from .generator import DSECaseGenerator

# Register DSE Tool with global registry
register_tool(ToolType.DSE_ENGINE, DSETool)

__all__ = [
    "DSETool",
    "DSEEngine",
    "DSEState",
    "DSEExecutorAdapter",
    "SimpleLogicBuilder",
    "DSECaseGenerator",
]
