"""
RQ1 Experiment Runner - Harness Generation Effectiveness

Adapted from experiments/rq1/rq1_experiment.py
Refactored to use PLCHaT's existing interfaces.

Evaluates:
- Table 1: Pipeline quality (Transpilation, Compilation, Execution pass rates)
- Table 2: Oracle quality (Assertion generation success, trigger rates)
"""

import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Project root: experiments/rq1/runner.py → rq1 → experiments → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.executor import STExecutor
from harness.compiler.utils import Logger, LEVEL
from tools.fuzzers.random.generator import RandomCaseGenerator

# Configuration
BENCHMARK_VERSION = "benchmark_260113"
BENCHMARK_ROOT = PROJECT_ROOT / "benchmark" / BENCHMARK_VERSION / "benchmark_raw"
RESULTS_BASE = PROJECT_ROOT / "output" / "rq1_results"

@dataclass
class RQ1Table1Result:
    """Table 1 pipeline quality result."""
    task_id: str
    transpilation_pass: bool
    compilation_pass: bool
    execution_pass: bool
    note: str = ""

    def to_csv_row(self) -> List[str]:
        return [
            self.task_id,
            "PASS" if self.transpilation_pass else "FAIL",
            "PASS" if self.compilation_pass else "FAIL",
            "PASS" if self.execution_pass else "FAIL",
            self.note
        ]


@dataclass
class RQ1Table2Result:
    """Table 2 oracle quality result."""
    task_id: str
    execution_pass: bool
    num_assertions: int
    trigger_rate: float
    note: str = ""

    def to_csv_row(self) -> List[str]:
        return [
            self.task_id,
            "PASS" if self.execution_pass else "FAIL",
            str(self.num_assertions),
            f"{self.trigger_rate:.4f}",
            self.note
        ]


