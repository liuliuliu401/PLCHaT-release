"""
PLCHaT ST Executor

ST code compilation and binary execution engine.

This module handles:
- ST to C compilation via MatIEC
- C to binary compilation via clang
- Binary execution with input handling
"""

import sys
from pathlib import Path
from typing import Optional, List, Dict, Any, Union, Tuple
import subprocess
import os
import shutil

from harness.compiler.utils import Logger, LEVEL
from core.data_types import STExecutionResult, ExpUnifiedIR


class STExecutor:
    """
    Direct executor for compiled ST code using MatIEC compiler chain.

    Handles compilation from ST to C to binary, and execution of the resulting binary.
    """

    def __init__(
        self,
        root_dir: Optional[str] = None,
        logger: Optional[Logger] = None,
        debug: bool = False,
        default_output_format: str = "StoredTestCase"
    ):
        """Initialize ST executor."""
        self.root_dir = root_dir or str(Path(__file__).resolve().parent.parent.parent)
        self.execution_dir = os.path.join(self.root_dir, "execution")
        self.logger = logger or Logger("/tmp/st_executor_logs", "st_executor.log",
                                      level=LEVEL.DEBUG if debug else LEVEL.INFO)
        self.debug = debug
        self.default_output_format = default_output_format

    def compile_st_to_c(
        self,
        st_code_path: str,
        output_dir: str,
        harness_path: str,
        include_files: Optional[List[str]] = None,
        benchmark_case: Optional[str] = None
    ) -> bool:
        """Compile ST code to C using MatIEC compiler."""
        self.logger.info_print(f"Compiling ST code to C: {st_code_path}")

        # Check MatIEC installation
        ok, msg = self.check_matiec_installation()
        if not ok:
            self.logger.error_print(f"MatIEC compiler not available: {msg}")
            return False

        os.makedirs(output_dir, exist_ok=True)

        # Find MatIEC path
        iec2c_bin = shutil.which("iec2c")
        if not iec2c_bin:
            self.logger.error_print("iec2c not found in PATH")
            return False

        matiec_path = str(Path(iec2c_bin).parent)

        try:
            original_pwd = os.getcwd()
            os.chdir(matiec_path)
            os.makedirs(output_dir, exist_ok=True)

            # Clean ST file
            cleaned_st_filename = os.path.basename(st_code_path).replace('.st', '.cleaned.st')
            compilation_target_path = os.path.join(output_dir, cleaned_st_filename)

            cmd_clean = f"perl -0777 -pe 's/\\(\\*.*?\\*\\)//gs' {st_code_path} | sed 's/\\/\\/.*//g' > {compilation_target_path}"
            try:
                subprocess.run(cmd_clean, shell=True, check=True)
            except subprocess.CalledProcessError:
                return False

            # Fix ST syntax issues for MatIEC compatibility
            try:
                with open(compilation_target_path, 'r') as f:
                    content = f.read()
                import re
                original_content = content

                # Fix 1: Named parameter syntax: func(PARAM1:=value, PARAM2:=value) -> func(value, value)
                def fix_named_params(match):
                    func_name = match.group(1)
                    params = match.group(2)
                    # Extract values from PARAM:=value pairs
                    values = re.findall(r'\w+:=([^,)\s]+)', params)
                    return f"{func_name}({', '.join(values)})"

                content = re.sub(r'(\w+)\s*\(([^)]*(?:\w+:=[^,)]+)[^)]*)\)', fix_named_params, content)

                # Fix 2: Single-line IF statements -> Multi-line format
                # IF condition THEN statement; END_IF; -> IF condition THEN\n    statement;\nEND_IF;
                def fix_single_line_if(match):
                    indent = match.group(1)
                    condition = match.group(2)
                    statement = match.group(3)
                    return f"{indent}IF {condition} THEN\n{indent}    {statement}\n{indent}END_IF;"

                # Pattern for: IF ... THEN ... END_IF;
                content = re.sub(r'(\s*)IF\s+(.+?)\s+THEN\s+(.+?)\s+END_IF;', fix_single_line_if, content)

                # Fix 3: Reorder declarations for MatIEC compatibility
                # MatIEC requires proper order: TYPE -> FUNCTION -> FUNCTION_BLOCK
                lines = content.split('\n')
                type_blocks = []
                function_blocks = []
                functions = []
                other_lines = []
                current_block = []
                in_type = False
                in_function = False
                in_function_block = False

                for line in lines:
                    # Check for TYPE start (TYPE ... :)
                    if re.match(r'^\s*TYPE\s+\w+\s*:', line):
                        # Save any pending block
                        if current_block:
                            if in_function_block:
                                function_blocks.append(current_block)
                            elif in_function:
                                functions.append(current_block)
                            else:
                                other_lines.extend(current_block)
                        current_block = [line]
                        in_type = True
                        in_function = False
                        in_function_block = False
                    # Check for FUNCTION start
                    elif re.match(r'^\s*FUNCTION\s+', line):
                        # Save any pending block
                        if current_block:
                            if in_type:
                                type_blocks.append(current_block)
                            elif in_function_block:
                                function_blocks.append(current_block)
                            else:
                                other_lines.extend(current_block)
                        current_block = [line]
                        in_function = True
                        in_type = False
                        in_function_block = False
                    # Check for FUNCTION_BLOCK start
                    elif re.match(r'^\s*FUNCTION_BLOCK\s+', line):
                        # Save any pending block
                        if current_block:
                            if in_type:
                                type_blocks.append(current_block)
                            elif in_function:
                                functions.append(current_block)
                            else:
                                other_lines.extend(current_block)
                        current_block = [line]
                        in_function_block = True
                        in_type = False
                        in_function = False
                    # Check for TYPE end (END_TYPE)
                    elif re.match(r'^\s*END_TYPE\b\s*;?', line):
                        current_block.append(line)
                        type_blocks.append(current_block)
                        current_block = []
                        in_type = False
                    # Check for FUNCTION end (END_FUNCTION) - must be exact match, not END_FUNCTION_BLOCK
                    elif re.match(r'^\s*END_FUNCTION\b\s*;?', line) and not re.search(r'FUNCTION_BLOCK', line):
                        current_block.append(line)
                        functions.append(current_block)
                        current_block = []
                        in_function = False
                    # Check for FUNCTION_BLOCK end (END_FUNCTION_BLOCK)
                    elif re.match(r'^\s*END_FUNCTION_BLOCK\s*;?', line):
                        current_block.append(line)
                        function_blocks.append(current_block)
                        current_block = []
                        in_function_block = False
                    else:
                        current_block.append(line)

                # Handle last block
                if current_block:
                    if in_type:
                        type_blocks.append(current_block)
                    elif in_function:
                        functions.append(current_block)
                    elif in_function_block:
                        function_blocks.append(current_block)
                    else:
                        other_lines.extend(current_block)

                # Reorder: TYPEs first, then FUNCTIONs, then FUNCTION_BLOCKs, then others
                reordered = []
                for type_block in type_blocks:
                    reordered.extend(type_block)
                for func in functions:
                    reordered.extend(func)
                for fb in function_blocks:
                    reordered.extend(fb)
                reordered.extend(other_lines)

                content = '\n'.join(reordered)

                if content != original_content:
                    self.logger.info_print(f"Applied ST syntax fixes")
                    with open(compilation_target_path, 'w') as f:
                        f.write(content)
            except Exception as e:
                self.logger.warning_print(f"Failed to fix ST syntax: {e}")

            cmd = ["./iec2c", "-T", output_dir, compilation_target_path]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                self.logger.error_print(f"ST compilation failed: {result.stderr}")
                return False

            os.chdir(original_pwd)
            self._apply_header_patches(output_dir)
            from harness.compiler.utils import patch_pous_setvar_time_to_dint
            patch_pous_setvar_time_to_dint(output_dir)

        finally:
            pass

        # Copy harness file
        harness_dest = os.path.join(output_dir, "harness.c")
        shutil.copy2(harness_path, harness_dest)
        self.logger.info_print(f"Copied harness file to: {harness_dest}")

        return True

    def _apply_header_patches(self, output_dir: str) -> None:
        """Apply essential header patches to generated C files."""
        patch_headers = """#include "iec_types.h"
#include "iec_types_all.h"
#include "iec_std_lib.h"
#include "iec_std_FB.h"
#include "accessor.h"
"""

        for root, _, files in os.walk(output_dir):
            for file in files:
                if file.endswith('.c') and file != 'harness.c':
                    c_file_path = os.path.join(root, file)
                    h_file_path = os.path.join(root, file.replace('.c', '.h'))

                    with open(c_file_path, 'r') as f:
                        content = f.read()
                        if '#include "iec_std_lib.h"' in content:
                            continue

                    patched_content = patch_headers + "\n"
                    if os.path.exists(h_file_path):
                        header_name = os.path.basename(h_file_path)
                        patched_content += f'#include "{header_name}"\n\n'
                    patched_content += content

                    with open(c_file_path, 'w') as f:
                        f.write(patched_content)

    def compile_c_to_binary(
        self,
        source_files: List[str],
        output_binary: str,
        include_dirs: List[str],
        libraries: List[str],
        coverage_mode: bool = False,
        benchmark_case: Optional[str] = None
    ) -> bool:
        """Compile C files to executable binary using clang."""
        self.logger.info_print(f"Compiling C files to binary: {output_binary}")

        cmd = ["clang-18", "-g"]
        if coverage_mode:
            cmd.extend(["-fprofile-instr-generate", "-fcoverage-mapping"])

        for include_dir in include_dirs:
            cmd.extend(["-I", include_dir])

        cmd.extend(source_files)
        cmd.extend(libraries)
        cmd.extend(["-lm", "-lz", "-lrt", "-lpthread", "-w"])
        cmd.extend(["-o", output_binary])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            self.logger.error_print(f"C compilation failed: {result.stderr}")
            return False

        self.logger.info_print(f"Successfully created executable: {output_binary}")
        return True

    def execute_binary(
        self,
        binary_path: str,
        input_data: Optional[str] = None,
        input_file: Optional[str] = None,
        timeout: int = 300,
        benchmark_case: Optional[str] = None,
        output_format: str = "StoredTestCase"
    ) -> Dict[str, Any]:
        """Execute compiled binary with optional input data."""
        self.logger.info_print(f"Executing binary: {binary_path}")

        if not os.path.exists(binary_path):
            return {
                "status": "error",
                "return_code": -1,
                "stdout": "",
                "stderr": f"Executable not found: {binary_path}",
                "message": "Executable not found"
            }

        cmd = [binary_path]

        try:
            # Resource-guarded run: target binaries can infinite-loop at ~100% CPU and
            # orphan (PPID=1) if this process is hard-killed mid-run. proc_guard arms
            # PR_SET_PDEATHSIG + group-kills on timeout + reaps by binary path.
            from harness.compiler.proc_guard import run_target_binary
            res = run_target_binary(
                cmd,
                timeout=timeout,
                stdin_path=input_file if (input_file and os.path.exists(input_file)) else None,
                input_text=input_data if (not input_file or not os.path.exists(input_file)) else None,
                binary_path=binary_path,
            )

            if res["timed_out"]:
                return {
                    "status": "timeout",
                    "return_code": -1,
                    "stdout": "",
                    "stderr": f"Execution timed out after {timeout} seconds",
                    "message": "Execution timed out"
                }

            return {
                "status": "success" if res["returncode"] == 0 else "error",
                "return_code": res["returncode"],
                "stdout": res["stdout"],
                "stderr": res["stderr"],
                "message": f"Execution completed with return code {res['returncode']}"
            }

        except Exception as e:
            return {
                "status": "error",
                "return_code": -1,
                "stdout": "",
                "stderr": str(e),
                "message": f"Execution failed: {str(e)}"
            }

    def check_matiec_installation(self) -> Tuple[bool, str]:
        """Check if MatIEC compiler is properly installed."""
        try:
            result = subprocess.run(["iec2c", "--help"], capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return True, shutil.which("iec2c")
            else:
                return False, "MatIEC compiler not working"
        except Exception as e:
            return False, f"MatIEC compiler not available: {str(e)}"
