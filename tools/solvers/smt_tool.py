"""
SMT Tool - Unified Symbolic Execution Tool

Implements BaseTool interface for symbolic execution using Z3.
This is a self-contained implementation using migrated components.
"""

from typing import Optional, Dict, Any
import logging
import uuid
from pathlib import Path

from harness.routing.base import BaseTool, ToolType, ToolMetadata, ToolExecutionError
from core.protocols.action_protocol import ToolCallRequest
from core.protocols.feedback_protocol import ActionResponse, create_action_response
from core.data_types.exp_types import ExpUnifiedIR

# Local migrated components
from .z3_backend import Z3Engine

# LLMSemanticSlicer requires config variables that may not be set
try:
    from .llm_slicer import LLMSemanticSlicer
    _has_llm_slicer = True
except (ImportError, AttributeError):
    _has_llm_slicer = False
    LLMSemanticSlicer = None


logger = logging.getLogger(__name__)


class SMTTool(BaseTool):
    """
    Unified SMT Solver Tool (τsmt).

    Self-contained implementation using migrated Z3Engine and LLMSemanticSlicer.
    """

    def __init__(self, benchmark_root: str):
        """
        Initialize the SMT Tool.

        Args:
            benchmark_root: Path to benchmark directory
        """
        super().__init__(benchmark_root)
        self._metadata = ToolMetadata(
            name="smt",
            description="Symbolic execution tool using Z3 solver with LLM-based constraint generation",
            version="1.0.0",
            requires_coverage=False,
            max_execution_time=120,
            supports_batch=False
        )

        # Initialize components
        self._z3_engine = Z3Engine()
        # LLMSemanticSlicer may not be available (requires config)
        if _has_llm_slicer and LLMSemanticSlicer is not None:
            self._llm_slicer = LLMSemanticSlicer()
        else:
            self._llm_slicer = None

    @property
    def tool_type(self) -> ToolType:
        """Return SMT solver tool type."""
        return ToolType.SMT_SOLVER

    def execute(
        self,
        request: ToolCallRequest,
        context: Optional[Dict[str, Any]] = None
    ) -> ActionResponse:
        """
        Execute SMT solving with the given request.

        Args:
            request: Tool call request with parameters:
                - mode: "trace_fix" or "semantic_analysis"
                - st_code: ST source code (required)
                - plan_context: Context for solver (goal, strategy, target_type, etc.)
                - snapshot: Concrete state values for trace_fix mode
            context: Additional execution context (currently unused)

        Returns:
            ActionResponse with:
                - trace_fix mode: ExpUnifiedIR containing solved inputs
                - semantic_analysis mode: Mixed format requirement summary
        """
        import time
        start_time = time.time()

        try:
            mode = request.parameters.get("mode", "trace_fix")
            st_code = request.parameters.get("st_code")
            plan_context = request.parameters.get("plan_context", {})

            if not st_code:
                raise ToolExecutionError(
                    self.tool_type,
                    "Missing 'st_code' parameter"
                )

            if mode == "trace_fix":
                # Mode A: Trace-Guided Fix
                snapshot = request.parameters.get("snapshot", {})

                print(f"\n[*] [SMTTool] Trace-Guided Fix requested. Goal: '{plan_context.get('goal')}'")

                # 1. LLM Slicing (if available)
                if self._llm_slicer is None:
                    print("[-] [SMTTool] LLM Slicer not available (requires config variables).")
                    execution_time_ms = int((time.time() - start_time) * 1000)
                    return create_action_response(
                        action_id=request.action_id,
                        status="failed",
                        data={
                            "mode": "trace_fix",
                            "reason": "LLM slicer not available - requires generator_model, generator_api_key config"
                        },
                        error_message="LLM slicer not available",
                        execution_time_ms=execution_time_ms
                    )

                z3_script = self._llm_slicer.generate_z3_script(st_code, plan_context)

                if not z3_script:
                    print("[-] [SMTTool] LLM Slicing failed (no script generated).")
                    execution_time_ms = int((time.time() - start_time) * 1000)
                    return create_action_response(
                        action_id=request.action_id,
                        status="failed",
                        data={
                            "mode": "trace_fix",
                            "reason": "LLM slicing failed"
                        },
                        error_message="LLM slicing failed",
                        execution_time_ms=execution_time_ms
                    )

                print(f"[DEBUG] [SMTTool] Generated Z3 Script:\n{'-'*20}\n{z3_script}\n{'-'*20}")

                # 2. Z3 Solving
                solve_result = self._z3_engine.solve_with_snapshot(z3_script, snapshot)

                execution_time_ms = int((time.time() - start_time) * 1000)

                if solve_result["status"] == "SAT":
                    solved_inputs = solve_result["inputs"]
                    print(f"[+] [SMTTool] SAT. Solved Inputs: {solved_inputs}")

                    # 3. Package as ExpUnifiedIR
                    result_ir = ExpUnifiedIR(
                        exp_id=f"sym_fix_{uuid.uuid4().hex[:6]}",
                        target_st_path="placeholder",
                        schema_path=str(Path(self._benchmark_root) / "input" / "input_schema_v2.json"),
                        tester_type="SMT_TraceRepair",
                        total_cycles=1,
                        sparse_timeline={0: solved_inputs}
                    )

                    # Print generated test case
                    print(f"\n{'='*60}")
                    print(f"[GENERATED TEST CASE]")
                    print(f"{'='*60}")
                    print(f"Exp ID: {result_ir.exp_id}")
                    print(f"Target ST: {result_ir.target_st_path}")
                    print(f"Schema: {result_ir.schema_path}")
                    print(f"Tester Type: {result_ir.tester_type}")
                    print(f"Total Cycles: {result_ir.total_cycles}")
                    print(f"Sparse Timeline (Cycle 0):")
                    for var, val in result_ir.sparse_timeline[0].items():
                        print(f"  {var} = {val}")
                    print(f"{'='*60}\n")

                    return create_action_response(
                        action_id=request.action_id,
                        status="success",
                        data={
                            "mode": "trace_fix",
                            "exp_ir": {
                                "exp_id": result_ir.exp_id,
                                "target_st_path": result_ir.target_st_path,
                                "schema_path": result_ir.schema_path,
                                "tester_type": result_ir.tester_type,
                                "total_cycles": result_ir.total_cycles,
                                "sparse_timeline": result_ir.sparse_timeline,
                                "metadata": result_ir.metadata
                            },
                            "solved_inputs": solved_inputs,
                            "solved_count": len(solved_inputs)
                        },
                        execution_time_ms=execution_time_ms
                    )

                elif solve_result["status"] == "UNSAT":
                    print(f"[-] [SMTTool] UNSAT. Reason: {solve_result['reason']}")
                    return create_action_response(
                        action_id=request.action_id,
                        status="failed",
                        data={
                            "mode": "trace_fix",
                            "reason": solve_result.get("reason", "Constraints are unsatisfiable")
                        },
                        error_message="No solution satisfies the constraints",
                        execution_time_ms=execution_time_ms
                    )

                else:  # ERROR
                    print(f"[-] [SMTTool] Execution Error. Reason: {solve_result['reason']}")
                    return create_action_response(
                        action_id=request.action_id,
                        status="error",
                        error_message=solve_result.get("reason", "Unknown Z3 error"),
                        execution_time_ms=execution_time_ms
                    )

            elif mode == "semantic_analysis":
                # Mode B: Deep Semantic Analysis (simplified, not using original SemanticSummarizer)
                print(f"\n[*] [SMTTool] Semantic Analysis requested. Archetype: {plan_context.get('archetype')}")

                # For now, return a placeholder response
                # Full implementation would use a separate semantic analyzer
                execution_time_ms = int((time.time() - start_time) * 1000)

                return create_action_response(
                    action_id=request.action_id,
                    status="success",
                    data={
                        "mode": "semantic_analysis",
                        "nl_description": f"Semantic analysis for {plan_context.get('archetype', 'unknown')}",
                        "pseudo_code": "# Placeholder for semantic analysis output"
                    },
                    execution_time_ms=execution_time_ms
                )

            else:
                raise ToolExecutionError(
                    self.tool_type,
                    f"Unknown mode: {mode}. Use 'trace_fix' or 'semantic_analysis'"
                )

        except ToolExecutionError:
            raise
        except Exception as e:
            import traceback
            logger.error(f"[SMTTool] Unexpected error: {e}\n{traceback.format_exc()}")
            return create_action_response(
                action_id=request.action_id,
                status="error",
                error_message=str(e),
                execution_time_ms=int((time.time() - start_time) * 1000)
            )

    def validate_request(self, request: ToolCallRequest) -> bool:
        """Validate the SMT tool request."""
        if not super().validate_request(request):
            return False

        mode = request.parameters.get("mode", "trace_fix")

        if mode not in ["trace_fix", "semantic_analysis"]:
            return False

        return "st_code" in request.parameters


__all__ = ["SMTTool"]
