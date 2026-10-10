"""
AFL++ Environment Checker

Validates AFL++ installation and system dependencies.
"""

import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class AFLEnvironmentError(Exception):
    """Exception raised when AFL++ environment is invalid."""
    pass


class AFLEnvChecker:
    """
    AFL++ environment checker.

    Features:
    - Detect AFL++ binary files
    - Verify MatIEC (iec2c) availability
    - Report missing dependencies
    """

    # Required AFL++ binaries
    AFL_BINARIES = ["afl-clang-fast", "afl-fuzz"]
    # Optional AFL++ binaries
    AFL_OPTIONAL_BINARIES = ["afl-showmap"]
    # Required system tools
    REQUIRED_TOOLS = ["iec2c", "plc", "timeout"]

    def __init__(self):
        """Initialize the environment checker."""
        self._binaries_found: Dict[str, Optional[str]] = {}
        self._errors: List[str] = []
        self._warnings: List[str] = []

    def check(self) -> bool:
        """
        Perform complete environment check.

        Returns:
            True if all required dependencies are found, False otherwise
        """
        self._errors.clear()
        self._warnings.clear()
        self._binaries_found.clear()

        # Check AFL++ binaries
        for binary in self.AFL_BINARIES:
            path = shutil.which(binary)
            if path:
                self._binaries_found[binary] = path
            else:
                self._errors.append(f"Missing required AFL++ binary: {binary}")

        # Check optional AFL++ binaries
        for binary in self.AFL_OPTIONAL_BINARIES:
            path = shutil.which(binary)
            if path:
                self._binaries_found[binary] = path
            else:
                self._warnings.append(f"Missing optional AFL++ binary: {binary}")

        # Check required system tools
        for tool in self.REQUIRED_TOOLS:
            path = shutil.which(tool)
            if path:
                self._binaries_found[tool] = path
            else:
                self._errors.append(f"Missing required tool: {tool}")

        return len(self._errors) == 0

    def get_binaries(self) -> Dict[str, Optional[str]]:
        """
        Get found binary file paths.

        Returns:
            Dictionary mapping binary names to their paths
        """
        return self._binaries_found.copy()

    def get_errors(self) -> List[str]:
        """Get error list."""
        return self._errors.copy()

    def get_warnings(self) -> List[str]:
        """Get warning list."""
        return self._warnings.copy()

    def print_report(self):
        """Print environment check report."""
        print("=" * 60)
        print("AFL++ Environment Check Report")
        print("=" * 60)

        # Found binaries
        print("\n[Found Binaries]")
        if self._binaries_found:
            for name, path in sorted(self._binaries_found.items()):
                print(f"  ✓ {name}: {path}")
        else:
            print("  (none found)")

        # Warnings
        if self._warnings:
            print("\n[Warnings]")
            for warning in self._warnings:
                print(f"  ⚠ {warning}")

        # Errors
        if self._errors:
            print("\n[Errors]")
            for error in self._errors:
                print(f"  ✗ {error}")

        # Summary
        print("\n" + "=" * 60)
        if not self._errors:
            print("Status: ✓ All required dependencies found")
        else:
            print(f"Status: ✗ {len(self._errors)} error(s) found")
        print("=" * 60)

    def get_matiec_paths(self) -> Tuple[Path, Path]:
        """
        Get MatIEC related paths.

        Returns:
            Tuple of (matiec_dir, matiec_c_lib_dir)

        Raises:
            AFLEnvironmentError: If iec2c is not found
        """
        iec2c_bin = self._binaries_found.get("iec2c")
        if not iec2c_bin:
            raise AFLEnvironmentError("iec2c not found in PATH")

        matiec_path = Path(iec2c_bin).resolve().parent
        matiec_c_lib_dir = matiec_path / "lib" / "C"

        if not matiec_c_lib_dir.exists():
            raise AFLEnvironmentError(
                f"MatIEC C lib directory not found: {matiec_c_lib_dir}"
            )

        return matiec_path, matiec_c_lib_dir

    def get_rusty_st_lib_dir(self) -> Path:
        """
        Get Rusty-PLC ST standard library path.

        Returns:
            Path to the IEC 61131-3 ST standard library directory

        Raises:
            AFLEnvironmentError: If plc binary is not found
        """
        plc_bin = self._binaries_found.get("plc")
        if not plc_bin:
            raise AFLEnvironmentError("plc binary not found in PATH")

        # Navigate to stdlib: bin/plc → lib/stdlib/iec61131-st
        lib_dir = Path(plc_bin).resolve().parent.parent.parent / "libs" / "stdlib" / "iec61131-st"

        if not lib_dir.exists():
            raise AFLEnvironmentError(
                f"Rusty ST lib directory not found: {lib_dir}"
            )

        return lib_dir


def check_environment() -> bool:
    """
    Convenience function: Perform environment check and print report.

    Returns:
        True if all required dependencies are found
    """
    checker = AFLEnvChecker()
    success = checker.check()
    checker.print_report()
    return success


if __name__ == "__main__":
    success = check_environment()
    sys.exit(0 if success else 1)


__all__ = [
    "AFLEnvironmentError",
    "AFLEnvChecker",
    "check_environment",
]
