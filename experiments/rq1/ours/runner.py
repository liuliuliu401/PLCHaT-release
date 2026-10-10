"""
RQ1 Ours Runner - PLCHaT Harness Generation Effectiveness

This module provides the main experiment runner for RQ1, evaluating PLCHaT's
ability to generate executable test wrappers and assertion-based oracles.

Modes:
- table1: Pipeline quality metrics (Transpilation, Compilation, Execution)
- table2-full: Complete assertion generation + testing
- table2-rerun: Reuse existing assertions for trigger rate testing

Usage:
    python -m experiments.run rq1 --baseline ours --table1 --fast
    python -m experiments.run rq1 --baseline ours --table2-full --fast
    python -m experiments.run rq1 --baseline ours --table2-rerun --existing-dir /path/to/results
"""

import csv
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.compiler.executor import STExecutor
from harness.compiler.utils import Logger, LEVEL
from harness.compiler.input_processor import STInputProcessor
from harness.test_analysis.integration import TestCaseAnalyzer
from tools.fuzzers.random.generator import RandomCaseGenerator
from core.data_types.exp_types import ExpUnifiedIR

# Configuration paths
BENCHMARK_VERSION = "benchmark_260113"
BENCHMARK_ROOT = PROJECT_ROOT / "benchmark" / BENCHMARK_VERSION / "benchmark_raw"
RESULTS_BASE = PROJECT_ROOT / "output" / "rq1_results" / "ours"

# Benchmark subdirectories
BENCHMARK_ST_DIR = "plc_st_files"
BENCHMARK_INPUT_DIR = "input"
BENCHMARK_SCHEMA_FILE = "input_schema_v2.json"
TASK_CLASSIFICATION_FILE = "task_classification.json"

# Default configuration
DEFAULT_RANDOM_TESTS = 200


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
    assertions_triggered: int
    trigger_rate: float
    note: str = ""

    def to_csv_row(self) -> List[str]:
        return [
            self.task_id,
            "PASS" if self.execution_pass else "FAIL",
            str(self.num_assertions),
            str(self.assertions_triggered),
            f"{self.trigger_rate:.4f}",
            self.note
        ]


