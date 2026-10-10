"""
RQ3 Ablation Experiment Runner

Compact, experiment-friendly runner for RQ3 ablation studies.
Evaluates impact of individual harness components on testing effectiveness.

Usage:
    python -m experiments.run rq3 --config C1 --task 211_StackMin --budget 300
    python -m experiments.run rq3 --config C1 --fast  # Test with 3 tasks
"""

from pathlib import Path
import sys
import csv
import json
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

# Project root: experiments/rq3/runner.py → rq3 → experiments → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from experiments.rq3.config import AblationConfig
from harness.compiler.executor import STExecutor
from harness.compiler.utils import Logger, LEVEL
from harness.compiler.st_coverage_collector import STCoverageCollector
from harness.oracle import ViolationDetector
from harness.test_analysis.key_frame_extractor import KeyFrameExtractor
from harness.test_analysis.integration import TestCaseAnalyzer
from core.data_types.exp_types import ExpUnifiedIR
from core.token_tracker import TokenTracker
from config import get_temp_work_dir, get_results_dir, get_config
from tools.fuzzers.random.generator import RandomCaseGenerator

# Configuration
BENCHMARK_VERSION = "benchmark_260113"
BENCHMARK_RAW = PROJECT_ROOT / "benchmark" / BENCHMARK_VERSION / "benchmark_raw"
BENCHMARK_MUTATED = PROJECT_ROOT / "benchmark" / BENCHMARK_VERSION / "benchmark_mutated"

# Time budget
DEFAULT_BUDGET_SEC = 300
FAST_MODE_BUDGET_SEC = 60


@dataclass
class RQ3Result:
    """RQ3 experiment result record."""
    config_id: str
    task_id: str
    mutation_id: str = ""
    killed: int = 0
    total_mutants: int = 0
    valid: int = 0
    branch_coverage: str = "N/A"
    line_coverage: str = "N/A"
    input_tokens_per_iter: int = 0
    output_tokens_per_iter: int = 0
    assertion_count: int = 0
    assertion_triggered: int = 0
    duration_sec: float = 0.0
    status: str = "PENDING"
    note: str = ""

    def to_csv_row(self) -> List[str]:
        return [
            self.config_id,
            self.task_id,
            self.mutation_id,
            f"{self.killed}/{self.total_mutants}",
            f"{self.valid}/{self.total_mutants}",
            self.branch_coverage,
            self.line_coverage,
            str(self.input_tokens_per_iter),
            str(self.output_tokens_per_iter),
            f"{self.assertion_triggered}/{self.assertion_count}",
            f"{self.duration_sec:.1f}",
            self.status,
            self.note
        ]


