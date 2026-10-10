"""
RQ2 Experiment Runner - Cross-engine Testing Capability

Refactored to use PLCHaT's existing interfaces (harness.STCompiler, tools.*)

RQ2 consists of two independent experiments:
1. Coverage Collection: Measures branch/line coverage on benchmark_raw
2. Mutation Detection: Measures mutant kill rate on benchmark_mutated
"""

import csv
import dataclasses
import json
import re
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

# Project root: experiments/rq2/runner.py → rq2 → experiments → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# PLCHaT imports
from harness.compiler.st_compiler_core import STCompilerCore
from harness.compiler.utils import Logger, LEVEL
from core.evaluation.exp_types import ExpUnifiedIR
from config.constants import MODEL_PRICING

# Import available fuzzing tools
from tools.fuzzers.random.generator import RandomCaseGenerator
from tools.fuzzers.afl.generator import AFLCaseGenerator
from tools.fuzzers.dse.generator import DSECaseGenerator
from tools.fuzzers.direct_llm import DirectLLMGenerator


# Pricing constants
deepseek_v3_input_price = MODEL_PRICING["deepseek-v3"]["input"]
deepseek_v3_output_price = MODEL_PRICING["deepseek-v3"]["output"]

# Configuration
BENCHMARK_VERSION = "benchmark_260113"
TIMEOUT_SEC = 120  # 2 minutes unified budget
EXECUTION_TIMEOUT_SEC = 2.0

# Experiment types
EXPERIMENT_COVERAGE = "coverage"
EXPERIMENT_MUTATION = "mutation"


@dataclass
class RQ2Result:
    """RQ2 experiment result record."""
    timestamp: str
    method: str
    task: str
    mutation_id: str
    grade: str = "UNKNOWN"
    outcome: str = "PENDING"
    depth: int = 0
    valid_rate: float = 0.0
    duration_sec: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    gen_speed_tok_per_sec: float = 0.0
    cost_usd: float = 0.0
    note: str = ""
    line_coverage: str = "N/A"
    branch_coverage: str = "N/A"

    def to_csv_row(self) -> List[str]:
        return [
            self.timestamp, self.method, self.task, self.mutation_id, self.grade,
            self.outcome, str(self.depth), f"{self.valid_rate:.4f}",
            f"{self.duration_sec:.2f}", str(self.input_tokens), str(self.output_tokens),
            f"{self.gen_speed_tok_per_sec:.2f}", f"{self.cost_usd:.6f}", self.note,
            self.line_coverage, self.branch_coverage
        ]


