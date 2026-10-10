"""
PLCHaT ST Coverage Collector

Complete coverage collection system migrated from st_coverage.py.
Supports single/multiple/incremental coverage collection with LLVM instrumentation.

Key features:
- execute_with_coverage(): Single test case coverage collection
- execute_with_multiple_coverage(): Multiple test cases aggregation
- execute_with_incremental_coverage(): Incremental coverage merging
- Complete LLVM coverage instrumentation pipeline
- Intelligent coverage feedback extraction

Migrated from: FuzzGen/utils/st_compiler_matiec/st_coverage.py
"""

import os
import sys
import re
import subprocess
import shutil
import tempfile
import glob
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Any, Dict, Union, Tuple

# Add parent directory to path for imports
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from harness.compiler.utils import Logger, LEVEL
from harness.compiler.executor import STExecutor
from core.data_types.execution_coverage import (
    CoverageRunResult,
    CoverageReport,
    CoverageSummary,
    CoverageBreakdown,
    STExecutionResult,
    ExecutionStatus
)
from core.data_types import StoredTestCase, ExpUnifiedIR


class STCoverageCollector:
    """
    Complete coverage collection specialist using MatIEC compiler with LLVM coverage instrumentation.

    Orchestrates coverage builds, runs, and result extraction.
    Supports both StoredTestCase and ExpUnifiedIR input/output formats.

    Migrated from: FuzzGen/utils/st_compiler_matiec/st_coverage.py::STCoverageManager
    """

    def __init__(
        self,
        root_dir: Optional[str] = None,
        max_executions: int = 10,
        force_rebuild: bool = False,
        logger: Optional[Logger] = None,
        debug: bool = False,
        default_output_format: str = "StoredTestCase",
        llvm_version: int = 18,
        enable_line_by_line: bool = False
    ):
        """
        Initialize coverage collector.

        Args:
            root_dir: Project root directory
            max_executions: Maximum concurrent executions
            force_rebuild: Force rebuild regardless of cache
            logger: Logger instance
            debug: Enable debug logging
            default_output_format: Default output format ("StoredTestCase" or "ExpUnifiedIR")
            llvm_version: LLVM version for coverage tools
            enable_line_by_line: Enable line-by-line coverage output (default: False, set True for debugging)
        """
        self.root_dir = root_dir or PROJECT_ROOT
        self.execution_dir = os.path.join(self.root_dir, "execution")
        self.logger = logger or Logger("/tmp/plchat_coverage_logs", "st_coverage.log",
                                       level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug
        self.default_output_format = default_output_format
        self.force_rebuild = force_rebuild
        self.max_executions = max_executions
        self.llvm_version = llvm_version
        self.enable_line_by_line = enable_line_by_line

        # Initialize executor component
        self.executor = STExecutor(
            root_dir=self.root_dir,
            logger=self.logger,
            debug=self.debug,
            default_output_format=self.default_output_format
        )

    def execute_with_coverage(
        self,
        st_code_input: Any,
        harness_input: Optional[object] = None,
        input_data: Optional[object] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        initial_state: Optional[object] = None,
        output_format: str = "StoredTestCase"
    ) -> Dict[str, Any]:
        """
        Execute ST code with coverage analysis for a single test case.

        Args:
            st_code_input: ST code to execute
            harness_input: C harness code
            input_data: Test input data
            include_files: Included ST files
            benchmark_case: Benchmark case name
            temp_dir: Temporary directory for execution
            initial_state: Initial PLC state
            output_format: Output format ("StoredTestCase" or "ExpUnifiedIR")

        Returns:
            Coverage result with detailed coverage data in specified format
        """
        self.logger.info_print("Executing ST code with coverage analysis...")

        # Create temp directory if not provided
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="plchat_coverage_")
        else:
            os.makedirs(temp_dir, exist_ok=True)

        # Create necessary directories
        benchmark_dir = os.path.join(temp_dir, "benchmark_execution", benchmark_case or "fuzzing_target")
        plc_st_code_dir = os.path.join(benchmark_dir, "plc_st_code")
        plc_c_code_dir = os.path.join(benchmark_dir, "plc_c_code")
        includes_dir = os.path.join(benchmark_dir, "includes")
        input_dir = os.path.join(benchmark_dir, "input")
        state_dir = os.path.join(benchmark_dir, "initial_state")
        output_dir = os.path.join(benchmark_dir, "output")
        coverage_dir = os.path.join(benchmark_dir, "coverage")

        for d in [plc_st_code_dir, plc_c_code_dir, includes_dir, input_dir, state_dir, output_dir, coverage_dir]:
            os.makedirs(d, exist_ok=True)

        # Prepare inputs using input processor
        from harness.compiler.input_processor import STInputProcessor
        self.input_processor = STInputProcessor(
            logger=self.logger,
            debug=self.debug,
            default_output_format=self.default_output_format
        )

        self.input_processor.handle_st_code_input(st_code_input, plc_st_code_dir)
        self.input_processor.handle_harness_input(harness_input, plc_c_code_dir)
        self.input_processor.handle_input_data(input_data, input_dir, output_format)
        self.input_processor.handle_include_files(include_files, includes_dir)
        self.input_processor.handle_initial_state(initial_state, state_dir)

        # Find ST code path
        st_code_path = None
        for file in os.listdir(plc_st_code_dir):
            if file.endswith('.st'):
                st_code_path = os.path.join(plc_st_code_dir, file)
                break
        if not st_code_path:
            raise ValueError("No ST code file found in plc_st_code directory")

        # Find harness path
        harness_path = None
        for file in ['harness.c', 'harness_coverage.c']:
            path = os.path.join(plc_c_code_dir, file)
            if os.path.exists(path):
                harness_path = path
                break
        if not harness_path:
            raise ValueError("No harness file found in plc_c_code directory")

        # Find target function
        target_function = self._find_target_function(st_code_path)
        if not target_function:
            target_function = os.path.splitext(os.path.basename(st_code_path))[0] + "_body__"
        self.logger.info_print(f"Target function for coverage: {target_function}")

        # Compile ST to C with coverage instrumentation
        self.logger.info_print("Compiling ST code to C with coverage instrumentation...")
        if not self._compile_st_to_c_with_coverage(
            st_code_path=st_code_path,
            output_dir=output_dir,
            harness_path=harness_path,
            include_files=include_files,
            benchmark_case=benchmark_case
        ):
            return {
                "status": "compilation_failed",
                "return_code": 1,
                "stdout": "",
                "stderr": "ST to C compilation failed",
                "coverage_data": None,
                "incremental": False
            }

        # Find the compiled binary
        binary_path = os.path.join(output_dir, "plc_coverage_harness")
        if not os.path.exists(binary_path):
            raise FileNotFoundError(f"Coverage binary not found at {binary_path}")

        # Run the binary with coverage collection
        self.logger.info_print("Running binary with coverage collection...")
        coverage_result = self._run_coverage_collection(
            binary_path=binary_path,
            input_dir=input_dir,
            coverage_dir=coverage_dir,
            target_function=target_function,
            benchmark_case=benchmark_case
        )

        # Extract coverage results
        report = self._extract_coverage_results(
            case_name=benchmark_case or "fuzzing_target",
            coverage_dir=coverage_dir,
            target_function=target_function
        )

        # Generate execution result
        execution_result = None
        input_file = os.path.join(input_dir, "input.txt") if os.path.exists(os.path.join(input_dir, "input.txt")) else None
        if input_file:
            execution_result = self.executor.execute_binary(
                binary_path=binary_path,
                input_file=input_file,
                timeout=30,
                benchmark_case=benchmark_case,
                output_format=output_format
            )

        # Convert to appropriate format
        if output_format == "ExpUnifiedIR":
            return {
                "status": "success",
                "return_code": 0,
                "stdout": coverage_result.get("stdout", ""),
                "stderr": coverage_result.get("stderr", ""),
                "coverage_data": report,
                "incremental": False
            }
        else:
            return {
                "status": coverage_result.get("status", "success"),
                "return_code": coverage_result.get("return_code", 0),
                "stdout": coverage_result.get("stdout", ""),
                "stderr": coverage_result.get("stderr", ""),
                "coverage_data": report,
                "incremental": False,
                "execution_result": execution_result
            }

    def execute_with_multiple_coverage(
        self,
        st_code_input: Any,
        harness_input: Optional[object] = None,
        input_data_list: Optional[List[Any]] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        initial_states: Optional[List[Any]] = None,
        output_format: str = "StoredTestCase",
        eval_timeout_sec: Optional[float] = None,
        reuse_compilation: bool = True
    ) -> Dict[str, Any]:
        """
        Execute ST code with coverage analysis for multiple test cases.

        Args:
            st_code_input: ST code to execute
            harness_input: C harness code
            input_data_list: List of input data for each test case
            include_files: Included ST files
            benchmark_case: Benchmark case name
            temp_dir: Temporary directory for execution
            initial_states: List of initial states for each test case
            output_format: Output format ("StoredTestCase" or "ExpUnifiedIR")
            eval_timeout_sec: Global timeout for evaluation
            reuse_compilation: Enable compilation cache reuse (default: True)

        Returns:
            Combined coverage result for all test cases in specified format
        """
        self.logger.info_print(f"Executing ST code with coverage analysis for multiple test cases: {len(input_data_list) if input_data_list else 0}")
        # Default WHOLE-BATCH timeout (one execute_with_multiple_coverage call) — NOT per-case.
        # Caps wall-clock per batch so a few slow/looping cases can't blow up the budget.
        if eval_timeout_sec is None:
            eval_timeout_sec = float(os.environ.get("PLCHAT_BATCH_TIMEOUT", "30"))

        # Try compilation cache fast path
        if reuse_compilation:
            fast_path_result = self._try_compilation_cache(
                st_code_input=st_code_input,
                harness_input=harness_input,
                input_data_list=input_data_list,
                benchmark_case=benchmark_case,
                temp_dir=temp_dir,
                output_format=output_format,
                eval_timeout_sec=eval_timeout_sec
            )
            if fast_path_result is not None:
                self.logger.info_print("Using cached compilation (fast path)")
                return fast_path_result

        # Standard compilation path
        self.logger.info_print("Compilation cache miss, proceeding with full compilation")

        # Create temp directory if not provided
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="plchat_multi_coverage_")
        else:
            os.makedirs(temp_dir, exist_ok=True)

        # Create necessary directories
        benchmark_dir = os.path.join(temp_dir, "benchmark_execution", benchmark_case or "fuzzing_target")
        plc_st_code_dir = os.path.join(benchmark_dir, "plc_st_code")
        plc_c_code_dir = os.path.join(benchmark_dir, "plc_c_code")
        includes_dir = os.path.join(benchmark_dir, "includes")
        input_dir = os.path.join(benchmark_dir, "input")
        state_dir = os.path.join(benchmark_dir, "initial_state")
        output_dir = os.path.join(benchmark_dir, "output")
        coverage_dir = os.path.join(benchmark_dir, "coverage")

        for d in [plc_st_code_dir, plc_c_code_dir, includes_dir, input_dir, state_dir, output_dir, coverage_dir]:
            os.makedirs(d, exist_ok=True)

        # Initialize input processor
        from harness.compiler.input_processor import STInputProcessor
        if not hasattr(self, 'input_processor'):
            self.input_processor = STInputProcessor(
                logger=self.logger,
                debug=self.debug,
                default_output_format=self.default_output_format
            )

        # Prepare inputs
        self.input_processor.handle_st_code_input(st_code_input, plc_st_code_dir)
        self.input_processor.handle_harness_input(harness_input, plc_c_code_dir)
        self.input_processor.handle_include_files(include_files, includes_dir)

        # Handle multiple input data files
        if input_data_list:
            for idx, input_data in enumerate(input_data_list):
                input_subdir = os.path.join(input_dir, f"test_case_{idx}")
                os.makedirs(input_subdir, exist_ok=True)
                self.input_processor.handle_input_data(input_data, input_subdir, output_format)
                self.logger.debug_print(f"Prepared input for test case {idx}")
        else:
            # Create default input if none provided
            self.input_processor.handle_input_data(None, input_dir, output_format)

        # Handle multiple initial states
        if initial_states:
            for idx, state in enumerate(initial_states):
                state_subdir = os.path.join(state_dir, f"test_case_{idx}")
                os.makedirs(state_subdir, exist_ok=True)
                self.input_processor.handle_initial_state(state, state_subdir)
                self.logger.debug_print(f"Prepared state for test case {idx}")

        # Find ST code path
        st_code_path = None
        for file in os.listdir(plc_st_code_dir):
            if file.endswith('.st'):
                st_code_path = os.path.join(plc_st_code_dir, file)
                break
        if not st_code_path:
            raise ValueError("No ST code file found in plc_st_code directory")

        # Find harness path
        harness_path = None
        for file in ['harness.c', 'harness_coverage.c']:
            path = os.path.join(plc_c_code_dir, file)
            if os.path.exists(path):
                harness_path = path
                break
        if not harness_path:
            raise ValueError("No harness file found in plc_c_code directory")

        # Find target function
        target_function = self._find_target_function(st_code_path)
        if not target_function:
            target_function = os.path.splitext(os.path.basename(st_code_path))[0] + "_body__"
        self.logger.info_print(f"Target function for coverage: {target_function}")

        # Compile ST to C with coverage instrumentation
        self.logger.info_print("Compiling ST code to C with coverage instrumentation...")
        if not self._compile_st_to_c_with_coverage(
            st_code_path=st_code_path,
            output_dir=output_dir,
            harness_path=harness_path,
            include_files=include_files,
            benchmark_case=benchmark_case
        ):
            return {
                "status": "compilation_failed",
                "return_code": 1,
                "stdout": "",
                "stderr": "ST to C compilation failed",
                "coverage_data": None,
                "incremental": False
            }

        # Find the compiled binary
        binary_path = os.path.join(output_dir, "plc_coverage_harness")
        if not os.path.exists(binary_path):
            raise FileNotFoundError(f"Coverage binary not found at {binary_path}")

        # Save to compilation cache for future reuse
        if reuse_compilation:
            try:
                st_content = self._extract_content(st_code_input, ".st")
                harness_content = self._extract_content(harness_input, ".c")
                if st_content and harness_content:
                    self._save_compilation_cache(
                        binary_path=binary_path,
                        st_content=st_content,
                        harness_content=harness_content,
                        metadata={"benchmark_case": benchmark_case}
                    )
            except Exception as e:
                self.logger.warning_print(f"Failed to save compilation cache: {e}")

        # Run the binary with coverage collection for multiple test cases
        self.logger.info_print("Running binary with coverage collection for multiple test cases...")
        coverage_result = self._run_multiple_coverage_collection(
            binary_path=binary_path,
            input_dir=input_dir,
            coverage_dir=coverage_dir,
            target_function=target_function,
            benchmark_case=benchmark_case,
            test_case_count=len(input_data_list) if input_data_list else 1,
            eval_timeout_sec=eval_timeout_sec
        )

        # Extract coverage results
        report = self._extract_coverage_results(
            case_name=f"{benchmark_case}_multi" if benchmark_case else "fuzzing_target_multi",
            coverage_dir=coverage_dir,
            target_function=target_function
        )

        # Generate combined execution result
        execution_result = None
        if input_data_list and len(input_data_list) > 0:
            # Execute with first input as representative
            first_input_dir = os.path.join(input_dir, "test_case_0")
            input_file = os.path.join(first_input_dir, "input.txt") if os.path.exists(os.path.join(first_input_dir, "input.txt")) else None
            if input_file:
                execution_result = self.executor.execute_binary(
                    binary_path=binary_path,
                    input_file=input_file,
                    timeout=30,
                    benchmark_case=benchmark_case,
                    output_format=output_format
                )

        # Return result in appropriate format
        if output_format == "ExpUnifiedIR":
            return {
                "status": "success",
                "return_code": 0,
                "stdout": coverage_result.get("stdout", ""),
                "stderr": coverage_result.get("stderr", ""),
                "coverage_data": report,
                "incremental": False
            }
        else:
            return {
                "status": coverage_result.get("status", "success"),
                "return_code": coverage_result.get("return_code", 0),
                "stdout": coverage_result.get("stdout", ""),
                "stderr": coverage_result.get("stderr", ""),
                "coverage_data": report,
                "incremental": False,
                "execution_result": execution_result
            }

    def execute_with_incremental_coverage(
        self,
        st_code_input: Any,
        harness_input: Optional[object] = None,
        input_data: Optional[object] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        base_coverage_dir: Optional[str] = None,
        incremental_mode: bool = True,
        initial_state: Optional[object] = None,
        output_format: str = "StoredTestCase"
    ) -> Dict[str, Any]:
        """
        Execute ST code with incremental coverage analysis.

        Args:
            st_code_input: ST code to execute
            harness_input: C harness code
            input_data: Test input data
            include_files: Included ST files
            benchmark_case: Benchmark case name
            temp_dir: Temporary directory for execution
            base_coverage_dir: Base coverage directory for incremental mode
            incremental_mode: Enable incremental coverage mode
            initial_state: Initial PLC state
            output_format: Output format ("StoredTestCase" or "ExpUnifiedIR")

        Returns:
            Coverage result with incremental coverage data in specified format
        """
        self.logger.info_print("Executing ST code with incremental coverage analysis...")

        # Check if we can actually do incremental coverage
        if not (incremental_mode and base_coverage_dir and os.path.isdir(base_coverage_dir)):
            self.logger.warning_print("Incremental mode disabled or base_coverage_dir missing; falling back to standard coverage run")
            return self.execute_with_coverage(
                st_code_input=st_code_input,
                harness_input=harness_input,
                input_data=input_data,
                include_files=include_files,
                benchmark_case=benchmark_case,
                temp_dir=temp_dir,
                initial_state=initial_state,
                output_format=output_format
            )

        # Create temp directory if not provided
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="plchat_incremental_cov_")
        else:
            os.makedirs(temp_dir, exist_ok=True)

        # Create necessary directories
        benchmark_dir = os.path.join(temp_dir, "benchmark_execution", benchmark_case or "fuzzing_target")
        plc_st_code_dir = os.path.join(benchmark_dir, "plc_st_code")
        plc_c_code_dir = os.path.join(benchmark_dir, "plc_c_code")
        includes_dir = os.path.join(benchmark_dir, "includes")
        input_dir = os.path.join(benchmark_dir, "input")
        state_dir = os.path.join(benchmark_dir, "initial_state")
        output_dir = os.path.join(benchmark_dir, "output")
        coverage_dir = os.path.join(benchmark_dir, "coverage")
        merged_coverage_dir = os.path.join(benchmark_dir, "merged_coverage")

        for d in [plc_st_code_dir, plc_c_code_dir, includes_dir, input_dir, state_dir, output_dir, coverage_dir, merged_coverage_dir]:
            os.makedirs(d, exist_ok=True)

        # Initialize input processor
        from harness.compiler.input_processor import STInputProcessor
        if not hasattr(self, 'input_processor'):
            self.input_processor = STInputProcessor(
                logger=self.logger,
                debug=self.debug,
                default_output_format=self.default_output_format
            )

        # Prepare inputs
        self.input_processor.handle_st_code_input(st_code_input, plc_st_code_dir)
        self.input_processor.handle_harness_input(harness_input, plc_c_code_dir)
        self.input_processor.handle_input_data(input_data, input_dir, output_format)
        self.input_processor.handle_include_files(include_files, includes_dir)
        self.input_processor.handle_initial_state(initial_state, state_dir)

        # Find ST code path
        st_code_path = None
        for file in os.listdir(plc_st_code_dir):
            if file.endswith('.st'):
                st_code_path = os.path.join(plc_st_code_dir, file)
                break
        if not st_code_path:
            raise ValueError("No ST code file found in plc_st_code directory")

        # Find harness path
        harness_path = None
        for file in ['harness.c', 'harness_coverage.c']:
            path = os.path.join(plc_c_code_dir, file)
            if os.path.exists(path):
                harness_path = path
                break
        if not harness_path:
            raise ValueError("No harness file found in plc_c_code directory")

        # Find target function
        target_function = self._find_target_function(st_code_path)
        if not target_function:
            target_function = os.path.splitext(os.path.basename(st_code_path))[0] + "_body__"
        self.logger.info_print(f"Target function for coverage: {target_function}")

        # Compile ST to C with coverage instrumentation
        self.logger.info_print("Compiling ST code to C with coverage instrumentation...")
        if not self._compile_st_to_c_with_coverage(
            st_code_path=st_code_path,
            output_dir=output_dir,
            harness_path=harness_path,
            include_files=include_files,
            benchmark_case=benchmark_case
        ):
            return {
                "status": "compilation_failed",
                "return_code": 1,
                "stdout": "",
                "stderr": "ST to C compilation failed",
                "coverage_data": None,
                "incremental": True
            }

        # Find the compiled binary
        binary_path = os.path.join(output_dir, "plc_coverage_harness")
        if not os.path.exists(binary_path):
            raise FileNotFoundError(f"Coverage binary not found at {binary_path}")

        # Run the binary with coverage collection
        self.logger.info_print("Running binary with coverage collection for incremental analysis...")
        coverage_result = self._run_coverage_collection(
            binary_path=binary_path,
            input_dir=input_dir,
            coverage_dir=coverage_dir,
            target_function=target_function,
            benchmark_case=benchmark_case
        )

        # Merge with base coverage
        self.logger.info_print("Merging coverage with base coverage...")
        merged_coverage = self._merge_coverage_results(
            base_coverage_dir=base_coverage_dir,
            new_coverage_dir=coverage_dir,
            merged_coverage_dir=merged_coverage_dir,
            target_function=target_function,
            binary_path=binary_path
        )

        # Extract merged coverage results
        report = self._extract_coverage_results(
            case_name=f"{benchmark_case}_merged" if benchmark_case else "fuzzing_target_merged",
            coverage_dir=merged_coverage_dir,
            target_function=target_function
        )

        # Generate execution result
        execution_result = None
        input_file = os.path.join(input_dir, "input.txt") if os.path.exists(os.path.join(input_dir, "input.txt")) else None
        if input_file:
            execution_result = self.executor.execute_binary(
                binary_path=binary_path,
                input_file=input_file,
                timeout=30,
                benchmark_case=benchmark_case,
                output_format=output_format
            )

        # Return result in appropriate format
        if output_format == "ExpUnifiedIR":
            return {
                "status": "success",
                "return_code": 0,
                "stdout": coverage_result.get("stdout", ""),
                "stderr": coverage_result.get("stderr", ""),
                "coverage_data": report,
                "incremental": True
            }
        else:
            return {
                "status": coverage_result.get("status", "success"),
                "return_code": coverage_result.get("return_code", 0),
                "stdout": coverage_result.get("stdout", ""),
                "stderr": coverage_result.get("stderr", ""),
                "coverage_data": report,
                "incremental": True,
                "execution_result": execution_result
            }

    def _compile_st_to_c_with_coverage(
        self,
        st_code_path: str,
        output_dir: str,
        harness_path: str,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None
    ) -> bool:
        """
        Compile ST code to C with coverage instrumentation using MatIEC compiler.

        Args:
            st_code_path: Path to ST source file
            output_dir: Output directory for generated C files
            harness_path: Path to C harness file
            include_files: List of included ST files
            benchmark_case: Benchmark case name

        Returns:
            True if compilation succeeded, False otherwise
        """
        self.logger.info_print(f"Compiling ST code to C with coverage: {st_code_path}")

        # Check MatIEC installation
        ok, msg = self.executor.check_matiec_installation()
        if not ok:
            self.logger.error_print(f"MatIEC compiler not available: {msg}")
            return False

        # Find MatIEC path
        iec2c_bin = shutil.which("iec2c")
        if not iec2c_bin:
            self.logger.error_print("iec2c not found in PATH")
            return False

        matiec_path = str(Path(iec2c_bin).parent)
        self.logger.debug_print(f"MatIEC path: {matiec_path}")

        try:
            # Preprocess ST (Remove comments)
            clean_st_path = os.path.join(output_dir, os.path.basename(st_code_path) + ".clean.st")

            # Use perl/sed pipeline equivalent to bash script
            # perl -0777 -pe 's/\(\*.*?\*\)//gs' input | sed 's/\/\/.*//g' > output
            with open(st_code_path, 'r') as f:
                content = f.read()

            # Remove (* ... *) comments (including multi-line)
            content = re.sub(r'\(\*.*?\*\)', '', content, flags=re.DOTALL)
            # Remove // ... comments
            content = re.sub(r'//.*', '', content)

            with open(clean_st_path, 'w') as f:
                f.write(content)

            self.logger.debug_print(f"Preprocessed ST file saved to: {clean_st_path}")

            # Run iec2c
            original_pwd = os.getcwd()
            os.chdir(matiec_path)

            # Create output directory
            os.makedirs(output_dir, exist_ok=True)

            # Run compilation command on CLEANED ST file
            cmd = [
                "./iec2c",
                "-p",  # Added -p flag to match bash script
                "-T", output_dir,
                clean_st_path
            ]
            self.logger.info_print(f"Running ST compilation: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                self.logger.error_print(f"ST compilation failed with return code {result.returncode}")
                self.logger.error_print(f"STDOUT: {result.stdout}")
                self.logger.error_print(f"STDERR: {result.stderr}")
                return False

            os.chdir(original_pwd)

            # Apply header patches to generated C files
            self._apply_header_patches(output_dir)
            from harness.compiler.utils import patch_pous_setvar_time_to_dint
            patch_pous_setvar_time_to_dint(output_dir)

            # Copy harness file
            harness_dest = os.path.join(output_dir, "harness_coverage.c")
            try:
                shutil.copy2(harness_path, harness_dest)
                self.logger.info_print(f"Copied harness file to: {harness_dest}")
            except Exception as e:
                self.logger.error_print(f"Failed to copy harness file: {e}")
                return False

            # Find MatIEC C library directory
            matiec_c_lib_dir = os.environ.get("MATIEC_C_LIB_DIR", os.path.join(matiec_path, "lib", "C"))

            # Collect generated C files
            generated_c_files = []
            for file in os.listdir(output_dir):
                if file.endswith(".c") and file != "harness_coverage.c":
                    generated_c_files.append(os.path.join(output_dir, file))

            # Collect MatIEC library C files
            lib_c_files = []
            if os.path.exists(matiec_c_lib_dir):
                for file in os.listdir(matiec_c_lib_dir):
                    if file.endswith(".c") and ("iec_std_lib" in file or "accessor" in file):
                        lib_c_files.append(os.path.join(matiec_c_lib_dir, file))

            # Compile C files to binary with coverage instrumentation
            return self._compile_c_to_binary_with_coverage(
                source_files=generated_c_files + lib_c_files + [harness_dest],
                output_binary=os.path.join(output_dir, "plc_coverage_harness"),
                include_dirs=[matiec_c_lib_dir, output_dir],
                benchmark_case=benchmark_case
            )

        except Exception as e:
            self.logger.error_print(f"Error during ST compilation: {e}")
            return False

    def _compile_c_to_binary_with_coverage(
        self,
        source_files: List[str],
        output_binary: str,
        include_dirs: List[str],
        benchmark_case: Optional[str] = None
    ) -> bool:
        """
        Compile C files to executable binary with coverage instrumentation.

        Args:
            source_files: List of C source files to compile
            output_binary: Path for output binary
            include_dirs: Include directories for compilation
            benchmark_case: Benchmark case name

        Returns:
            True if compilation succeeded, False otherwise
        """
        self.logger.info_print(f"Compiling C files to binary with coverage: {output_binary}")

        # Build compilation command
        clang_bin = f"clang-{self.llvm_version}"
        cmd = [clang_bin, "-g", "-fprofile-instr-generate", "-fcoverage-mapping"]

        # Add include directories
        for include_dir in include_dirs:
            cmd.extend(["-I", include_dir])

        # Add source files
        cmd.extend(source_files)

        # Add libraries
        cmd.extend(["-lm", "-lz", "-lrt", "-lpthread", "-w"])

        # Add output
        cmd.extend(["-o", output_binary])

        self.logger.info_print(f"Compiling C code: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                self.logger.error_print(f"C compilation failed with return code {result.returncode}")
                self.logger.error_print(f"STDOUT: {result.stdout}")
                self.logger.error_print(f"STDERR: {result.stderr}")
                return False

            self.logger.info_print(f"Successfully created coverage executable: {output_binary}")
            return True
        except Exception as e:
            self.logger.error_print(f"Error during C compilation: {e}")
            return False

    def _run_coverage_collection(
        self,
        binary_path: str,
        input_dir: str,
        coverage_dir: str,
        target_function: str,
        benchmark_case: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Run binary with coverage collection.

        Args:
            binary_path: Path to executable binary
            input_dir: Directory containing input files
            coverage_dir: Directory for coverage output
            target_function: Target function for coverage analysis
            benchmark_case: Benchmark case name

        Returns:
            Dictionary containing coverage execution results
        """
        self.logger.info_print(f"Running coverage collection for target function: {target_function}")
        os.makedirs(coverage_dir, exist_ok=True)

        # Set up environment variables for coverage
        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = os.path.join(coverage_dir, "default-%p.profraw")

        # Find input file
        input_file = None
        for file in ["input.txt", "input_000.txt"]:
            path = os.path.join(input_dir, file)
            if os.path.exists(path):
                input_file = path
                break

        if not input_file:
            # Create default input file
            input_file = os.path.join(input_dir, "input.txt")
            with open(input_file, "w") as f:
                f.write("1 2 3 4 5 6 7 8 9 10")
            self.logger.warning_print(f"No input file found, created default: {input_file}")

        # Run the binary (resource-guarded: PR_SET_PDEATHSIG + group-kill on timeout
        # + reap by binary path, so infinite-loop harnesses never orphan at ~100% CPU)
        cmd = [binary_path]
        try:
            from harness.compiler.proc_guard import run_target_binary
            res = run_target_binary(
                cmd, timeout=30, stdin_path=input_file, env=env, binary_path=binary_path
            )

            if res["returncode"] != 0:
                self.logger.warning_print(f"Binary execution returned non-zero exit code: {res['returncode']}")

            # Merge raw coverage data
            self._merge_coverage_data(coverage_dir)

            # Generate coverage report
            report = self._generate_coverage_report(
                binary_path=binary_path,
                coverage_dir=coverage_dir,
                target_function=target_function
            )

            return {
                "status": "success" if res["returncode"] == 0 else "execution_failed",
                "return_code": res["returncode"],
                "stdout": res["stdout"],
                "stderr": res["stderr"],
                "coverage_report": report
            }

        except Exception as e:
            self.logger.error_print(f"Error during coverage collection: {e}")
            return {
                "status": "error",
                "return_code": -1,
                "stdout": "",
                "stderr": str(e),
                "coverage_report": None
            }

    def _run_multiple_coverage_collection(
        self,
        binary_path: str,
        input_dir: str,
        coverage_dir: str,
        target_function: str,
        benchmark_case: Optional[str] = None,
        test_case_count: int = 1,
        eval_timeout_sec: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Run binary with coverage collection for multiple test cases.

        Args:
            binary_path: Path to executable binary
            input_dir: Directory containing input files for multiple test cases
            coverage_dir: Directory for coverage output
            target_function: Target function for coverage analysis
            benchmark_case: Benchmark case name
            test_case_count: Number of test cases to execute
            eval_timeout_sec: Global timeout for evaluation

        Returns:
            Dictionary containing coverage execution results
        """
        self.logger.info_print(f"Running coverage collection for multiple test cases: {test_case_count}")
        os.makedirs(coverage_dir, exist_ok=True)

        # Set up environment variables for coverage
        env = os.environ.copy()
        env["LLVM_PROFILE_FILE"] = os.path.join(coverage_dir, "default-%p.profraw")

        all_stdout = []
        all_stderr = []
        return_code = 0
        start_time = time.time()

        for i in range(test_case_count):
            # If max evaluation time is configured and timeout reached, truncate
            if eval_timeout_sec and (time.time() - start_time) > eval_timeout_sec:
                self.logger.warning_print(f"Evaluation global timeout ({eval_timeout_sec}s) reached! Truncated at case {i}/{test_case_count}.")
                break

            test_case_dir = os.path.join(input_dir, f"test_case_{i}")
            if not os.path.exists(test_case_dir):
                test_case_dir = input_dir

            # Find input file in test case directory
            input_file = None
            for file in ["input.txt", "input_000.txt"]:
                path = os.path.join(test_case_dir, file)
                if os.path.exists(path):
                    input_file = path
                    break

            if not input_file:
                # Create default input file
                input_file = os.path.join(test_case_dir, "input.txt")
                os.makedirs(test_case_dir, exist_ok=True)
                with open(input_file, "w") as f:
                    f.write("1 2 3 4 5 6 7 8 9 10")
                self.logger.warning_print(f"No input file found for test case {i}, created default: {input_file}")

            # Run the binary (resource-guarded; see proc_guard rationale)
            cmd = [binary_path]
            try:
                from harness.compiler.proc_guard import run_target_binary
                res = run_target_binary(
                    cmd,
                    timeout=int(os.environ.get("PLCHAT_EXEC_TIMEOUT", "2")),
                    stdin_path=input_file,
                    env=env,
                    binary_path=binary_path,
                )

                if res["returncode"] != 0:
                    self.logger.warning_print(f"Binary execution for test case {i} returned non-zero exit code: {res['returncode']}")
                    return_code = res["returncode"]

                all_stdout.append(f"Test case {i} output:\n{res['stdout']}")
                all_stderr.append(f"Test case {i} errors:\n{res['stderr']}")

            except Exception as e:
                self.logger.error_print(f"Error during coverage collection for test case {i}: {e}")
                all_stderr.append(f"Test case {i} error: {e}")
                return_code = -1

        # Merge raw coverage data
        self._merge_coverage_data(coverage_dir)

        # Generate coverage report
        report = self._generate_coverage_report(
            binary_path=binary_path,
            coverage_dir=coverage_dir,
            target_function=target_function
        )

        return {
            "status": "success" if return_code == 0 else "execution_failed",
            "return_code": return_code,
            "stdout": "\n".join(all_stdout),
            "stderr": "\n".join(all_stderr),
            "coverage_report": report
        }

    def _merge_coverage_data(self, coverage_dir: str) -> bool:
        """
        Merge raw coverage data files into a single profdata file.

        Args:
            coverage_dir: Directory containing coverage data files

        Returns:
            True if merge succeeded, False otherwise
        """
        self.logger.info_print("Merging coverage data files...")

        # Find all profraw files
        profraw_pattern = os.path.join(coverage_dir, "default-*.profraw")
        profdata_file = os.path.join(coverage_dir, "coverage.profdata")
        profdata_bin = f"llvm-profdata-{self.llvm_version}"

        # Expand profraw files using glob
        profraw_files = glob.glob(profraw_pattern)
        if not profraw_files:
            self.logger.error_print(f"No .profraw files found in {coverage_dir}")
            return False

        try:
            cmd = [profdata_bin, "merge", "-o", profdata_file] + profraw_files
            self.logger.debug_print(f"Running coverage merge: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                self.logger.error_print(f"Coverage data merge failed with return code {result.returncode}")
                self.logger.error_print(f"STDOUT: {result.stdout}")
                self.logger.error_print(f"STDERR: {result.stderr}")
                return False

            self.logger.info_print(f"Coverage data merged successfully: {profdata_file}")
            return True

        except Exception as e:
            self.logger.error_print(f"Error during coverage data merge: {e}")
            return False

    def _generate_coverage_report(
        self,
        binary_path: str,
        coverage_dir: str,
        target_function: str
    ) -> Dict[str, Any]:
        """
        Generate coverage report for target function.

        Args:
            binary_path: Path to executable binary
            coverage_dir: Directory containing coverage data
            target_function: Target function for coverage analysis

        Returns:
            Dictionary containing coverage report data
        """
        self.logger.info_print(f"Generating coverage report for function: {target_function}")
        profdata_file = os.path.join(coverage_dir, "coverage.profdata")
        if not os.path.exists(profdata_file):
            self.logger.error_print(f"Coverage data file not found: {profdata_file}")
            return {}

        reports_dir = os.path.join(coverage_dir, "reports")
        os.makedirs(reports_dir, exist_ok=True)
        summary_file = os.path.join(reports_dir, "coverage_summary.txt")
        cov_bin = f"llvm-cov-{self.llvm_version}"

        try:
            cmd = [
                cov_bin, "report",
                binary_path,
                "-instr-profile", profdata_file,
                "-name", target_function
            ]
            self.logger.debug_print(f"Running coverage report: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                self.logger.error_print(f"Coverage report generation failed with return code {result.returncode}")
                self.logger.error_print(f"STDOUT: {result.stdout}")
                self.logger.error_print(f"STDERR: {result.stderr}")
                return {}

            # Save summary report
            with open(summary_file, "w") as f:
                f.write(result.stdout)

            self.logger.info_print(f"Coverage summary saved to: {summary_file}")

        except Exception as e:
            self.logger.error_print(f"Error generating coverage summary: {e}")
            return {}

        detailed_file = os.path.join(reports_dir, "target_function_coverage.txt")
        try:
            cmd = [
                cov_bin, "show",
                binary_path,
                "-instr-profile", profdata_file,
                "-name", target_function,
                "-format=text"
            ]
            self.logger.debug_print(f"Running detailed coverage report: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                self.logger.error_print(f"Detailed coverage report generation failed with return code {result.returncode}")
                self.logger.error_print(f"STDOUT: {result.stdout}")
                self.logger.error_print(f"STDERR: {result.stderr}")
                return {}

            # Save detailed report
            with open(detailed_file, "w") as f:
                f.write(result.stdout)

            self.logger.info_print(f"Detailed coverage report saved to: {detailed_file}")

        except Exception as e:
            self.logger.error_print(f"Error generating detailed coverage report: {e}")
            # Don't return {} - we already have summary report

        # Line-by-line coverage output (only if enabled)
        if self.enable_line_by_line:
            line_by_line_file = os.path.join(reports_dir, "line_by_line_coverage.txt")
            try:
                # Try with function-specific first
                cmd = [
                    cov_bin, "show",
                    binary_path,
                    "-instr-profile", profdata_file,
                    "-name", target_function,
                    "-format=text"
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                # If function-specific fails or is empty, try POUS.c
                if result.returncode != 0 or not result.stdout.strip():
                    cmd_pous = [
                        cov_bin, "show",
                        binary_path,
                        "-instr-profile", profdata_file,
                        "-name=POUS.c",
                        "-format=text"
                    ]
                    result = subprocess.run(cmd_pous, capture_output=True, text=True, timeout=30)

                # Save line-by-line coverage
                with open(line_by_line_file, "w") as f:
                    f.write(result.stdout)

                self.logger.info_print(f"Line-by-line coverage saved to: {line_by_line_file}")

            except Exception as e:
                self.logger.error_print(f"Error generating line-by-line coverage: {e}")

        # Parse summary report for structured data
        summary_data = self._parse_coverage_summary(summary_file)

        result_dict = {
            "target_function": target_function,
            "summary_file": summary_file,
            "detailed_file": detailed_file,
            "summary_data": summary_data,
            "timestamp": datetime.now().isoformat()
        }

        # Add line-by-line file path if generated
        if self.enable_line_by_line:
            line_by_line_file = os.path.join(reports_dir, "line_by_line_coverage.txt")
            if os.path.exists(line_by_line_file):
                result_dict["line_by_line_file"] = line_by_line_file

        return result_dict

    def _parse_coverage_summary(self, summary_file: str) -> CoverageSummary:
        """
        Parse coverage summary text file into structured data.
        Fixed to correctly filter files and handle column deduplication.
        """
        self.logger.debug_print(f"Parsing coverage summary from: {summary_file}")

        if not os.path.exists(summary_file):
            return CoverageSummary(error=f"File not found: {summary_file}")

        try:
            with open(summary_file, "r") as f:
                lines = f.readlines()

            # 1. Parse Header to determine column order
            header_line = None
            for line in lines:
                if "Filename" in line:
                    header_line = line.strip()
                    break

            if not header_line:
                raise ValueError("Header line not found")

            # Use a set to prevent duplicate column types
            header_parts = header_line.split()
            coverage_types = []
            seen_types = set()

            for part in header_parts:
                if part in ["Regions", "Functions", "Lines", "Branches"]:
                    if part not in seen_types:
                        coverage_types.append(part)
                        seen_types.add(part)

            # 2. Extract stats for valid PLC files (POUS.c)
            target_files_stats = []
            for line in lines:
                parts = line.split()
                if not parts or len(parts) < 3:
                    continue
                filename = parts[0]

                # Logic: Keep only .c files that are NOT the harness
                if filename.endswith(".c") and "harness" not in filename:
                    target_files_stats.append(parts)

            # 3. Aggregate statistics
            summary = CoverageSummary()

            def aggregate_stats(stats_list, type_idx):
                agg_total = 0
                agg_missed = 0
                valid_rows = 0

                for parts in stats_list:
                    try:
                        # Each metric block is 3 columns: Total, Missed, Cover%
                        if type_idx + 1 < len(parts):
                            t_str = parts[type_idx].replace(',', '')
                            m_str = parts[type_idx + 1].replace(',', '')

                            if t_str.isdigit() and m_str.isdigit():
                                agg_total += int(t_str)
                                agg_missed += int(m_str)
                                valid_rows += 1
                    except (ValueError, IndexError):
                        continue

                if agg_total == 0:
                    return CoverageBreakdown(percentage="0.00%", total=0, missed=0, covered=0)

                agg_covered = agg_total - agg_missed
                perc = (agg_covered / agg_total) * 100.0
                return CoverageBreakdown(
                    percentage=f"{perc:.2f}%",
                    total=agg_total,
                    missed=agg_missed,
                    covered=agg_covered
                )

            # 4. Map columns to summary fields
            current_col_idx = 1

            for cov_type in coverage_types:
                coverage_data = aggregate_stats(target_files_stats, current_col_idx)

                if cov_type == "Regions":
                    summary.region_coverage = coverage_data
                elif cov_type == "Functions":
                    summary.function_coverage = coverage_data
                elif cov_type == "Lines":
                    summary.line_coverage = coverage_data
                elif cov_type == "Branches":
                    summary.branch_coverage = coverage_data

                current_col_idx += 3

            return summary

        except Exception as e:
            self.logger.error_print(f"Error parsing coverage summary: {e}")
            return CoverageSummary(error=str(e))

    def _extract_coverage_results(
        self,
        case_name: str,
        coverage_dir: str,
        target_function: str
    ) -> CoverageReport:
        """
        Extract and parse coverage results from coverage files.

        Args:
            case_name: Name of the test case
            coverage_dir: Directory containing coverage files
            target_function: Target function for coverage analysis

        Returns:
            CoverageReport object with parsed coverage data
        """
        self.logger.info_print(f"Extracting coverage results for case: {case_name}")

        # Parse coverage summary
        summary_file = os.path.join(coverage_dir, "reports", "coverage_summary.txt")
        summary = None
        if os.path.exists(summary_file):
            summary = self._parse_coverage_summary(summary_file)

        # List coverage files
        coverage_files = []
        coverage_path = os.path.join(coverage_dir, "coverage")
        if os.path.exists(coverage_path):
            for root, _, files in os.walk(coverage_path):
                for file in files:
                    coverage_files.append(os.path.relpath(os.path.join(root, file), coverage_path))

        # Generate covered IDs
        covered_ids = self._generate_covered_ids(coverage_dir, summary)

        return CoverageReport(
            case_name=case_name,
            coverage_available=True,
            coverage_summary=summary,
            coverage_files=coverage_files,
            merge_info={
                "covered_ids": covered_ids.get("covered_ids", []),
                "missed_lines": covered_ids.get("missed_lines", []),
                "extraction_timestamp": datetime.now().isoformat(),
                "case_name": case_name,
                "coverage_files_count": len(coverage_files),
                "target_function": target_function
            }
        )

    def _generate_covered_ids(
        self,
        coverage_dir: str,
        summary: Optional[CoverageSummary]
    ) -> Dict[str, List[str]]:
        """
        Extract intelligent coverage feedback, discarding useless synthetic IDs.
        Returns a dict with 'covered' IDs (minimal) and actual 'missed' code lines.
        """
        self.logger.debug_print("Extracting intelligent coverage data from reports")
        intelligence = {"covered_ids": [], "missed_lines": []}

        try:
            detailed_file = os.path.join(coverage_dir, "reports", "target_function_coverage.txt")
            if os.path.exists(detailed_file):
                extracted = self._extract_ids_from_coverage_report(detailed_file)

                # Limit to prevent overflow
                intelligence["missed_lines"] = extracted.get("missed", [])[:10]
                # Keep minimal for compatibility
                intelligence["covered_ids"] = extracted.get("covered", [])[:5]

        except Exception as e:
            self.logger.warning_print(f"Error extracting coverage intelligence: {e}")

        return intelligence

    def _extract_ids_from_coverage_report(self, report_file: str) -> Dict[str, List[str]]:
        """
        Extract specific line IDs from detailed coverage report.
        Groups contiguous missed lines into contextual blocks for Agent analysis.
        """
        result = {"covered": [], "missed": []}
        try:
            with open(report_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            current_file = None
            file_lines = []

            # Step 1: Extract all valid lines
            for raw_line in lines:
                line_clean = raw_line.strip()

                # Detect file headers
                if line_clean.endswith(':') and not line_clean.startswith('|'):
                    file_path = line_clean.rstrip(':')
                    if file_path.endswith('.c') or file_path.endswith('.st'):
                        filename = file_path.split('/')[-1]
                        # Skip library files
                        if "iec_" in filename or "accessor" in filename or "harness" in filename:
                            current_file = None
                        else:
                            current_file = filename
                    continue

                # Parse coverage lines
                if current_file and '|' in line_clean and not line_clean.startswith('-'):
                    if line_clean.startswith('|'):
                        continue

                    parts = line_clean.split('|', 2)
                    if len(parts) >= 3:
                        line_num = parts[0].strip()
                        count = parts[1].strip()
                        code = parts[2].strip()

                        if line_num.isdigit():
                            file_lines.append((current_file, int(line_num), count, code))

            # Step 2: Build contiguous missed code blocks with context
            missed_blocks = []
            current_block = None

            for i, (fname, lnum, count, code) in enumerate(file_lines):
                is_meaningful = (
                    len(code) > 2 and
                    not code.startswith('//') and
                    code not in ["{", "}", "};"]
                )

                if not is_meaningful:
                    continue

                if count == '0':
                    # Start or continue a missed block
                    if current_block is None or current_block["file"] != fname:
                        # Finalize previous block
                        if current_block is not None:
                            missed_blocks.append(current_block)

                        # Start new block with context
                        current_block = {
                            "file": fname,
                            "start_line": lnum,
                            "end_line": lnum,
                            "missed_lines": [lnum],
                            "context_before": [],
                            "code_snippets": [code]
                        }

                        # Look back for covered context (max 2 lines)
                        context = []
                        back_idx = i - 1
                        while back_idx >= 0 and len(context) < 2:
                            b_fname, b_lnum, b_count, b_code = file_lines[back_idx]
                            if b_fname != fname:
                                break
                            b_meaningful = (
                                len(b_code) > 2 and
                                not b_code.startswith('//') and
                                b_code not in ["{", "}", "};"]
                            )
                            if b_meaningful and b_count != '0':
                                context.append(f"  {b_lnum}| {b_code}")
                            back_idx -= 1

                        current_block["context_before"] = list(reversed(context))

                    else:
                        # Continue current block
                        current_block["end_line"] = lnum
                        current_block["missed_lines"].append(lnum)
                        current_block["code_snippets"].append(code)
                else:
                    # Finalize block if we hit covered code
                    if current_block is not None:
                        missed_blocks.append(current_block)
                        current_block = None

            # Don't forget the last block
            if current_block is not None:
                missed_blocks.append(current_block)

            # Convert blocks to missed lines format
            for b in missed_blocks:
                lines_str = []
                for ctx in b.get("context_before", []):
                    lines_str.append(ctx)
                for snippet in b.get("code_snippets", []):
                    lines_str.append(f"  X | {snippet}")
                result["missed"].append("\n".join(lines_str))

            # Extract covered IDs
            for fname, lnum, count, code in file_lines:
                is_meaningful = (
                    len(code) > 2 and
                    not code.startswith('//') and
                    code not in ["{", "}", "};"]
                )

                if not is_meaningful:
                    continue

                if count != '0' and any(c.isdigit() for c in count):
                    result["covered"].append(f"line:{fname}:{lnum}")

        except Exception as e:
            self.logger.debug_print(f"Error parsing coverage report: {e}")

        return result

    def _merge_coverage_results(
        self,
        base_coverage_dir: str,
        new_coverage_dir: str,
        merged_coverage_dir: str,
        target_function: str,
        binary_path: str
    ) -> bool:
        """
        Merge base coverage with new coverage results.

        Args:
            base_coverage_dir: Directory containing base coverage data
            new_coverage_dir: Directory containing new coverage data
            merged_coverage_dir: Directory for merged coverage output
            target_function: Target function for coverage analysis
            binary_path: Path to binary for report generation

        Returns:
            True if merge succeeded, False otherwise
        """
        self.logger.info_print("Merging coverage results with base coverage...")
        os.makedirs(merged_coverage_dir, exist_ok=True)

        # Copy base coverage data
        try:
            shutil.copytree(base_coverage_dir, merged_coverage_dir, dirs_exist_ok=True)
            self.logger.debug_print(f"Copied base coverage to: {merged_coverage_dir}")
        except Exception as e:
            self.logger.error_print(f"Error copying base coverage: {e}")
            return False

        # Find profdata files to merge
        base_profdata = os.path.join(base_coverage_dir, "coverage.profdata")
        new_profdata = os.path.join(new_coverage_dir, "coverage.profdata")
        merged_profdata = os.path.join(merged_coverage_dir, "coverage.profdata")

        if not os.path.exists(base_profdata):
            self.logger.warning_print(f"Base profdata file not found: {base_profdata}")
            base_profdata = None

        if not os.path.exists(new_profdata):
            self.logger.warning_print(f"New profdata file not found: {new_profdata}")
            new_profdata = None

        # Merge profdata files
        if base_profdata and new_profdata:
            try:
                profdata_bin = f"llvm-profdata-{self.llvm_version}"
                cmd = [
                    profdata_bin, "merge",
                    "-sparse=true",
                    "-o", merged_profdata,
                    base_profdata,
                    new_profdata
                ]
                self.logger.debug_print(f"Running coverage merge: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    self.logger.error_print(f"Coverage merge failed with return code {result.returncode}")
                    self.logger.error_print(f"STDOUT: {result.stdout}")
                    self.logger.error_print(f"STDERR: {result.stderr}")
                    return False

                self.logger.info_print(f"Coverage data merged successfully: {merged_profdata}")

                # Generate merged coverage report
                if os.path.exists(binary_path):
                    self._generate_coverage_report(
                        binary_path=binary_path,
                        coverage_dir=merged_coverage_dir,
                        target_function=target_function
                    )

                return True

            except Exception as e:
                self.logger.error_print(f"Error during coverage merge: {e}")
                return False

        return True

    def _find_target_function(self, st_code_path: str) -> str:
        """
        Extract target function name from ST code for coverage analysis.

        Args:
            st_code_path: Path to ST source file

        Returns:
            Target function name or empty string if not found
        Note: MatIEC compiler converts function names to UPPERCASE, so we return uppercase.
        """
        try:
            with open(st_code_path, 'r') as f:
                content = f.read()

            # Look for function block names
            function_block_match = re.search(r'FUNCTION_BLOCK\s+(\w+)', content, re.IGNORECASE)
            if function_block_match:
                function_name = function_block_match.group(1)
                # MatIEC generates uppercase function names
                function_name = function_name.upper()
                self.logger.debug_print(f"Found function block: {function_name}")
                return f"{function_name}_body__"

            # Look for program names
            program_match = re.search(r'PROGRAM\s+(\w+)', content, re.IGNORECASE)
            if program_match:
                program_name = program_match.group(1)
                # MatIEC generates uppercase function names
                program_name = program_name.upper()
                self.logger.debug_print(f"Found program: {program_name}")
                return f"{program_name}_body__"

            # Default to filename without extension (uppercased)
            file_name = os.path.splitext(os.path.basename(st_code_path))[0]
            file_name = file_name.upper()
            self.logger.debug_print(f"No function block found, using filename: {file_name}")
            return f"{file_name}_body__"

        except Exception as e:
            self.logger.warning_print(f"Error finding target function: {e}")
            return ""

    def _apply_header_patches(self, output_dir: str) -> None:
        """
        Apply essential header patches to generated C files.

        Args:
            output_dir: Directory containing generated C files
        """
        self.logger.info_print("Applying header patches to generated C files...")

        # Essential header patch content
        patch_headers = """#include "iec_types.h"
#include "iec_types_all.h"
#include "iec_std_lib.h"
#include "iec_std_FB.h"
#include "accessor.h"
"""

        # Find all C files in the output directory
        for root, _, files in os.walk(output_dir):
            for file in files:
                if file.endswith('.c') and file != 'harness_coverage.c':
                    c_file_path = os.path.join(root, file)
                    h_file_path = os.path.join(root, file.replace('.c', '.h'))

                    # Skip if already patched
                    with open(c_file_path, 'r') as f:
                        content = f.read()
                    if '#include "iec_std_lib.h"' in content:
                        self.logger.debug_print(f"Skipping already patched file: {file}")
                        continue

                    self.logger.debug_print(f"Patching file: {file}")

                    # Create patched content
                    patched_content = patch_headers + "\n"

                    # Include the header file if it exists
                    if os.path.exists(h_file_path):
                        header_name = os.path.basename(h_file_path)
                        patched_content += f'#include "{header_name}"\n\n'

                    # Append original content
                    patched_content += content

                    # Write back the patched content
                    with open(c_file_path, 'w') as f:
                        f.write(patched_content)

        self.logger.info_print("Header patching completed successfully")

    def _try_compilation_cache(
        self,
        st_code_input: Any,
        harness_input: Optional[object],
        input_data_list: Optional[List[Any]],
        benchmark_case: Optional[str],
        temp_dir: Optional[str],
        output_format: str,
        eval_timeout_sec: Optional[float] = None
    ) -> Optional[Dict[str, Any]]:
        """
# Try to use the compilation cache fast path

If cache hit, skip compilation and execute directly.

        Args:
st_code_input: ST code
harness_input: Harness code
input data list
benchmark_case: Benchmark name
temp_dir: temporary directory
output_format: output format

        Returns:
# If cache hit, return the execution result, otherwise return None
        """
        try:
            from harness.compiler.compilation_cache import CompilationCacheManager

            # Extract ST and harness content
            st_content = self._extract_content(st_code_input, ".st")
            harness_content = self._extract_content(harness_input, ".c")

            if not st_content or not harness_content:
                return None

            # Calculate cache key
            cache_key = CompilationCacheManager.compute_cache_key(st_content, harness_content)

            # Check cache
            cached_binary = CompilationCacheManager.get_cached_binary(cache_key)
            if not cached_binary:
                return None

            # Cache hit, using cached binary
            self.logger.info_print(f"Cache hit for key: {cache_key}")

            return self._execute_with_cached_binary(
                cached_binary=cached_binary,
                input_data_list=input_data_list,
                benchmark_case=benchmark_case,
                temp_dir=temp_dir,
                output_format=output_format,
                eval_timeout_sec=eval_timeout_sec
            )

        except Exception as e:
            self.logger.warning_print(f"Compilation cache check failed: {e}")
            return None

    def _extract_content(self, input_data: Any, expected_suffix: str) -> Optional[str]:
        """
# Extract text content from input

        Args:
input_data: input data (could be path, string, or object)
expected_suffix: Expected file suffix

        Returns:
Text content or None
        """
        # Path object
        if isinstance(input_data, Path):
            if input_data.suffix == expected_suffix or expected_suffix in str(input_data):
                return input_data.read_text(encoding='utf-8')
            return None

        # String path
        if isinstance(input_data, str):
            if input_data.endswith(expected_suffix) and os.path.exists(input_data):
                with open(input_data, 'r', encoding='utf-8') as f:
                    return f.read()
            # It might be direct code content
            if expected_suffix == ".st" and ("PROGRAM" in input_data or "FUNCTION" in input_data):
                return input_data
            if expected_suffix == ".c" and ("#include" in input_data or "void" in input_data):
                return input_data
            return None

        # Object with to_harness_input method (ExpUnifiedIR)
        if hasattr(input_data, 'to_harness_input'):
            return input_data.to_harness_input()

        return None

    def _execute_with_cached_binary(
        self,
        cached_binary: Path,
        input_data_list: Optional[List[Any]],
        benchmark_case: Optional[str],
        temp_dir: Optional[str],
        output_format: str,
        eval_timeout_sec: Optional[float] = None
    ) -> Dict[str, Any]:
        """
Test using cached binary execution

        Args:
cached_binary: Cached binary file path
input_data_list: input data list
benchmark_case: Benchmark name
temp_dir: temporary directory
output_format: output format

        Returns:
Execution result
        """
        # Create temp directory if not provided
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="plchat_cached_coverage_")
        else:
            os.makedirs(temp_dir, exist_ok=True)

        # Create necessary directories
        benchmark_dir = os.path.join(temp_dir, "benchmark_execution", benchmark_case or "fuzzing_target")
        input_dir = os.path.join(benchmark_dir, "input")
        coverage_dir = os.path.join(benchmark_dir, "coverage")

        for d in [input_dir, coverage_dir]:
            os.makedirs(d, exist_ok=True)

        # Initialize input processor
        from harness.compiler.input_processor import STInputProcessor
        if not hasattr(self, 'input_processor'):
            self.input_processor = STInputProcessor(
                logger=self.logger,
                debug=self.debug,
                default_output_format=self.default_output_format
            )

        # Prepare inputs
        if input_data_list:
            for idx, input_data in enumerate(input_data_list):
                input_subdir = os.path.join(input_dir, f"test_case_{idx}")
                os.makedirs(input_subdir, exist_ok=True)
                self.input_processor.handle_input_data(input_data, input_subdir, output_format)

        # Find target function (MatIEC generates uppercase function names)
        # Extract function name from benchmark_case by removing leading numbers and underscores
        # e.g., "211_StackMin" -> "STACKMIN"
        if benchmark_case:
            # Remove leading numbers and underscores
            import re
            func_name = re.sub(r'^[\d_]+', '', benchmark_case)
            # Convert to uppercase (MatIEC convention)
            func_name = func_name.upper()
            target_function = f"{func_name}_body__"
        else:
            target_function = "fuzzing_target_body__"
        self.logger.info_print(f"Target function for coverage: {target_function}")

        # Run with cached binary
        self.logger.info_print(f"Running cached binary with coverage collection...")
        coverage_result = self._run_multiple_coverage_collection(
            binary_path=str(cached_binary),
            input_dir=input_dir,
            coverage_dir=coverage_dir,
            target_function=target_function,
            benchmark_case=benchmark_case,
            test_case_count=len(input_data_list) if input_data_list else 1,
            eval_timeout_sec=eval_timeout_sec
        )

        # Extract coverage results
        report = self._extract_coverage_results(
            case_name=f"{benchmark_case}_multi" if benchmark_case else "fuzzing_target_multi",
            coverage_dir=coverage_dir,
            target_function=target_function
        )

        # Return result in appropriate format
        if output_format == "ExpUnifiedIR":
            return {
                "status": "success",
                "return_code": 0,
                "stdout": coverage_result.get("stdout", ""),
                "stderr": coverage_result.get("stderr", ""),
                "coverage_data": report,
                "incremental": False,
                "cached": True
            }
        else:
            return {
                "status": coverage_result.get("status", "success"),
                "return_code": coverage_result.get("return_code", 0),
                "stdout": coverage_result.get("stdout", ""),
                "stderr": coverage_result.get("stderr", ""),
                "coverage_data": report,
                "incremental": False,
                "cached": True
            }

    def _save_compilation_cache(
        self,
        binary_path: str,
        st_content: str,
        harness_content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
Save the compilation result to cache

# Called after normal compilation is complete, saves the result for use in subsequent iterations.

        Args:
binary_path: path to the compiled binary file
st_content: ST source code content
Harness source code content
metadata: additional metadata
        """
        try:
            from harness.compiler.compilation_cache import CompilationCacheManager

            cache_key = CompilationCacheManager.compute_cache_key(st_content, harness_content)
            CompilationCacheManager.save_compilation(
                cache_key=cache_key,
                binary_path=Path(binary_path),
                st_content=st_content,
                harness_content=harness_content,
                metadata=metadata
            )
            self.logger.info_print(f"Saved compilation to cache: {cache_key}")

        except Exception as e:
            self.logger.warning_print(f"Failed to save compilation cache: {e}")
