"""
PLCHaT ST Batch Executor

Batch execution system for multiple test cases with compilation optimization.
Compiles once, executes multiple times, and aggregates results.

Key features:
- Batch compilation optimization (compile once, execute many times)
- Batch execution loop with timeout control
- Concurrent execution control
- Result aggregation and error handling
"""

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# Add parent directory to path for imports
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from harness.compiler.utils import Logger, LEVEL
from harness.compiler.executor import STExecutor
from harness.compiler.input_processor import STInputProcessor
from core.data_types.execution_coverage import STExecutionResult

class STBatchExecutor:
    """
    Batch execution system for multiple test cases.

    Optimizes execution by compiling the ST code once and then
    executing it multiple times with different inputs.

    Supports both StoredTestCase and ExpUnifiedIR input/output formats.
    """

    def __init__(
        self,
        root_dir: Optional[str] = None,
        logger: Optional[Logger] = None,
        debug: bool = False,
        default_output_format: str = "StoredTestCase",
        max_concurrent: int = 4
    ):
        """
        Initialize batch executor.

        Args:
            root_dir: Project root directory
            logger: Logger instance
            debug: Enable debug logging
            default_output_format: Default output format ("StoredTestCase" or "ExpUnifiedIR")
            max_concurrent: Maximum concurrent executions
        """
        self.root_dir = root_dir or PROJECT_ROOT
        self.logger = logger or Logger("/tmp/plchat_batch_executor_logs", "st_batch_executor.log",
                                       level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug
        self.default_output_format = default_output_format
        self.max_concurrent = max_concurrent

        # Initialize executor and input processor
        self.executor = STExecutor(
            root_dir=self.root_dir,
            logger=self.logger,
            debug=self.debug,
            default_output_format=self.default_output_format
        )
        self.input_processor = STInputProcessor(
            logger=self.logger,
            debug=self.debug,
            default_output_format=self.default_output_format
        )

    def execute_batch(
        self,
        st_code_input: Any,
        harness_input: Any,
        input_data_list: List[Any],
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        timeout: int = 30,
        output_format: str = "StoredTestCase"
    ) -> List[Dict[str, Any]]:
        """
        Execute ST code with multiple test cases in batch.

        Args:
            st_code_input: ST code to execute
            harness_input: C harness code
            input_data_list: List of input data for each test case
            include_files: Included ST files
            benchmark_case: Benchmark case name
            temp_dir: Temporary directory for execution
            timeout: Execution timeout per test case
            output_format: Output format ("StoredTestCase" or "ExpUnifiedIR")

        Returns:
            List of execution results for each test case
        """
        self.logger.info_print(f"Executing batch with {len(input_data_list)} test cases")

        if not input_data_list:
            self.logger.warning_print("No input data provided, returning empty result")
            return []

        # Create temp directory if not provided
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="plchat_batch_")
        else:
            os.makedirs(temp_dir, exist_ok=True)

        # Create necessary directories
        benchmark_dir = os.path.join(temp_dir, "benchmark_execution", benchmark_case or "batch_target")
        plc_st_code_dir = os.path.join(benchmark_dir, "plc_st_code")
        plc_c_code_dir = os.path.join(benchmark_dir, "plc_c_code")
        includes_dir = os.path.join(benchmark_dir, "includes")
        input_dir = os.path.join(benchmark_dir, "input")
        output_dir = os.path.join(benchmark_dir, "output")

        for d in [plc_st_code_dir, plc_c_code_dir, includes_dir, input_dir, output_dir]:
            os.makedirs(d, exist_ok=True)

        # Prepare inputs
        self.input_processor.handle_st_code_input(st_code_input, plc_st_code_dir)
        self.input_processor.handle_harness_input(harness_input, plc_c_code_dir)
        self.input_processor.handle_include_files(include_files, includes_dir)

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

        # Compile ST to C (once for all test cases)
        self.logger.info_print("Compiling ST code to C (batch compilation)...")
        if not self.executor.compile_st_to_c(
            st_code_path=st_code_path,
            output_dir=output_dir,
            harness_path=harness_path,
            include_files=include_files,
            benchmark_case=benchmark_case
        ):
            error_msg = "ST to C compilation failed"
            self.logger.error_print(error_msg)
            return [{
                "status": "compilation_failed",
                "return_code": 1,
                "stdout": "",
                "stderr": error_msg,
                "message": error_msg
            }]

        # Compile C to binary (once for all test cases)
        self.logger.info_print("Compiling C to binary (batch compilation)...")

        # Collect generated C files
        generated_c_files = []
        for file in os.listdir(output_dir):
            if file.endswith(".c") and file != "harness.c":
                generated_c_files.append(os.path.join(output_dir, file))

        # Find MatIEC C library directory
        iec2c_bin = shutil.which("iec2c")
        matiec_path = str(Path(iec2c_bin).parent) if iec2c_bin else "/usr/local/bin"
        matiec_c_lib_dir = os.environ.get("MATIEC_C_LIB_DIR", os.path.join(matiec_path, "lib", "C"))

        # Collect MatIEC library C files
        lib_c_files = []
        if os.path.exists(matiec_c_lib_dir):
            for file in os.listdir(matiec_c_lib_dir):
                if file.endswith(".c") and ("iec_std_lib" in file or "accessor" in file):
                    lib_c_files.append(os.path.join(matiec_c_lib_dir, file))

        # Combine all source files
        source_files = generated_c_files + lib_c_files + [os.path.join(output_dir, "harness.c")]
        binary_path = os.path.join(output_dir, "plc_batch_harness")

        if not self.executor.compile_c_to_binary(
            source_files=source_files,
            output_binary=binary_path,
            include_dirs=[matiec_c_lib_dir, output_dir],
            libraries=[],
            coverage_mode=False
        ):
            error_msg = "C to binary compilation failed"
            self.logger.error_print(error_msg)
            return [{
                "status": "compilation_failed",
                "return_code": 1,
                "stdout": "",
                "stderr": error_msg,
                "message": error_msg
            }]

        self.logger.info_print(f"Binary compiled successfully: {binary_path}")

        # Execute binary with each input (batch execution)
        results = []
        if self.max_concurrent > 1:
            results = self._execute_concurrent(
                binary_path=binary_path,
                input_data_list=input_data_list,
                input_dir=input_dir,
                timeout=timeout,
                output_format=output_format
            )
        else:
            results = self._execute_sequential(
                binary_path=binary_path,
                input_data_list=input_data_list,
                input_dir=input_dir,
                timeout=timeout,
                output_format=output_format
            )

        self.logger.info_print(f"Batch execution completed: {len(results)} results")
        return results

    def _execute_sequential(
        self,
        binary_path: str,
        input_data_list: List[Any],
        input_dir: str,
        timeout: int,
        output_format: str
    ) -> List[Dict[str, Any]]:
        """
        Execute test cases sequentially.

        Args:
            binary_path: Path to compiled binary
            input_data_list: List of input data
            input_dir: Directory for input files
            timeout: Execution timeout per test case
            output_format: Output format

        Returns:
            List of execution results
        """
        results = []

        for idx, input_data in enumerate(input_data_list):
            self.logger.info_print(f"Executing test case {idx + 1}/{len(input_data_list)}")

            # Prepare input file for this test case
            test_input_dir = os.path.join(input_dir, f"test_case_{idx}")
            os.makedirs(test_input_dir, exist_ok=True)
            self.input_processor.handle_input_data(input_data, test_input_dir, output_format)

            input_file = os.path.join(test_input_dir, "input.txt")

            # Execute binary
            result = self.executor.execute_binary(
                binary_path=binary_path,
                input_file=input_file if os.path.exists(input_file) else None,
                timeout=timeout,
                output_format=output_format
            )

            # Add test case index to result
            if isinstance(result, dict):
                result["test_case_index"] = idx
            else:
                # For STExecutionResult, add to execution_summary
                pass

            results.append(result)

        return results

    def _execute_concurrent(
        self,
        binary_path: str,
        input_data_list: List[Any],
        input_dir: str,
        timeout: int,
        output_format: str
    ) -> List[Dict[str, Any]]:
        """
        Execute test cases concurrently with thread pool.

        Args:
            binary_path: Path to compiled binary
            input_data_list: List of input data
            input_dir: Directory for input files
            timeout: Execution timeout per test case
            output_format: Output format

        Returns:
            List of execution results
        """
        results = [None] * len(input_data_list)
        lock = threading.Lock()

        def execute_single(idx: int, input_data: Any) -> Dict[str, Any]:
            """Execute a single test case."""
            self.logger.info_print(f"Executing test case {idx + 1}/{len(input_data_list)} (concurrent)")

            # Prepare input file for this test case
            test_input_dir = os.path.join(input_dir, f"test_case_{idx}")
            os.makedirs(test_input_dir, exist_ok=True)

            # Use a thread-local input processor to avoid conflicts
            
            thread_input_processor = STInputProcessor(
                logger=self.logger,
                debug=self.debug,
                default_output_format=self.default_output_format
            )
            thread_input_processor.handle_input_data(input_data, test_input_dir, output_format)

            input_file = os.path.join(test_input_dir, "input.txt")

            # Execute binary
            result = self.executor.execute_binary(
                binary_path=binary_path,
                input_file=input_file if os.path.exists(input_file) else None,
                timeout=timeout,
                output_format=output_format
            )

            # Add test case index to result
            if isinstance(result, dict):
                result["test_case_index"] = idx

            return result

        # Execute with thread pool
        with ThreadPoolExecutor(max_workers=self.max_concurrent) as executor:
            futures = {
                executor.submit(execute_single, idx, input_data): idx
                for idx, input_data in enumerate(input_data_list)
            }

            for future in as_completed(futures):
                idx = futures[future]
                try:
                    result = future.result()
                    with lock:
                        results[idx] = result
                except Exception as e:
                    self.logger.error_print(f"Test case {idx} failed with exception: {e}")
                    with lock:
                        results[idx] = {
                            "status": "error",
                            "return_code": -1,
                            "stdout": "",
                            "stderr": str(e),
                            "message": f"Exception during execution: {str(e)}",
                            "test_case_index": idx
                        }

        return results

    def execute_batch_with_coverage(
        self,
        st_code_input: Any,
        harness_input: Any,
        input_data_list: List[Any],
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        timeout: int = 30,
        output_format: str = "StoredTestCase"
    ) -> Dict[str, Any]:
        """
        Execute ST code with coverage for multiple test cases (aggregated coverage).

        This is a convenience method that uses the coverage collector.

        Args:
            st_code_input: ST code to execute
            harness_input: C harness code
            input_data_list: List of input data for each test case
            include_files: Included ST files
            benchmark_case: Benchmark case name
            temp_dir: Temporary directory for execution
            timeout: Execution timeout per test case
            output_format: Output format ("StoredTestCase" or "ExpUnifiedIR")

        Returns:
            Aggregated coverage result for all test cases
        """
        from harness.compiler.st_coverage_collector import STCoverageCollector

        coverage_collector = STCoverageCollector(
            root_dir=self.root_dir,
            logger=self.logger,
            debug=self.debug,
            default_output_format=self.default_output_format
        )

        return coverage_collector.execute_with_multiple_coverage(
            st_code_input=st_code_input,
            harness_input=harness_input,
            input_data_list=input_data_list,
            include_files=include_files,
            benchmark_case=benchmark_case,
            temp_dir=temp_dir,
            output_format=output_format
        )


import shutil
