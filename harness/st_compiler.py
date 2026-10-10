"""
PLCHaT ST Compiler - Public Manager

Unified public manager integrating all compiler and tool components.
This is the main entry point for users to use PLCHaT.

Similar to the original st_compiler_manager.py, provides:
- Compiler management (STCompilerCore)
- Tool routing (ToolRouter)
- Oracle (ViolationDetector)
- Adapters (MCPAdapter)

Usage:
    from harness.st_compiler import STCompiler

    compiler = STCompiler(benchmark_root="/path/to/benchmarks")

    # Execute ST code
    result = compiler.execute(st_code="code.st", input_data="1 2 3")

    # Coverage analysis
    coverage = compiler.measure(st_code="code.st", input_data="1 2 3")
"""

import os
from pathlib import Path
from typing import Optional, Dict, Any, List, Union

# Project root: st_compiler.py → harness → PROJECT_ROOT (1 parent up? No, st_compiler.py is in harness/)
# Structure: PROJECT_ROOT/harness/st_compiler.py
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Compiler components
from harness.compiler.st_compiler_core import STCompilerCore

# Routing
from harness.routing import ToolRouter, ToolType, register_tool, set_benchmark_root

# Oracle
from harness.oracle import ViolationDetector

# Adapters
from harness.adapters import MCPAdapter


