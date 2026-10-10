"""
Tools Module - Independent Testing Tools

Provides access to various testing engines:
- SMT/DSE solvers for symbolic execution
- AFL++ for coverage-guided fuzzing (pending)
- Random fuzzer for broad exploration (τrand)
- Direct LLM for baseline comparison (pending)
"""

# Import solver tools (SMT)
from tools.solvers import SMTTool, Z3Engine

# LLMSemanticSlicer requires config variables that may not be set
try:
    from tools.solvers import LLMSemanticSlicer
    _has_llm_slicer = True
except (ImportError, AttributeError):
    _has_llm_slicer = False

# Import fuzzer tools (Random)
from tools.fuzzers import RandomCaseGenerator, RandomFuzzerTool

# Placeholder imports for tools not yet migrated
# from tools.fuzzers import AFLOrchestrator, DirectLLMFuzzer

__all__ = [
    # Solvers
    "SMTTool",
    "Z3Engine",
    # Fuzzers
    "RandomCaseGenerator",
    "RandomFuzzerTool",
    # "AFLOrchestrator",
    # "DirectLLMFuzzer",
]

# Conditionally add LLMSemanticSlicer if available
if _has_llm_slicer:
    __all__.append("LLMSemanticSlicer")
