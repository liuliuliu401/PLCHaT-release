"""
Random Fuzzer Tool - Coverage-Guided Random Fuzzing for PLC Programs

Implements BaseTool interface for random fuzzing with:
- Coverage-guided depth adaptation
- Batch processing with greedy selection
- Stagnation detection and depth increase
- Real coverage collection via STCoverageCollector

Migrated from: baselines/random/fuzzer.py
"""

import json
import logging
import random
import sys
import threading
import time
import uuid
import tempfile
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from harness.routing.base import (
    BaseTool,
    ToolType,
    ToolMetadata,
    ToolExecutionError,
)
from core.protocols.action_protocol import ToolCallRequest
from core.protocols.feedback_protocol import ActionResponse, create_action_response
from core.data_types.exp_types import ExpUnifiedIR

from .generator import RandomCaseGenerator


class PLCExecutor:
    """
    Real PLC execution wrapper with coverage collection.

    Delegates to STCoverageCollector for real execution and coverage metrics.
    """

    def __init__(self, project_root: str, debug: bool = False):
        self.project_root = Path(project_root)
        self.debug = debug

        # Lazy import to avoid circular dependencies
        from harness.compiler.st_coverage_collector import STCoverageCollector
        from harness.compiler.utils import Logger, LEVEL

        self.logger = Logger(
            "/tmp/plchat_random_fuzzer",
            "random_fuzzer_executor.log",
            level=LEVEL.DEBUG if debug else LEVEL.INFO
        )

        self._collector = STCoverageCollector(
            root_dir=str(self.project_root),
            logger=self.logger,
            debug=debug,
            force_rebuild=False  # Use cache when available
        )

    def execute_batch(
        self,
        task_name: str,
        st_path: Path,
        harness_c_path: Optional[Path],
        schema_path: Path,
        test_cases: List[ExpUnifiedIR],
        timeout_sec: int = 30
    ) -> Dict[str, Any]:
        """
        Execute a batch of test cases with coverage collection.

        Args:
            task_name: Benchmark task name
            st_path: Path to ST source file
            harness_c_path: Path to harness.c (None to auto-generate)
            schema_path: Path to input_schema_v2.json
            test_cases: List of ExpUnifiedIR test cases
            timeout_sec: Execution timeout per batch

        Returns:
            Dict with coverage metrics and execution status
        """
        try:
            # Generate harness if missing
            if not harness_c_path or not harness_c_path.exists():
                harness_c_path = self._ensure_harness(task_name, st_path)

            # Convert test cases to harness input format
            input_list = []
            for tc in test_cases:
                try:
                    input_list.append(tc.to_harness_input())
                except Exception as e:
                    self.logger.warn_print(f"Failed to convert test case {tc.exp_id}: {e}")
                    input_list.append("")  # Empty input for failed conversions

            # Create temp directory for this execution
            temp_dir = tempfile.mkdtemp(prefix=f"plchat_fuzz_{task_name}_")

            try:
                # Execute with coverage
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
                    # CoverageReport object with CoverageSummary
                    summary = cov_data.coverage_summary
                    line_pct = summary.line_coverage.percentage or "0.0%"
                    branch_pct = summary.branch_coverage.percentage or "0.0%"
                    func_pct = summary.function_coverage.percentage or "0.0%"
                    region_pct = summary.region_coverage.percentage or "0.0%"

                    return {
                        "success": result.get("status") == "success",
                        "line_cov": line_pct,
                        "branch_cov": branch_pct,
                        "func_cov": func_pct,
                        "region_cov": region_pct,
                        "raw": cov_data
                    }
                elif cov_data and isinstance(cov_data, dict):
                    # Fallback for dict format
                    return {
                        "success": result.get("status") == "success",
                        "line_cov": f"{cov_data.get('line_percent', 0.0):.2f}%",
                        "branch_cov": f"{cov_data.get('branch_percent', 0.0):.2f}%",
                        "func_cov": f"{cov_data.get('function_percent', 0.0):.2f}%",
                        "raw": cov_data
                    }
                else:
                    # No coverage data available
                    return {
                        "success": result.get("status") == "success",
                        "line_cov": "0.00%",
                        "branch_cov": "0.00%",
                        "func_cov": "0.00%",
                        "error": "No coverage data returned"
                    }

            finally:
                # Cleanup temp directory
                try:
                    import shutil
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except:
                    pass

        except Exception as e:
            self.logger.error_print(f"Execution failed: {e}")
            # Return error status but don't crash the fuzzer
            return {
                "success": False,
                "line_cov": "0.00%",
                "branch_cov": "0.00%",
                "func_cov": "0.00%",
                "error": str(e)
            }

    def _ensure_harness(self, task_name: str, st_path: Path) -> Path:
        """Generate harness if missing using HarnessPipeline."""
        task_path = st_path.parent.parent
        harness_c_path = task_path / "plc_c_files" / "harness.c"

        if harness_c_path.exists():
            return harness_c_path

        try:
            from harness.compiler.generator.pipeline import HarnessPipeline

            output_dir = task_path / "plc_c_files"
            pipeline = HarnessPipeline(debug=self.debug, logger=self.logger)

            synthesis_result = pipeline.synthesize(st_path, output_dir)

            if synthesis_result.success:
                return synthesis_result.harness_path
            else:
                raise RuntimeError(f"Harness generation failed: {synthesis_result.error}")

        except Exception as e:
            self.logger.error_print(f"Failed to generate harness: {e}")
            raise


