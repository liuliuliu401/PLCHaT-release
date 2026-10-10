"""
test case analysis component

Deep analysis guided by test intent
- LLM analysis test intention
- LLM generated assertion code
- Patch inserted into harness
- MATIEC execution and coverage collection
- Coverage completeness analysis

Usage:
    from harness.test_analysis import TestAnalysisAgent

    agent = TestAnalysisAgent(
        st_path="path/to/file.st",
        harness_path="path/to/harness.c"
    )

    report = agent.analyze(
test_intent="Analyze the coverage completeness of channel boundary condition testing",
        test_inputs=["80\\n", "100\\n", "0\\n"]
    )
"""

from pathlib import Path
import sys

# Project root: __init__.py → test_analysis → harness → PROJECT_ROOT
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Execution and coverage collection
from harness.test_analysis.execution import (
    execute_with_assertions,
    collect_coverage_with_assertions
)

# Agent and tool management
from harness.test_analysis.agent import TestAnalysisAgent
from harness.test_analysis.tool_manager import TestAnalysisToolManager

# Assert design and insertion
from harness.test_analysis.assertion.llm_assertion_designer import LLMAssertionDesigner
from harness.test_analysis.assertion.patch_inserter import AssertionPatcher, PatchResult

# Test intent
from harness.test_analysis.intent.intent_provider import IntentProvider, TestIntent

# Minimization analysis (has import issues, commented for now)
# from harness.test_analysis.minimization_integrator import MinimizationIntegrator
# from core.data_types.test_analysis_types import MinComparisonResult

__all__ = [
    # Main entry
    "TestAnalysisAgent",
    "TestAnalysisToolManager",

    # Execution and coverage
    "execute_with_assertions",
    "collect_coverage_with_assertions",

    # Assertion related
    "LLMAssertionDesigner",
    "AssertionPatcher",
    "PatchResult",

    # Test intent
    "IntentProvider",
    "TestIntent",

    # Minimization analysis
    "MinimizationIntegrator",
    "MinComparisonResult",
]

__version__ = "7.0.0 (v3 designer)"
