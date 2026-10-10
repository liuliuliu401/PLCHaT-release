"""
PLCHaT ST Compiler Core - Public API Layer

# Unified compiler entry point, integrating all components to provide a concise public API.
Integrates components such as STExecutor, STCoverageCollector, STBatchExecutor, STStateAnalyzer, etc.

Migrated from: FuzzGen/utils/st_compiler_matiec/st_compiler_core.py
Simplified: Removed multi-benchmark management, focused on core compilation API.
"""

import os
import sys
import shutil
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Union

# Project root: st_compiler_core.py → compiler → harness → PROJECT_ROOT
# Structure: PROJECT_ROOT/harness/compiler/st_compiler_core.py (2 parents up to harness, then 1 more to root? No)
# st_compiler_core.py → compiler → harness → PROJECT_ROOT (3 parents? No, 2 parents to harness root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# PLCHaT imports
from harness.compiler.utils import Logger, LEVEL
from harness.compiler.executor import STExecutor
from harness.compiler.st_coverage_collector import STCoverageCollector
from harness.compiler.st_batch_executor import STBatchExecutor
from harness.compiler.st_state_analyzer import STStateAnalyzer
from harness.compiler.input_processor import STInputProcessor

from core.data_types.execution_coverage import (
    STExecutionResult,
    ExecutionSummary,
    ExecutionStatus,
    ValidationResult,
    IncrementalSimulationResult,
    IncrementalSummary
)
from core.data_types import StoredTestCase, ExpUnifiedIR, InitialState

