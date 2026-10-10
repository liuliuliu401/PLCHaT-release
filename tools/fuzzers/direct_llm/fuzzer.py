"""
Direct LLM Fuzzer - Wrapper for DirectLLMGenerator

Provides fuzzer interface for Direct LLM generation.
"""

from .generator import DirectLLMGenerator


class DirectLLMFuzzer(DirectLLMGenerator):
    """
    Alias for DirectLLMGenerator to maintain fuzzer naming convention.
    """

    pass
