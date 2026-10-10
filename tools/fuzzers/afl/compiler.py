"""
AFL++ Compiler Wrapper

Handles AFL++ instrumentation compilation for PLC programs.

Design:
- Reuses STExecutor from harness.compiler for ST→C transpilation
- Only handles AFL-specific logic:
  - Probe replacement (exit→trap)
  - AFL++ instrumentation via afl-clang-fast

Migrated from: baselines/afl/generator.py (prepare method)
Refactored to eliminate code duplication with harness.compiler.
"""

import os
import re
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional, Tuple

from .env_checker import AFLEnvChecker, AFLEnvironmentError


class AFLCompiler:
    """
AFL++ compilation wrapper.

# Function:
- Reuse STExecutor for ST→C translation
- Probe replacement (exit→trap)
- AFL instrumentation compilation (afl-clang-fast)

Migrated from: baselines/afl/generator.py:AFLStageOrchestrator.prepare()
Refactor: reuse harness.compiler.STExecutor, eliminate code duplication
    """

    def __init__(self, env_checker: Optional[AFLEnvChecker] = None):
        """
        Initialize the AFL compiler.

        Args:
            env_checker: Pre-configured environment checker
        """
        if env_checker is None:
            env_checker = AFLEnvChecker()
            if not env_checker.check():
                raise AFLEnvironmentError(
                    "AFL++ environment check failed. "
                    "Please install AFL++ and required dependencies."
                )

        self.env_checker = env_checker
        self.matiec_path, self.matiec_c_lib_dir = env_checker.get_matiec_paths()

        # Lazy import to avoid circular dependency
        from harness.compiler.executor import STExecutor
        self.executor = STExecutor()

    def prepare(
        self,
        st_path: Path,
        harness_src_path: Path,
        output_dir: Path,
    ) -> Path:
        """
Prepare the AFL-instrumented binary.

Process:
1. Reuse STExecutor to perform ST→C translation
2. Probe replacement (exit→trap)
# 3. AFL instrumentation compilation

        Args:
            st_path: Path to ST source file
            harness_src_path: Path to harness.c source file
            output_dir: Output directory for compiled artifacts

        Returns:
            Path to the compiled AFL-instrumented binary

        Raises:
            RuntimeError: If compilation fails
        """
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        print(f"[*] Preparing AFL++ assets for {st_path.name}...")

        # Step 1: Reuse STExecutor to perform ST→C translation
        success = self.executor.compile_st_to_c(
            st_code_path=str(st_path),
            output_dir=str(output_dir),
            harness_path=str(harness_src_path)
        )

        if not success:
            raise RuntimeError(f"ST→C compilation failed for {st_path}")

        # Step 2: Probe replacement (AFL-specific logic)
        self._replace_probes(output_dir)

        # Step 3: AFL instrumentation compilation (AFL-specific logic)
        binary_path = self._compile_with_afl(output_dir)

        print(f"[√] AFL++ instrumentation completed: {binary_path}")
        return binary_path

    def _replace_probes(self, output_dir: Path):
        """
Replace kill probe.

# Replace exit(1) with __builtin_trap() so that AFL can correctly capture crashes.
# This is AFL-specific logic, not in STExecutor.
        """
        for c_file in output_dir.glob("*.c"):
            content = c_file.read_text(encoding='utf-8')

            # Replace exit(1) with __builtin_trap()
            new_content = content.replace("exit(1);", "__builtin_trap();")
            new_content = new_content.replace("exit (1);", "__builtin_trap();")

            if new_content != content:
                c_file.write_text(new_content, encoding='utf-8')

    def _compile_with_afl(self, output_dir: Path) -> Path:
        """
Compile with AFL instrumentation.

        Returns:
            Path to the compiled binary
        """
        binary_path = output_dir / "afl_harness"

        # List all .c files
        generated_c = [str(p) for p in output_dir.glob("*.c")]
        lib_c_files = [
            str(p) for p in self.matiec_c_lib_dir.glob("*.c")
            if "iec_std_lib" in p.name or "accessor" in p.name
        ]

        build_cmd = [
            "afl-clang-fast",
            "-g",
            f"-I{self.matiec_c_lib_dir}",
            f"-I{output_dir}",
            *generated_c,
            *lib_c_files,
            "-lm", "-lz", "-lrt", "-lpthread", "-w",
            "-o", str(binary_path)
        ]

        proc = subprocess.run(build_cmd, check=True, capture_output=True, text=True)

        # Count instrumentation positions
        total_locs = 0
        for line in (proc.stdout + proc.stderr).splitlines():
            match = re.search(r"Instrumented (\d+) locations", line)
            if match:
                total_locs += int(match.group(1))

        print(f"[+] Total Instrumented Locations (CFG Edges): {total_locs}")
        return binary_path


@contextmanager
def temp_dir(prefix: str = "plchat_afl_"):
    """
Temporary directory context manager.

Automatically clean up temporary directories to prevent leaks.

    Usage:
        with temp_dir("prefix_") as temp_path:
# Use temp_path
# Auto cleanup
    """
    temp_path = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield temp_path
    finally:
        # Clean temporary directory
        if temp_path.exists():
            shutil.rmtree(temp_path, ignore_errors=True)


__all__ = ["AFLCompiler", "temp_dir"]
