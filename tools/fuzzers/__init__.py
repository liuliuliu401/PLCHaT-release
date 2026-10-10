"""
Fuzzers Module - Coverage-Guided Fuzzing Tools

Provides various fuzzing engines for RQ2 experiments:
- RandomCaseGenerator: Type-aware random generation with weighted sampling (τrand)
- AFLCaseGenerator: AFL++-inspired mutation-based generation (τmut)
- DSECaseGenerator: Dynamic symbolic execution using Z3 solver (τdse)
- DirectLLMGenerator: Pure LLM generation baseline (τllm)
"""

from .random import RandomCaseGenerator, RandomFuzzerTool
from .dse import DSETool, DSEEngine, DSEState, DSECaseGenerator
from .afl.generator import AFLCaseGenerator
from .direct_llm import DirectLLMGenerator, DirectLLMFuzzer

__all__ = [
    "RandomCaseGenerator",
    "RandomFuzzerTool",
    "DSETool",
    "DSEEngine",
    "DSEState",
    "DSECaseGenerator",
    "AFLCaseGenerator",
    "DirectLLMGenerator",
    "DirectLLMFuzzer",
]
