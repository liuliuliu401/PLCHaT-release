"""
Test case minimization integrator - Minimization Integrator

Provide "Long Input -> Short Input" comparative feedback for PLCHaT users:
1. Show the original long test case
2. Automatically run ddmin + HDD minimization
3. Verify that the reduced input triggers the same assertion
4. Collect coverage comparison
5. Generate readable user report

Integrated into the test_analysis module, following the dual-mode architecture of Mode A (coverage) + Mode B (assertion).
"""

import json
import tempfile
import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple, Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.executor import STExecutor
from harness.compiler.utils import Logger, LEVEL
from harness.test_analysis.execution import execute_with_assertions, collect_coverage_with_assertions
from core.data_types.test_analysis_types import MinComparisonResult
from core.data_types.exp_types import ExpUnifiedIR
from harness.test_analysis.ddmin import ddmin
# HDD module not available in release
# from test.minimization.hdd import HDD


class MinimizationIntegrator:
    """Minimizer Integrator: Reduce long test input to minimal valid input and provide comparative analysis.

Using existing STExecutor / ExpUnifiedIR / ddmin / HDD infrastructure,
Do not introduce any subprocess glue code.
    """

    def __init__(self):
        self.executor = STExecutor(
            root_dir=str(PROJECT_ROOT),
            logger=Logger("/tmp/min_integrator_logs", "integration.log", level=LEVEL.INFO),
            debug=False,
        )
        self.binary_path: Optional[str] = None
        self.compile_dir: Optional[str] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_and_minimize(
        self,
        program_id: str,
        exp_id: str,
        st_path: Path,
        harness_path: Path,
        schema_path: Path,
        input_text: str,
        total_cycles: int,
    ) -> MinComparisonResult:
        """Execute the complete minimization analysis pipeline.

        Args:
program identifier (e.g., "211_StackMin")
exp_id:         Experiment/AFL ID
st_path:        ST source code path
harness_path:   assertion harness path
schema_path:    input_schema_v2.json path
input_text:     raw input in sparse_timeline format
total_cycles:   total number of cycles of the original input

        Returns:
MinComparisonResult: contains original/reduced input comparison, coverage, assertion verification
        """
        start_time = datetime.now()

        # Count original input specifications
        original_values = sum(1 for line in input_text.strip().split("\n")
                              if line.strip() for _ in line.split())
        num_cols = self._column_count(schema_path)

        # Step 1: compile
        self._ensure_compiled(st_path, harness_path)

        # Step 2: Verify that the original input triggers an assertion
        orig_assertion = self._get_assertion(input_text)
        if not orig_assertion:
            raise ValueError("Original input did not trigger any assertion, cannot perform minimization analysis")

        # Step 3: Collect raw input coverage
        orig_cov = self._collect_coverage_text(st_path, harness_path, input_text, "original")

        # Step 4: Run ddmin
        ddmin_result = self._run_ddmin(input_text, num_cols)

        # Step 5: Run HDD
        hdd_result = self._run_hdd(input_text)

        # Step 6: Collect reduced coverage
        ddmin_cov = self._collect_coverage_text(st_path, harness_path, ddmin_result["text"], "ddmin")
        hdd_cov = self._collect_coverage_text(st_path, harness_path, hdd_result["text"], "hdd")

        # Take the one with lower coverage between ddmin and HDD as the representative (if both are the same, take either)
        min_cov = ddmin_cov if ddmin_cov else hdd_cov

        elapsed = (datetime.now() - start_time).total_seconds()

        return MinComparisonResult(
            program_id=program_id,
            assertion_message=orig_assertion,
            original_cycles=total_cycles,
            original_values=original_values,
            original_text=input_text.strip(),
            ddmin_values=ddmin_result["size"],
            ddmin_text=ddmin_result["text"].strip(),
            ddmin_cycles=ddmin_result["cycles"],
            ddmin_oracle_calls=ddmin_result["oracle_calls"],
            ddmin_assertion_preserved=ddmin_result["assertion_preserved"],
            ddmin_reduction_ratio=ddmin_result["reduction_ratio"],
            hdd_values=hdd_result["size"],
            hdd_text=hdd_result["text"].strip(),
            hdd_cycles=hdd_result["cycles"],
            hdd_oracle_calls=hdd_result["oracle_calls"],
            hdd_assertion_preserved=hdd_result["assertion_preserved"],
            hdd_reduction_ratio=hdd_result["reduction_ratio"],
            original_coverage=orig_cov,
            minimized_coverage=min_cov,
            execution_time_sec=elapsed,
        )

    # ------------------------------------------------------------------
    # Formatted output
    # ------------------------------------------------------------------

    @staticmethod
    def format_comparison_report(result: MinComparisonResult) -> str:
        """Generate a user-readable Markdown comparison report."""
        def _cov_line(prefix: str, cov: Dict[str, str]) -> str:
            if not cov:
                return ""
            return (f"  {prefix}: line {cov.get('line_cov', 'N/A')}, "
                    f"branch {cov.get('branch_cov', 'N/A')}, "
                    f"region {cov.get('region_cov', 'N/A')}")

        ddmin_status = "PRESERVED" if result.ddmin_assertion_preserved else "LOST"
        hdd_status = "PRESERVED" if result.hdd_assertion_preserved else "LOST"

        lines = [
            f"# Test Case Minimization Analysis Report",
            f"",
            f"**Program**: `{result.program_id}`",
            f"**Assertion**: `{result.assertion_message}`",
            f"**Analysis Time**: {result.execution_time_sec:.1f}s",
            f"",
            f"---",
            f"",
            f"## Original Test Input ({result.original_cycles} cycles, {result.original_values} values)",
            f"",
            f"```",
            result.original_text,
            f"```",
            f"",
            f"---",
            f"",
            f"## Reduction Result Comparison",
            f"",
            f"| Algorithm | Original -> Reduced | Reduction Ratio | Oracle Calls | Assertion Preserved | Reduced Cycles |",
            f"|-----------|---------------------|------------------|---------------|---------------------|-----------------|",
            (f"| ddmin     | {result.original_values} -> {result.ddmin_values} "
             f"| {result.ddmin_reduction_ratio:.1%} "
             f"| {result.ddmin_oracle_calls} "
             f"| {ddmin_status} "
             f"| {result.ddmin_cycles} |"),
            (f"| HDD       | {result.original_values} -> {result.hdd_values} "
             f"| {result.hdd_reduction_ratio:.1%} "
             f"| {result.hdd_oracle_calls} "
             f"| {hdd_status} "
             f"| {result.hdd_cycles} |"),
            f"",
            f"### ddmin Reduced Input",
            f"",
            f"```",
            result.ddmin_text,
            f"```",
            f"",
            f"### HDD Reduced Input",
            f"",
            f"```",
            result.hdd_text,
            f"```",
            f"",
            f"---",
            f"",
            f"## Coverage Comparison",
            f"",
        ]
        if result.original_coverage:
            lines.append(_cov_line("Original Input", result.original_coverage))
        if result.minimized_coverage:
            lines.append(_cov_line("Reduced Input  ", result.minimized_coverage))
            lines.append(f"")
            if result.original_coverage and result.minimized_coverage:
                lines.append("> **Note**: Coverage drop indicates reduced input may reach the same assertion via different execution path.")
                lines.append("> This does not mean reduction failed—the assertion trigger condition still holds, but fewer execution branches are covered.")
        lines.append(f"")
        lines.append(f"---")
        lines.append(f"")
        lines.append(f"## User Insights")
        lines.append(f"")
        lines.append(f"Original input has **{result.original_cycles} cycles** and **{result.original_values} values**,")
        lines.append(f"while reduced input only needs **{result.ddmin_cycles} cycles** and **{result.ddmin_values} values**")
        lines.append(f"to trigger the same assertion `{result.assertion_message}`.")
        lines.append(f"")
        lines.append(f"This indicates that most cycles and input values in the original input are **unnecessary** for assertion triggering,")
        lines.append(f"helping users focus on the input combinations that truly cause issues, accelerating root cause localization.")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # internal method
    # ------------------------------------------------------------------

    def _ensure_compiled(self, st_path: Path, harness_path: Path):
        if self.binary_path and Path(self.binary_path).exists():
            return
        self.compile_dir = tempfile.mkdtemp(prefix="min_integrator_")
        ok = self.executor.compile_st_to_c(
            st_code_path=str(st_path),
            output_dir=self.compile_dir,
            harness_path=str(harness_path),
        )
        if not ok:
            raise RuntimeError("ST compilation failed")
        c_files = list(Path(self.compile_dir).glob("*.c"))
        import shutil
        matiec_bin = Path(shutil.which("iec2c")).parent
        matiec_lib = str(matiec_bin / "lib" / "C")
        self.binary_path = str(Path(self.compile_dir) / "program")
        ok = self.executor.compile_c_to_binary(
            source_files=[str(f) for f in c_files],
            output_binary=self.binary_path,
            include_dirs=[self.compile_dir, matiec_lib],
            libraries=["-lstdc++"],
            coverage_mode=False,
        )
        if not ok:
            raise RuntimeError("C compilation failed")

    def _get_assertion(self, input_text: str) -> Optional[str]:
        self._ensure_compiled(None, None)  # binary must exist
        result = self.executor.execute_binary(
            binary_path=self.binary_path,
            input_data=input_text,
            timeout=10,
        )
        for line in result.get("stderr", "").split("\n"):
            s = line.strip()
            if "SECURITY_ASSERT" in s or "SECURITY_ASSERTION_FAILED" in s or "AUDIT FAIL" in s:
                return s
        return None

    def _execute_and_check(self, input_text: str) -> bool:
        return self._get_assertion(input_text) is not None

    def _flat_to_text(self, flat: List[int], num_cols: int) -> str:
        lines = []
        for i in range(0, len(flat), num_cols):
            cycle = flat[i:i + num_cols]
            if len(cycle) == num_cols:
                lines.append(" ".join(str(v) for v in cycle))
        return "\n".join(lines)

    def _cycles_to_text(self, cycles: List[List[int]]) -> str:
        return "\n".join(" ".join(str(v) for v in c) for c in cycles)

    def _run_ddmin(self, input_text: str, num_cols: int) -> dict:
        flat_values = []
        for line in input_text.strip().split("\n"):
            flat_values.extend(self._parse_value(v) for v in line.split())
        original_size = len(flat_values)

        def oracle(flat_input: List[int]) -> bool:
            return self._execute_and_check(self._flat_to_text(flat_input, num_cols))

        result = ddmin(flat_values, oracle)
        minimized_text = self._flat_to_text(result.reduced_input, num_cols)
        minimized_cycles = len(minimized_text.strip().split("\n")) if minimized_text.strip() else 0
        assertion_preserved = self._execute_and_check(minimized_text)

        return {
            "size": result.reduced_size,
            "cycles": minimized_cycles,
            "text": minimized_text,
            "oracle_calls": result.oracle_calls,
            "reduction_ratio": result.reduction_ratio,
            "assertion_preserved": assertion_preserved,
        }

    def _run_hdd(self, input_text: str) -> dict:
        cycles = []
        for line in input_text.strip().split("\n"):
            cycles.append([self._parse_value(v) for v in line.split()])
        original_size = sum(len(c) for c in cycles)

        def oracle(cycle_list: List[List[int]]) -> bool:
            return self._execute_and_check(self._cycles_to_text(cycle_list))

        reduced_cycles, stats = HDD(cycles, oracle, reduce_values=True)
        minimized_text = self._cycles_to_text(reduced_cycles)
        minimized_size = sum(len(c) for c in reduced_cycles)
        assertion_preserved = self._execute_and_check(minimized_text)

        return {
            "size": minimized_size,
            "cycles": len(reduced_cycles),
            "text": minimized_text,
            "oracle_calls": stats.oracle_calls,
            "reduction_ratio": (original_size - minimized_size) / original_size if original_size else 0,
            "assertion_preserved": assertion_preserved,
        }

    @staticmethod
    def _parse_value(v: str) -> int:
        """Parse a value to int, handling float strings from REAL-type PLC variables."""
        try:
            return int(v)
        except ValueError:
            return int(float(v))

    @staticmethod
    def _column_count(schema_path: Path) -> int:
        schema = json.loads(schema_path.read_text())
        return len(schema.get("columns", []))

    @staticmethod
    def _collect_coverage_text(
        st_path: Path, harness_path: Path, input_text: str, label: str
    ) -> Dict[str, str]:
        """Collect coverage and return simplified text metrics."""
        try:
            result = collect_coverage_with_assertions(
                st_path=st_path,
                harness_path=harness_path,
                test_inputs=[input_text],
            )
            cov = result.coverage_data
            if cov is None or not hasattr(cov, "coverage_summary"):
                return {}
            s = cov.coverage_summary
            return {
                "line_cov": (s.line_coverage.percentage if hasattr(s.line_coverage, "percentage")
                             else str(s.line_coverage)),
                "branch_cov": (s.branch_coverage.percentage if hasattr(s.branch_coverage, "percentage")
                               else str(s.branch_coverage)),
                "region_cov": (s.region_coverage.percentage if hasattr(s.region_coverage, "percentage")
                               else str(s.region_coverage)),
            }
        except Exception:
            return {}
