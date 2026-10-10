"""Test intent analysis module"""

from pathlib import Path
import sys

# Project root: intent/__init__.py → test_analysis → harness → PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.test_analysis.intent.intent_provider import IntentProvider
from core.data_types.test_analysis_types import TestIntent

__all__ = ["IntentProvider", "TestIntent"]
