"""
RQ3: Component Ablation Studies

Evaluates the impact of individual harness components on:
- Fault detection effectiveness (mutation kill rate)
- Coverage metrics (branch/line)
- Token efficiency (input/output per iteration)
- Assertion generation and trigger rates

Configurations:
- C1: Full Framework (distill + oracle)
- C2: w/o Distill (naive truncation)
- C3: w/o Trace Distillation (raw trace)
- C4: w/o Active Oracle in feedback
- C0: No inter-round feedback
- E_raw: Raw output (no oracle/metrics)
"""

from experiments.rq3.config import AblationConfig
from experiments.rq3.runner import RQ3Runner

__all__ = ["AblationConfig", "RQ3Runner"]
