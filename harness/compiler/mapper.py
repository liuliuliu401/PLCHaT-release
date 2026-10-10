"""
PLCHaT Action Mapper

Intent-to-signal translation with Zero-Order Hold (ZOH) strategy ($\mathcal{A}$).
Handles input processing and format conversion between different representations.
"""

import os
import shutil
import subprocess
from typing import Optional, Dict, Any, List, Tuple, Union
import uuid

# PLCHaT imports
from harness.compiler.utils import Logger, LEVEL
from core.data_types import (
    STExecutionResult,
    ExecutionSummary,
    PLCTestCase,
    PLCCycle,
    PLCVarState,
    PLCParsedTestCaseSummary,
    StoredTestCase,
    IOPair,
    ExpUnifiedIR,
)


class DatasetManager:
    """Standalone dataset/benchmark configuration manager."""

    def __init__(
        self,
        logger: Optional[Logger] = None,
        debug: bool = False,
        test_cases_config: Optional[Dict[str, bool]] = None,
        benchmark_root: Optional[str] = None,
    ):
        self.logger = logger or Logger("/tmp/action_mapper_logs", "dataset_manager.log",
                                      level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug
        self.test_cases_config = test_cases_config or {}
        self.benchmark_root = benchmark_root or ""

    def get_enabled_test_cases(self) -> List[str]:
        """Get list of enabled test cases from configuration."""
        return [case_name for case_name, enabled in self.test_cases_config.items() if enabled]

    def get_benchmark_root(self) -> str:
        """Get current benchmark root directory."""
        return self.benchmark_root

    def is_test_case_enabled(self, case_name: str) -> bool:
        """Check if a specific test case is enabled."""
        return self.test_cases_config.get(case_name, False)

    def update_test_cases_config(self, new_config: Dict[str, bool]) -> None:
        """Update test cases configuration."""
        self.test_cases_config.update(new_config)

    def set_benchmark_root(self, new_root: str) -> None:
        """Set new benchmark root directory."""
        if os.path.exists(new_root):
            self.benchmark_root = new_root
            self.logger.success_print(f"✓ Benchmark root set to: {new_root}")
        else:
            error_msg = f"Benchmark root directory does not exist: {new_root}"
            self.logger.error_print(error_msg)
            raise ValueError(error_msg)

    def get_test_cases_config(self) -> Dict[str, bool]:
        """Get current test cases configuration."""
        return self.test_cases_config.copy()


class MatIECEnvChecker:
    """Standalone environment checker for MatIEC compiler dependencies."""

    def __init__(self, logger: Optional[Logger] = None, debug: bool = False):
        self.logger = logger or Logger("/tmp/action_mapper_logs", "matiec_env.log",
                                      level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug

    def check_matiec_installation(self) -> Tuple[bool, str]:
        """Check if MatIEC compiler is properly installed."""
        try:
            result = subprocess.run(["iec2c", "--help"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                self.logger.success_print("✓ MatIEC compiler found and working")
                return True, shutil.which("iec2c")
            else:
                return False, "MatIEC compiler (iec2c) not found or not working"
        except (subprocess.TimeoutExpired, subprocess.CalledProcessError, FileNotFoundError) as e:
            return False, f"MatIEC compiler not available: {str(e)}"

    def check_llvm_tools(self) -> Tuple[bool, str]:
        """Check if LLVM coverage tools (llvm-profdata, llvm-cov) are available."""
        tools = ["llvm-profdata-18", "llvm-cov-18"]
        missing = []

        for tool in tools:
            try:
                subprocess.run([tool, "--version"], capture_output=True, text=True, timeout=5)
            except (FileNotFoundError, subprocess.TimeoutExpired):
                missing.append(tool)

        if missing:
            return False, f"Missing LLVM tools: {', '.join(missing)}"
        else:
            self.logger.success_print("✓ LLVM coverage tools found")
            return True, "All LLVM tools available"

    def check_clang_version(self) -> Tuple[bool, str]:
        """Check if compatible clang version is available."""
        try:
            result = subprocess.run(["clang-18", "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                self.logger.success_print("✓ Clang-18 found")
                return True, result.stdout.split('\n')[0]
            else:
                return False, "Clang-18 not found"
        except Exception as e:
            return False, f"Clang-18 check failed: {str(e)}"


class ActionMapper:
    """
    Intent-to-signal translation with ZOH ($\mathcal{A}$).
    Handles input processing, format conversion, and Zero-Order Hold strategy.
    """

    def __init__(
        self,
        logger: Optional[Logger] = None,
        debug: bool = False,
        test_cases_config: Optional[Dict[str, bool]] = None,
        benchmark_root: Optional[str] = None,
        default_output_format: str = "StoredTestCase"
    ):
        """
        Initialize action mapper.

        Args:
            logger: Logger instance
            debug: Enable debug logging
            test_cases_config: Configuration for enabled test cases
            benchmark_root: Root directory for benchmarks
            default_output_format: Default output format ("StoredTestCase" or "ExpUnifiedIR")
        """
        self.logger = logger or Logger("/tmp/action_mapper_logs", "action_mapper.log",
                                      level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug
        self.default_output_format = default_output_format
        self.dataset = DatasetManager(logger=self.logger, debug=debug,
                                     test_cases_config=test_cases_config,
                                     benchmark_root=benchmark_root)
        self.env_checker = MatIECEnvChecker(logger=self.logger, debug=debug)

    def map_intent_to_signal(
        self,
        intent: ExpUnifiedIR,
        cycles: int = 10,
        scan_cycle_ms: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Map intent (ExpUnifiedIR) to signal sequence using Zero-Order Hold.

        Args:
            intent: ExpUnifiedIR containing sparse timeline
            cycles: Total number of cycles to execute
            scan_cycle_ms: Scan cycle duration in milliseconds

        Returns:
            List of signal dictionaries for each cycle
        """
        signal_sequence = []

        for cycle in range(cycles):
            # Apply ZOH: use the same input values for all cycles
            # unless there's a specific update for this cycle in sparse_timeline
            if cycle in intent.sparse_timeline:
                # Use the specific update for this cycle
                signal_sequence.append(intent.sparse_timeline[cycle].copy())
            else:
                # Find the most recent update before this cycle
                last_update = None
                for c in range(cycle, -1, -1):
                    if c in intent.sparse_timeline:
                        last_update = intent.sparse_timeline[c]
                        break

                if last_update:
                    signal_sequence.append(last_update.copy())
                else:
                    # No input defined, use empty signal
                    signal_sequence.append({})

        return signal_sequence

    def apply_zoh(
        self,
        input_signal: Dict[str, Any],
        hold_cycles: int
    ) -> List[Dict[str, Any]]:
        """
        Apply Zero-Order Hold to a single input signal.

        Args:
            input_signal: Single input signal dictionary
            hold_cycles: Number of cycles to hold the signal

        Returns:
            List of identical signal dictionaries for each cycle
        """
        return [input_signal.copy() for _ in range(hold_cycles)]

    def validate_input_schema(
        self,
        input_data: Dict[str, Any],
        schema: Dict[str, Any]
    ) -> bool:
        """
        Validate input data against schema.

        Args:
            input_data: Input data to validate
            schema: Schema definition (from input_schema_v2.json)

        Returns:
            True if input data is valid according to schema
        """
        if not schema or "variables" not in schema:
            self.logger.warning_print("No schema provided, skipping validation")
            return True

        variables = schema["variables"]

        # Check all required variables are present
        for var_name, var_info in variables.items():
            if var_info.get("required", False) and var_name not in input_data:
                self.logger.error_print(f"Required variable missing: {var_name}")
                return False

            # Check type if present in input
            if var_name in input_data:
                expected_type = var_info.get("iec_type", "ANY")
                # Simplified type checking
                # Full implementation would validate against IEC types
                pass

        return True

    def parse_execution_output(
        self,
        execution_result: Dict[str, Any],
        output_format: str = "StoredTestCase"
    ) -> Union[STExecutionResult, ExpUnifiedIR]:
        """
        Parse the PLC execution output into structured format.

        Args:
            execution_result: Raw execution result dictionary
            output_format: Output format ("StoredTestCase" or "ExpUnifiedIR")

        Returns:
            Parsed execution result in specified format
        """
        stdout = execution_result.get("stdout", "")

        if output_format == "ExpUnifiedIR":
            return ExpUnifiedIR(
                exp_id=str(uuid.uuid4()),
                tester_type="MatIEC",
                target_st_path="unknown",
                sparse_timeline={},
                expected_logic={}
            )
        else:
            return STExecutionResult(
                status="success" if execution_result.get("return_code") == 0 else "error",
                return_code=execution_result.get("return_code", -1),
                message=execution_result.get("message", "Execution completed"),
                execution_summary=ExecutionSummary(total_test_cases=1, total_cycles=1),
                test_cases=[],
                raw_stdout=stdout,
                raw_stderr=execution_result.get("stderr", "")
            )

    # ----------------- File handling methods -----------------
    def handle_st_code_input(self, st_code_input, plc_st_code_dir: str) -> None:
        """Handle different types of ST code input (file, directory, or string content)."""
        self.logger.debug_print(f"Processing ST code input: {type(st_code_input).__name__}")

        if isinstance(st_code_input, str):
            if st_code_input.endswith('.st') and os.path.isfile(st_code_input):
                self.logger.debug_print(f"Copying ST file: {st_code_input}")
                shutil.copy2(st_code_input, plc_st_code_dir)
                self.logger.success_print(f"✓ ST file copied: {os.path.basename(st_code_input)}")
            elif os.path.isdir(st_code_input):
                self.logger.debug_print(f"Processing ST directory: {st_code_input}")
                files_copied = 0
                for file in os.listdir(st_code_input):
                    if file.endswith('.st'):
                        src_path = os.path.join(st_code_input, file)
                        shutil.copy2(src_path, plc_st_code_dir)
                        files_copied += 1
                        self.logger.debug_print(f"  Copied: {file}")
                self.logger.success_print(f"✓ {files_copied} ST files copied from directory")
            else:
                self.logger.debug_print("Processing direct ST content")
                with open(os.path.join(plc_st_code_dir, "program.st"), "w") as f:
                    f.write(st_code_input)
                self.logger.success_print("✓ ST content written to program.st")
        else:
            raise ValueError("st_code_input must be a string (file path, directory, or ST content)")

    def handle_harness_input(self, harness_input, plc_c_code_dir: str) -> None:
        """Handle different types of harness input."""
        self.logger.debug_print(f"Processing harness input: {type(harness_input).__name__}")

        if harness_input is None:
            error_msg = "Harness input is required. Please provide harness.c file or content."
            self.logger.error_print(error_msg)
            raise ValueError(error_msg)

        elif isinstance(harness_input, str):
            if harness_input.endswith('.c') and os.path.isfile(harness_input):
                self.logger.debug_print(f"Copying harness file: {harness_input}")
                shutil.copy2(harness_input, os.path.join(plc_c_code_dir, "harness.c"))
                self.logger.success_print(f"✓ Harness file copied: {os.path.basename(harness_input)}")
            elif os.path.isdir(harness_input):
                self.logger.debug_print(f"Processing harness directory: {harness_input}")
                files_copied = 0
                for file in os.listdir(harness_input):
                    if file.endswith(('.c', '.h')):
                        src_file = os.path.join(harness_input, file)
                        shutil.copy2(src_file, plc_c_code_dir)
                        files_copied += 1
                        self.logger.debug_print(f"  Copied: {file}")
                self.logger.success_print(f"✓ {files_copied} harness files copied from directory")
            else:
                self.logger.debug_print("Processing direct harness content")
                with open(os.path.join(plc_c_code_dir, "harness.c"), "w") as f:
                    f.write(harness_input)
                self.logger.success_print("✓ Harness content written to harness.c")

    def handle_input_data(self, input_data, input_dir: str, output_format: str = "StoredTestCase") -> None:
        """Handle different types of input data."""
        self.logger.debug_print(f"Processing input data: {type(input_data).__name__}")

        if input_data is None:
            self.logger.debug_print("Creating default input file")
            default_input = "0 0 0 0 0 0 0 0 0 0"
            with open(os.path.join(input_dir, "input.txt"), "w") as f:
                f.write(default_input)
            self.logger.success_print("✓ Default input file created")
        elif isinstance(input_data, str):
            if os.path.isdir(input_data):
                self.logger.debug_print(f"Processing input directory: {input_data}")
                files_copied = 0
                for file in os.listdir(input_data):
                    if file.endswith('.txt'):
                        src_path = os.path.join(input_data, file)
                        shutil.copy2(src_path, input_dir)
                        files_copied += 1
                        self.logger.debug_print(f"  Copied: {file}")
                self.logger.success_print(f"✓ {files_copied} input files copied from directory")
            elif input_data.endswith('.txt') and os.path.isfile(input_data):
                self.logger.debug_print(f"Copying input file: {input_data}")
                shutil.copy2(input_data, os.path.join(input_dir, "input.txt"))
                self.logger.success_print(f"✓ Input file copied: {os.path.basename(input_data)}")
            else:
                self.logger.debug_print("Processing direct input content")
                with open(os.path.join(input_dir, "input.txt"), "w") as f:
                    f.write(input_data)
                self.logger.success_print("✓ Input content written to input.txt")

    # ----------------- Configuration management (routed) -----------------
    def get_enabled_test_cases(self) -> List[str]:
        """Get list of enabled test cases from configuration."""
        return self.dataset.get_enabled_test_cases()

    def get_benchmark_root(self) -> str:
        """Get current benchmark root directory."""
        return self.dataset.get_benchmark_root()

    def is_test_case_enabled(self, case_name: str) -> bool:
        """Check if a specific test case is enabled."""
        return self.dataset.is_test_case_enabled(case_name)

    def update_test_cases_config(self, new_config: Dict[str, bool]) -> None:
        """Update test cases configuration."""
        self.dataset.update_test_cases_config(new_config)

    def set_benchmark_root(self, new_root: str) -> None:
        """Set new benchmark root directory."""
        self.dataset.set_benchmark_root(new_root)

    def get_test_cases_config(self) -> Dict[str, bool]:
        """Get current test cases configuration."""
        return self.dataset.get_test_cases_config()

    # ----------------- Environment checks (routed) -----------------
    def check_matiec_installation(self) -> Tuple[bool, str]:
        """Check if MatIEC compiler is properly installed."""
        return self.env_checker.check_matiec_installation()

    def check_llvm_tools(self) -> Tuple[bool, str]:
        """Check if LLVM coverage tools are available."""
        return self.env_checker.check_llvm_tools()
