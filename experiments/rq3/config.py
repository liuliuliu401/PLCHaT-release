"""
RQ3 Ablation Configuration

Defines the six experimental configurations used in RQ3:
- C1: Full Framework (distill + oracle)
- C2: w/o Distill (naive truncation)
- C3: w/o Trace Distillation (raw trace)
- C4: w/o Active Oracle in feedback
- C0: No inter-round feedback
- E_raw: Raw output (no oracle/metrics)
"""

from dataclasses import dataclass
from typing import Dict, Any


# Predefined configurations from the paper
_CONFIGS: Dict[str, Dict[str, bool]] = {
    "C1": {"distill": True, "truncate": False, "oracle": True, "metrics": True},
    "C2": {"distill": False, "truncate": True, "oracle": True, "metrics": True},
    "C3": {"distill": False, "truncate": False, "oracle": True, "metrics": True},
    "C4": {"distill": True, "truncate": False, "oracle": False, "metrics": True},
    "E_raw": {"distill": False, "truncate": False, "oracle": False, "metrics": False},
    "C0": {"distill": False, "truncate": False, "oracle": False, "metrics": False},
}


@dataclass
class AblationConfig:
    """Configuration for RQ3 ablation experiments."""

    config_id: str
    enable_distillation: bool
    enable_truncation: bool
    enable_oracle: bool
    enable_metrics: bool

    @classmethod
    def from_id(cls, config_id: str) -> "AblationConfig":
        """Create configuration from predefined ID."""
        cfg = _CONFIGS.get(config_id)
        if cfg is None:
            raise ValueError(f"Unknown config: {config_id}. Available: {list(_CONFIGS.keys())}")
        return cls(
            config_id=config_id,
            enable_distillation=cfg["distill"],
            enable_truncation=cfg["truncate"],
            enable_oracle=cfg["oracle"],
            enable_metrics=cfg["metrics"]
        )

    @property
    def description(self) -> str:
        """Human-readable description of this configuration."""
        descriptions = {
            "C1": "Full Framework (distill + oracle)",
            "C2": "w/o Distill (naive truncation)",
            "C3": "w/o Trace Distillation (raw trace)",
            "C4": "w/o Active Oracle in feedback",
            "C0": "No inter-round feedback",
            "E_raw": "Raw output (no oracle/metrics)",
        }
        return descriptions.get(self.config_id, "Unknown")

    def has_inter_round_feedback(self) -> bool:
        """Whether this configuration provides feedback between rounds."""
        return self.config_id not in ("C0", "E_raw")

    def has_oracle_feedback(self) -> bool:
        """Whether this configuration includes oracle in feedback."""
        return self.enable_oracle and self.config_id in ("C1", "C2", "C3")

    def has_metrics_feedback(self) -> bool:
        """Whether this configuration includes metrics in feedback."""
        return self.enable_metrics and self.config_id != "E_raw"


__all__ = ["AblationConfig"]
