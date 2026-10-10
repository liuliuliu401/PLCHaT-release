"""
DSE Executor Adapter - Bridges DSE Engine with PLCHaT Execution Infrastructure

Provides:
- Symbolic execution logic generation
- Test case execution with coverage
- Result conversion to ExpUnifiedIR

Design:
- Wraps STCoverageCollector for real execution
- Provides symbolic execution interface for DSE
- Compatible with Random Fuzzer's execution model
"""

import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

from core.data_types.exp_types import ExpUnifiedIR
from harness.compiler.cache_manager import CacheManager

logger = logging.getLogger(__name__)


class DSEExecutorAdapter:
    """
    DSE Executor connecting DSE Engine with PLCHaT execution infrastructure.

    Provides test case execution with coverage collection (aligned with Random Fuzzer's PLCExecutor).
    """

    def __init__(
        self,
        project_root: str,
        debug: bool = False
    ):
        self.project_root = Path(project_root)
        self.debug = debug

        # Lazy import to avoid circular dependencies
        from harness.compiler.st_coverage_collector import STCoverageCollector
        from harness.compiler.utils import Logger, LEVEL

        self.logger = Logger(
            "/tmp/plchat_dse_executor",
            "dse_executor.log",
            level=LEVEL.DEBUG if debug else LEVEL.INFO
        )

        self._collector = STCoverageCollector(
            root_dir=str(self.project_root),
            logger=self.logger,
            debug=debug,
            force_rebuild=False
        )

    def _ensure_harness(self, task_name: str, st_path: Path) -> Path:
        """
        Auto-generate harness if missing (private method).

        Args:
            task_name: Benchmark task name
            st_path: Path to ST source file

        Returns:
            Path to harness.c file
        """
        # Lazy import
        from harness.compiler.generator.pipeline import HarnessPipeline

        pipeline = HarnessPipeline(
            logger=self.logger,
            debug=self.debug
        )

        # Generate harness using synthesize method
        task_path = st_path.parent.parent
        output_dir = task_path / "plc_c_files"
        output_dir.mkdir(parents=True, exist_ok=True)

        harness_result = pipeline.synthesize(
            st_path=st_path,
            output_dir=output_dir,
            force_rebuild=False
        )

        if harness_result.success and harness_result.harness_path:
            return harness_result.harness_path

        if harness_result and "harness_path" in harness_result:
            return Path(harness_result["harness_path"])

        # Fallback to conventional location
        task_dir = st_path.parent
        harness_path = task_dir / "plc_c_code" / "harness.c"
        if harness_path.exists():
            return harness_path

        raise FileNotFoundError(f"Cannot find or generate harness for {task_name}")

    def execute_test_cases(
        self,
        task_name: str,
        st_path: Path,
        test_cases: List[ExpUnifiedIR],
        harness_c_path: Optional[Path] = None,
        timeout_sec: int = 30
    ) -> Dict[str, Any]:
        """
        Execute a batch of test cases with coverage collection.

        Args:
            task_name: Benchmark task name
            st_path: Path to ST source file
            test_cases: List of ExpUnifiedIR test cases
            harness_c_path: Path to harness.c (None to auto-generate)
            timeout_sec: Execution timeout per batch

        Returns:
            Dict with coverage metrics and execution status
        """
        try:
            # Generate harness if missing (aligned with Random Fuzzer)
            if not harness_c_path or not harness_c_path.exists():
                harness_c_path = self._ensure_harness(task_name, st_path)

            # Convert test cases to harness input format
            input_list = []
            for tc in test_cases:
                try:
                    input_list.append(tc.to_harness_input())
                except Exception as e:
                    self.logger.warn_print(f"Failed to convert test case {tc.exp_id}: {e}")
                    input_list.append("")

            # Create temp directory for this execution (using CacheManager)
            temp_dir = CacheManager.get_temp_dir(f"dse_{task_name}")

            try:
                result = self._collector.execute_with_multiple_coverage(
                    st_code_input=str(st_path),
                    harness_input=str(harness_c_path),
                    input_data_list=input_list,
                    benchmark_case=task_name,
                    temp_dir=temp_dir,
                    output_format="StoredTestCase",
                    eval_timeout_sec=timeout_sec
                )

                # Extract coverage metrics
                cov_data = result.get("coverage_data")
                if cov_data and hasattr(cov_data, 'coverage_summary') and cov_data.coverage_summary:
                    summary = cov_data.coverage_summary
                    return {
                        "success": result.get("status") == "success",
                        "line_cov": summary.line_coverage.percentage or "0.0%",
                        "branch_cov": summary.branch_coverage.percentage or "0.0%",
                        "func_cov": summary.function_coverage.percentage or "0.0%",
                        "region_cov": summary.region_coverage.percentage or "0.0%",
                        "raw": cov_data
                    }
                elif cov_data and isinstance(cov_data, dict):
                    return {
                        "success": result.get("status") == "success",
                        "line_cov": f"{cov_data.get('line_percent', 0.0):.2f}%",
                        "branch_cov": f"{cov_data.get('branch_percent', 0.0):.2f}%",
                        "func_cov": f"{cov_data.get('function_percent', 0.0):.2f}%",
                        "raw": cov_data
                    }
                else:
                    return {
                        "success": result.get("status") == "success",
                        "line_cov": "0.00%",
                        "branch_cov": "0.00%",
                        "raw": result
                    }

            except Exception as e:
                logger.error(f"DSE batch execution failed: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "line_cov": "0.00%",
                    "branch_cov": "0.00%"
                }

        except Exception as e:
            logger.error(f"DSE executor setup failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "line_cov": "0.00%",
                "branch_cov": "0.00%"
            }


