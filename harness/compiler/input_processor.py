"""
PLCHaT ST Input Processor

Handles file operations, input transformations, and execution output parsing.
Supports both StoredTestCase and ExpUnifiedIR input/output formats.

Migrated from: FuzzGen/utils/st_compiler_matiec/st_utils.py
"""

import os
import sys
import subprocess
import shutil
import json
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union

# Add parent directory to path for imports
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from harness.compiler.utils import Logger, LEVEL
from core.data_types.execution_coverage import (
    STExecutionResult,
    ExecutionSummary,
    ExecutionStatus
)
from core.data_types.test_case_types import (
    PLCTestCase,
    PLCCycle,
    PLCVarState,
    PLCParsedTestCaseSummary
)
from core.data_types import StoredTestCase, ExpUnifiedIR
# THIS IS CORRECT NEVER TRY EXCEPT IN IMPOTR AREA!!!

class STInputProcessor:
    """
    ST Input Processing and Utilities Class.

    Handles file operations, input transformations, and execution output parsing.
    Supports both StoredTestCase and ExpUnifiedIR input/output formats.

    Migrated from: FuzzGen/utils/st_compiler_matiec/st_utils.py::STInputProcessor
    """

    def __init__(
        self,
        logger: Optional[Logger] = None,
        debug: bool = False,
        default_output_format: str = "StoredTestCase"
    ):
        """
        Initialize input processor.

        Args:
            logger: Logger instance
            debug: Enable debug logging
            default_output_format: Default output format ("StoredTestCase" or "ExpUnifiedIR")
        """
        self.logger = logger or Logger("/tmp/plchat_input_processor_logs", "st_input_processor.log",
                                       level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug
        self.default_output_format = default_output_format

    def check_matiec_installation(self) -> Tuple[bool, str]:
        """Check if MatIEC compiler is properly installed."""
        try:
            result = subprocess.run(["iec2c", "--help"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return True, shutil.which("iec2c")
            else:
                return False, "MatIEC compiler (iec2c) not found or not working"
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
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
            return True, "All LLVM tools available"

    def handle_st_code_input(self, st_code_input, plc_st_code_dir: str) -> None:
        """Handle different types of ST code input (file, directory, or string content)."""
        self.logger.debug_print(f"Processing ST code input: {type(st_code_input).__name__}")

        if isinstance(st_code_input, str):
            if st_code_input.endswith('.st') and os.path.isfile(st_code_input):
                # Handle single ST file
                self.logger.debug_print(f"Copying ST file: {st_code_input}")
                shutil.copy2(st_code_input, plc_st_code_dir)
                self.logger.info_print(f"ST file copied: {os.path.basename(st_code_input)}")
            elif os.path.isdir(st_code_input):
                # Handle directory of ST files
                self.logger.debug_print(f"Processing ST directory: {st_code_input}")
                files_copied = 0
                for file in os.listdir(st_code_input):
                    if file.endswith('.st'):
                        src_path = os.path.join(st_code_input, file)
                        shutil.copy2(src_path, plc_st_code_dir)
                        files_copied += 1
                        self.logger.debug_print(f"  Copied: {file}")
                self.logger.info_print(f"{files_copied} ST files copied from directory")
            else:
                # Handle direct ST content as string
                self.logger.debug_print("Processing direct ST content")
                with open(os.path.join(plc_st_code_dir, "program.st"), "w") as f:
                    f.write(st_code_input)
                self.logger.info_print("ST content written to program.st")
        else:
            raise ValueError("st_code_input must be a string (file path, directory, or ST content)")

    def handle_harness_input(self, harness_input, plc_c_code_dir: str) -> None:
        """Handle different types of harness input with mandatory requirement."""
        self.logger.debug_print(f"Processing harness input: {type(harness_input).__name__}")

        # Clean target directory
        if os.path.exists(plc_c_code_dir):
            self.logger.debug_print(f"Cleaning target directory: {plc_c_code_dir}")
            for filename in os.listdir(plc_c_code_dir):
                file_path = os.path.join(plc_c_code_dir, filename)
                try:
                    if os.path.isfile(file_path) or os.path.islink(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    self.logger.error_print(f"Failed to delete {file_path}. Reason: {e}")
        else:
            os.makedirs(plc_c_code_dir, exist_ok=True)

        if harness_input is None:
            error_msg = (
                "Harness input is required. Please provide:\n"
                "- Path to harness.c file\n"
                "- Directory containing harness files\n"
                "- Direct C code content as string\n"
                "No default harness will be used."
            )
            self.logger.error_print(error_msg)
            raise ValueError(error_msg)

        elif isinstance(harness_input, str):
            if harness_input.endswith('.c') and os.path.isfile(harness_input):
                # Handle single harness file
                self.logger.debug_print(f"Copying harness file: {harness_input}")
                shutil.copy2(harness_input, os.path.join(plc_c_code_dir, "harness.c"))
                self.logger.info_print(f"Harness file copied: {os.path.basename(harness_input)}")
            elif os.path.isdir(harness_input):
                # Handle directory of harness files
                self.logger.debug_print(f"Processing harness directory: {harness_input}")
                files_copied = 0
                for file in os.listdir(harness_input):
                    if file.endswith(('.c', '.h')):
                        src_file = os.path.join(harness_input, file)
                        shutil.copy2(src_file, plc_c_code_dir)
                        files_copied += 1
                        self.logger.debug_print(f"  Copied: {file}")
                self.logger.info_print(f"{files_copied} harness files copied from directory")
            else:
                # Handle direct C content as string
                self.logger.debug_print("Processing direct harness content")
                with open(os.path.join(plc_c_code_dir, "harness.c"), "w") as f:
                    f.write(harness_input)
                self.logger.info_print("Harness content written to harness.c")

    def handle_input_data(self, input_data, input_dir: str, output_format: str = "StoredTestCase") -> None:
        """
        Handle different types of input data supporting multiple test cases.

        Args:
            input_data: Input data (StoredTestCase, ExpUnifiedIR, or raw data)
            input_dir: Target directory for input files
            output_format: Output format ("StoredTestCase" or "ExpUnifiedIR")
        """
        self.logger.debug_print(f"Processing input data: {type(input_data).__name__}")

        if input_data is None:
            # Create default input file
            self.logger.debug_print("Creating default input file")
            default_input = "0 0 0 0 0 0 0 0 0 0"
            with open(os.path.join(input_dir, "input.txt"), "w") as f:
                f.write(default_input)
            self.logger.info_print("Default input file created")
        elif isinstance(input_data, str):
            if os.path.isdir(input_data):
                # Handle directory of input files
                self.logger.debug_print(f"Processing input directory: {input_data}")
                files_copied = 0
                for file in os.listdir(input_data):
                    if file.endswith('.txt'):
                        src_path = os.path.join(input_data, file)
                        shutil.copy2(src_path, input_dir)
                        files_copied += 1
                        self.logger.debug_print(f"  Copied: {file}")
                self.logger.info_print(f"{files_copied} input files copied from directory")
            elif input_data.endswith('.txt') and os.path.isfile(input_data):
                # Handle single input file
                self.logger.debug_print(f"Copying input file: {input_data}")
                shutil.copy2(input_data, os.path.join(input_dir, "input.txt"))
                self.logger.info_print(f"Input file copied: {os.path.basename(input_data)}")
            else:
                # Handle direct input content as string
                self.logger.debug_print("Processing direct input content")
                with open(os.path.join(input_dir, "input.txt"), "w") as f:
                    f.write(input_data)
                self.logger.info_print("Input content written to input.txt")
        elif isinstance(input_data, StoredTestCase):
            # Convert StoredTestCase to input format
            self.logger.debug_print("Processing StoredTestCase input")
            input_content = self._stored_test_case_to_input_format(input_data)
            with open(os.path.join(input_dir, "input.txt"), "w") as f:
                f.write(input_content)
            self.logger.info_print("Input created from StoredTestCase")
        elif ExpUnifiedIR is not None and isinstance(input_data, ExpUnifiedIR):
            # Convert ExpUnifiedIR to input format
            self.logger.debug_print("Processing ExpUnifiedIR input")
            input_content = input_data.to_harness_input()
            with open(os.path.join(input_dir, "input.txt"), "w") as f:
                f.write(input_content)
            self.logger.info_print("Input created from ExpUnifiedIR")
        else:
            raise ValueError(f"Unsupported input data type: {type(input_data).__name__}")

    def _stored_test_case_to_input_format(self, stored_test_case: StoredTestCase) -> str:
        """Convert StoredTestCase to input format readable by harness."""
        if not stored_test_case.io_pairs:
            return ""

        # Get input order from first io pair
        input_order = list(stored_test_case.io_pairs[0].inputs.keys())
        lines = []

        for pair in stored_test_case.io_pairs:
            vals = []
            for k in input_order:
                v = pair.inputs.get(k, 0)
                if isinstance(v, list):
                    vals.append(" ".join(str(x) for x in v))
                else:
                    vals.append(str(int(v)) if isinstance(v, bool) else str(v))
            lines.append(" ".join(vals))

        return "\n".join(lines)

    def handle_include_files(self, include_files, includes_dir: str) -> None:
        """Handle include files with default placeholder creation."""
        self.logger.debug_print(f"Processing include files: {type(include_files).__name__}")
        os.makedirs(includes_dir, exist_ok=True)

        # Create default include file
        with open(os.path.join(includes_dir, "include.txt"), "w") as f:
            f.write("# No additional includes needed\n")

        if include_files and isinstance(include_files, list):
            files_copied = 0
            self.logger.debug_print(f"Processing {len(include_files)} include files")
            for include_file in include_files:
                if os.path.isfile(include_file):
                    shutil.copy2(include_file, includes_dir)
                    files_copied += 1
                    self.logger.debug_print(f"  Copied: {os.path.basename(include_file)}")
            self.logger.info_print(f"{files_copied} include files copied")

        # Ensure directory is not empty
        if not os.listdir(includes_dir):
            with open(os.path.join(includes_dir, ".gitkeep"), "w") as f:
                f.write("")

    def handle_initial_state(self, initial_state, state_dir: str) -> None:
        """Handle initial state configuration for incremental simulation."""
        os.makedirs(state_dir, exist_ok=True)
        self.logger.debug_print(f"Handling initial state input: {type(initial_state).__name__}")

        if initial_state is None:
            # Create default empty initial state file
            default_state = {
                "VAR_OUTPUT": {},
                "VAR_INTERNAL": {},
                "metadata": {
                    "description": "Default empty initial state",
                    "created_by": "STInputProcessor",
                    "round": 0
                }
            }
            with open(os.path.join(state_dir, "initial_state.json"), "w") as f:
                json.dump(default_state, f, indent=2)
            self.logger.info_print("Created default initial state JSON file")
        elif isinstance(initial_state, str):
            if initial_state.endswith('.json') and os.path.isfile(initial_state):
                # Copy existing JSON file
                dest_path = os.path.join(state_dir, "initial_state.json")
                shutil.copy2(initial_state, dest_path)
                self.logger.info_print(f"Copied JSON file: {os.path.basename(initial_state)}")
        elif isinstance(initial_state, dict):
            # Handle dictionary initial state
            with open(os.path.join(state_dir, "initial_state.json"), "w") as f:
                json.dump(initial_state, f, indent=2)
            self.logger.info_print("Created initial state from dictionary")

    def parse_execution_output(
        self,
        execution_result: Dict[str, Any],
        output_format: str = "StoredTestCase"
    ) -> Union[STExecutionResult, Any]:
        """
        Parse the PLC execution output into structured format.

        Args:
            execution_result: Raw execution result dictionary
            output_format: Output format ("StoredTestCase" or "ExpUnifiedIR")

        Returns:
            Parsed execution result in specified format
        """
        # Default to StoredTestCase format for compatibility
        if output_format not in ["StoredTestCase", "ExpUnifiedIR"]:
            output_format = "StoredTestCase"

        stdout = execution_result.get("stdout", "")
        if not stdout or stdout.strip() == "":
            if output_format == "ExpUnifiedIR" and ExpUnifiedIR is not None:
                return ExpUnifiedIR(
                    exp_id=str(uuid.uuid4()),
                    tester_type="MatIEC",
                    target_st_path="unknown",
                    sparse_timeline={},
                    expected_logic={}
                )
            else:
                return STExecutionResult(
                    status="error",
                    return_code=execution_result.get("return_code", -1),
                    message="No execution output received",
                    execution_summary=ExecutionSummary(total_test_cases=0, total_cycles=0),
                    test_cases=[],
                    raw_stdout=execution_result.get("stdout", ""),
                    raw_stderr=execution_result.get("stderr", "")
                )

        # First try to parse as structured data (original format)
        try:
            parsed_result = self._parse_as_structured_data(execution_result, stdout)
            # If structured parsing yielded no test cases, try simple format
            if not parsed_result.test_cases and "--- Cycle " in stdout:
                self.logger.debug_print("No test cases from structured parser, trying simple format")
                parsed_result = self._parse_as_simple_output(execution_result, output_format)

            if output_format == "ExpUnifiedIR" and ExpUnifiedIR is not None:
                return self._convert_to_exp_unified_ir(parsed_result)
            return parsed_result
        except Exception as e:
            self.logger.warning_print(f"Failed to parse as structured data: {e}")
            # Fallback to simple parsing
            return self._parse_as_simple_output(execution_result, output_format)

    def _parse_as_structured_data(
        self,
        execution_result: Dict[str, Any],
        stdout: str
    ) -> STExecutionResult:
        """Parse output using the original structured format from st_compiler_rusty."""
        lines = stdout.split('\n')
        test_cases = []
        current_test_case = None
        current_cycle = None
        current_state = None
        current_var_section = None

        # Track execution matrix information
        input_count = 0
        state_count = 0
        expected_executions = 0
        actual_executions = 0

        for line_num, line in enumerate(lines):
            line = line.strip()

            # Parse execution matrix information
            if "Input files count:" in line:
                try:
                    input_count = int(line.split(":")[1].strip())
                except:
                    pass
            elif "State files count:" in line:
                try:
                    state_count = int(line.split(":")[1].strip())
                except:
                    pass
            elif "Expected total executions:" in line:
                try:
                    expected_executions = int(line.split(":")[1].strip())
                except:
                    pass
            elif "Total executions performed:" in line:
                try:
                    actual_executions = int(line.split(":")[1].strip())
                except:
                    pass
            elif "Executing Test Case:" in line:
                # Finish previous test case
                if current_cycle and current_test_case:
                    current_test_case["cycles"].append(current_cycle)
                if current_test_case:
                    if not current_test_case.get("summary"):
                        if current_test_case["cycles"]:
                            final_cycle = current_test_case["cycles"][-1]
                            final_state = final_cycle.get("after_execution", {})
                        else:
                            final_state = {}
                        current_test_case["summary"] = {
                            "total_cycles": len(current_test_case["cycles"]),
                            "final_state": final_state
                        }
                    test_cases.append(current_test_case)

                # Start new test case
                parts = line.split(":", 1)
                if len(parts) >= 2:
                    test_info = parts[1].strip()
                    current_test_case = {
                        "test_case_name": test_info,
                        "cycles": [],
                        "summary": {}
                    }
                    current_cycle = None

            elif "========== PLC Cycle" in line:
                # Finish previous cycle
                if current_cycle and current_test_case:
                    current_test_case["cycles"].append(current_cycle)

                # Start new cycle
                try:
                    cycle_num = int(''.join(filter(str.isdigit, line)))
                    current_cycle = {
                        "cycle": cycle_num,
                        "before_execution": {
                            "VAR_INPUT": {},
                            "VAR_OUTPUT": {},
                            "VAR_INTERNAL": {}
                        },
                        "after_execution": {
                            "VAR_INPUT": {},
                            "VAR_OUTPUT": {},
                            "VAR_INTERNAL": {}
                        }
                    }
                    current_state = None
                    current_var_section = None
                except Exception as e:
                    self.logger.debug_print(f"Error parsing cycle number: {e}")

            elif "--- State Before Execution ---" in line:
                current_state = "before_execution"
                current_var_section = None

            elif "--- State After Execution ---" in line:
                current_state = "after_execution"
                current_var_section = None

            elif current_cycle and current_state:
                if "VAR_INPUT:" in line:
                    current_var_section = "VAR_INPUT"
                elif "VAR_OUTPUT:" in line:
                    current_var_section = "VAR_OUTPUT"
                elif "VAR_INTERNAL:" in line:
                    current_var_section = "VAR_INTERNAL"
                elif current_var_section and "=" in line:
                    try:
                        var_name, value_str = [part.strip() for part in line.split("=", 1)]

                        # Handle array values
                        if "[" in value_str or "," in value_str:
                            # Extract numbers from array notation
                            values = [int(x.strip()) for x in value_str.replace("[", "").replace("]", "").split(",") if x.strip()]
                            value = values
                        else:
                            try:
                                value = int(value_str)
                            except ValueError:
                                value = value_str

                        if current_var_section and current_state:
                            current_cycle[current_state][current_var_section][var_name] = value
                    except Exception as e:
                        self.logger.debug_print(f"Error parsing variable line: {e}")

            elif "--- PLC Simulation Completed" in line:
                # Finish current cycle and test case
                if current_cycle and current_test_case:
                    current_test_case["cycles"].append(current_cycle)
                current_cycle = None

        # Final cleanup
        if current_cycle and current_test_case:
            current_test_case["cycles"].append(current_cycle)
        if current_test_case:
            if not current_test_case.get("summary"):
                if current_test_case["cycles"]:
                    final_cycle = current_test_case["cycles"][-1]
                    final_state = final_cycle.get("after_execution", {})
                else:
                    final_state = {}
                current_test_case["summary"] = {
                    "total_cycles": len(current_test_case["cycles"]),
                    "final_state": final_state
                }
            test_cases.append(current_test_case)

        # Use actual execution count if available, otherwise count test cases
        total_test_cases = actual_executions if actual_executions > 0 else len(test_cases)
        total_cycles = sum(len(tc['cycles']) for tc in test_cases) if test_cases else 0

        # Convert to structured dataclasses
        structured_test_cases = []
        for tc in test_cases:
            cycles = []
            for c in tc['cycles']:
                before_state = PLCVarState(
                    VAR_INPUT=c['before_execution']['VAR_INPUT'],
                    VAR_OUTPUT=c['before_execution']['VAR_OUTPUT'],
                    VAR_INTERNAL=c['before_execution']['VAR_INTERNAL']
                )
                after_state = PLCVarState(
                    VAR_INPUT=c['after_execution']['VAR_INPUT'],
                    VAR_OUTPUT=c['after_execution']['VAR_OUTPUT'],
                    VAR_INTERNAL=c['after_execution']['VAR_INTERNAL']
                )
                cycle = PLCCycle(
                    cycle=c['cycle'],
                    before_execution=before_state,
                    after_execution=after_state
                )
                cycles.append(cycle)

            final_state = tc['summary']['final_state'] if tc.get('summary') else {}
            summary = PLCParsedTestCaseSummary(
                total_cycles=tc['summary']['total_cycles'] if tc.get('summary') else len(cycles),
                final_state=PLCVarState(
                    VAR_INPUT=final_state.get('VAR_INPUT', {}),
                    VAR_OUTPUT=final_state.get('VAR_OUTPUT', {}),
                    VAR_INTERNAL=final_state.get('VAR_INTERNAL', {})
                )
            )

            structured_tc = PLCTestCase(
                test_case_name=tc['test_case_name'],
                cycles=cycles,
                summary=summary
            )
            structured_test_cases.append(structured_tc)

        execution_status = "success" if total_test_cases > 0 else "error"
        return_code = execution_result.get("return_code", 0)

        return STExecutionResult(
            status=execution_status,
            return_code=return_code,
            message=f"Execution completed with {total_test_cases} test cases and {total_cycles} cycles",
            execution_summary=ExecutionSummary(
                total_test_cases=total_test_cases,
                total_cycles=total_cycles,
                expected_executions=expected_executions,
                input_count=input_count,
                state_count=state_count
            ),
            test_cases=structured_test_cases,
            raw_stdout=stdout,
            raw_stderr=execution_result.get("stderr", "")
        )

    def _parse_as_simple_output(
        self,
        execution_result: Dict[str, Any],
        output_format: str
    ) -> Union[STExecutionResult, Any]:
        """Parse simple output format (--- Cycle X ---)."""
        stdout = execution_result.get("stdout", "")
        return_code = execution_result.get("return_code", 0)

        # Try to parse simple cycle format
        cycles = []
        cycle_num = 0
        var_input = {}
        var_output = {}
        var_internal = {}
        has_data = False
        in_inputs_section = False
        in_outputs_section = False
        in_internal_section = False

        for line in stdout.split('\n'):
            line = line.strip()

            if line.startswith("--- Cycle ") and " ---" in line:
                # Save previous cycle
                if has_data:
                    cycles.append(PLCCycle(
                        cycle=cycle_num,
                        before_execution=PLCVarState(
                            VAR_INPUT=dict(var_input),
                            VAR_OUTPUT={},
                            VAR_INTERNAL={}
                        ),
                        after_execution=PLCVarState(
                            VAR_INPUT=dict(var_input),
                            VAR_OUTPUT=dict(var_output),
                            VAR_INTERNAL=dict(var_internal)
                        )
                    ))

                # Start new cycle
                try:
                    cycle_num = int(line.replace("--- Cycle ", "").replace(" ---", ""))
                except:
                    cycle_num += 1

                var_input = {}
                var_output = {}
                var_internal = {}
                has_data = False
                in_inputs_section = False
                in_outputs_section = False
                in_internal_section = False

            elif line.startswith("INPUTS:") or line.startswith("Inputs:"):
                has_data = True
                in_inputs_section = True
                in_outputs_section = False
                in_internal_section = False
                # Handle single-line format: INPUTS: VAR=val, VAR=val
                inputs_part = line.replace("INPUTS:", "").replace("Inputs:", "").strip()
                if '=' in inputs_part:
                    for item in inputs_part.split(','):
                        item = item.strip()
                        if '=' in item:
                            name, value = item.split('=', 1)
                            var_input[name.strip()] = value.strip()

            elif line.startswith("OUTPUTS:") or line.startswith("Outputs:"):
                has_data = True
                in_outputs_section = True
                in_inputs_section = False
                in_internal_section = False
                # Handle single-line format: OUTPUTS: VAR=val, VAR=val
                outputs_part = line.replace("OUTPUTS:", "").replace("Outputs:", "").strip()
                if '=' in outputs_part:
                    for item in outputs_part.split(','):
                        item = item.strip()
                        if '=' in item:
                            name, value = item.split('=', 1)
                            var_output[name.strip()] = value.strip()

            elif line.startswith("INTERNAL:") or line.startswith("Internal:"):
                has_data = True
                in_internal_section = True
                in_inputs_section = False
                in_outputs_section = False
                internal_part = line.replace("INTERNAL:", "").replace("Internal:", "").strip()
                if '=' in internal_part:
                    import re
                    internal_part = re.sub(r'(\w+)\s*=\s*\[(.*?)\]', lambda m: f"{m.group(1)}=<array>", internal_part)
                    for item in internal_part.split(','):
                        item = item.strip()
                        if '=' in item:
                            name, value = item.split('=', 1)
                            var_internal[name.strip()] = value.strip()

            # Handle multi-line format (e.g., MultiPumpCtrl)
            # Format: "  VAR: value" where VAR is indented under Inputs/Outputs section
            elif line and not line.startswith("---") and ':' in line:
                parts = line.split(':', 1)
                if len(parts) == 2:
                    name = parts[0].strip()
                    value_str = parts[1].strip()

                    # Skip array continuation lines
                    if name in ['PRIORITIES', 'SELECTIONS', 'RUNCOMDS'] and not value_str:
                        continue

                    # Determine which section this belongs to
                    if in_inputs_section:
                        var_input[name] = value_str
                        has_data = True
                    elif in_outputs_section:
                        var_output[name] = value_str
                        has_data = True
                    elif in_internal_section:
                        var_internal[name] = value_str
                        has_data = True

            # Check for section headers (without colon at end)
            elif line.strip() == "Inputs":
                in_inputs_section = True
                in_outputs_section = False
                in_internal_section = False
            elif line.strip() == "Outputs":
                in_outputs_section = True
                in_inputs_section = False
                in_internal_section = False
            elif line.strip() == "Internal State":
                in_internal_section = True
                in_inputs_section = False
                in_outputs_section = False

        # Save last cycle
        if has_data:
            cycles.append(PLCCycle(
                cycle=cycle_num,
                before_execution=PLCVarState(
                    VAR_INPUT=dict(var_input),
                    VAR_OUTPUT={},
                    VAR_INTERNAL={}
                ),
                after_execution=PLCVarState(
                    VAR_INPUT=dict(var_input),
                    VAR_OUTPUT=dict(var_output),
                    VAR_INTERNAL=dict(var_internal)
                )
            ))

        # Determine status - successful if return code is 0 or we parsed cycles
        status = "success" if return_code == 0 or cycles else "error"

        if output_format == "ExpUnifiedIR" and ExpUnifiedIR is not None:
            return ExpUnifiedIR(
                exp_id=str(uuid.uuid4()),
                tester_type="MatIEC_simple",
                target_st_path="unknown",
                sparse_timeline={},
                expected_logic={}
            )
        else:
            # Create test case with all cycles
            structured_test_cases = []
            if cycles:
                structured_tc = PLCTestCase(
                    test_case_name="simple_execution",
                    cycles=cycles,
                    summary=PLCParsedTestCaseSummary(
                        total_cycles=len(cycles),
                        final_state=cycles[-1].after_execution if cycles else PLCVarState()
                    )
                )
                structured_test_cases.append(structured_tc)

            return STExecutionResult(
                status=status,
                return_code=return_code,
                message=f"Execution completed with {len(structured_test_cases)} test cases and {sum(len(tc.cycles) for tc in structured_test_cases)} cycles",
                execution_summary=ExecutionSummary(
                    total_test_cases=len(structured_test_cases),
                    total_cycles=sum(len(tc.cycles) for tc in structured_test_cases)
                ),
                test_cases=structured_test_cases,
                raw_stdout=stdout,
                raw_stderr=execution_result.get("stderr", "")
            )

    def _convert_to_exp_unified_ir(self, result: STExecutionResult) -> Any:
        """Convert STExecutionResult to ExpUnifiedIR format."""
        if ExpUnifiedIR is None:
            return None

        # Simplified conversion for demonstration
        sparse_timeline = {}
        expected_logic = {}

        if result.test_cases:
            for tc in result.test_cases:
                for cycle in tc.cycles:
                    cycle_idx = cycle.cycle - 1  # 0-based index
                    if cycle_idx not in sparse_timeline:
                        sparse_timeline[cycle_idx] = {}

                    # Extract inputs from before state
                    inputs = {}
                    for var_name, value in cycle.before_execution.VAR_INPUT.items():
                        inputs[var_name] = value
                    sparse_timeline[cycle_idx].update(inputs)

                    # Extract expected outputs from after state
                    if cycle_idx not in expected_logic:
                        expected_logic[cycle_idx] = {}

                    outputs = {}
                    for var_name, value in cycle.after_execution.VAR_OUTPUT.items():
                        outputs[var_name] = value
                    expected_logic[cycle_idx].update(outputs)

        return ExpUnifiedIR(
            exp_id=str(uuid.uuid4()),
            tester_type="MatIEC",
            target_st_path="unknown",
            scan_cycle_ms=10,
            total_cycles=max(sparse_timeline.keys(), default=0) + 1,
            sparse_timeline=sparse_timeline,
            expected_logic=expected_logic
        )
