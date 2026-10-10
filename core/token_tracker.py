"""
Global LLM Token Tracker - singleton for experiment-wide token counting.

Intercepts ALL ChatOpenAI.invoke() calls across the entire codebase via
monkey-patch in config.py. No per-component changes needed.

Usage:
    from core.token_tracker import TokenTracker
    tracker = TokenTracker.get()
    
    # Before experiment:
    tracker.reset()
    
    # After experiment:
    print(tracker.summary())  # {"input": 12345, "output": 6789, "calls": 42}
"""

import threading
from typing import Dict, Any
from dataclasses import dataclass, field


@dataclass
class TokenTracker:
    """Thread-safe global token counter for all LLM invocations."""

    input_tokens: int = 0
    output_tokens: int = 0
    api_calls: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    _instance: "TokenTracker" = field(default=None, repr=False, init=False)

    @classmethod
    def get(cls) -> "TokenTracker":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def record(self, prompt_tokens: int = 0, completion_tokens: int = 0):
        """Record token usage from a single LLM call (thread-safe)."""
        with self._lock:
            self.input_tokens += prompt_tokens
            self.output_tokens += completion_tokens
            self.api_calls += 1

    def reset(self):
        """Reset all counters to zero."""
        with self._lock:
            self.input_tokens = 0
            self.output_tokens = 0
            self.api_calls = 0

    def summary(self) -> Dict[str, int]:
        """Return current token counts."""
        with self._lock:
            return {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "api_calls": self.api_calls,
            }

    def snapshot(self) -> Dict[str, int]:
        """Return current counts and reset. Useful for per-iteration tracking."""
        with self._lock:
            s = {
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "api_calls": self.api_calls,
            }
            self.input_tokens = 0
            self.output_tokens = 0
            self.api_calls = 0
            return s
