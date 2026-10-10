"""
RQ2 Experiments - Cross-engine Testing Capability

Evaluates different testing engines (AFL++, Random, DSE, Direct LLM)
on code coverage and fault detection using PLCHaT's test infrastructure.
"""

from pathlib import Path
import sys

# experiments/rq2 → experiments → PROJECT_ROOT (2 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

__all__ = ["RQ2Runner", "RQ2Util"]
