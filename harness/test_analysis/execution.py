"""
Execution and coverage collection tool

Integrate STExecutor and STCoverageCollector to provide actual execution and coverage collection functionality.
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import logging
import time
import shutil

# Project root: execution.py → test_analysis → harness → PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
import sys
sys.path.insert(0, str(PROJECT_ROOT))

# Global relative position reference
from harness.compiler.executor import STExecutor
from harness.compiler.st_coverage_collector import STCoverageCollector
from harness.compiler.utils import Logger, LEVEL

# Use existing data contract
from core.data_types.execution_coverage import (
    STExecutionResult,
    CoverageRunResult,
    ExecutionStatus
)
from core.data_types.test_analysis_types import TestCaseReport


logger = logging.getLogger(__name__)


def execute_with_assertions(
    st_path: Path,
    harness_path: Path,
    test_input: Optional[str] = None
) -> STExecutionResult:
    """
Execute patched harness and capture assertion failures.

    Args:
st_path: ST source code path
harness_path: Path of the patched harness.c
test_input: Test input data

    Returns:
STExecutionResult: execution result
    """
    func_logger = Logger("/tmp/plchat_test_analysis", "exec_assertions.log", level=LEVEL.INFO)

    func_logger.info_print("=" * 60)
    func_logger.info_print("Executing Patched Harness (MATIEC)")
    func_logger.info_print("=" * 60)

    try:
        # Initialize executor
        executor = STExecutor(
            root_dir=str(PROJECT_ROOT),
            logger=func_logger,
            debug=False
        )

        # Check MATIEC
        ok, msg = executor.check_matiec_installation()
        func_logger.info_print(f"MATIEC: {'✓' if ok else '✗'} - {msg}")

        if not ok:
            return STExecutionResult(
                status="error",
                return_code=-1,
                message="MATIEC not available",
                raw_stderr=msg
            )

        # Create temporary directory
        import tempfile
        with tempfile.TemporaryDirectory(prefix="plchat_exec_") as exec_dir:
            # Step 1: Compile ST to C
            func_logger.info_print("Step 1: ST -> C Compilation")
            st_ok = executor.compile_st_to_c(
                st_code_path=str(st_path),
                output_dir=exec_dir,
                harness_path=str(harness_path)
            )

            if not st_ok:
                return STExecutionResult(
                    status="compilation_failed",
                    return_code=1,
                    message="ST to C compilation failed",
                    raw_stderr="Compilation failed"
                )

            func_logger.info_print("OK - ST compilation successful")

            # Step 2: Compile C to binary
            func_logger.info_print("Step 2: C -> Binary Compilation")

            c_files = list(Path(exec_dir).glob("*.c"))
            binary_path = str(Path(exec_dir) / "plc_harness_test")

            # Find include directory
            # Correct path: iec2c is located in the matiec root directory, header files in lib/C
            matiec_bin = shutil.which("iec2c")
            matiec_lib = str(Path(matiec_bin).parent / "lib" / "C") if matiec_bin else "/usr/local/lib/matiec"

            c_ok = executor.compile_c_to_binary(
                source_files=[str(f) for f in c_files],
                output_binary=binary_path,
                include_dirs=[matiec_lib, exec_dir],
                libraries=[],
                coverage_mode=False
            )

            if not c_ok:
                return STExecutionResult(
                    status="build_failed",
                    return_code=1,
                    message="C to binary compilation failed",
                    raw_stderr="Build failed"
                )

            func_logger.info_print(f"OK - Binary: {binary_path}")

            # Step 3: Execute
            func_logger.info_print("Step 3: Execute Binary")

            input_data = test_input or "80\n"
            exec_dict = executor.execute_binary(
                binary_path=binary_path,
                input_data=input_data,
                timeout=5
            )

            func_logger.info_print(f"Exit Code: {exec_dict['return_code']}")
            func_logger.info_print(f"Status: {exec_dict['status']}")

            # Parse assertion failed
            assertion_failures = []
            stderr = exec_dict.get('stderr', '')

            for line in stderr.split('\n'):
                if 'SECURITY ASSERT' in line or 'AUDIT FAIL' in line:
                    assertion_failures.append(line.strip())
                    func_logger.info_print(f"Assertion Failed: {line.strip()}")

            return STExecutionResult(
                status=exec_dict['status'],
                return_code=exec_dict['return_code'],
                message=exec_dict.get('message', ''),
                raw_stdout=exec_dict.get('stdout', ''),
                raw_stderr=stderr
            )

    except Exception as e:
        func_logger.error_print(f"Execution Exception: {e}")
        return STExecutionResult(
            status="error",
            return_code=-1,
            message=f"Execution exception: {str(e)}",
            raw_stderr=str(e)
        )


def collect_coverage_with_assertions(
    st_path: Path,
    harness_path: Path,
    test_inputs: List[str]
) -> CoverageRunResult:
    """
Collect coverage data.

    Args:
st_path: ST source code path
harness_path: The path of harness.c after patching
test_inputs: test input list

    Returns:
CoverageRunResult: coverage result
    """
    func_logger = Logger("/tmp/plchat_coverage_analysis", "coverage.log", level=LEVEL.INFO)

    func_logger.info_print("=" * 60)
    func_logger.info_print("Coverage Collection (LLVM)")
    func_logger.info_print("=" * 60)

    try:
        collector = STCoverageCollector(
            root_dir=str(PROJECT_ROOT),
            max_executions=len(test_inputs),
            force_rebuild=False,
            logger=func_logger,
            debug=False,
            llvm_version=18
        )

        func_logger.info_print(f"Test Inputs: {len(test_inputs)} items")

        # Prepare input
        input_data = "\n".join(test_inputs) if test_inputs else "80\n"

        # Perform coverage collection
        result = collector.execute_with_coverage(
            st_code_input=str(st_path),
            harness_input=str(harness_path),
            input_data=input_data,
            benchmark_case="test_analysis",
            output_format="StoredTestCase"
        )

        func_logger.info_print(f"Status: {result.get('status', 'unknown')}")

        if result.get('coverage_data'):
            cov = result['coverage_data']
            func_logger.info_print(f"Coverage Data: OK")
        else:
            func_logger.info_print(f"Coverage Data: FAILED")

        return CoverageRunResult(
            status=result.get('status', 'error'),
            return_code=result.get('return_code', -1),
            stdout=result.get('stdout', ''),
            stderr=result.get('stderr', ''),
            coverage_data=result.get('coverage_data'),
            incremental=result.get('incremental', False)
        )

    except Exception as e:
        func_logger.error_print(f"Coverage Collection Exception: {e}")
        return CoverageRunResult(
            status="coverage_failed",
            return_code=-1,
            message=str(e),
            stderr=str(e)
        )


__all__ = [
    "execute_with_assertions",
    "collect_coverage_with_assertions",
]
