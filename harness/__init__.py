"""
PLCHaT Harness - Main Public Interface

This is PLCHaT's public entry point, only exports the most core classes and functions.

Main components:
- STCompiler: Unified compiler manager (recommended)
- ToolRouter: Tool routing system
- ViolationDetector: Violation detection oracle

Recommended usage:
    from harness import STCompiler, create_compiler

    compiler = create_compiler(benchmark_root="/path/to/benchmarks")
    result = compiler.execute(st_code="code.st", input_data="1 2 3")
"""

# ========== Core: Unified Compiler Manager ==========
from harness.st_compiler import STCompiler, create_compiler, check_environment

# ========== Tool Routing System (R Component) ==========
from harness.routing import (
    ToolRouter,
    ToolType,
    register_tool,
    set_benchmark_root,
)

# ========== Oracle (ℱ Component) ==========
from harness.oracle import (
    ViolationDetector,
    Violation,
    ViolationReport,
)

# ========== Compiler Components (Direct use, advanced usage) ==========
from harness.compiler import STCompilerCore

# ========== Adapters ==========
from harness.adapters import MCPAdapter

# ========== Test Analysis Components ==========
from harness.test_analysis import (
    TestAnalysisAgent,
    TestAnalysisToolManager,
    execute_with_assertions,
    collect_coverage_with_assertions,
)

__all__ = [
    # === Core API (Recommended) ===
    "STCompiler",
    "create_compiler",
    "check_environment",

    # === Tool Routing ===
    "ToolRouter",
    "ToolType",
    "register_tool",
    "set_benchmark_root",

    # === Oracle ===
    "ViolationDetector",
    "Violation",
    "ViolationReport",

    # === Compiler Core (Advanced usage) ===
    "STCompilerCore",

    # === Adapters ===
    "MCPAdapter",

    # === Test Analysis ===
    "TestAnalysisAgent",
    "TestAnalysisToolManager",
    "execute_with_assertions",
    "collect_coverage_with_assertions",
]


# Module information
__version__ = "1.0.0"
__author__ = "PLCHaT Team"
