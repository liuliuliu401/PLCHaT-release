"""
Solvers Module - Symbolic Execution Tools

Provides SMT solving capabilities using Z3:
- Z3Engine: Z3 constraint solver backend
- LLMSemanticSlicer: LLM-based constraint generation from ST code
- SMTTool: Unified tool implementing BaseTool interface

This module wraps the existing SolverTools
to maintain compatibility with the original implementation.
"""

# Import core components
from .z3_backend import Z3Engine, Z3_AVAILABLE

# LLMSemanticSlicer requires config variables that may not be set
try:
    from .llm_slicer import LLMSemanticSlicer
    _has_llm_slicer = True
except (ImportError, AttributeError):
    _has_llm_slicer = False
    LLMSemanticSlicer = None

from .smt_tool import SMTTool

# Register with global ToolRegistry
from harness.routing import ToolType, register_tool

register_tool(ToolType.SMT_SOLVER, SMTTool)

__all__ = [
    "Z3Engine",
    "Z3_AVAILABLE",
    "SMTTool",
]

# Conditionally add LLMSemanticSlicer if available
if _has_llm_slicer and LLMSemanticSlicer is not None:
    __all__.append("LLMSemanticSlicer")
