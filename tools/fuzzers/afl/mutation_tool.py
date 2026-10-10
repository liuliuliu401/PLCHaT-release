"""
AFL++ Mutation Fuzzer Tool (τmut)

Implements BaseTool interface for AFL++ mutation fuzzing.
Paper: "a coverage-guided mutation engine τmut (AFL++-based) for structural path penetration"

Migrated from: baselines/afl/generator.py
Refactored: Fixed temp file leak using context manager
"""

import json
import time
from pathlib import Path
from typing import Dict, Any, Optional

from harness.routing.base import (
    BaseTool,
    ToolType,
    ToolMetadata,
    ToolExecutionError,
)
from core.protocols.action_protocol import ToolCallRequest
from core.protocols.feedback_protocol import ActionResponse, create_action_response

from .config import AFLConfig, DEFAULT_MAX_RUNTIME_SEC, DEFAULT_MAX_CYCLES, DEFAULT_MAX_EVAL_CASES
from .env_checker import AFLEnvChecker, AFLEnvironmentError
from .compiler import AFLCompiler, temp_dir
from .orchestrator import AFLOrchestrator


class MutationFuzzerTool(BaseTool):
    """
AFL++ mutation tool (τmut) with BaseTool interface.

Paper description:
    "a coverage-guided mutation engine τmut (AFL++-based)
    for structural path penetration"

Function:
- Unified invocation through the BaseTool interface
- Supports parameterized configuration
- Returns ExpUnifiedIR format result
- Integrated coverage-guided mutation

    Parameters via ToolCallRequest.parameters:
        - task_name: Benchmark task name (e.g., "212_FindMinMaxValues") [REQUIRED]
        - max_runtime_sec: Maximum runtime in seconds (default: 600)
        - max_cycles: Maximum cycles per test case (default: 50)
        - max_eval_cases: Maximum cases to export (default: 50)
        - stop_on_crash: Stop on valid crash (default: false)
        - sampling_interval_sec: Coverage sampling interval (default: 1800)
    """

    def __init__(self, benchmark_root: str):
        """
        Initialize the AFL++ Mutation Tool.

        Args:
            benchmark_root: Path to the benchmark directory
        """
        super().__init__(benchmark_root)

        # Environment check
        self.env_checker = AFLEnvChecker()
        if not self.env_checker.check():
            raise AFLEnvironmentError(
                "AFL++ environment check failed. "
                "Please install AFL++ and required dependencies."
            )

        self._metadata = ToolMetadata(
            name="mutation",
            description="AFL++ coverage-guided mutation engine",
            version="1.0.0",
            requires_coverage=True,
            max_execution_time=86400,  # 24h
            supports_batch=False  # AFL manages its own batching
        )

        # Lazy initialized components
        self._compiler: Optional[AFLCompiler] = None

    @property
    def tool_type(self) -> ToolType:
        """Return mutation fuzzer tool type."""
        return ToolType.MUTATION_ENGINE

    def execute(
        self,
        request: ToolCallRequest,
        context: Optional[Dict[str, Any]] = None
    ) -> ActionResponse:
        """
        Execute AFL++ mutation fuzzing.

        Args:
            request: Tool call request with parameters
            context: Additional execution context

        Returns:
            ActionResponse with generated test cases and statistics
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
            max_runtime_sec = request.parameters.get(
                "max_runtime_sec", DEFAULT_MAX_RUNTIME_SEC
            )
            max_cycles = request.parameters.get(
                "max_cycles", DEFAULT_MAX_CYCLES
            )
            max_eval_cases = request.parameters.get(
                "max_eval_cases", DEFAULT_MAX_EVAL_CASES
            )
            stop_on_crash = request.parameters.get("stop_on_crash", False)
            sampling_interval_sec = request.parameters.get(
                "sampling_interval_sec", 1800
            )

            # Resolve paths
            task_path = Path(self._benchmark_root) / task_name
            st_path = task_path / "plc_st_files" / f"{task_name}.st"
            harness_src = task_path / "plc_c_files" / "harness.c"
            schema_path = task_path / "input" / "input_schema_v2.json"

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
                schema_dict = json.load(f)

            # Ensure harness exists
            if not harness_src.exists():
                # Generate harness using harness.compiler
                harness_src = self._ensure_harness(task_path, st_path)

            # Use temp_dir context manager to ensure automatic cleanup
            with temp_dir(prefix=f"afl_{task_name}_") as output_dir:
                # Create AFL configuration
                config = AFLConfig(
                    task_root=str(task_path),
                    output_dir=str(output_dir),
                    max_runtime_sec=max_runtime_sec,
                    max_cycles=max_cycles,
                    max_eval_cases=max_eval_cases,
                    stop_on_crash=stop_on_crash,
                    sampling_interval_sec=sampling_interval_sec,
                )

                # Initialize compiler
                if self._compiler is None:
                    self._compiler = AFLCompiler(self.env_checker)

                # Compile with AFL instrumentation
                binary_path = self._compiler.prepare(
                    st_path=st_path,
                    harness_src_path=harness_src,
                    output_dir=output_dir,
                )

                # Run AFL++ orchestration (with optional LLM-injected high-quality seeds)
                orchestrator = AFLOrchestrator(
                    config=config,
                    schema_dict=schema_dict,
                    st_path=st_path,
                    binary_path=binary_path,
                    initial_seeds=request.parameters.get("initial_seeds") or [],
                )

                # Set sampling callback if provided in context
                if context and "sampling_callback" in context:
                    orchestrator.sampling_callback = context["sampling_callback"]

                # Execute
                orchestrator.run(stop_on_crash=stop_on_crash)

                # Load exported IR (read before context closes)
                ir_path = output_dir / config.ir_filename
                generated_cases = []
                if ir_path.exists():
                    with open(ir_path, 'r') as f:
                        generated_cases = json.load(f)

            # temp_dir context has been automatically cleaned

            # Package results
            execution_time_ms = int((time.time() - start_time) * 1000)

            return create_action_response(
                action_id=request.action_id,
                status="success",
                data={
                    "task_name": task_name,
                    "generated_cases": generated_cases,
                    "total_generated": len(generated_cases),
                    "statistics": {
                        "total_execs": orchestrator.total_execs_accumulated,
                        "paths_discovered": len(orchestrator.seen_queue),
                        "crashes_found": len(orchestrator.seen_crashes),
                        "final_depth": orchestrator.current_n,
                        "total_plc_cycles": orchestrator.total_plc_cycles,
                        "verified_killed": orchestrator.verified_killed,
                    }
                },
                execution_time_ms=execution_time_ms
            )

        except ToolExecutionError:
            raise
        except FileNotFoundError as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return create_action_response(
                action_id=request.action_id,
                status="error",
                error_message=f"File not found: {e}",
                execution_time_ms=execution_time_ms
            )
        except (RuntimeError, OSError) as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            return create_action_response(
                action_id=request.action_id,
                status="error",
                error_message=f"Compilation/execution error: {e}",
                execution_time_ms=execution_time_ms
            )
        except Exception as e:
            import traceback
            execution_time_ms = int((time.time() - start_time) * 1000)
            return create_action_response(
                action_id=request.action_id,
                status="error",
                error_message=str(e),
                execution_time_ms=execution_time_ms
            )

    def _ensure_harness(self, task_path: Path, st_path: Path) -> Path:
        """
        Generate harness if missing.

        Args:
            task_path: Path to the task directory
            st_path: Path to ST source file

        Returns:
            Path to the generated harness.c

        Raises:
            ToolExecutionError: If harness generation fails
        """
        try:
            from harness.compiler.generator.pipeline import HarnessPipeline
            from harness.compiler.utils import Logger, LEVEL

            logger = Logger("/tmp/plchat_afl", "afl_harness.log", level=LEVEL.INFO)

            output_dir = task_path / "plc_c_files"
            output_dir.mkdir(parents=True, exist_ok=True)

            pipeline = HarnessPipeline(debug=False, logger=logger)
            result = pipeline.synthesize(st_path, output_dir)

            if result.success:
                return result.harness_path
            else:
                raise RuntimeError(f"Harness generation failed: {result.error}")

        except (RuntimeError, OSError) as e:
            raise ToolExecutionError(
                self.tool_type,
                f"Failed to generate harness: {e}"
            )

    def validate_request(self, request: ToolCallRequest) -> bool:
        """Validate the AFL++ mutation fuzzer request."""
        if not super().validate_request(request):
            return False

        # Check required parameters
        return "task_name" in request.parameters


__all__ = ["MutationFuzzerTool"]
