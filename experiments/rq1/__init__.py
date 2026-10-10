"""
RQ1 Experiments - Harness Generation Effectiveness

Evaluates PLCHaT's ability to generate executable test wrappers and
assertion-based oracles compared to existing approaches.
"""

from pathlib import Path
import sys

# experiments/rq1 → experiments → PROJECT_ROOT (2 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

__all__ = ["RQ1Runner", "RQ1Util"]
