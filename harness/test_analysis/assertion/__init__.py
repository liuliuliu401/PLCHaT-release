"""Assertion design module (v3 - LLM assertion code generation)"""

from pathlib import Path
import sys

# Project root: assertion/__init__.py → test_analysis → harness → PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from harness.test_analysis.assertion.llm_assertion_designer import LLMAssertionDesigner, AssertionCode
from harness.test_analysis.assertion.patch_inserter import AssertionPatcher, PatchResult

__all__ = [
    "LLMAssertionDesigner",
    "AssertionCode",
    "AssertionPatcher",
    "PatchResult",
]
