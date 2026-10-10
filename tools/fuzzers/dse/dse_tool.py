"""
DSE Tool - Dynamic Symbolic Execution Tool (τdse)

Implements BaseTool interface for DSE using:
- ASTToZ3Transpiler: ST → Z3 symbolic execution code
- DSEEngine: Core symbolic execution engine
- DSEExecutorAdapter: Integration with PLCHaT execution infrastructure

Design:
- Follows BaseTool interface pattern
- Outputs ExpUnifiedIR format
- Aligned with Random/AFL tool conventions
"""

import json
import logging
import time
from pathlib import Path
from typing import Optional, Dict, Any, List

from harness.routing.base import (
    BaseTool,
    ToolType,
    ToolMetadata,
    ToolExecutionError,
)
from core.protocols.action_protocol import ToolCallRequest
from core.protocols.feedback_protocol import ActionResponse, create_action_response
from core.data_types.exp_types import ExpUnifiedIR

from .engine import DSEEngine
from .executor_adapter import DSEExecutorAdapter
from .ast_to_z3 import ASTToZ3Transpiler
from .st_parser_lark.parser import parse_program

logger = logging.getLogger(__name__)


class DSETool(BaseTool):
    """
    Dynamic Symbolic Execution Tool (τdse).

    Systematically explores all branches using Z3 constraint solving
    and symbolic execution. Outputs test cases in ExpUnifiedIR format.

    Pipeline:
        ST Code → parse_program() → AST → ASTToZ3Transpiler → Z3 Code
        → DSEEngine.run() → Test Cases → (Optional) Coverage
    """

    def __init__(self, benchmark_root: str, debug: bool = False):
        """
        Initialize the DSE Tool.

        Args:
            benchmark_root: Path to benchmark directory
            debug: Enable debug logging
        """
        super().__init__(benchmark_root)
        self._debug = debug
        self._metadata = ToolMetadata(
            name="dse",
            description="Dynamic symbolic execution tool using Z3 solver for systematic branch exploration",
            version="2.0.0",
            requires_coverage=True,
            max_execution_time=300,
            supports_batch=True
        )

        # Initialize executor adapter
        self._executor = DSEExecutorAdapter(
            project_root=self._benchmark_root,
            debug=debug
        )

        # Initialize transpiler
        self._transpiler = ASTToZ3Transpiler(
            debug=debug,
            max_unwind=10
        )

    @property
    def tool_type(self) -> ToolType:
        """Return DSE engine tool type."""
        return ToolType.DSE_ENGINE

    def execute(
        self,
        request: ToolCallRequest,
        context: Optional[Dict[str, Any]] = None
    ) -> ActionResponse:
        """
        Execute DSE with the given request.

        Args:
            request: Tool call request with parameters:
                - task_name: Benchmark task name (required)
                - st_code_path: Path to ST source file (required)
                - schema_path: Path to input schema (optional)
                - max_depth: Maximum exploration cycles (default: 50)
                - max_cycles: Maximum cycles per test case (default: 50)
                - scan_cycle_ms: Scan cycle duration in ms (default: 50)
                - timeout: Timeout in seconds (default: 120)
                - with_coverage: Execute with coverage collection (default: true)
                - plateau_limit: Stagnation threshold before depth increase (default: 20)
            context: Additional execution context (coverage, state, etc.)

        Returns:
            ActionResponse with:
                - generated_cases: List of ExpUnifiedIR test cases
                - total_generated: Number of test cases generated
                - statistics: Execution statistics including coverage
        """
        start_time = time.time()

        try:
            # Extract parameters (aligned with Random/AFL conventions)
            task_name = request.parameters.get("task_name")
            st_code_path = request.parameters.get("st_code_path")
            schema_path = request.parameters.get("schema_path")
            max_depth = request.parameters.get("max_depth", 50)
            max_cycles = request.parameters.get("max_cycles", 50)
            scan_cycle_ms = request.parameters.get("scan_cycle_ms", 50)
            timeout = request.parameters.get("timeout", 120)
            with_coverage = request.parameters.get("with_coverage", True)
            plateau_limit = request.parameters.get("plateau_limit", 20)

            if not task_name or not st_code_path:
                raise ToolExecutionError(
                    self.tool_type,
                    "Missing required parameters: task_name, st_code_path"
                )

            st_path = Path(st_code_path)
            if not st_path.exists():
                raise ToolExecutionError(
                    self.tool_type,
                    f"ST file not found: {st_code_path}"
                )

            # Load schema if provided
            schema_dict = {}
            if schema_path:
                schema_file = Path(schema_path)
                if schema_file.exists():
                    with open(schema_file, 'r', encoding='utf-8') as f:
                        schema_dict = json.load(f)

            logger.info(f"\n[*] [DSETool] Starting DSE for task: {task_name}")
            logger.info(f"    ST: {st_path}")
            logger.info(f"    Max depth: {max_depth}, Max cycles: {max_cycles}, Timeout: {timeout}s")

            # ========================================================================
            # Stage 1: Parse ST code
            # ========================================================================
            st_code = st_path.read_text(encoding="utf-8")

            # Log ST code content (for integration test verification)
            logger.info(f"    [*] ST Code Content ({len(st_code)} bytes):")
            lines = st_code.split('\n')
            for i, line in enumerate(lines[:50], 1):  # First 50 lines
                logger.info(f"        {i:3d}: {line}")
            if len(lines) > 50:
                remaining = len(lines) - 50
                logger.info(f"        ... ({remaining} more lines)")

            try:
                pou_list = parse_program(st_code)
                if not pou_list:
                    raise ToolExecutionError(self.tool_type, "No POU found in ST code")
                pou = pou_list[0]  # Use first POU
                logger.info(f"    [*] Parsed: {pou.name}")
                logger.info(f"    [*] POU has {len(pou.decls)} variable sections")
            except Exception as e:
                raise ToolExecutionError(self.tool_type, f"Failed to parse ST code: {e}")

            # ========================================================================
            # Stage 2: Transpile to Z3 code
            # ========================================================================
            try:
                z3_code = self._transpiler.transpile_from_st(st_code)
                logger.info(f"    [*] Generated Z3 code: {len(z3_code)} bytes")
            except Exception as e:
                raise ToolExecutionError(self.tool_type, f"Failed to transpile: {e}")

            # ========================================================================
            # Stage 3: Load logic function
            # ========================================================================
            try:
                namespace = {'z3': __import__('z3')}
                exec(z3_code, namespace)
                execute_st_logic = namespace['execute_st_logic']
            except Exception as e:
                raise ToolExecutionError(self.tool_type, f"Failed to load logic: {e}")

            # ========================================================================
            # Stage 4: Run DSE engine with adaptive depth increase
            # ========================================================================
            # Adaptive exploration with stagnation detection (aligned with Random Fuzzer)
            current_depth = 3  # Start shallow for quick coverage
            consecutive_no_progress = 0
            max_branches_seen = 0

            all_raw_cases = []
            all_covered_branches = set()
            total_rounds = 0

            while current_depth <= max_depth:
                remaining_time = timeout - int(time.time() - start_time)
                if remaining_time <= 0:
                    logger.warning(f"    [*] Timeout reached, stopping at depth {current_depth}")
                    break

                logger.info(f"    [*] Round {total_rounds + 1}: Exploring at depth {current_depth}")

                engine = DSEEngine(
                    task_name=task_name,
                    schema_dict=schema_dict,
                    max_depth=current_depth,
                    timeout_sec=remaining_time,
                    debug_mode=self._debug
                )

                raw_cases = engine.run(execute_st_logic)
                new_branches = len(engine.covered_branches) - max_branches_seen
                max_branches_seen = len(engine.covered_branches)

                logger.info(f"    [*] Round {total_rounds + 1} results:")
                logger.info(f"        - New branches: {new_branches}")
                logger.info(f"        - Total branches: {max_branches_seen}")
                logger.info(f"        - Test cases: {len(raw_cases)}")

                # Merge results
                all_raw_cases.extend(raw_cases)
                all_covered_branches.update(engine.covered_branches)
                total_rounds += 1

                # Check for progress (stagnation detection)
                if new_branches > 0:
                    consecutive_no_progress = 0
                    logger.info(f"    [*] Progress made, continuing at depth {current_depth}")
                else:
                    consecutive_no_progress += 1
                    logger.info(f"    [*] No progress ({consecutive_no_progress}/{plateau_limit})")

                    # Increase depth on stagnation
                    if consecutive_no_progress >= plateau_limit:
                        if current_depth < max_depth:
                            increase = min(5, max_depth - current_depth)
                            current_depth += increase
                            consecutive_no_progress = 0
                            logger.info(f"    [*] Stagnation detected, increasing depth to {current_depth}")
                        else:
                            logger.info(f"    [*] Max depth reached, stopping")
                            break

            logger.info(f"    [*] Exploration complete:")
            logger.info(f"        - Total rounds: {total_rounds}")
            logger.info(f"        - Total branches: {len(all_covered_branches)}")
            logger.info(f"        - Total test cases: {len(all_raw_cases)}")

            # Convert to ExpUnifiedIR with multi-cycle expansion (aligned with Random Fuzzer)
            generated_cases = []
            max_eval_cases = 100  # Limit total test cases for coverage evaluation

            for idx, case_dict in enumerate(all_raw_cases):
                if idx >= max_eval_cases:
                    break

                case_dict["target_st_path"] = str(st_path)
                if schema_path:
                    case_dict["schema_path"] = str(schema_path)
                case_dict["scan_cycle_ms"] = scan_cycle_ms

                # Multi-cycle expansion: expand single-cycle DSE cases to multi-cycle sequences
                original_timeline = case_dict.get("sparse_timeline", {})
                if original_timeline:
                    # Get the first cycle input (DSE generates single-cycle cases)
                    first_cycle_input = original_timeline.get("0", {})

                    # Build multi-cycle timeline
                    expanded_timeline = {}
                    for cycle in range(max_cycles):
                        cycle_key = str(cycle)
                        if cycle == 0:
                            # First cycle: use DSE generated input
                            expanded_timeline[cycle_key] = first_cycle_input
                        else:
                            # Subsequent cycles: use default values (all zeros/false)
                            # This maintains stability while allowing multi-cycle execution
                            expanded_timeline[cycle_key] = {
                                k: "0" if v in ["1", "0"] else "0"
                                for k, v in first_cycle_input.items()
                            }

                    case_dict["sparse_timeline"] = expanded_timeline
                    case_dict["total_cycles"] = max_cycles

                generated_cases.append(ExpUnifiedIR(**case_dict))

            # Convert IR cases to dict format (aligned with Random/AFL)
            generated_cases_data = [
                {
                    "exp_id": tc.exp_id,
                    "target_st_path": tc.target_st_path,
                    "schema_path": tc.schema_path,
                    "tester_type": tc.tester_type,
                    "scan_cycle_ms": tc.scan_cycle_ms,
                    "total_cycles": tc.total_cycles,
                    "sparse_timeline": tc.sparse_timeline,
                }
                for tc in generated_cases
            ]

            # Log generated test case details (for integration test verification)
            logger.info(f"    [*] Generated Test Cases Details:")
            for i, case_data in enumerate(generated_cases_data):
                logger.info(f"        [{i+1}] ID: {case_data['exp_id']}")
                logger.info(f"            Cycles: {case_data['total_cycles']}")
                logger.info(f"            Timeline: {case_data['sparse_timeline']}")

            # Execute with coverage if cases were generated and requested
            coverage_result = {}
            if with_coverage and generated_cases:
                logger.info(f"    [*] Executing {len(generated_cases)} test cases with coverage collection...")

                # Debug: Log first test case input format
                if generated_cases:
                    first_tc = generated_cases[0]
                    logger.debug(f"    [*] First test case debug:")
                    logger.debug(f"        - exp_id: {first_tc.exp_id}")
                    logger.debug(f"        - total_cycles: {first_tc.total_cycles}")
                    logger.debug(f"        - sparse_timeline keys: {list(first_tc.sparse_timeline.keys())}")

                    # Try to convert to harness input and verify format
                    try:
                        harness_input = first_tc.to_harness_input()
                        lines = harness_input.split('\n')
                        logger.debug(f"        - Harness input lines: {len(lines)}")
                        logger.debug(f"        - First 3 lines: {lines[:3]}")
                    except Exception as e:
                        logger.warning(f"    [*] Failed to convert test case to harness input: {e}")

                coverage_result = self._executor.execute_test_cases(
                    task_name=task_name,
                    st_path=st_path,
                    test_cases=generated_cases,
                    timeout_sec=60
                )
                logger.info(f"    [*] Coverage results:")
                logger.info(f"        - Line coverage: {coverage_result.get('line_cov', 'N/A')}")
                logger.info(f"        - Branch coverage: {coverage_result.get('branch_cov', 'N/A')}")
                logger.info(f"        - Function coverage: {coverage_result.get('func_cov', 'N/A')}")

                # Warn if coverage is unexpectedly low
                line_cov = coverage_result.get('line_cov', 'N/A')
                if isinstance(line_cov, str) and line_cov == '0.00%':
                    logger.warning(f"    [!] Coverage measurement returned 0% - this may indicate:")
                    logger.warning(f"        - Test case format mismatch with schema")
                    logger.warning(f"        - Compilation or execution failure")
                    logger.warning(f"        - Coverage instrumentation issue")
                    logger.warning(f"    [!] Check executor logs for detailed errors")

            elapsed = time.time() - start_time
            execution_time_ms = int(elapsed * 1000)

            return create_action_response(
                action_id=request.action_id,
                status="success",
                data={
                    "task_name": task_name,
                    "generated_cases": generated_cases_data,
                    "total_generated": len(generated_cases),
                    "statistics": {
                        "total_cases": len(generated_cases),
                        "total_rounds": total_rounds,
                        "covered_branches": len(all_covered_branches),
                        "line_cov": coverage_result.get("line_cov", "N/A"),
                        "branch_cov": coverage_result.get("branch_cov", "N/A"),
                        "func_cov": coverage_result.get("func_cov", "N/A"),
                    }
                },
                execution_time_ms=execution_time_ms
            )

        except Exception as e:
            logger.error(f"[DSETool] Execution failed: {e}")
            import traceback
            logger.error(traceback.format_exc())

            execution_time_ms = int((time.time() - start_time) * 1000)
            return create_action_response(
                action_id=request.action_id,
                status="error",
                error_message=str(e),
                execution_time_ms=execution_time_ms
            )

    def validate_request(self, request: ToolCallRequest) -> bool:
        """Validate the DSE request (aligned with Random/AFL)."""
        if not super().validate_request(request):
            return False

        # Check required parameters
        return "task_name" in request.parameters


__all__ = ["DSETool"]