class RandomFuzzerTool(BaseTool):
    """
    Random Fuzzer Tool (τrand) with BaseTool interface.

    Features:
    - Coverage-guided depth adaptation (ICSQuartz style)
    - Batch processing with greedy selection
    - Stagnation detection and automatic depth increase
    - Async coverage auditing for high throughput

    Parameters via ToolCallRequest.parameters:
        - task_name: Benchmark task name (e.g., "232_ShiftSequence")
        - st_code: ST source code (optional, will read from file if not provided)
        - schema_path: Path to input schema JSON
        - max_depth: Maximum exploration depth (default 100)
        - plateau_limit: Stagnation threshold before depth increase (default 20)
        - scan_cycle_ms: Scan cycle duration in ms (default 50)
        - max_runtime_sec: Maximum runtime in seconds (default 600)
        - batch_size: Batch processing size (default 1)
        - max_cycles: Maximum cycles per test case (default 50)
        - max_iterations: Maximum iterations to run (optional)
    """

    def __init__(self, benchmark_root: str):
        """
        Initialize the Random Fuzzer Tool.

        Args:
            benchmark_root: Path to benchmark directory
        """
        super().__init__(benchmark_root)
        self._metadata = ToolMetadata(
            name="random",
            description="Coverage-guided random fuzzer with weighted sampling",
            version="1.0.0",
            requires_coverage=True,
            max_execution_time=600,
            supports_batch=True
        )

        # Core components
        self._generator = RandomCaseGenerator()
        self._executor = PLCExecutor(benchmark_root)

    @property
    def tool_type(self) -> ToolType:
        """Return random fuzzer tool type."""
        return ToolType.RANDOM_FUZZER

    def execute(
        self,
        request: ToolCallRequest,
        context: Optional[Dict[str, Any]] = None
    ) -> ActionResponse:
        """
        Execute random fuzzing with the given request.

        Args:
            request: Tool call request with parameters (see class docstring)
            context: Additional execution context (coverage info, etc.)

        Returns:
            ActionResponse with:
                - Generated test cases (ExpUnifiedIR format)
                - Coverage statistics
                - Execution metadata
        """
        start_time = time.time()

        try:
            # Extract parameters
            task_name = request.parameters.get("task_name")
            if not task_name:
                raise ToolExecutionError(
                    self.tool_type,
                    "Missing 'task_name' parameter"
                )

            # Configuration
            max_depth = request.parameters.get("max_depth", 100)
            plateau_limit = request.parameters.get("plateau_limit", 20)
            scan_cycle_ms = request.parameters.get("scan_cycle_ms", 50)
            max_runtime_sec = request.parameters.get("max_runtime_sec", 600)
            batch_size = request.parameters.get("batch_size", 1)
            max_cycles = request.parameters.get("max_cycles", 50)
            max_iterations = request.parameters.get("max_iterations")

            # Resolve paths
            task_path = Path(self._benchmark_root) / task_name
            st_path = task_path / "plc_st_files" / f"{task_name}.st"
            schema_path = task_path / "input" / "input_schema_v2.json"
            harness_c = task_path / "plc_c_files" / "harness.c"

            # Validate paths
            if not st_path.exists():
                raise ToolExecutionError(
                    self.tool_type,
                    f"ST file not found: {st_path}"
                )
            if not schema_path.exists():
                raise ToolExecutionError(
                    self.tool_type,
                    f"Schema file not found: {schema_path}"
                )

            # Load schema
            with open(schema_path, 'r') as f:
                schema_v2 = json.load(f)

            # Load ST code
            st_code = request.parameters.get("st_code")
            if st_code is None:
                st_code = st_path.read_text()

            # Initialize fuzzing state
            current_depth = 1
            consecutive_no_progress = 0
            max_line_cov = 0.0
            max_branch_cov = 0.0
            max_func_cov = 0.0
            max_region_cov = 0.0
            all_generated_cases: List[ExpUnifiedIR] = []

            # Statistics
            total_execs = 0
            total_rounds = 0
            valid_execs = 0
            unique_crashes = 0

            # Fuzzing loop
            i = 0
            while max_iterations is None or i < max_iterations:
                # Check timeout
                if time.time() - start_time > max_runtime_sec:
                    break

                # Determine batch size
                if max_iterations is None or max_iterations < 0:
                    curr_batch_size = batch_size
                else:
                    curr_batch_size = min(batch_size, max_iterations - i)

                actual_depth = min(current_depth, max_cycles)

                # Generate batch
                batch_ir_cases = []
                for b_idx in range(curr_batch_size):
                    sparse_timeline = {}
                    for cycle in range(actual_depth):
                        payload = self._generator.generate_case(st_code, schema_v2)
                        if payload:
                            sparse_timeline[cycle] = payload

                    batch_ir_cases.append(ExpUnifiedIR(
                        exp_id=f"{task_name}_iter_{i + b_idx}_{uuid.uuid4().hex[:6]}",
                        target_st_path=str(st_path),
                        schema_path=str(schema_path),
                        tester_type="RandomFuzzer",
                        scan_cycle_ms=scan_cycle_ms,
                        total_cycles=actual_depth,
                        sparse_timeline=sparse_timeline
                    ))

                # Store first batch if empty
                if not all_generated_cases:
                    all_generated_cases = batch_ir_cases

                total_execs += curr_batch_size
                total_rounds += 1

                # Execute batch with real coverage collection
                # Note: harness_c will be auto-generated if missing
                result = self._executor.execute_batch(
                    task_name=task_name,
                    st_path=st_path,
                    harness_c_path=harness_c if harness_c.exists() else None,
                    schema_path=schema_path,
                    test_cases=batch_ir_cases,
                    timeout_sec=30
                )

                if result["success"]:
                    valid_execs += curr_batch_size
                    l_cov = float(result["line_cov"].replace('%', ''))
                    b_cov = float(result["branch_cov"].replace('%', ''))
                    f_cov = float(result["func_cov"].replace('%', ''))
                    r_cov = float(result.get("region_cov", "0%").replace('%', ''))

                    has_progress = (l_cov > max_line_cov) or (b_cov > max_branch_cov)

                    if has_progress:
                        all_generated_cases = batch_ir_cases
                        max_line_cov = max(max_line_cov, l_cov)
                        max_branch_cov = max(max_branch_cov, b_cov)
                        max_func_cov = max(max_func_cov, f_cov)
                        max_region_cov = max(max_region_cov, r_cov)
                        consecutive_no_progress = 0
                    else:
                        consecutive_no_progress += 1

                    # Depth adjustment on stagnation
                    if consecutive_no_progress >= plateau_limit:
                        if current_depth < max_depth:
                            current_depth += 5
                            consecutive_no_progress = 0
                        else:
                            break
                else:
                    unique_crashes += 1

                i += curr_batch_size

            # Package results
            execution_time_ms = int((time.time() - start_time) * 1000)

            # Convert IR cases to dict format for response
            generated_cases_data = [
                {
                    "exp_id": ir.exp_id,
                    "target_st_path": ir.target_st_path,
                    "schema_path": ir.schema_path,
                    "tester_type": ir.tester_type,
                    "total_cycles": ir.total_cycles,
                    "sparse_timeline": ir.sparse_timeline,
                }
                for ir in all_generated_cases
            ]

            return create_action_response(
                action_id=request.action_id,
                status="success",
                data={
                    "task_name": task_name,
                    "generated_cases": generated_cases_data,
                    "total_generated": len(all_generated_cases),
                    "statistics": {
                        "total_execs": total_execs,
                        "total_rounds": total_rounds,
                        "valid_execs": valid_execs,
                        "max_line_cov": max_line_cov,
                        "max_branch_cov": max_branch_cov,
                        "max_func_cov": max_func_cov,
                        "max_region_cov": max_region_cov,
                        "unique_crashes": unique_crashes,
                    }
                },
                execution_time_ms=execution_time_ms
            )

        except ToolExecutionError:
            raise
        except Exception as e:
            import traceback
            execution_time_ms = int((time.time() - start_time) * 1000)
            return create_action_response(
                action_id=request.action_id,
                status="error",
                error_message=str(e),
                execution_time_ms=execution_time_ms
            )

    def validate_request(self, request: ToolCallRequest) -> bool:
        """Validate the random fuzzer request."""
        if not super().validate_request(request):
            return False

        # Check required parameters
        return "task_name" in request.parameters


__all__ = [
    "RandomFuzzerTool",
    "PLCExecutor",
]
