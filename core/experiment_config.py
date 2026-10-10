"""
Experiment Configuration Manager

Provides unified configuration for all experiments (RQ1, RQ2, RQ3).
Controls where temporary files and results are stored.
"""

import os
from pathlib import Path
from typing import Optional
import yaml

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class ExperimentConfig:
    """Unified configuration for all experiments."""

    # Default configuration
    DEFAULTS = {
        "experiments": {
            "results_dir": "output",      # Local results directory
            "temp_dir": "temp",            # Local temp directory
            "cleanup_temp": False,         # Auto-cleanup after completion
        }
    }

    def __init__(self, config_path: Optional[Path] = None):
        """Initialize experiment configuration.

        Args:
            config_path: Path to config file (default: config/default.yaml)
        """
        self.config_path = config_path or PROJECT_ROOT / "config" / "default.yaml"
        self.config = self._load_config()

    def _load_config(self) -> dict:
        """Load configuration from YAML file."""
        # Start with defaults
        config = {"experiments": self.DEFAULTS["experiments"].copy()}

        # Load from file if exists
        if self.config_path.exists():
            try:
                with open(self.config_path) as f:
                    user_config = yaml.safe_load(f)
                    if user_config and "experiments" in user_config:
                        config["experiments"].update(user_config["experiments"])
            except Exception as e:
                print(f"Warning: Failed to load config from {self.config_path}: {e}")

        return config

    def get_results_dir(self, experiment: str) -> Path:
        """Get results directory for an experiment.

        Args:
            experiment: Experiment name (e.g., "rq1", "rq2", "rq3")

        Returns:
            Path to results directory
        """
        base = self.config["experiments"]["results_dir"]

        # Check if absolute path
        if Path(base).is_absolute():
            return Path(base) / f"{experiment}_results"
        else:
            return PROJECT_ROOT / base / f"{experiment}_results"

    def get_temp_dir(self, experiment: str, create: bool = True) -> Path:
        """Get temporary working directory for an experiment.

        Args:
            experiment: Experiment name (e.g., "rq1", "rq2", "rq3")
            create: Whether to create the directory

        Returns:
            Path to temporary directory
        """
        base = self.config["experiments"]["temp_dir"]

        # Check if absolute path
        if Path(base).is_absolute():
            temp_base = Path(base)
        else:
            temp_base = PROJECT_ROOT / base

        # Create experiment-specific temp directory
        import uuid
        temp_dir = temp_base / f"{experiment}_{uuid.uuid4().hex[:8]}"

        if create:
            temp_base.mkdir(parents=True, exist_ok=True)
            temp_dir.mkdir(parents=True, exist_ok=True)

        return temp_dir

    def should_cleanup_temp(self) -> bool:
        """Whether to auto-cleanup temp files."""
        return self.config["experiments"].get("cleanup_temp", False)

    @staticmethod
    def get_system_temp() -> Path:
        """Get system temp directory for experiments.

        Returns:
            Path to /tmp/plchat_experiments
        """
        temp = Path("/tmp/plchat_experiments")
        temp.mkdir(parents=True, exist_ok=True)
        return temp

    def print_config(self):
        """Print current configuration."""
        print("\n=== Experiment Configuration ===")
        print(f"Results Directory: {self.config['experiments']['results_dir']}")
        print(f"Temp Directory: {self.config['experiments']['temp_dir']}")
        print(f"Auto-cleanup: {self.config['experiments']['cleanup_temp']}")
        print("\nExample paths:")
        for exp in ["rq1", "rq2", "rq3"]:
            print(f"  {exp.upper()} results: {self.get_results_dir(exp)}")
        print(f"  System temp: {self.get_system_temp()}")
        print("===============================\n")


# Global instance
_global_config: Optional[ExperimentConfig] = None


def get_config(config_path: Optional[Path] = None) -> ExperimentConfig:
    """Get global experiment configuration instance.

    Args:
        config_path: Optional path to config file

    Returns:
        ExperimentConfig instance
    """
    global _global_config
    if _global_config is None or config_path is not None:
        _global_config = ExperimentConfig(config_path)
    return _global_config


def set_temp_preference(location: str):
    """Set temporary file location preference.

    Args:
        location: "local" (PROJECT_ROOT/temp) or "system" (/tmp/plchat_experiments)
    """
    config = get_config()
    if location == "local":
        config.config["experiments"]["temp_dir"] = "temp"
    elif location == "system":
        config.config["experiments"]["temp_dir"] = "/tmp/plchat_experiments"
    else:
        raise ValueError(f"Invalid location: {location}. Use 'local' or 'system'")


def set_results_preference(location: str):
    """Set results directory preference.

    Args:
        location: "local" (PROJECT_ROOT/output) or "system" (/tmp/plchat_results)
    """
    config = get_config()
    if location == "local":
        config.config["experiments"]["results_dir"] = "output"
    elif location == "system":
        config.config["experiments"]["results_dir"] = "/tmp/plchat_results"
    else:
        raise ValueError(f"Invalid location: {location}. Use 'local' or 'system'")


__all__ = [
    "ExperimentConfig",
    "get_config",
    "set_temp_preference",
    "set_results_preference",
]
