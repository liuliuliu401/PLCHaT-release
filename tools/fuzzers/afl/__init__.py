"""
AFL++ Mutation Tool (τmut)

Coverage-guided mutation engine based on AFL++ for structural path penetration.

Components:
- SeedNormalizer: PLC semantic normalization
- AFLCompiler: AFL++ instrumentation wrapper
- AFLOrchestrator: AFL++ execution orchestration
- MutationFuzzerTool: BaseTool interface implementation

Migrated from: baselines/afl/generator.py
Refactored: Eliminated code duplication, fixed anti-patterns
"""

from .seed_normalizer import SeedNormalizer
from .env_checker import AFLEnvChecker, AFLEnvironmentError, check_environment
from .config import AFLConfig
from .compiler import AFLCompiler, temp_dir
from .orchestrator import AFLOrchestrator
from .mutation_tool import MutationFuzzerTool
from .generator import AFLCaseGenerator

__all__ = [
    "SeedNormalizer",
    "AFLEnvChecker",
    "AFLEnvironmentError",
    "check_environment",
    "AFLConfig",
    "AFLCompiler",
    "temp_dir",
    "AFLOrchestrator",
    "MutationFuzzerTool",
    "AFLCaseGenerator",
]
