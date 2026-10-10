"""
AFL++ Mutation Tool Configuration

Constants and configuration for AFL++ integration.
"""

from pathlib import Path
from typing import Dict, Any

# AFL++ binary names
AFL_CLANG_FAST = "afl-clang-fast"
AFL_FUZZ = "afl-fuzz"
AFL_SHOWMAP = "afl-showmap"

# Default configuration values
DEFAULT_MAX_RUNTIME_SEC = 600
DEFAULT_MAX_CYCLES = 50
DEFAULT_MAX_EVAL_CASES = 50
DEFAULT_PLATEAU_SECONDS = 10
DEFAULT_MAX_NO_PROGRESS_STAGES = 1000

# AFL execution environment variables
AFL_ENV_VARS = {
    "AFL_SKIP_CPUFREQ": "1",
    "AFL_I_DONT_CARE_ABOUT_MISSING_CRASHES": "1",
    "AFL_CRASH_EXITCODE": "77",
}

# IR export default filename
DEFAULT_IR_FILENAME = "afl_unified_ir.json"


class AFLConfig:
    """
    AFL++ configuration container.

    Wraps all configuration parameters for AFL++ execution.
    """

    def __init__(
        self,
        task_root: str,
        output_dir: str,
        max_runtime_sec: int = DEFAULT_MAX_RUNTIME_SEC,
        max_cycles: int = DEFAULT_MAX_CYCLES,
        max_eval_cases: int = DEFAULT_MAX_EVAL_CASES,
        plateau_seconds: int = DEFAULT_PLATEAU_SECONDS,
        max_no_progress_stages: int = DEFAULT_MAX_NO_PROGRESS_STAGES,
        ir_filename: str = DEFAULT_IR_FILENAME,
        stop_on_crash: bool = False,
        sampling_interval_sec: int = 1800,
    ):
        """
        Initialize AFL configuration.

        Args:
            task_root: Path to the benchmark task directory
            output_dir: Path to the output directory
            max_runtime_sec: Maximum runtime in seconds
            max_cycles: Maximum cycles per test case (industrial stress)
            max_eval_cases: Maximum number of cases to export (quality filtering)
            plateau_seconds: Seconds without progress before evolution
            max_no_progress_stages: Max consecutive stages without progress
            ir_filename: Name of the exported IR file
            stop_on_crash: Stop immediately when a valid crash is found (RQ2)
            sampling_interval_sec: Interval for coverage sampling (24h experiments)
        """
        self.task_root = Path(task_root).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.max_runtime_sec = max_runtime_sec
        self.max_cycles = max_cycles
        self.max_eval_cases = max_eval_cases
        self.plateau_seconds = plateau_seconds
        self.max_no_progress_stages = max_no_progress_stages
        self.ir_filename = ir_filename
        self.stop_on_crash = stop_on_crash
        self.sampling_interval_sec = sampling_interval_sec

        # Derived paths
        self.afl_in_dir = self.output_dir / "afl_in"
        self.afl_out_dir = self.output_dir / "afl_out"

    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "task_root": str(self.task_root),
            "output_dir": str(self.output_dir),
            "max_runtime_sec": self.max_runtime_sec,
            "max_cycles": self.max_cycles,
            "max_eval_cases": self.max_eval_cases,
            "plateau_seconds": self.plateau_seconds,
            "max_no_progress_stages": self.max_no_progress_stages,
            "ir_filename": self.ir_filename,
            "stop_on_crash": self.stop_on_crash,
            "sampling_interval_sec": self.sampling_interval_sec,
        }


__all__ = [
    "AFL_CLANG_FAST",
    "AFL_FUZZ",
    "AFL_SHOWMAP",
    "DEFAULT_MAX_RUNTIME_SEC",
    "DEFAULT_MAX_CYCLES",
    "DEFAULT_MAX_EVAL_CASES",
    "DEFAULT_PLATEAU_SECONDS",
    "DEFAULT_MAX_NO_PROGRESS_STAGES",
    "AFL_ENV_VARS",
    "DEFAULT_IR_FILENAME",
    "AFLConfig",
]