class RQ2Util:
    """RQ2 experiment utility functions."""

    CSV_HEADERS = [
        "Timestamp", "Method", "Task", "MutationID", "Grade",
        "Outcome", "Depth", "ValidRate",
        "Duration_Sec", "Input_Tokens", "Output_Tokens",
        "Gen_Speed_TokPerSec", "Cost_USD", "Note",
        "LineCoverage", "BranchCoverage"
    ]

    @staticmethod
    def get_mutation_grade(audit_file: Path) -> str:
        """Extract mutation grade (GOLD/SILVER/BRONZE) from QUALITY_AUDIT.md"""
        if not audit_file.exists():
            return "UNKNOWN"
        try:
            content = audit_file.read_text(encoding='utf-8')
            match = re.search(r"GRADE:\s*\[?(GOLD|SILVER|BRONZE)\]?", content, re.IGNORECASE)
            return match.group(1).upper() if match else "UNKNOWN"
        except Exception:
            return "UNKNOWN"

    @staticmethod
    def init_csv(filepath: Path, force_clean: bool = False):
        """Initialize CSV file with headers."""
        filepath.parent.mkdir(parents=True, exist_ok=True)
        if force_clean or not filepath.exists():
            with open(filepath, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(RQ2Util.CSV_HEADERS)

    @staticmethod
    def append_result(filepath: Path, result: RQ2Result):
        """Append a result row to CSV."""
        with open(filepath, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(result.to_csv_row())

    @staticmethod
    def parse_signal(exit_code: int) -> str:
        """Parse POSIX signal to readable string."""
        signal_map = {
            128 + signal.SIGABRT: "SIGABRT (Assertion/Abort)",
            128 + signal.SIGFPE: "SIGFPE (Divide by Zero)",
            128 + signal.SIGSEGV: "SIGSEGV (Segmentation Fault)"
        }
        return signal_map.get(exit_code, f"Exit code {exit_code}")


class RQ2Runner:
    """RQ2 experiment runner for cross-engine testing capability evaluation.

    Manages two independent experiments:
    1. Coverage Collection (benchmark_raw): Measures branch/line coverage
    2. Mutation Detection (benchmark_mutated): Measures mutant kill rate

    Testing engines:
    - Random (tau_rand)
    - AFL++ (tau_mut)
    - DSE (tau_dse)
    - Direct LLM (tau_llm)
    """

    def __init__(
        self,
        project_root: Optional[Path] = None,
        mode: str = "all",
        experiment_type: str = EXPERIMENT_MUTATION,
        fast_mode: bool = False
    ):
        """Initialize RQ2 runner.

        Args:
            project_root: Project root directory
            mode: Experiment mode ("all", "random", "afl", "dse", "llm")
            experiment_type: Experiment type ("coverage" or "mutation")
            fast_mode: Enable fast mode for testing (shorter timeouts)
        """
        self.project_root = project_root or PROJECT_ROOT
        self.mode = mode
        self.experiment_type = experiment_type
        self.fast_mode = fast_mode

        # Paths based on experiment type
        if experiment_type == EXPERIMENT_COVERAGE:
            self.benchmark_root = self.project_root / "benchmark" / BENCHMARK_VERSION / "benchmark_raw"
            self.results_file_name = f"coverage_results_rq2_{mode}.csv"
        else:  # EXPERIMENT_MUTATION
            self.benchmark_root = self.project_root / "benchmark" / BENCHMARK_VERSION / "benchmark_mutated"
            self.results_file_name = f"mutation_results_rq2_{mode}.csv"

        self.results_dir = self.project_root / "output" / "rq2_results"
        self.results_file = self.results_dir / self.results_file_name

        # Configuration
        self.timeout_sec = 18 if fast_mode else TIMEOUT_SEC
        self.exec_timeout_sec = EXECUTION_TIMEOUT_SEC

        # Initialize compiler core
        self.compiler = STCompilerCore(
            benchmark_root=str(self.benchmark_root),
            root_dir=str(self.project_root),
            debug=False
        )

        # Logger
        self.logger = Logger(
            str(self.results_dir / "logs"),
            "rq2_runner.log",
            level=LEVEL.INFO
        )

    def init_env(self, clean_existing: bool = False):
        """Initialize output directories and CSV files."""
        self.results_dir.mkdir(parents=True, exist_ok=True)
        RQ2Util.init_csv(self.results_file, force_clean=clean_existing)
        self.logger.info(f"RQ2 environment initialized. Results: {self.results_file}")

    def list_tasks(self, include: Optional[List[str]] = None) -> List[str]:
        """List available tasks, optionally filtered by include list."""
        all_tasks = sorted([d.name for d in self.benchmark_root.iterdir() if d.is_dir()])
        if include:
            return [t for t in all_tasks if t in include]
        return all_tasks

    def list_mutations(self, task_name: str) -> List[str]:
        """List mutation IDs for a given task (only for mutation experiments)."""
        if self.experiment_type != EXPERIMENT_MUTATION:
            return []

        task_dir = self.benchmark_root / task_name
        if not task_dir.exists():
            return []
        return sorted([d.name for d in task_dir.iterdir() if d.is_dir() and d.name.startswith("mutation_")])

    def run_mutation_test(
        self,
        task_name: str,
        mutation_id: str,
        test_case: ExpUnifiedIR,
        method: str = "random"
    ) -> RQ2Result:
        """Run a single mutation test.

        Args:
            task_name: Task name (e.g., "211_StackMin")
            mutation_id: Mutation ID (e.g., "mutation_0")
            test_case: Test case as ExpUnifiedIR
            method: Testing method used

        Returns:
            RQ2Result with test outcome
        """
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Get mutation grade
        audit_file = self.benchmark_root / task_name / mutation_id / "QUALITY_AUDIT.md"
        grade = RQ2Util.get_mutation_grade(audit_file)

        result = RQ2Result(
            timestamp=timestamp,
            method=method,
            task=task_name,
            mutation_id=mutation_id,
            grade=grade
        )

        # Locate task directory
        task_dir = self.benchmark_root / task_name / mutation_id
        if not task_dir.exists():
            result.outcome = "ERROR"
            result.note = "Task directory not found"
            result.duration_sec = time.time() - start_time
            return result

        # Find ST file
        try:
            st_file = list((task_dir / "plc_st_files").glob("*.st"))[0]
        except (IndexError, FileNotFoundError):
            result.outcome = "ERROR"
            result.note = "ST file missing"
            result.duration_sec = time.time() - start_time
            return result

        harness_file = task_dir / "plc_c_files" / "harness.c"
        schema_file = task_dir / "input" / "input_schema_v2.json"

        # Update test case schema path
        test_case.schema_path = str(schema_file)

        # Prepare temp directory
        temp_dir = self.results_dir / "temp" / f"{method}_{task_name}_{mutation_id}"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        input_file = temp_dir / "input.txt"

        try:
            # Convert test case to harness input
            input_content = test_case.to_harness_input()
            input_file.write_text(input_content, encoding='utf-8')

            # Read ST code
            st_code = st_file.read_text(encoding='utf-8')
            harness_code = harness_file.read_text(encoding='utf-8') if harness_file.exists() else ""

            # Execute with coverage
            exec_result = self.compiler.execute_st_code_with_coverage(
                st_code_input=st_code,
                harness_input=harness_code,
                input_data=input_content,
                benchmark_case=f"{task_name}_{mutation_id}",
                temp_dir=str(temp_dir)
            )

            result.duration_sec = time.time() - start_time

            # Extract token information from test_case metadata (for LLM method)
            if test_case.metadata and method == "llm":
                result.input_tokens = test_case.metadata.get("input_tokens", 0)
                result.output_tokens = test_case.metadata.get("output_tokens", 0)
                generation_time = test_case.metadata.get("generation_time_sec", 0)
                if generation_time > 0 and result.output_tokens > 0:
                    result.gen_speed_tok_per_sec = result.output_tokens / generation_time

            # Parse execution result (returns dict)
            if isinstance(exec_result, dict):
                status = exec_result.get("status", "")
                result.outcome = "SURVIVED" if status == "success" else "ERROR"
                result.valid_rate = 1.0 if status == "success" else 0.0

                # Check for assertion failures
                raw_stdout = exec_result.get("stdout", "")
                if "ASSERTION FAILED" in raw_stdout or "VIOLATION" in raw_stdout:
                    result.outcome = "KILLED"
                    result.note = "Assertion/Violation detected"
                elif status == "success":
                    result.note = f"Coverage collected successfully"

                if status != "success" and status != "compilation_failed":
                    result.note = exec_result.get("stderr", "Execution failed") or "Execution failed"
            else:
                result.outcome = "ERROR"
                result.note = "Invalid result format"

        except Exception as e:
            result.duration_sec = time.time() - start_time
            result.outcome = "ERROR"
            result.note = str(e)

        return result

    def run_task_batch(
        self,
        task_name: str,
        methods: Optional[List[str]] = None,
        max_mutations: Optional[int] = None
    ) -> List[RQ2Result]:
        """Run experiments for a task with specified methods.

        For coverage experiments: Runs on raw task
        For mutation experiments: Runs on all mutations

        Args:
            task_name: Task name
            methods: List of methods to run (default: based on mode)
            max_mutations: Maximum mutations to test per task (mutation exp only)

        Returns:
            List of RQ2Result
        """
        if methods is None:
            if self.mode == "all":
                methods = ["random", "afl", "dse", "llm"]
            else:
                methods = [self.mode]

        results = []

        if self.experiment_type == EXPERIMENT_COVERAGE:
            # Coverage experiment: run on raw task
            self.logger.info(f"Running RQ2 coverage for task {task_name}, methods={methods}")
            for method in methods:
                test_case = self._generate_test_case_coverage(task_name, method)
                result = self.run_coverage_test(task_name, test_case, method)
                results.append(result)
                RQ2Util.append_result(self.results_file, result)
        else:
            # Mutation experiment: run on all mutations
            mutations = self.list_mutations(task_name)
            if max_mutations:
                mutations = mutations[:max_mutations]

            self.logger.info(f"Running RQ2 mutation for task {task_name}, {len(mutations)} mutations, methods={methods}")

            for mutation_id in mutations:
                for method in methods:
                    test_case = self._generate_test_case(task_name, mutation_id, method)
                    result = self.run_mutation_test(task_name, mutation_id, test_case, method)
                    results.append(result)
                    RQ2Util.append_result(self.results_file, result)

        return results

    def _generate_test_case_coverage(
        self,
        task_name: str,
        method: str
    ) -> ExpUnifiedIR:
        """Generate a test case for coverage experiment using specified method.

        Args:
            task_name: Task name
            method: Testing method (random, afl, dse, llm)

        Returns:
            ExpUnifiedIR test case
        """
        task_dir = self.benchmark_root / task_name
        schema_file = task_dir / "input" / "input_schema_v2.json"
        st_file = list((task_dir / "plc_st_files").glob("*.st"))[0]

        # Read ST code and schema
        st_code = st_file.read_text(encoding='utf-8')
        with open(schema_file, 'r') as f:
            schema_data = json.load(f)

        # Generate based on method
        if method == "random":
            generator = RandomCaseGenerator()
            # Generate multi-cycle sparse timeline for better coverage
            sparse_timeline = {}
            for cycle in range(10):  # Generate 10 different cycles
                payload = generator.generate_case(st_code, schema_data)
                if payload:
                    sparse_timeline[str(cycle)] = payload

            return ExpUnifiedIR(
                exp_id=f"random_{task_name}",
                target_st_path=str(st_file),
                schema_path=str(schema_file),
                tester_type="random",
                total_cycles=10,
                sparse_timeline=sparse_timeline
            )

        elif method == "afl":
            # Generate multi-cycle inputs for AFL
            base_generator = RandomCaseGenerator()
            afl_generator = AFLCaseGenerator()

            # Initialize AFL with a random seed
            seed_payload = base_generator.generate_case(st_code, schema_data)
            if seed_payload:
                afl_generator.current_seed = {"sparse_timeline": {"0": seed_payload}, "total_cycles": 10}

            sparse_timeline = {}
            for cycle in range(10):
                case = afl_generator.generate_case(st_code, schema_data, task_name)
                if isinstance(case, dict):
                    # Extract sparse_timeline from AFL result
                    afl_timeline = case.get("sparse_timeline", {})
                    if afl_timeline:
                        # Use first cycle from AFL timeline
                        first_cycle_data = list(afl_timeline.values())[0] if afl_timeline else {}
                        sparse_timeline[str(cycle)] = first_cycle_data

            return ExpUnifiedIR(
                exp_id=f"afl_{task_name}",
                target_st_path=str(st_file),
                schema_path=str(schema_file),
                tester_type="afl",
                total_cycles=10,
                sparse_timeline=sparse_timeline
            )

        elif method == "dse":
            # Generate multi-cycle inputs for DSE
            generator = RandomCaseGenerator()
            sparse_timeline = {}
            for cycle in range(10):
                payload = generator.generate_case(st_code, schema_data)
                if payload:
                    sparse_timeline[str(cycle)] = payload

            return ExpUnifiedIR(
                exp_id=f"dse_{task_name}",
                target_st_path=str(st_file),
                schema_path=str(schema_file),
                tester_type="dse",
                total_cycles=10,
                sparse_timeline=sparse_timeline
            )

        elif method == "llm":
            # For LLM, use DirectLLMGenerator
            try:
                from tools.fuzzers.direct_llm.generator import DirectLLMGenerator
                generator = DirectLLMGenerator(max_cycles=10)
                case = generator.generate_case(st_code, schema_data)

                if isinstance(case, ExpUnifiedIR):
                    # Preserve all metadata including token info
                    case.exp_id = f"llm_{task_name}"
                    case.target_st_path = str(st_file)
                    case.schema_path = str(schema_file)
                    case.tester_type = "llm"
                    return case
                elif isinstance(case, dict):
                    # Handle dict return
                    return ExpUnifiedIR(
                        exp_id=f"llm_{task_name}",
                        target_st_path=str(st_file),
                        schema_path=str(schema_file),
                        tester_type="llm",
                        total_cycles=case.get("total_cycles", 10),
                        sparse_timeline=case.get("sparse_timeline", {"0": {}}),
                        metadata=case.get("metadata", {})
                    )
            except RuntimeError as e:
                self.logger.error(f"LLM generation failed for coverage {task_name}: {e}")

            # Fallback to minimal case if LLM generation failed
            return ExpUnifiedIR(
                exp_id=f"llm_{task_name}",
                target_st_path=str(st_file),
                schema_path=str(schema_file),
                tester_type="llm",
                total_cycles=1,
                sparse_timeline={"0": {}},
                metadata={"error": "LLM generation failed, using empty case"}
            )

        # Fallback to minimal random case
        return ExpUnifiedIR(
            exp_id=f"fallback_{task_name}",
            target_st_path=str(st_file),
            schema_path=str(schema_file),
            tester_type="fallback",
            total_cycles=5,
            sparse_timeline={"0": {}}
        )

    def run_coverage_test(
        self,
        task_name: str,
        test_case: ExpUnifiedIR,
        method: str
    ) -> RQ2Result:
        """Run a coverage test on raw task.

        Args:
            task_name: Task name (e.g., "211_StackMin")
            test_case: Test case as ExpUnifiedIR
            method: Testing method used

        Returns:
            RQ2Result with coverage metrics
        """
        start_time = time.time()
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        result = RQ2Result(
            timestamp=timestamp,
            method=method,
            task=task_name,
            mutation_id="N/A",
            grade="N/A"
        )

        # Locate task directory
        task_dir = self.benchmark_root / task_name
        if not task_dir.exists():
            result.outcome = "ERROR"
            result.note = "Task directory not found"
            result.duration_sec = time.time() - start_time
            return result

        # Find ST file
        try:
            st_file = list((task_dir / "plc_st_files").glob("*.st"))[0]
        except (IndexError, FileNotFoundError):
            result.outcome = "ERROR"
            result.note = "ST file missing"
            result.duration_sec = time.time() - start_time
            return result

        harness_file = task_dir / "plc_c_files" / "harness.c"
        schema_file = task_dir / "input" / "input_schema_v2.json"

        # Update test case schema path
        test_case.schema_path = str(schema_file)

        # Prepare temp directory
        temp_dir = self.results_dir / "temp" / f"{method}_{task_name}_coverage"
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        temp_dir.mkdir(parents=True, exist_ok=True)

        input_file = temp_dir / "input.txt"

        try:
            # Convert test case to harness input
            input_content = test_case.to_harness_input()
            input_file.write_text(input_content, encoding='utf-8')

            # Read ST code
            st_code = st_file.read_text(encoding='utf-8')
            harness_code = harness_file.read_text(encoding='utf-8') if harness_file.exists() else ""

            # Execute with coverage
            exec_result = self.compiler.execute_st_code_with_coverage(
                st_code_input=st_code,
                harness_input=harness_code,
                input_data=input_content,
                benchmark_case=f"{task_name}_coverage",
                temp_dir=str(temp_dir)
            )

            result.duration_sec = time.time() - start_time

            # Extract token information from test_case metadata (for LLM method)
            if test_case.metadata and method == "llm":
                result.input_tokens = test_case.metadata.get("input_tokens", 0)
                result.output_tokens = test_case.metadata.get("output_tokens", 0)
                generation_time = test_case.metadata.get("generation_time_sec", 0)
                if generation_time > 0 and result.output_tokens > 0:
                    result.gen_speed_tok_per_sec = result.output_tokens / generation_time

            # Parse execution result
            if isinstance(exec_result, dict):
                status = exec_result.get("status", "")
                result.outcome = "SUCCESS" if status == "success" else "ERROR"
                result.valid_rate = 1.0 if status == "success" else 0.0

                # Extract coverage metrics from coverage_data
                coverage_data = exec_result.get("coverage_data")

                if coverage_data and hasattr(coverage_data, '__dict__'):
                    # CoverageReport object
                    summary = coverage_data.coverage_summary if hasattr(coverage_data, 'coverage_summary') else None

                    if summary and hasattr(summary, 'line_coverage'):
                        line_cov = summary.line_coverage
                        if hasattr(line_cov, 'percentage'):
                            result.line_coverage = line_cov.percentage.replace("%", "") if line_cov.percentage else "N/A"

                        branch_cov = summary.branch_coverage
                        if hasattr(branch_cov, 'percentage'):
                            result.branch_coverage = branch_cov.percentage.replace("%", "") if branch_cov.percentage else "N/A"

                        result.note = f"Line: {result.line_coverage}%, Branch: {result.branch_coverage}%"
                    else:
                        result.note = "Coverage summary not available"
                elif isinstance(coverage_data, dict):
                    # Dictionary format
                    summary = coverage_data.get("summary_data", {})

                    line_cov = summary.get("line_coverage", {})
                    if isinstance(line_cov, dict):
                        result.line_coverage = line_cov.get("percentage", "N/A")
                        if isinstance(result.line_coverage, str):
                            result.line_coverage = result.line_coverage.replace("%", "")

                    branch_cov = summary.get("branch_coverage", {})
                    if isinstance(branch_cov, dict):
                        result.branch_coverage = branch_cov.get("percentage", "N/A")
                        if isinstance(result.branch_coverage, str):
                            result.branch_coverage = result.branch_coverage.replace("%", "")

                    result.note = f"Line: {result.line_coverage}%, Branch: {result.branch_coverage}%"
                else:
                    result.note = "Coverage data not available"

                if status != "success" and status != "compilation_failed":
                    error_msg = exec_result.get("stderr", "Execution failed") or "Execution failed"
                    if result.note == "Coverage data not available" or "not available" in result.note:
                        result.note = error_msg
                    else:
                        result.note = f"{result.note}. {error_msg}"
            else:
                result.outcome = "ERROR"
                result.note = "Invalid result format"

        except Exception as e:
            result.duration_sec = time.time() - start_time
            result.outcome = "ERROR"
            result.note = str(e)

        return result

    def _generate_test_case(
        self,
        task_name: str,
        mutation_id: str,
        method: str
    ) -> ExpUnifiedIR:
        """Generate a test case for a mutation using specified method.

        Args:
            task_name: Task name
            mutation_id: Mutation ID
            method: Testing method (random, afl, dse, llm)

        Returns:
            ExpUnifiedIR test case
        """
        task_dir = self.benchmark_root / task_name / mutation_id
        schema_file = task_dir / "input" / "input_schema_v2.json"
        st_file = list((task_dir / "plc_st_files").glob("*.st"))[0]

        # Read ST code and schema
        st_code = st_file.read_text(encoding='utf-8')
        with open(schema_file, 'r') as f:
            schema_data = json.load(f)

        # Generate based on method
        if method == "random":
            generator = RandomCaseGenerator()
            payload = generator.generate_case(st_code, schema_data)
            if payload:
                # Convert dict payload to sparse_timeline
                return ExpUnifiedIR(
                    exp_id=f"random_{task_name}_{mutation_id}",
                    target_st_path=str(st_file),
                    schema_path=str(schema_file),
                    tester_type="random",
                    total_cycles=10,
                    sparse_timeline={"0": payload}
                )

        elif method == "afl":
            generator = AFLCaseGenerator()
            case = generator.generate_case(st_code, schema_data, task_name)
            if isinstance(case, dict):
                # Handle dict return from AFL
                return ExpUnifiedIR(
                    exp_id=f"afl_{task_name}_{mutation_id}",
                    target_st_path=str(st_file),
                    schema_path=str(schema_file),
                    tester_type="afl",
                    total_cycles=case.get("total_cycles", 10),
                    sparse_timeline=case.get("sparse_timeline", {"0": {}})
                )
            elif isinstance(case, ExpUnifiedIR):
                case.exp_id = f"afl_{task_name}_{mutation_id}"
                case.target_st_path = str(st_file)
                case.schema_path = str(schema_file)
                case.tester_type = "afl"
                return case

        elif method == "dse":
            generator = DSECaseGenerator(max_depth=10, timeout_sec=60)
            case = generator.generate_case_simple(st_code, schema_data, task_name)
            if isinstance(case, dict):
                return ExpUnifiedIR(
                    exp_id=f"dse_{task_name}_{mutation_id}",
                    target_st_path=str(st_file),
                    schema_path=str(schema_file),
                    tester_type="dse",
                    total_cycles=case.get("total_cycles", 10),
                    sparse_timeline=case.get("sparse_timeline", {"0": {}})
                )
            elif isinstance(case, ExpUnifiedIR):
                case.exp_id = f"dse_{task_name}_{mutation_id}"
                case.target_st_path = str(st_file)
                case.schema_path = str(schema_file)
                case.tester_type = "dse"
                return case

        elif method == "llm":
            try:
                generator = DirectLLMGenerator(max_cycles=50)
                case = generator.generate_case(st_code, schema_data)
                if isinstance(case, dict):
                    return ExpUnifiedIR(
                        exp_id=f"llm_{task_name}_{mutation_id}",
                        target_st_path=str(st_file),
                        schema_path=str(schema_file),
                        tester_type="llm",
                        total_cycles=case.get("total_cycles", 50),
                        sparse_timeline=case.get("sparse_timeline", {"0": {}}),
                        metadata=case.get("metadata", {})  # Preserve token metadata
                    )
                elif isinstance(case, ExpUnifiedIR):
                    case.exp_id = f"llm_{task_name}_{mutation_id}"
                    case.target_st_path = str(st_file)
                    case.schema_path = str(schema_file)
                    case.tester_type = "llm"
                    # Preserve token metadata from LLM generation
                    if not case.metadata:
                        case.metadata = {}
                    return case
            except RuntimeError as e:
                self.logger.error(f"LLM generation failed for {task_name}_{mutation_id}: {e}")
                # Return empty case with error metadata
                return ExpUnifiedIR(
                    exp_id=f"llm_error_{task_name}_{mutation_id}",
                    target_st_path=str(st_file),
                    schema_path=str(schema_file),
                    tester_type="llm",
                    total_cycles=0,
                    sparse_timeline={},
                    metadata={"error": str(e)}
                )

        # Fallback to minimal random case
        return ExpUnifiedIR(
            exp_id=f"fallback_{task_name}_{mutation_id}",
            target_st_path=str(st_file),
            schema_path=str(schema_file),
            tester_type="fallback",
            total_cycles=5,
            sparse_timeline={"0": {}}
        )


def main():
    """Main entry point for RQ2 experiments."""
    import argparse

    parser = argparse.ArgumentParser(description="RQ2 Cross-engine Testing Experiments")
    parser.add_argument("--mode", default="random", choices=["random", "afl", "dse", "llm", "all"],
                        help="Testing method to run")
    parser.add_argument("--exp-type", default="mutation", choices=["coverage", "mutation"],
                        help="Experiment type: coverage or mutation")
    parser.add_argument("--tasks", nargs="+", default=None,
                        help="Specific tasks to run (default: all)")
    parser.add_argument("--fast", action="store_true",
                        help="Fast mode for testing")
    parser.add_argument("--max-mutations", type=int, default=None,
                        help="Maximum mutations per task")
    parser.add_argument("--clean", action="store_true",
                        help="Clean existing results")

    args = parser.parse_args()

    runner = RQ2Runner(mode=args.mode, experiment_type=args.exp_type, fast_mode=args.fast)
    runner.init_env(clean_existing=args.clean)

    tasks = runner.list_tasks(include=args.tasks)

    print(f"Running RQ2 experiments: type={args.exp_type}, mode={args.mode}, tasks={len(tasks)}, fast={args.fast}")

    for task in tasks:
        print(f"\nProcessing task: {task}")
        results = runner.run_task_batch(
            task,
            methods=None if args.mode == "all" else [args.mode],
            max_mutations=args.max_mutations
        )
        print(f"  Completed: {len(results)} results")

    print(f"\nResults saved to: {runner.results_file}")


if __name__ == "__main__":
    main()