class RQ1Util:
    """RQ1 experiment utility functions."""

    TABLE1_HEADERS = ["TaskID", "Transpilation", "Compilation", "Execution", "Note"]
    TABLE2_HEADERS = ["TaskID", "ExecutionPass", "NumAssertions", "TriggerRate", "Note"]

    @staticmethod
    def init_csv(filepath: Path, headers: List[str], force_clean: bool = False):
        """Initialize CSV file with headers."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        if force_clean or not filepath.exists():
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(headers)

    @staticmethod
    def append_result(filepath: Path, result):
        """Append a result row to CSV."""
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(result.to_csv_row())


class RQ1Runner:
    """RQ1 experiment runner for harness generation effectiveness evaluation.

    Evaluates PLCHaT's ability to:
    1. Generate executable test wrappers (Table 1)
    2. Generate assertion-based oracles (Table 2)
    """

    def __init__(self, project_root: Optional[Path] = None, fast_mode: bool = False):
        """Initialize RQ1 runner.

        Args:
            project_root: Project root directory
            fast_mode: Enable fast mode for testing (fewer tasks)
        """
        self.project_root = project_root or PROJECT_ROOT
        self.fast_mode = fast_mode

        # Paths
        self.benchmark_root = BENCHMARK_ROOT
        self.results_table1 = RESULTS_BASE / "table1.csv"
        self.results_table2 = RESULTS_BASE / "table2.csv"

        # Initialize executor
        self.executor = STExecutor(
            root_dir=str(self.project_root),
            logger=None,
            debug=False
        )

        # Initialize logger
        self.logger = Logger(
            str(RESULTS_BASE / "logs"),
            "rq1_runner.log",
            level=LEVEL.INFO
        )

    def init_env(self, clean_existing: bool = False):
        """Initialize output directories and CSV files."""
        RESULTS_BASE.mkdir(parents=True, exist_ok=True)
        RQ1Util.init_csv(self.results_table1, RQ1Util.TABLE1_HEADERS, clean_existing)
        RQ1Util.init_csv(self.results_table2, RQ1Util.TABLE2_HEADERS, clean_existing)
        self.logger.info(f"RQ1 environment initialized")

    def list_tasks(self, include: Optional[List[str]] = None) -> List[str]:
        """List available tasks, optionally filtered."""
        all_tasks = sorted([
            d.name for d in self.benchmark_root.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ])
        if include:
            return [t for t in all_tasks if t in include]
        if self.fast_mode:
            return all_tasks[:3]  # Quick test with 3 tasks
        return all_tasks

    def run_table1_task(self, task_id: str) -> RQ1Table1Result:
        """Run Table 1 pipeline quality test for a single task.

        Args:
            task_id: Task identifier (e.g., "211_StackMin")

        Returns:
            RQ1Table1Result with pipeline pass/fail status
        """
        result = RQ1Table1Result(
            task_id=task_id,
            transpilation_pass=False,
            compilation_pass=False,
            execution_pass=False
        )

        task_dir = self.benchmark_root / task_id
        st_file = task_dir / "plc_st_files" / f"{task_id}.st"
        harness_file = task_dir / "plc_c_files" / "harness.c"

        if not st_file.exists():
            result.note = "ST file not found"
            return result

        output_dir = RESULTS_BASE / "table1_temp" / task_id
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Step 1: ST → C (Transpilation)
            self.logger.info_print(f"  {task_id}: ST → C")
            transpilation_ok = self.executor.compile_st_to_c(
                st_code_path=str(st_file),
                output_dir=str(output_dir),
                harness_path=str(harness_file) if harness_file.exists() else None
            )
            result.transpilation_pass = transpilation_ok

            if not result.transpilation_pass:
                result.note = "Transpilation failed"
                return result

            # Step 2: C → Binary (Compilation)
            self.logger.info_print(f"  {task_id}: C → Binary")
            c_files = list(output_dir.glob("*.c"))
            binary_path = output_dir / "plc_harness_test"

            if not c_files:
                result.note = "No C files generated"
                return result

            # Get MatIEC library path
            matiec_bin = shutil.which("iec2c")
            if matiec_bin:
                matiec_lib = str(Path(matiec_bin).parent / "lib" / "C")
            else:
                matiec_lib = "/usr/local/lib/matiec"

            compilation_ok = self.executor.compile_c_to_binary(
                source_files=[str(f) for f in c_files],
                output_binary=str(binary_path),
                include_dirs=[matiec_lib],
                libraries=[],
                coverage_mode=True
            )
            result.compilation_pass = compilation_ok

            if not result.compilation_pass:
                result.note = "Compilation failed"
                return result

            # Step 3: Execution test
            self.logger.info_print(f"  {task_id}: Execution test")
            # Create simple input
            input_file = output_dir / "input.txt"
            input_file.write_text("0 0 0\n", encoding='utf-8')

            exec_result = self.executor.execute_binary(
                binary_path=str(binary_path),
                input_file=str(input_file),
                timeout=5
            )
            result.execution_pass = exec_result.get("success", False)
            result.note = exec_result.get("error", "") if not result.execution_pass else ""

        except Exception as e:
            result.note = f"Exception: {str(e)}"

        return result

    def run_table1_batch(self, tasks: Optional[List[str]] = None) -> List[RQ1Table1Result]:
        """Run Table 1 tests for a batch of tasks.

        Args:
            tasks: List of task IDs (default: all or fast_mode subset)

        Returns:
            List of RQ1Table1Result
        """
        tasks = self.list_tasks(include=tasks)
        results = []

        self.logger.info(f"Running Table 1 for {len(tasks)} tasks")

        for task_id in tasks:
            self.logger.info_print(f"Processing: {task_id}")
            result = self.run_table1_task(task_id)
            results.append(result)
            RQ1Util.append_result(self.results_table1, result)

        # Summary
        trans_pass = sum(1 for r in results if r.transpilation_pass)
        comp_pass = sum(1 for r in results if r.compilation_pass)
        exec_pass = sum(1 for r in results if r.execution_pass)

        self.logger.info(f"Table 1 Summary: {len(results)} tasks")
        self.logger.info(f"  Transpilation: {trans_pass}/{len(results)} ({100*trans_pass/len(results):.1f}%)")
        self.logger.info(f"  Compilation: {comp_pass}/{len(results)} ({100*comp_pass/len(results):.1f}%)")
        self.logger.info(f"  Execution: {exec_pass}/{len(results)} ({100*exec_pass/len(results):.1f}%)")

        return results

    def run_table2_task(self, task_id: str, num_random_tests: int = 200) -> RQ1Table2Result:
        """Run Table 2 oracle quality test for a single task.

        Args:
            task_id: Task identifier
            num_random_tests: Number of random tests for trigger rate

        Returns:
            RQ1Table2Result with oracle quality metrics
        """
        result = RQ1Table2Result(
            task_id=task_id,
            execution_pass=False,
            num_assertions=0,
            trigger_rate=0.0
        )

        task_dir = self.benchmark_root / task_id
        st_file = task_dir / "plc_st_files" / f"{task_id}.st"
        harness_file = task_dir / "plc_c_files" / "harness.c"
        schema_file = task_dir / "input" / "input_schema_v2.json"

        if not all([st_file.exists(), harness_file.exists(), schema_file.exists()]):
            result.note = "Required files not found"
            return result

        try:
            # TODO: Implement assertion generation and trigger rate calculation
            # This requires TestAnalysisAgent integration
            result.note = "Not yet implemented - requires assertion generation"
        except Exception as e:
            result.note = f"Exception: {str(e)}"

        return result


def main():
    """Main entry point for RQ1 experiments."""
    import argparse

    parser = argparse.ArgumentParser(description="RQ1 Harness Generation Experiments")
    parser.add_argument("--table1", action="store_true",
                        help="Run Table 1 pipeline quality tests")
    parser.add_argument("--table2", action="store_true",
                        help="Run Table 2 oracle quality tests")
    parser.add_argument("--tasks", nargs="+", default=None,
                        help="Specific tasks to run")
    parser.add_argument("--fast", action="store_true",
                        help="Fast mode for testing")
    parser.add_argument("--clean", action="store_true",
                        help="Clean existing results")

    args = parser.parse_args()

    runner = RQ1Runner(fast_mode=args.fast)
    runner.init_env(clean_existing=args.clean)

    if args.table1:
        results = runner.run_table1_batch(tasks=args.tasks)
        print(f"\nTable 1 results: {len(results)} tasks")
        print(f"Results saved to: {runner.results_table1}")

    if args.table2:
        print("Table 2 not yet implemented")


if __name__ == "__main__":
    main()