class STCompiler:
    """
    PLCHaT Unified Compiler Manager

    Integrates all components, provides a concise high-level API.
    This is the main entry point for users to use PLCHaT.
    """

    def __init__(
        self,
        benchmark_root: Optional[str] = None,
        root_dir: Optional[str] = None,
        debug: bool = False
    ):
        """
        Initialize STCompiler manager

        Args:
            benchmark_root: Benchmark root directory
            root_dir: Project root directory
            debug: Enable debug mode
        """
        self.root_dir = root_dir or str(PROJECT_ROOT)
        self.benchmark_root = benchmark_root or os.path.join(self.root_dir, "benchmarks")
        self.debug = debug

        # Initialize compiler core
        self.compiler_core = STCompilerCore(
            benchmark_root=self.benchmark_root,
            root_dir=self.root_dir,
            debug=debug
        )

        # Initialize tool router
        self.tool_router = ToolRouter(
            benchmark_root=self.benchmark_root
        )

        # Initialize oracle
        self.violation_detector = ViolationDetector()

        # Initialize adapter
        self.mcp_adapter = MCPAdapter(router=self.tool_router)

        # Set global benchmark root directory
        set_benchmark_root(self.benchmark_root)

    # ==================== Environment ====================

    def check_environment(self) -> Dict[str, Any]:
        """Check all environment dependencies"""
        env_check = self.compiler_core.check_environment()
        return {
            "compiler": env_check,
            "router": "available",
            "oracle": "available",
            "adapters": "available"
        }

    # ==================== Core Execution ====================

    def execute(
        self,
        st_code: Any,
        input_data: Any = None,
        harness: Any = None,
        timeout: int = 30,
        **kwargs
    ) -> Any:
        """
        Execute ST code

        Args:
            st_code: ST code (file path or content)
            input_data: Input data
            harness: C harness code
            timeout: Timeout period
            **kwargs: Other parameters

        Returns:
            Execution result
        """
        return self.compiler_core.execute_st_code(
            st_code_input=st_code,
            input_data=input_data,
            harness_input=harness,
            timeout=timeout,
            **kwargs
        )

    def validate_syntax(self, st_code: Any) -> Any:
        """Validate ST syntax"""
        return self.compiler_core.validate_st_syntax(st_code)

    # ==================== Coverage ====================

    def measure(
        self,
        st_code: Any,
        input_data: Any = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute ST code and collect coverage

        Args:
            st_code: ST code
            input_data: Input data
            **kwargs: Other parameters

        Returns:
            Coverage result
        """
        return self.compiler_core.execute_st_code_with_coverage(
            st_code_input=st_code,
            input_data=input_data,
            **kwargs
        )

    def measure_incremental(
        self,
        st_code: Any,
        input_data: Any = None,
        base_coverage: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute incremental coverage analysis"""
        return self.compiler_core.execute_st_code_with_incremental_coverage(
            st_code_input=st_code,
            input_data=input_data,
            base_coverage_dir=base_coverage,
            **kwargs
        )

    def measure_multiple(
        self,
        st_code: Any,
        input_data_list: List[Any] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Execute coverage analysis for multiple test cases"""
        return self.compiler_core.execute_st_code_with_multiple_coverage(
            st_code_input=st_code,
            input_data_list=input_data_list,
            **kwargs
        )

    # ==================== Batch Operations ====================

    def execute_multiple(
        self,
        st_code: Any,
        input_data_list: List[Any] = None,
        **kwargs
    ) -> Any:
        """Execute multiple test cases"""
        return self.compiler_core.execute_st_code_multiple_cases(
            st_code_input=st_code,
            input_data_list=input_data_list,
            **kwargs
        )

    def execute_incremental(
        self,
        st_code: Any,
        num_rounds: int = 3,
        **kwargs
    ) -> Any:
        """Execute incremental simulation"""
        return self.compiler_core.execute_incremental_simulation(
            st_code_input=st_code,
            num_rounds=num_rounds,
            **kwargs
        )

    # ==================== State Analysis ====================

    def analyze_state(
        self,
        execution_result: Any,
        analysis_type: str = "timeline"
    ) -> Dict[str, Any]:
        """
        Analyze state of execution result

        Args:
            execution_result: Execution result
            analysis_type: Analysis type (timeline, violations, summary)

        Returns:
            Analysis result
        """
        if analysis_type == "timeline":
            return self.compiler_core.extract_sparse_timeline(execution_result)
        elif analysis_type == "violations":
            return self.compiler_core.detect_violations(execution_result)
        elif analysis_type == "summary":
            return self.compiler_core.summarize_execution(execution_result)
        else:
            raise ValueError(f"Unknown analysis type: {analysis_type}")

    def detect_violations(self, execution_result: Any) -> Dict[str, Any]:
        """Detect violations in execution"""
        return self.compiler_core.detect_violations(execution_result)

    # ==================== Tool Routing ====================

    def route_tool(
        self,
        tool_type: ToolType,
        params: Dict[str, Any]
    ) -> Any:
        """
        Route tool request

        Args:
            tool_type: Tool type
            params: Tool parameters

        Returns:
            Tool execution result
        """
        return self.tool_router.route(tool_type, params)

    def register_tool(self, tool_type: ToolType, tool_class: Any) -> None:
        """Register new tool"""
        register_tool(tool_type, tool_class)

    # ==================== Adapters ====================

    def use_mcp(self) -> MCPAdapter:
        """Get MCP adapter"""
        return self.mcp_adapter

    # ==================== Utilities ====================

    def get_compiler_core(self) -> STCompilerCore:
        """Get underlying compiler core (advanced usage)"""
        return self.compiler_core

    def cleanup(self, temp_dir: str) -> None:
        """Clean up temporary files"""
        self.compiler_core.cleanup_temp_files(temp_dir)


# Convenience functions
def create_compiler(
    benchmark_root: Optional[str] = None,
    debug: bool = False
) -> STCompiler:
    """
    Convenience function to create STCompiler instance

    Args:
        benchmark_root: Benchmark root directory
        debug: Enable debug mode

    Returns:
        STCompiler: Compiler manager instance
    """
    return STCompiler(benchmark_root=benchmark_root, debug=debug)


# Check environment
def check_environment(
    benchmark_root: Optional[str] = None
) -> Dict[str, Any]:
    """
    Convenience function to check PLCHaT environment

    Args:
        benchmark_root: Benchmark root directory

    Returns:
        Environment check result
    """
    compiler = create_compiler(benchmark_root=benchmark_root)
    return compiler.check_environment()


__all__ = [
    "STCompiler",
    "create_compiler",
    "check_environment"
]