class STCompilerCore:
    """
PLCHaT compiler public API entry point

Integrate all compiler components to provide a unified interface for upper-level usage.
Supports ST code compilation, execution, coverage analysis, status analysis and other functions.

Main function:
- Environment check: MatIEC, LLVM tools
- Syntax validation: validate_st_syntax()
- Single execution: execute_st_code()
- Incremental simulation: execute_incremental_simulation()
Batch execution: execute_st_code_multiple_cases()
- Coverage collection: execute_st_code_with_coverage()
- Status analysis: through STStateAnalyzer
    """

    def __init__(
        self,
        benchmark_root: Optional[str] = None,
        root_dir: Optional[str] = None,
        max_executions: int = 10,
        force_rebuild: bool = False,
        logger: Optional[Logger] = None,
        debug: bool = False,
        default_output_format: str = "STExecutionResult"
    ):
        """
# Initialize STCompilerCore

        Args:
benchmark_root: Benchmark root directory
root_dir: project root directory
max_executions: Maximum concurrent executions
force_rebuild: force rebuild
logger: Logger instance
debug: enable debug logging
default_output_format: default output format
        """
        self.root_dir = root_dir or str(PROJECT_ROOT)
        self.benchmark_root = benchmark_root or os.path.join(self.root_dir, "benchmarks")
        self.max_executions = max_executions
        self.force_rebuild = force_rebuild
        self.debug = debug
        self.default_output_format = default_output_format

        # Initialize logging
        log_dir = os.path.join(self.root_dir, "logs", "st_compiler")
        self.logger = logger or Logger(
            folder=log_dir,
            file_name="compiler_core.log",
            level=LEVEL.DEBUG if debug else LEVEL.INFO
        )

        # Initialize component
        self.input_processor = STInputProcessor(
            logger=self.logger,
            debug=debug,
            default_output_format=default_output_format
        )

        self.executor = STExecutor(
            root_dir=self.root_dir,
            logger=self.logger,
            debug=debug,
            default_output_format=default_output_format
        )

        self.coverage_collector = STCoverageCollector(
            root_dir=self.root_dir,
            max_executions=max_executions,
            force_rebuild=force_rebuild,
            logger=self.logger,
            debug=debug,
            llvm_version=18
        )

        self.batch_executor = STBatchExecutor(
            root_dir=self.root_dir,
            logger=self.logger,
            debug=debug,
            default_output_format=default_output_format
        )

        self.state_analyzer = STStateAnalyzer(
            logger=self.logger,
            debug=debug
        )

        self.logger.info_print(f"STCompilerCore initialized")
        self.logger.info_print(f"  root_dir: {self.root_dir}")
        self.logger.info_print(f"  benchmark_root: {self.benchmark_root}")

    # ==================== Environment Check ====================

    def check_matiec_installation(self) -> Tuple[bool, str]:
        """Check whether the MatIEC compiler is correctly installed"""
        return self.input_processor.check_matiec_installation()

    def check_llvm_tools(self) -> Tuple[bool, str]:
        """# Check if the LLVM coverage tool is available"""
        return self.input_processor.check_llvm_tools()

    def check_environment(self) -> Dict[str, Tuple[bool, str]]:
        """Check all environment dependencies"""
        return {
            "matiec": self.check_matiec_installation(),
            "llvm_tools": self.check_llvm_tools()
        }

    # ==================== Syntax Validation ====================

    def validate_st_syntax(
        self,
        st_code_path: str,
        output_dir: Optional[str] = None
    ) -> ValidationResult:
        """
Verify ST code syntax

        Args:
st_code_path: ST code file path
output_dir: Output directory (optional)

        Returns:
ValidationResult: validation result
        """
        self.logger.info_print(f"Validating ST syntax: {st_code_path}")

        use_temp = False
        if output_dir is None:
            output_dir = tempfile.mkdtemp(prefix="st_validation_")
            use_temp = True
        else:
            os.makedirs(output_dir, exist_ok=True)

        # Find default harness
        default_harness_path = os.path.join(self.benchmark_root, "plc_c_code", "harness.c")
        if not os.path.exists(default_harness_path):
            # Try to find in benchmark_root
            for root, _, files in os.walk(self.benchmark_root):
                for file in files:
                    if file == "harness.c":
                        default_harness_path = os.path.join(root, file)
                        break
                else:
                    continue
                break

        # If there is no harness, create the minimum version
        if not os.path.exists(default_harness_path):
            self.logger.warning_print(f"No harness found, creating minimal one")
            os.makedirs(os.path.dirname(default_harness_path), exist_ok=True)
            with open(default_harness_path, "w") as f:
                f.write('#include "iec_types.h"\n#include "iec_std_lib.h"\nint main() { return 0; }\n')

        # Execute ST→C compilation to verify syntax
        success = self.executor.compile_st_to_c(
            st_code_path=st_code_path,
            output_dir=output_dir,
            harness_path=default_harness_path,
            include_files=None,
            benchmark_case="syntax_validation"
        )

        if use_temp and os.path.exists(output_dir):
            shutil.rmtree(output_dir)

        if success:
            return ValidationResult(
                status="success",
                return_code=0,
                message="ST syntax is valid"
            )
        else:
            return ValidationResult(
                status="failed",
                return_code=1,
                message="ST to C compilation failed, syntax may be invalid",
                details="Check ST code for syntax errors"
            )

    # ==================== Single Execution ====================

    def execute_st_code(
        self,
        st_code_input: Any,
        timeout: int = 30,
        harness_input: Optional[Any] = None,
        input_data: Optional[Any] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        initial_state: Optional[Any] = None,
        output_format: str = None
    ) -> STExecutionResult:
        """
Execute ST code once

        Args:
st_code_input: ST code input (file path or content)
timeout: timeout time (seconds)
harness_input: C harness code
input_data: input data
include_files: list of included ST files
# Benchmark case name
temp_dir: temporary directory
initial_state: initial state
output_format: output format

        Returns:
STExecutionResult: Execution result
        """
        if output_format is None:
            output_format = self.default_output_format

        self.logger.info_print(f"Executing ST code (format: {output_format})")

        # Create working directory
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="st_execution_")
        else:
            os.makedirs(temp_dir, exist_ok=True)

        benchmark_case = benchmark_case or "fuzzing_target"
        benchmark_dir = os.path.join(temp_dir, "benchmark_execution", benchmark_case)

        # Create subdirectory
        plc_st_code_dir = os.path.join(benchmark_dir, "plc_st_code")
        plc_c_code_dir = os.path.join(benchmark_dir, "plc_c_code")
        includes_dir = os.path.join(benchmark_dir, "includes")
        input_dir = os.path.join(benchmark_dir, "input")
        state_dir = os.path.join(benchmark_dir, "initial_state")
        output_dir = os.path.join(benchmark_dir, "output")

        for d in [plc_st_code_dir, plc_c_code_dir, includes_dir, input_dir, state_dir, output_dir]:
            os.makedirs(d, exist_ok=True)

        # Process input
        self.input_processor.handle_st_code_input(st_code_input, plc_st_code_dir)
        self.input_processor.handle_harness_input(harness_input, plc_c_code_dir)
        self.input_processor.handle_input_data(input_data, input_dir, output_format)
        self.input_processor.handle_include_files(include_files, includes_dir)
        self.input_processor.handle_initial_state(initial_state, state_dir)

        # Find ST code file
        st_code_path = None
        for file in os.listdir(plc_st_code_dir):
            if file.endswith('.st'):
                st_code_path = os.path.join(plc_st_code_dir, file)
                break
        if not st_code_path:
            raise ValueError("No ST code file found in plc_st_code directory")

        # Find harness file
        harness_path = None
        for file in ['harness.c']:
            path = os.path.join(plc_c_code_dir, file)
            if os.path.exists(path):
                harness_path = path
                break
        if not harness_path:
            raise ValueError("No harness file found in plc_c_code directory")

        # ST→C compilation
        if not self.executor.compile_st_to_c(
            st_code_path=st_code_path,
            output_dir=output_dir,
            harness_path=harness_path,
            include_files=include_files,
            benchmark_case=benchmark_case
        ):
            return STExecutionResult(
                status="compilation_failed",
                return_code=1,
                message="ST to C compilation failed",
                raw_stderr="ST to C compilation failed"
            )

        # C→Binary compilation
        iec2c_bin = shutil.which("iec2c")
        matiec_path = str(Path(iec2c_bin).parent) if iec2c_bin else "/usr/local/bin"
        matiec_c_lib_dir = os.environ.get("MATIEC_C_LIB_DIR", os.path.join(matiec_path, "lib", "C"))

        generated_c_files = [
            os.path.join(output_dir, f) for f in os.listdir(output_dir)
            if f.endswith(".c") and not f.startswith("harness")
        ]

        lib_c_files = []
        if os.path.exists(matiec_c_lib_dir):
            lib_c_files = [
                os.path.join(matiec_c_lib_dir, f) for f in os.listdir(matiec_c_lib_dir)
                if f.endswith(".c") and ("iec_std_lib" in f or "accessor" in f)
            ]

        source_files = generated_c_files + lib_c_files + [os.path.join(output_dir, "harness.c")]
        binary_path = os.path.join(output_dir, "plc_harness")

        if not self.executor.compile_c_to_binary(
            source_files=source_files,
            output_binary=binary_path,
            include_dirs=[matiec_c_lib_dir, output_dir],
            libraries=[],
            coverage_mode=False,
            benchmark_case=benchmark_case
        ):
            return STExecutionResult(
                status="compilation_failed",
                return_code=1,
                message="C to binary compilation failed",
                raw_stderr="C to binary compilation failed"
            )

        # Find input file
        input_file = None
        for file in ["input.txt", "input_000.txt"]:
            path = os.path.join(input_dir, file)
            if os.path.exists(path):
                input_file = path
                break
        if not input_file:
            raise ValueError("No input file found in input directory")

        # Execute binary
        raw_result = self.executor.execute_binary(
            binary_path=binary_path,
            input_file=input_file,
            timeout=timeout,
            benchmark_case=benchmark_case,
            output_format=output_format
        )

        # Parse output into structured objects
        result = self.input_processor.parse_execution_output(raw_result, output_format)

        self.logger.info_print(f"Execution completed with status: {result.status}")
        return result

    # ==================== Incremental Simulation ====================

    def execute_incremental_simulation(
        self,
        st_code_input: Any,
        harness_input: Optional[Any] = None,
        input_data: Optional[Any] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        num_rounds: int = 3,
        cycles_per_round: int = 1,
        start_round: int = 0,
        start_state: Optional[Any] = None,
        output_format: str = None
    ) -> IncrementalSimulationResult:
        """
Incremental simulation: multiple rounds of execution, state passed between rounds

        Args:
st_code_input: ST code input
harness_input: C harness code
input_data: input data
include_files: List of included ST files
benchmark_case: Benchmark case name
temp_dir: temporary directory
num_rounds: number of rounds to execute
cycles_per_round: number of cycles per round
start_round: starting round number
initial state
output_format: Output format

        Returns:
IncrementalSimulationResult: Incremental simulation result
        """
        if output_format is None:
            output_format = self.default_output_format

        self.logger.info_print(f"Starting incremental simulation: {num_rounds} rounds")

        results = []
        current_state = start_state

        base_temp_dir = temp_dir or tempfile.mkdtemp(prefix="st_incremental_")
        os.makedirs(base_temp_dir, exist_ok=True)

        for round_num in range(start_round, start_round + num_rounds):
            self.logger.info_print(f"Round {round_num + 1}/{num_rounds}")

            round_temp_dir = os.path.join(base_temp_dir, f"round_{round_num}")
            os.makedirs(round_temp_dir, exist_ok=True)

            result = self.execute_st_code(
                st_code_input=st_code_input,
                harness_input=harness_input,
                input_data=input_data,
                include_files=include_files,
                benchmark_case=benchmark_case,
                temp_dir=round_temp_dir,
                initial_state=current_state,
                output_format=output_format
            )

            results.append(result)

            # Extract final state
            if result.test_cases:
                last_test_case = result.test_cases[-1]
                if last_test_case.summary and hasattr(last_test_case.summary, 'final_state'):
                    current_state = self._plc_var_state_to_initial(
                        last_test_case.summary.final_state,
                        round_number=round_num + 1
                    )

        # Summarize results
        status = "success" if all(r.status == "success" for r in results) else "partial_success"
        total_cycles = sum(len(tc.cycles) for r in results for tc in r.test_cases)

        summary = IncrementalSummary(
            total_rounds=num_rounds,
            successful_rounds=sum(1 for r in results if r.status == "success"),
            total_test_cases=len(results),
            total_cycles=total_cycles,
            cycles_per_round=cycles_per_round,
            state_continuity=True
        )

        return IncrementalSimulationResult(
            status=status,
            rounds=results,
            final_state=current_state,
            summary=summary,
            message=f"Incremental simulation completed: {num_rounds} rounds"
        )

    def _plc_var_state_to_initial(
        self,
        var_state: Any,
        round_number: int = 0
    ) -> InitialState:
        """Convert PLCVarState to InitialState"""
        if hasattr(var_state, 'VAR_OUTPUT') and hasattr(var_state, 'VAR_INTERNAL'):
            return InitialState(
                VAR_OUTPUT=var_state.VAR_OUTPUT,
                VAR_INTERNAL=var_state.VAR_INTERNAL,
                metadata={"round": round_number}
            )
        return InitialState()

    # ==================== Multiple Test Cases ====================

    def execute_st_code_multiple_cases(
        self,
        st_code_input: Any,
        timeout: int = 30,
        harness_input: Optional[Any] = None,
        input_data_list: Optional[List[Any]] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        initial_states: Optional[List[Any]] = None,
        output_format: str = None
    ) -> STExecutionResult:
        """
Execute multiple test cases (same ST program)

        Args:
st_code_input: ST code input
timeout: timeout duration (seconds)
harness_input: C harness code
input_data_list: Input data list
include_files: list of included ST files
benchmark_case: Benchmark case name
temp_dir: Temporary directory
initial_states: list of initial states
output_format: output format

        Returns:
Merged execution results
        """
        if output_format is None:
            output_format = self.default_output_format

        self.logger.info_print(f"Executing multiple test cases")

        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="st_multi_execution_")
        else:
            os.makedirs(temp_dir, exist_ok=True)

        benchmark_case = benchmark_case or "fuzzing_target"
        benchmark_dir = os.path.join(temp_dir, "benchmark_execution", benchmark_case)

        # Create directory
        plc_st_code_dir = os.path.join(benchmark_dir, "plc_st_code")
        plc_c_code_dir = os.path.join(benchmark_dir, "plc_c_code")
        includes_dir = os.path.join(benchmark_dir, "includes")
        input_dir = os.path.join(benchmark_dir, "input")
        state_dir = os.path.join(benchmark_dir, "initial_state")
        output_dir = os.path.join(benchmark_dir, "output")

        for d in [plc_st_code_dir, plc_c_code_dir, includes_dir, input_dir, state_dir, output_dir]:
            os.makedirs(d, exist_ok=True)

        # Process ST code and harness (only once)
        self.input_processor.handle_st_code_input(st_code_input, plc_st_code_dir)
        self.input_processor.handle_harness_input(harness_input, plc_c_code_dir)
        self.input_processor.handle_include_files(include_files, includes_dir)

        # Handle multiple inputs
        if input_data_list:
            for idx, input_data in enumerate(input_data_list):
                input_subdir = os.path.join(input_dir, f"test_case_{idx}")
                os.makedirs(input_subdir, exist_ok=True)
                self.input_processor.handle_input_data(input_data, input_subdir, output_format)

        # Handle multiple initial states
        if initial_states:
            for idx, state in enumerate(initial_states):
                state_subdir = os.path.join(state_dir, f"test_case_{idx}")
                os.makedirs(state_subdir, exist_ok=True)
                self.input_processor.handle_initial_state(state, state_subdir)

        # Find ST code and harness file
        st_code_path = None
        for file in os.listdir(plc_st_code_dir):
            if file.endswith('.st'):
                st_code_path = os.path.join(plc_st_code_dir, file)
                break
        if not st_code_path:
            raise ValueError("No ST code file found")

        harness_path = None
        for file in ['harness.c']:
            path = os.path.join(plc_c_code_dir, file)
            if os.path.exists(path):
                harness_path = path
                break
        if not harness_path:
            raise ValueError("No harness file found")

        # ST→C compilation
        if not self.executor.compile_st_to_c(
            st_code_path=st_code_path,
            output_dir=output_dir,
            harness_path=harness_path,
            include_files=include_files,
            benchmark_case=benchmark_case
        ):
            return STExecutionResult(
                status="compilation_failed",
                return_code=1,
                message="ST to C compilation failed"
            )

        # C→Binary compilation
        iec2c_bin = shutil.which("iec2c")
        matiec_path = str(Path(iec2c_bin).parent) if iec2c_bin else "/usr/local/bin"
        matiec_c_lib_dir = os.environ.get("MATIEC_C_LIB_DIR", os.path.join(matiec_path, "lib", "C"))

        generated_c_files = [
            os.path.join(output_dir, f) for f in os.listdir(output_dir)
            if f.endswith(".c") and f != "harness.c"
        ]

        lib_c_files = []
        if os.path.exists(matiec_c_lib_dir):
            lib_c_files = [
                os.path.join(matiec_c_lib_dir, f) for f in os.listdir(matiec_c_lib_dir)
                if f.endswith(".c") and ("iec_std_lib" in f or "accessor" in f)
            ]

        source_files = generated_c_files + lib_c_files + [os.path.join(output_dir, "harness.c")]
        binary_path = os.path.join(output_dir, "plc_harness")

        if not self.executor.compile_c_to_binary(
            source_files=source_files,
            output_binary=binary_path,
            include_dirs=[matiec_c_lib_dir, output_dir],
            libraries=[],
            coverage_mode=False,
            benchmark_case=benchmark_case
        ):
            return STExecutionResult(
                status="compilation_failed",
                return_code=1,
                message="C to binary compilation failed"
            )

        # Execute multiple test cases
        results = []
        num_test_cases = len(input_data_list) if input_data_list else 1

        for i in range(num_test_cases):
            test_case_dir = os.path.join(input_dir, f"test_case_{i}")
            if not os.path.exists(test_case_dir):
                test_case_dir = input_dir

            input_file = None
            for file in ["input.txt", "input_000.txt"]:
                path = os.path.join(test_case_dir, file)
                if os.path.exists(path):
                    input_file = path
                    break
            if not input_file:
                continue

            raw_result = self.executor.execute_binary(
                binary_path=binary_path,
                input_file=input_file,
                timeout=timeout,
                benchmark_case=benchmark_case,
                output_format=output_format
            )
            result = self.input_processor.parse_execution_output(raw_result, output_format)
            results.append(result)

        # Merge results
        total_test_cases = sum(r.execution_summary.total_test_cases for r in results)
        total_cycles = sum(r.execution_summary.total_cycles for r in results)

        combined_test_cases = []
        for i, result in enumerate(results):
            if hasattr(result, 'test_cases'):
                for tc in result.test_cases:
                    tc.test_case_name = f"test_case_{i}_{tc.test_case_name}"
                    combined_test_cases.append(tc)

        status = "success"
        if any(r.status != "success" for r in results):
            if all(r.status != "success" for r in results):
                status = "error"
            else:
                status = "partial_success"

        return STExecutionResult(
            status=status,
            return_code=0 if status == "success" else 1,
            message=f"Multiple test cases executed: {num_test_cases} total",
            execution_summary=ExecutionSummary(
                total_test_cases=total_test_cases,
                total_cycles=total_cycles,
                expected_executions=num_test_cases,
                input_count=num_test_cases,
                state_count=len(initial_states) if initial_states else 0
            ),
            test_cases=combined_test_cases,
            raw_stdout="\n".join(r.raw_stdout for r in results),
            raw_stderr="\n".join(r.raw_stderr for r in results)
        )

    # ==================== Coverage Methods ====================

    def execute_st_code_with_coverage(
        self,
        st_code_input: Any,
        harness_input: Optional[Any] = None,
        input_data: Optional[Any] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        initial_state: Optional[Any] = None,
        output_format: str = None
    ) -> Dict[str, Any]:
        """Execute ST code and collect coverage"""
        return self.coverage_collector.execute_with_coverage(
            st_code_input=st_code_input,
            harness_input=harness_input,
            input_data=input_data,
            include_files=include_files,
            benchmark_case=benchmark_case,
            temp_dir=temp_dir,
            initial_state=initial_state,
            output_format=output_format or self.default_output_format
        )

    def execute_st_code_with_incremental_coverage(
        self,
        st_code_input: Any,
        harness_input: Optional[Any] = None,
        input_data: Optional[Any] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        base_coverage_dir: Optional[str] = None,
        incremental_mode: bool = True,
        initial_state: Optional[Any] = None,
        output_format: str = None
    ) -> Dict[str, Any]:
        """Execute ST code and collect incremental coverage"""
        return self.coverage_collector.execute_with_incremental_coverage(
            st_code_input=st_code_input,
            harness_input=harness_input,
            input_data=input_data,
            include_files=include_files,
            benchmark_case=benchmark_case,
            temp_dir=temp_dir,
            base_coverage_dir=base_coverage_dir,
            incremental_mode=incremental_mode,
            initial_state=initial_state,
            output_format=output_format or self.default_output_format
        )

    def execute_st_code_with_multiple_coverage(
        self,
        st_code_input: Any,
        harness_input: Optional[Any] = None,
        input_data_list: Optional[List[Any]] = None,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None,
        temp_dir: Optional[str] = None,
        initial_states: Optional[List[Any]] = None,
        output_format: str = None
    ) -> Dict[str, Any]:
        """Execute multiple test cases and aggregate coverage"""
        return self.coverage_collector.execute_with_multiple_coverage(
            st_code_input=st_code_input,
            harness_input=harness_input,
            input_data_list=input_data_list,
            include_files=include_files,
            benchmark_case=benchmark_case,
            temp_dir=temp_dir,
            initial_states=initial_states,
            output_format=output_format or self.default_output_format
        )

    # ==================== State Analysis Methods ====================

    def extract_sparse_timeline(
        self,
        execution_result: STExecutionResult,
        test_case_index: int = 0
    ) -> Dict[int, Any]:
        """Extract sparse timeline from execution results"""
        return self.state_analyzer.extract_sparse_timeline(
            execution_result=execution_result,
            test_case_index=test_case_index
        )

    def detect_violations(
        self,
        execution_result: STExecutionResult,
        test_case_index: int = 0
    ) -> Dict[str, Any]:
        """# Detect violations during execution"""
        from harness.oracle.violation_detector import ViolationDetector
        detector = ViolationDetector(logger=self.logger)
        return detector.detect_violations(
            execution_result=execution_result,
            test_case_index=test_case_index
        )

    def summarize_execution(
        self,
        execution_result: STExecutionResult
    ) -> Dict[str, Any]:
        """Generate executive summary"""
        return self.state_analyzer.summarize_execution(execution_result)

    # ==================== Utility Methods ====================

    def create_initial_state_from_execution(
        self,
        execution_result: STExecutionResult,
        test_case_index: int = 0,
        cycle_index: int = -1,
        round_number: int = 0
    ) -> InitialState:
        """Create initial state from execution results."""
        if not execution_result.test_cases:
            return InitialState(metadata={"source": "empty_execution"})

        test_case = execution_result.test_cases[test_case_index]
        if not test_case.cycles:
            return InitialState(metadata={"source": "empty_test_case"})

        cycle = test_case.cycles[cycle_index] if cycle_index >= 0 else test_case.cycles[-1]

        return InitialState(
            VAR_OUTPUT=cycle.after_execution.VAR_OUTPUT,
            VAR_INTERNAL=cycle.after_execution.VAR_INTERNAL,
            metadata={
                "source": "execution_result",
                "test_case_index": test_case_index,
                "cycle_index": cycle_index,
                "round_number": round_number,
                "timestamp": str(datetime.now())
            }
        )

    def get_coverage_report(
        self,
        coverage_dir: str
    ) -> Dict[str, Any]:
        """Get coverage report"""
        return self.coverage_collector._generate_coverage_report(coverage_dir)

    def cleanup_temp_files(self, temp_dir: str) -> None:
        """Clean up temporary files"""
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
            self.logger.info_print(f"Cleaned up temp directory: {temp_dir}")


# Convenient export function
def create_compiler(
    benchmark_root: Optional[str] = None,
    root_dir: Optional[str] = None,
    debug: bool = False
) -> STCompilerCore:
    """
Convenience function for creating a compiler instance

    Args:
Benchmark root directory
root_dir: project root directory
debug: Enable debug mode

    Returns:
STCompilerCore: compiler instance
    """
    return STCompilerCore(
        benchmark_root=benchmark_root,
        root_dir=root_dir,
        debug=debug
    )
