"""
Random Fuzzer Tools (τrand)

Provides weighted random test case generation and fuzzing loop for PLC programs.
Migrated from baselines/random/ with full preservation of core logic.

Components:
- RandomCaseGenerator: Weighted random generation with magic number analysis
- RandomFuzzerTool: BaseTool-compliant fuzzer with coverage-guided adaptation
"""

from .generator import RandomCaseGenerator
from .fuzzer import RandomFuzzerTool

# Register with global ToolRegistry
from harness.routing import ToolType, register_tool

register_tool(ToolType.RANDOM_FUZZER, RandomFuzzerTool)

__all__ = [
    "RandomCaseGenerator",
    "RandomFuzzerTool",
]