class SimpleLogicBuilder:
    """
    Simple symbolic logic builder for basic ST constructs.

    This is a minimal implementation for basic IF/ELSE logic.
    For full ST support, consider integrating with LLM-based transpiler
    or ST parser.
    """

    @staticmethod
    def build_mock_logic() -> Callable:
        """
        Build a mock logic function for testing.

        Returns a callable that follows the DSE logic function contract:
        def execute_st_logic(engine: DSEEngine, state: DSEState)
        """
        import z3
        from .state import DSEState

        def mock_motor_logic(engine, state: DSEState):
            """
            Mock motor starter logic for testing.

            Simulates:
                IF btn THEN counter := counter + 1; END_IF
                IF counter >= 2 THEN motor_on := TRUE; END_IF
            """
            # Initialize internal state only on first cycle
            if state.cycle == 1 and 'counter' not in state.internal_mem:
                state.internal_mem['counter'] = z3.IntVal(0)
                state.internal_mem['motor_on'] = z3.BoolVal(False)

            # Register current cycle input
            btn_sym = z3.Bool(f'btn_c{state.cycle}')
            state.add_input_symbol('btn', btn_sym)

            # Logic block 1: IF btn THEN counter := counter + 1
            s_btn_T, s_btn_F = engine.fork_if(
                state,
                state.input_mem['btn'] == True,
                "B_BTN_PRESSED",
                "B_BTN_RELEASED"
            )

            active_states_mid = []
            if s_btn_T:
                s_btn_T.internal_mem['counter'] = s_btn_T.internal_mem['counter'] + 1
                active_states_mid.append(s_btn_T)
            if s_btn_F:
                active_states_mid.append(s_btn_F)

            # Logic block 2: IF counter >= 2 THEN motor_on := TRUE
            for s in active_states_mid:
                s_mtr_T, s_mtr_F = engine.fork_if(
                    s,
                    s.internal_mem['counter'] >= 2,
                    "B_MOTOR_ACTIVATED",
                    "B_MOTOR_STANDBY"
                )

                # End cycle for all terminal paths
                if s_mtr_T:
                    s_mtr_T.internal_mem['motor_on'] = z3.BoolVal(True)
                    engine.end_cycle(s_mtr_T)
                if s_mtr_F:
                    engine.end_cycle(s_mtr_F)

        return mock_motor_logic


__all__ = ["DSEExecutorAdapter", "SimpleLogicBuilder"]
