"""
Agents Module - Optional External Cognitive Agents

This module provides optional agent implementations for
strategic planning and test generation.

Note: These agents are OPTIONAL. The PLCHaT harness
can function fully in an agentless mode.
"""

from .generator import Generator
from .router import LLMRouter, RouterRequest, InjectedContext

__all__ = ["Generator", "LLMRouter", "RouterRequest", "InjectedContext"]