class RQ1OursRunner:
    """RQ1 experiment runner for PLCHaT (ours) evaluation.

    Evaluates PLCHaT's ability to:
    1. Generate executable test wrappers (Table 1)
    2. Generate assertion-based oracles (Table 2)
    """

    def __init__(self, fast_mode: bool = False, **kwargs):
        """Initialize RQ1 runner.

        Args:
            fast_mode: Enable fast mode for testing (fewer tasks)
            **kwargs: Additional configuration
                num_random_tests: Number of random tests for Table 2
        """
        self.fast_mode = fast_mode
        self.project_root = PROJECT_ROOT
        self.benchmark_root = BENCHMARK_ROOT
        self.results_base = RESULTS_BASE

        # Configuration
        self.num_random_tests = kwargs.get("num_random_tests", DEFAULT_RANDOM_TESTS)

        # Paths
        self.results_table1 = self.results_base / "table1.csv"
        self.results_table2 = self.results_base / "table2.csv"

        # Initialize logger
        self.logger = Logger(
            str(self.results_base / "logs"),
            "rq1_ours.log",
            level=LEVEL.INFO
        )

        # Load task classification
        self.classification = self._load_classification()

    def _load_classification(self) -> Dict:
        """Load task classification from benchmark."""
        cls_file = self.benchmark_root / TASK_CLASSIFICATION_FILE
        if cls_file.exists():
            with open(cls_file) as f:
                return json.load(f)
        return {}

    def init_env(self, clean_existing: bool = False):
        """Initialize output directories and CSV files."""
        self.results_base.mkdir(parents=True, exist_ok=True)

        if clean_existing:
            if self.results_table1.exists():
                self.results_table1.unlink()
            if self.results_table2.exists():
                self.results_table2.unlink()

        # Initialize CSV files
        self._init_csv(self.results_table1, ["TaskID", "Transpilation", "Compilation", "Execution", "Note"])
        self._init_csv(self.results_table2, ["TaskID", "ExecutionPass", "NumAssertions", "Triggered", "TriggerRate", "Note"])

        self.logger.info(f"RQ1 environment initialized")

    def _init_csv(self, filepath: Path, headers: List[str]):
        """Initialize CSV file with headers."""
        if not filepath.exists():
            filepath.parent.mkdir(parents=True, exist_ok=True)
            with open(filepath, "w", newline="") as f:
                csv.writer(f).writerow(headers)

    def _append_csv(self, filepath: Path, row: List[str]):
        """Append a row to CSV file."""
        with open(filepath, "a", newline="") as f:
            csv.writer(f).writerow(row)

    def list_tasks(self, include: Optional[List[str]] = None) -> List[str]:
        """List available tasks, optionally filtered."""
        all_tasks = sorted([
            d.name for d in self.benchmark_root.iterdir()
            if d.is_dir() and not d.name.startswith("_") and d.name[0].isdigit()
        ])
        if include:
            return [t for t in all_tasks if t in include]
        if self.fast_mode:
            return all_tasks[:3]
        return all_tasks

    def run_table1_task(self, task_id: str, output_dir: Path) -> RQ1Table1Result:
        """Run Table 1 pipeline quality test for a single task.

        Args:
            task_id: Task identifier (e.g., "211_StackMin")
            output_dir: Output directory for this task

        Returns:
            RQ1Table1Result with pipeline pass/fail status
        """
        result = RQ1Table1Result(
            task_id=task_id,
            transpilation_pass=False,
            compilation_pass=False,
            execution_pass=False
        )

        task_dir = output_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        st_file = self.benchmark_root / task_id / BENCHMARK_ST_DIR / f"{task_id}.st"
        harness_file = self.benchmark_root / task_id / "plc_c_files" / "harness.c"

        if not st_file.exists():
            result.note = "ST file not found"
            return result

        try:
            executor = STExecutor(
                root_dir=str(self.project_root),
                logger=self.logger,
                debug=False
            )

            # Step 1: ST → C (Transpilation)
            self.logger.info_print(f"  {task_id}: ST → C")
            transpilation_ok = executor.compile_st_to_c(
                st_code_path=str(st_file),
                output_dir=str(task_dir),
                harness_path=str(harness_file) if harness_file.exists() else None
            )
            result.transpilation_pass = transpilation_ok

            if not result.transpilation_pass:
                result.note = "Transpilation failed"
                return result

            # Step 2: C → Binary (Compilation)
            self.logger.info_print(f"  {task_id}: C → Binary")
            c_files = list(task_dir.glob("*.c"))
            binary_path = task_dir / "plc_harness_test"

            if not c_files:
                result.note = "No C files generated"
                return result

            # Get MatIEC library path
            matiec_bin = shutil.which("iec2c")
            if matiec_bin:
                matiec_lib = str(Path(matiec_bin).parent / "lib" / "C")
            else:
                matiec_lib = "/usr/local/lib/matiec"

            compilation_ok = executor.compile_c_to_binary(
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

            # Use STInputProcessor to handle benchmark input directory
            benchmark_input_dir = self.benchmark_root / task_id / "input"

            if benchmark_input_dir.exists():
                # Use benchmark's input directory (contains input.txt with test cases)
                input_processor = STInputProcessor(logger=self.logger)
                temp_input_dir = task_dir / "temp_input"
                temp_input_dir.mkdir(exist_ok=True)

                # Process input directory - this copies all .txt files
                input_processor.handle_input_data(str(benchmark_input_dir), str(temp_input_dir))

                input_file = temp_input_dir / "input.txt"
                test_count = len(input_file.read_text().strip().splitlines()) if input_file.exists() else 0
                self.logger.info_print(f"  Using benchmark inputs: {test_count} test cases")
            else:
                # Fallback: let STInputProcessor create default input
                input_processor = STInputProcessor(logger=self.logger)
                temp_input_dir = task_dir / "temp_input"
                temp_input_dir.mkdir(exist_ok=True)

                input_processor.handle_input_data(None, str(temp_input_dir))
                input_file = temp_input_dir / "input.txt"
                self.logger.info_print(f"  Using default input (benchmark input not found)")

            exec_result = executor.execute_binary(
                binary_path=str(binary_path),
                input_file=str(input_file) if input_file.exists() else None,
                timeout=5
            )
            result.execution_pass = exec_result.get("status") == "success"
            result.note = exec_result.get("message", "") if not result.execution_pass else ""

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
        task_ids = self.list_tasks(include=tasks)
        results = []

        # Create timestamped output directory
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = self.results_base / f"table1_run_{timestamp}"

        self.logger.info(f"Running Table 1 for {len(task_ids)} tasks")

        for task_id in task_ids:
            self.logger.info_print(f"Processing: {task_id}")
            result = self.run_table1_task(task_id, output_dir)
            results.append(result)
            self._append_csv(self.results_table1, result.to_csv_row())

        # Summary
        trans_pass = sum(1 for r in results if r.transpilation_pass)
        comp_pass = sum(1 for r in results if r.compilation_pass)
        exec_pass = sum(1 for r in results if r.execution_pass)

        self.logger.info(f"Table 1 Summary: {len(results)} tasks")
        self.logger.info(f"  Transpilation: {trans_pass}/{len(results)} ({100*trans_pass/len(results):.1f}%)")
        self.logger.info(f"  Compilation: {comp_pass}/{len(results)} ({100*comp_pass/len(results):.1f}%)")
        self.logger.info(f"  Execution: {exec_pass}/{len(results)} ({100*exec_pass/len(results):.1f}%)")

        return results

    def run_table2_full_task(self, task_id: str, output_dir: Path,
                            num_random_tests: int = 200) -> RQ1Table2Result:
        """Run Table 2 oracle quality test for a single task (full mode).

        Args:
            task_id: Task identifier
            output_dir: Output directory
            num_random_tests: Number of random tests for trigger rate

        Returns:
            RQ1Table2Result with oracle quality metrics
        """
        result = RQ1Table2Result(
            task_id=task_id,
            execution_pass=False,
            num_assertions=0,
            assertions_triggered=0,
            trigger_rate=0.0
        )

        task_dir = output_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        st_path = self.benchmark_root / task_id / BENCHMARK_ST_DIR / f"{task_id}.st"
        harness_path = self.benchmark_root / task_id / "plc_c_files" / "harness.c"
        schema_path = self.benchmark_root / task_id / BENCHMARK_INPUT_DIR / BENCHMARK_SCHEMA_FILE

        if not all([st_path.exists(), harness_path.exists(), schema_path.exists()]):
            result.note = "Required files not found"
            return result

        try:
            # Step 1: Generate assertions
            self.logger.info_print(f"  {task_id}: Generating assertions")
            analyzer = TestCaseAnalyzer(
                st_path=st_path,
                harness_path=harness_path,
                logger=self.logger,
                work_dir=task_dir
            )
            analysis_result = analyzer.analyze(work_dir=task_dir)

            asserted_harness_path = analysis_result.patched_harness
            assertion_count = analysis_result.assertion_code.count("fflush(stderr)")

            # Step 2: Compile asserted version
            self.logger.info_print(f"  {task_id}: Compiling asserted harness")
            silent_logger = Logger("/tmp/plchat_silent", "silent.log", level=LEVEL.ERROR)

            executor = STExecutor(root_dir=str(self.project_root), logger=silent_logger, debug=False)

            temp_dir = task_dir / "temp"
            temp_dir.mkdir(exist_ok=True)

            st_ok = executor.compile_st_to_c(
                st_code_path=str(st_path),
                output_dir=str(temp_dir),
                harness_path="/dev/null"
            )

            if not st_ok:
                result.note = "ST compilation failed"
                return result

            # Copy asserted harness
            target_harness = temp_dir / "harness_assertioned.c"
            shutil.copy(asserted_harness_path, target_harness)

            # Compile binary
            c_files = list(temp_dir.glob("*.c"))
            binary_path = task_dir / "plc_harness_test"

            matiec_bin = shutil.which("iec2c")
            matiec_lib = str(Path(matiec_bin).parent / "lib" / "C") if matiec_bin else "/usr/local/lib/matiec"

            c_ok = executor.compile_c_to_binary(
                source_files=[str(f) for f in c_files],
                output_binary=str(binary_path),
                include_dirs=[matiec_lib, str(temp_dir)],
                libraries=[],
                coverage_mode=False
            )

            if not c_ok:
                result.note = "C compilation failed"
                return result

            # Step 3: Test trigger rate
            self.logger.info_print(f"  {task_id}: Testing trigger rate")
            triggered_count = 0

            with open(st_path) as f:
                st_code = f.read()
            with open(schema_path) as f:
                schema = json.load(f)

            generator = RandomCaseGenerator(seed=42)

            for i in range(num_random_tests):
                payload = generator.generate_case(st_code, schema)
                if payload is None:
                    continue

                # Convert to harness input format
                input_lines = []
                for key, value in payload.items():
                    if isinstance(value, list):
                        input_lines.extend(str(v) for v in value)
                    else:
                        input_lines.append(str(value))
                input_data = "\n".join(input_lines) + "\n"

                try:
                    result_proc = subprocess.run(
                        [str(binary_path)],
                        input=input_data,
                        capture_output=True,
                        text=True,
                        timeout=2
                    )

                    if "SECURITY_ASSERTION_FAILED" in result_proc.stderr:
                        triggered_count += 1

                except subprocess.TimeoutExpired:
                    pass

            result.execution_pass = True
            result.num_assertions = assertion_count
            result.assertions_triggered = triggered_count
            result.trigger_rate = triggered_count / assertion_count if assertion_count > 0 else 0

        except Exception as e:
            result.note = f"Exception: {str(e)}"

        return result

    def run_table2_full_batch(self, tasks: Optional[List[str]] = None) -> List[RQ1Table2Result]:
        """Run Table 2 full tests for a batch of tasks."""
        task_ids = self.list_tasks(include=tasks)
        results = []

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        output_dir = self.results_base / f"table2_full_{timestamp}"

        self.logger.info(f"Running Table 2 Full for {len(task_ids)} tasks")

        for task_id in task_ids:
            self.logger.info_print(f"Processing: {task_id}")
            result = self.run_table2_full_task(task_id, output_dir, self.num_random_tests)
            results.append(result)
            self._append_csv(self.results_table2, result.to_csv_row())

        # Summary
        exec_pass = sum(1 for r in results if r.execution_pass)
        total_assertions = sum(r.num_assertions for r in results)
        total_triggered = sum(r.assertions_triggered for r in results)

        self.logger.info(f"Table 2 Full Summary: {len(results)} tasks")
        self.logger.info(f"  Execution Pass: {exec_pass}/{len(results)}")
        self.logger.info(f"  Total Assertions: {total_assertions}")
        self.logger.info(f"  Total Triggered: {total_triggered}")
        self.logger.info(f"  Trigger Rate: {total_triggered/total_assertions if total_assertions > 0 else 0:.2%}")

        return results