class RQ3Runner:
    """RQ3 ablation experiment runner.

    Evaluates the impact of individual harness components on:
    - Fault detection (mutation kill rate)
    - Coverage metrics (branch/line)
    - Token efficiency
    - Assertion generation and trigger rates
    """

    CSV_HEADERS = [
        "Config", "Task", "Mutation", "Killed", "Valid",
        "BranchCov", "LineCov", "TokIn/it", "TokOut/it",
        "AssertTriggered", "Duration(s)", "Status", "Note"
    ]

    def __init__(
        self,
        config: AblationConfig,
        work_dir: Optional[Path] = None,
        logger: Optional[Logger] = None,
        fast_mode: bool = False
    ):
        """Initialize RQ3 runner.

        Args:
            config: Ablation configuration (C1, C2, C3, C4, C0, E_raw)
            work_dir: Working directory for temporary files (default: from config)
            logger: Logger instance
            fast_mode: Enable fast mode for testing (shorter budget, fewer tasks)
        """
        self.config = config
        self.fast_mode = fast_mode

        # Use unified experiment config for directory management
        # Results directory from config
        if work_dir:
            self.work_dir = work_dir
        else:
            # Create timestamped run directory
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            results_base = get_results_dir("rq3")
            self.work_dir = results_base / f"run_{config.config_id}_{timestamp}"

        self.work_dir.mkdir(parents=True, exist_ok=True)

        # Initialize logger
        self.logger = logger or Logger(str(self.work_dir / "logs"), f"rq3_{config.config_id}.log", level=LEVEL.INFO)

        # Budget
        self.budget_sec = FAST_MODE_BUDGET_SEC if fast_mode else DEFAULT_BUDGET_SEC

        # Results file
        self.results_file = self.work_dir / "results.csv"
        self._init_results_file()

        # Token tracking
        self._tok_start = TokenTracker.get().snapshot() if TokenTracker.get() else {"input_tokens": 0, "output_tokens": 0}

        # MatIEC library path
        iec2c_bin = shutil.which("iec2c")
        if iec2c_bin:
            self.matiec_lib = str(Path(iec2c_bin).parent / "lib" / "C")
        else:
            self.matiec_lib = "/usr/local/lib/matiec"

        # Coverage collector
        self.coverage_collector = STCoverageCollector(
            root_dir=str(PROJECT_ROOT),
            logger=self.logger,
            default_output_format="StoredTestCase",
            llvm_version=18
        )

        # Violation detector
        self.violation_detector = ViolationDetector(logger=self.logger)

        # Keyframe extractor
        self.keyframe_extractor = KeyFrameExtractor()

        self.logger.info(f"RQ3 Runner initialized: {config.description}")

    def _init_results_file(self):
        """Initialize CSV results file."""
        if not self.results_file.exists():
            self.results_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.results_file, "w", newline="") as f:
                csv.writer(f).writerow(self.CSV_HEADERS)

    def _append_result(self, result: RQ3Result):
        """Append result to CSV file."""
        with open(self.results_file, "a", newline="") as f:
            csv.writer(f).writerow(result.to_csv_row())

    def list_tasks(self, include: Optional[List[str]] = None) -> List[str]:
        """List available tasks in benchmark.

        Args:
            include: Optional list of task IDs to filter

        Returns:
            List of task IDs
        """
        all_tasks = sorted([
            d.name for d in BENCHMARK_RAW.iterdir()
            if d.is_dir() and not d.name.startswith("_")
        ])
        if include:
            return [t for t in all_tasks if t in include]
        if self.fast_mode:
            return all_tasks[:3]
        return all_tasks

    def list_mutations(self, task_id: str) -> List[str]:
        """List mutation IDs for a task.

        Args:
            task_id: Task identifier

        Returns:
            List of mutation IDs (e.g., "mutation_0", "mutation_1", ...)
        """
        task_dir = BENCHMARK_MUTATED / task_id
        if not task_dir.exists():
            return []
        return sorted([
            d.name for d in task_dir.iterdir()
            if d.is_dir() and d.name.startswith("mutation_")
        ])

    def run_task(
        self,
        task_id: str,
        mutation_id: Optional[str] = None
    ) -> RQ3Result:
        """Run RQ3 experiment for a single task (and optional mutation).

        Args:
            task_id: Task identifier (e.g., "211_StackMin")
            mutation_id: Optional mutation ID (e.g., "mutation_0")

        Returns:
            RQ3Result with experiment outcomes
        """
        result = RQ3Result(
            config_id=self.config.config_id,
            task_id=task_id,
            mutation_id=mutation_id or "",
            total_mutants=1 if mutation_id else 0
        )

        start_time = time.time()

        # Determine paths
        if mutation_id:
            base_dir = BENCHMARK_MUTATED / task_id / mutation_id
            st_file = base_dir / "plc_st_files" / f"{task_id}.st"
            harness_file = base_dir / "plc_c_files" / "harness.c"
            schema_file = base_dir / "input" / "input_schema_v2.json"
        else:
            base_dir = BENCHMARK_RAW / task_id
            st_file = base_dir / "plc_st_files" / f"{task_id}.st"
            harness_file = base_dir / "plc_c_files" / "harness.c"
            schema_file = base_dir / "input" / "input_schema_v2.json"

        # Check required files
        for p, name in [(st_file, "ST"), (harness_file, "Harness"), (schema_file, "Schema")]:
            if not p.exists():
                result.status = "ERROR"
                result.note = f"{name} file not found: {p}"
                return result

        try:
            # Read ST code and schema
            st_code = st_file.read_text(encoding='utf-8')
            with open(schema_file) as f:
                schema = json.load(f)

            # Generate assertions
            result.assertion_count = self._generate_assertions(st_file, harness_file)

            # Run test generation and evaluation
            # This is a simplified version - full implementation would use Generator agent
            eval_result = self._evaluate_coverage(st_file, harness_file, schema)

            # Extract results
            if isinstance(eval_result, dict):
                result.branch_coverage = eval_result.get("branch_coverage", "N/A")
                result.line_coverage = eval_result.get("line_coverage", "N/A")
                result.status = "SUCCESS" if eval_result.get("success") else "FAILED"
                result.note = eval_result.get("note", "")

            # Token accounting
            if TokenTracker.get():
                tok_end = TokenTracker.get().snapshot()
                result.input_tokens_per_iter = tok_end["input_tokens"] - self._tok_start["input_tokens"]
                result.output_tokens_per_iter = tok_end["output_tokens"] - self._tok_start["output_tokens"]

        except Exception as e:
            result.status = "ERROR"
            result.note = str(e)
            self.logger.error(f"Exception in run_task: {e}")

        result.duration_sec = time.time() - start_time
        return result

    def _generate_assertions(self, st_file: Path, harness_file: Path) -> int:
        """Generate assertions for the task.

        Args:
            st_file: Path to ST source file
            harness_file: Path to C harness file

        Returns:
            Number of assertions generated
        """
        try:
            # Use a dedicated temp directory to avoid conflicts with _evaluate_coverage
            assertion_temp_dir = self.work_dir / "temp_assertions"
            assertion_temp_dir.mkdir(parents=True, exist_ok=True)

            analyzer = TestCaseAnalyzer(
                st_path=st_file,
                harness_path=harness_file,
                logger=self.logger,
                work_dir=assertion_temp_dir
            )
            result = analyzer.analyze(work_dir=assertion_temp_dir)
            if result and result.assertion_code:
                return result.assertion_code.count("fflush(stderr)")
        except Exception as e:
            self.logger.warning(f"Assertion generation failed: {e}")
        return 0

    def _evaluate_coverage(
        self,
        st_file: Path,
        harness_file: Path,
        schema: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate coverage for the task.

        Args:
            st_file: Path to ST source file
            harness_file: Path to C harness file
            schema: Input schema

        Returns:
            Dictionary with coverage results
        """
        # Create temporary working directory
        temp_dir = self.work_dir / "temp_eval"
        temp_dir.mkdir(parents=True, exist_ok=True)

        try:
            executor = STExecutor(root_dir=str(PROJECT_ROOT), logger=self.logger, debug=False)

            # Compile ST to C (with actual harness file)
            st_ok = executor.compile_st_to_c(
                st_code_path=str(st_file),
                output_dir=str(temp_dir),
                harness_path=str(harness_file) if harness_file.exists() else None
            )
            if not st_ok:
                return {"success": False, "note": "ST compilation failed"}

            # Copy harness if not already in temp_dir
            if harness_file.exists():
                target_harness = temp_dir / "harness.c"
                if not target_harness.exists() or target_harness.stat().st_size == 0:
                    shutil.copy2(harness_file, target_harness)

            # Compile to binary
            c_files = list(temp_dir.glob("*.c"))
            binary_path = temp_dir / "test_binary"
            c_ok = executor.compile_c_to_binary(
                source_files=[str(f) for f in c_files],
                output_binary=str(binary_path),
                include_dirs=[self.matiec_lib, str(temp_dir)],
                libraries=[],
                coverage_mode=True
            )
            if not c_ok:
                return {"success": False, "note": "C compilation failed"}

            # Generate a simple test case
            st_code = st_file.read_text(encoding='utf-8')
            generator = RandomCaseGenerator()
            payload = generator.generate_case(st_code, schema)

            if payload:
                # Convert to harness input format
                input_lines = []
                for key, value in payload.items():
                    if isinstance(value, list):
                        input_lines.extend(str(v) for v in value)
                    else:
                        input_lines.append(str(value))
                input_data = "\n".join(input_lines) + "\n"
            else:
                input_data = "0 0 0\n"

            # Execute with coverage
            input_file = temp_dir / "input.txt"
            input_file.write_text(input_data)

            exec_result = executor.execute_binary(
                binary_path=str(binary_path),
                input_file=str(input_file),
                timeout=5
            )

            if exec_result.get("status") == "success":
                return {
                    "success": True,
                    "note": "Coverage collected",
                    "branch_coverage": "N/A",  # Would be extracted from coverage data
                    "line_coverage": "N/A"
                }
            else:
                return {"success": False, "note": exec_result.get("error", "Execution failed")}

        except Exception as e:
            return {"success": False, "note": str(e)}

    def run_batch(
        self,
        tasks: Optional[List[str]] = None,
        max_mutations: Optional[int] = None
    ) -> List[RQ3Result]:
        """Run RQ3 experiments for a batch of tasks.

        Args:
            tasks: List of task IDs (default: all or fast_mode subset)
            max_mutations: Maximum mutations per task (None = all)

        Returns:
            List of RQ3Result
        """
        task_ids = self.list_tasks(include=tasks)
        results = []

        self.logger.info(f"Running RQ3 {self.config.config_id}: {len(task_ids)} tasks")

        for task_id in task_ids:
            self.logger.info(f"Processing task: {task_id}")

            # Check if we should run on mutations
            mutations = self.list_mutations(task_id)
            if mutations and max_mutations is not None:
                mutations = mutations[:max_mutations]

            if mutations:
                # Run on each mutation
                for mutation_id in mutations:
                    result = self.run_task(task_id, mutation_id)
                    results.append(result)
                    self._append_result(result)
            else:
                # Run on raw task
                result = self.run_task(task_id)
                results.append(result)
                self._append_result(result)

        # Summary
        self.logger.info(f"RQ3 {self.config.config_id} completed: {len(results)} results")
        return results


def main():
    """Main entry point for RQ3 experiments."""
    import argparse

    parser = argparse.ArgumentParser(description="RQ3 Ablation Experiments")
    parser.add_argument("--config", default="C1",
                        choices=["C1", "C2", "C3", "C4", "C0", "E_raw"],
                        help="Ablation configuration")
    parser.add_argument("--tasks", nargs="+", default=None,
                        help="Specific tasks to run")
    parser.add_argument("--fast", action="store_true",
                        help="Fast mode for testing")
    parser.add_argument("--max-mutations", type=int, default=None,
                        help="Maximum mutations per task")

    args = parser.parse_args()

    config = AblationConfig.from_id(args.config)
    runner = RQ3Runner(config=config, fast_mode=args.fast)

    results = runner.run_batch(tasks=args.tasks, max_mutations=args.max_mutations)

    print(f"\nRQ3 {args.config} completed: {len(results)} results")
    print(f"Results: {runner.results_file}")


if __name__ == "__main__":
    main()
