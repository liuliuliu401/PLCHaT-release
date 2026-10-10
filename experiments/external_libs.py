"""
External Libraries Configuration Manager for PLCHaT Experiments

This module manages the locations and validation of external libraries used in RQ experiments:
- SWE-agent: General-purpose coding agent baseline
- LLM-CodeGen-TestGen: Koziolek et al. test generation baseline
- MatIEC: ST to C compiler (required for all baselines)

Usage:
    # Set external library paths via command line or config file
    python -m experiments.run rq1 --baseline swe-agent --external-lib swe-agent=/path/to/swe-agent

    # Or via environment variables
    export PLCHAT_EXTERNAL_LIB_SWE_AGENT=/path/to/swe-agent
    export PLCHAT_EXTERNAL_LIB_MATIEC=/path/to/matiec

    # Or via config file
    # Create .claude/external_libs.conf with:
    # swe-agent=/path/to/swe-agent
    # matiec=/path/to/matiec
"""

import os
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple
import warnings

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_FILE = PROJECT_ROOT / ".claude" / "external_libs.conf"


class ExternalLibManager:
    """Manages external library locations and validation."""

    # Required libraries for each baseline
    BASELINE_REQUIREMENTS = {
        "ours": {
            "required": [],
            "optional": ["matiec"]
        },
        "claude-code": {
            "required": [],
            "optional": ["matiec"]
        },
        "swe-agent": {
            "required": ["swe-agent", "matiec"],
            "optional": []
        },
        "koziolek": {
            "required": ["koziolek", "matiec"],
            "optional": []
        }
    }

    def __init__(self):
        self.lib_paths: Dict[str, Path] = {}
        self._load_from_all_sources()

    def _load_from_all_sources(self):
        """Load library paths from all sources (priority: cmdline > env > config)."""
        # 1. Load from config file
        self._load_from_config()

        # 2. Override with environment variables
        self._load_from_env()

        # 3. Override with command line arguments (set externally)
        self._load_from_cmdline_cache()

    def _load_from_config(self):
        """Load library paths from config file."""
        if CONFIG_FILE.exists():
            with open(CONFIG_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        self.lib_paths[key.strip()] = Path(value.strip()).expanduser().resolve()

    def _load_from_env(self):
        """Load library paths from environment variables."""
        env_prefix = "PLCHAT_EXTERNAL_LIB_"
        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                lib_name = key[len(env_prefix):].lower().replace("_", "-")
                self.lib_paths[lib_name] = Path(value).expanduser().resolve()

    def _load_from_cmdline_cache(self):
        """Load from command line cache (set via set_lib_path)."""
        # This is populated when command line args are parsed
        pass

    def set_lib_path(self, lib_name: str, lib_path: Path):
        """Set a library path programmatically (e.g., from command line)."""
        self.lib_paths[lib_name] = lib_path.expanduser().resolve()

    def get_lib_path(self, lib_name: str) -> Optional[Path]:
        """Get the path for a library, or None if not set."""
        return self.lib_paths.get(lib_name)

    def check_baseline_requirements(self, baseline: str, silent: bool = False) -> Tuple[bool, str]:
        """Check if all required libraries for a baseline are available.

        Returns:
            (is_ready, message): Tuple of readiness status and message
        """
        if baseline not in self.BASELINE_REQUIREMENTS:
            return False, f"Unknown baseline: {baseline}"

        reqs = self.BASELINE_REQUIREMENTS[baseline]
        missing = []
        available = []

        for lib in reqs["required"]:
            path = self.get_lib_path(lib)
            if path is None or not path.exists():
                missing.append(lib)
            else:
                available.append(lib)

        if missing:
            if not silent:
                msg = f"Cannot run {baseline} baseline: missing required libraries: {', '.join(missing)}\n"
                msg += f"Configure via: --external-lib {missing[0]}=/path/to/{missing[0]}\n"
                msg += f"Or environment: PLCHAT_EXTERNAL_LIB_{missing[0].upper().replace('-', '_')}=/path/to/{missing[0]}\n"
                msg += f"Or config file: {CONFIG_FILE}"
                warnings.warn(msg)
            return False, f"Missing: {', '.join(missing)}"

        return True, f"All required libraries available: {', '.join(available)}"

    def get_baseline_runner(self, baseline: str, fast_mode: bool = False, **kwargs):
        """Get the runner class for a baseline, checking requirements first.

        Args:
            baseline: Baseline name (ours, claude-code, swe-agent, koziolek)
            fast_mode: Enable fast mode
            **kwargs: Additional arguments to pass to the runner

        Returns:
            Instantiated baseline runner
        """
        is_ready, msg = self.check_baseline_requirements(baseline)

        if not is_ready:
            raise RuntimeError(f"Cannot run {baseline} baseline: {msg}")

        # Import and instantiate the appropriate runner
        if baseline == "ours":
            from experiments.rq1.ours.runner import RQ1OursRunner
            return RQ1OursRunner(fast_mode=fast_mode, **kwargs)
        elif baseline == "claude-code":
            from experiments.rq1.baselines.claude_code import ClaudeCodeBaseline
            return ClaudeCodeBaseline(fast_mode=fast_mode, **kwargs)
        elif baseline == "swe-agent":
            from experiments.rq1.baselines.swe_agent import SWEAgentBaseline
            swe_path = self.get_lib_path("swe-agent")
            return SWEAgentBaseline(swe_agent_path=swe_path, fast_mode=fast_mode, **kwargs)
        elif baseline == "koziolek":
            from experiments.rq1.baselines.koziolek import KoziolekBaseline
            koziolek_path = self.get_lib_path("koziolek")
            matiec_path = self.get_lib_path("matiec")
            return KoziolekBaseline(koziolek_path=koziolek_path, matiec_path=matiec_path,
                                   fast_mode=fast_mode, **kwargs)
        else:
            raise ValueError(f"Unknown baseline: {baseline}")

    def print_status(self):
        """Print the status of all libraries."""
        print("\n=== External Libraries Status ===")
        print(f"Config file: {CONFIG_FILE}")
        print()

        for lib_name in ["swe-agent", "koziolek", "matiec"]:
            path = self.get_lib_path(lib_name)
            if path:
                status = "✓" if path.exists() else "✗ (not found)"
                print(f"  {lib_name}: {path} {status}")
            else:
                print(f"  {lib_name}: (not set)")
        print()


# Global instance
_manager = None


def get_manager() -> ExternalLibManager:
    """Get the global external library manager instance."""
    global _manager
    if _manager is None:
        _manager = ExternalLibManager()
    return _manager


def print_help():
    """Print help on configuring external libraries."""
    help_text = """
External Libraries Configuration for PLCHaT Experiments
======================================================

Some baselines require external libraries. You must provide their locations.

Required Libraries:
-------------------
1. swe-agent : SWE-agent installation (for SWE-agent baseline)
2. koziolek  : LLM-CodeGen-TestGen directory (for Koziolek baseline)
3. matiec    : MatIEC compiler installation (optional, system default used if not set)

Configuration Methods:
----------------------

Method 1: Command Line Arguments
    python -m experiments.run rq1 --baseline swe-agent \\
        --external-lib swe-agent=/path/to/swe-agent \\
        --external-lib matiec=/path/to/matiec

Method 2: Environment Variables
    export PLCHAT_EXTERNAL_LIB_SWE_AGENT=/path/to/swe-agent
    export PLCHAT_EXTERNAL_LIB_KOZIOLEK=/path/to/LLM-CodeGen-TestGen
    export PLCHAT_EXTERNAL_LIB_MATIEC=/path/to/matiec

Method 3: Config File (.claude/external_libs.conf)
    Create .claude/external_libs.conf with:
    swe-agent=/path/to/swe-agent
    koziolek=/path/to/LLM-CodeGen-TestGen
    matiec=/path/to/matiec

    Priority: Command Line > Environment Variables > Config File

Checking Status:
----------------
    python -m experiments.run rq1 --check-external-libs

Baseline Requirements:
----------------------
- ours (PLCHaT)         : No external libraries required
- claude-code (Agent)    : No external libraries required (self-contained)
- swe-agent             : swe-agent, matiec
- koziolek              : koziolek, matiec
"""
    print(help_text)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--check-external-libs", action="store_true",
                        help="Check external libraries status")
    parser.add_argument("--help-external-libs", action="store_true",
                        help="Show help on configuring external libraries")
    args = parser.parse_args()

    if args.help_external_libs:
        print_help()
    elif args.check_external_libs:
        get_manager().print_status()
    else:
        print_help()
