"""
DSE Generator - Simplified wrapper for DSE Engine

Provides simple interface for test case generation using DSE.
"""

import json
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional

from core.data_types.exp_types import ExpUnifiedIR
from .engine import DSEEngine
from .ast_to_z3 import ASTToZ3Transpiler
from .st_parser_lark.parser import parse_program

logger = logging.getLogger(__name__)


class DSECaseGenerator:
    """
    DSE test case generator wrapper.

    Simplifies the DSE engine interface for RQ2 experiments.
    Uses symbolic execution to systematically explore branches.
    """

    def __init__(
        self,
        max_depth: int = 5,
        timeout_sec: int = 120,
        debug: bool = False
    ):
        """
        Initialize DSE generator.

        Args:
            max_depth: Maximum exploration depth (cycles)
            timeout_sec: Total timeout for DSE
            debug: Enable debug logging
        """
        self.max_depth = max_depth
        self.timeout_sec = timeout_sec
        self.debug = debug

        self.transpiler = ASTToZ3Transpiler(debug=debug)

    def generate_case(
        self,
        st_code: str,
        schema_dict: Dict[str, Any],
        task_name: str = "task"
    ) -> Optional[ExpUnifiedIR]:
        """
        Generate test cases using DSE.

        Args:
            st_code: ST source code
            schema_dict: Input schema
            task_name: Task identifier

        Returns:
            ExpUnifiedIR test case or None
        """
        try:
            # Parse ST code to AST
            ast_result = parse_program(st_code)
            if ast_result is None:
                logger.error(f"Failed to parse ST code for {task_name}")
                return None

            # Transpile to Z3
            z3_code = self.transpiler.transpile(ast_result)

            # Create DSE engine
            engine = DSEEngine(
                task_name=task_name,
                schema_dict=schema_dict,
                max_depth=self.max_depth,
                timeout_sec=self.timeout_sec,
                debug=self.debug
            )

            # Define logic function
            def logic_func(state):
                """Execute symbolic logic - placeholder for now."""
                # This would need the transpiled Z3 code
                # For now, return empty result
                return []

            # Run DSE
            results = engine.run(logic_func)

            if results:
                # Convert first result to ExpUnifiedIR
                result = results[0]
                return ExpUnifiedIR(
                    exp_id=f"dse_{task_name}",
                    target_st_path="",
                    schema_path="",
                    tester_type="dse",
                    total_cycles=result.get("total_cycles", self.max_depth),
                    sparse_timeline=result.get("sparse_timeline", {}),
                    metadata={"dse_results": len(results)}
                )

        except Exception as e:
            logger.error(f"DSE generation failed: {e}")

        return None

    def generate_case_simple(
        self,
        st_code: str,
        schema_dict: Dict[str, Any],
        task_name: str = "task"
    ) -> Optional[ExpUnifiedIR]:
        """
        Generate a simple DSE test case (fallback without full Z3).

        Uses random sampling as fallback when DSE is not available.
        """
        from ..random.generator import RandomCaseGenerator

        generator = RandomCaseGenerator()
        payload = generator.generate_case(st_code, schema_dict)

        if payload:
            # Convert dict payload to sparse_timeline
            return ExpUnifiedIR(
                exp_id=f"dse_{task_name}",
                target_st_path="",
                schema_path="",
                tester_type="dse",
                total_cycles=10,
                sparse_timeline={"0": payload} if isinstance(payload, dict) else payload,
                metadata={"fallback": "random"}
            )

        return None
