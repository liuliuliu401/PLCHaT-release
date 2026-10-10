"""
LLM Assertion Designer - compatibility shim for v4

This module delegates to LLMAssertionDesignerV4, which:
- Performs systematic safety invariant analysis
- Uses P0 (core design) / P1 (edge safety) priority system
- Learns variable access patterns from existing harness.c
- Generates check_assertions() function with proper pointer access

Legacy v1/v2 moved to: harness/test_analysis_legacy/assertion/
"""

from harness.test_analysis.assertion.llm_assertion_designer_v4 import (
    LLMAssertionDesignerV4 as LLMAssertionDesigner,
    AssertionCodeV4 as AssertionCode,
)

__all__ = ["LLMAssertionDesigner", "AssertionCode"]
