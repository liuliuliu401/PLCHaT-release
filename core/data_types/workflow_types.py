"""
Workflow Type Definitions
"""
from pathlib import Path
import sys

# Project root resolution
# core/data_types/workflow_types.py → data_types → core → PROJECT_ROOT (3 parents)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from typing import Optional, Literal, List, Dict, Any
from dataclasses import dataclass, field


@dataclass
class WorkflowConfig:
    """Workflow configuration"""
    mode: Literal["interactive", "auto"] = "interactive"
    max_time_seconds: Optional[int] = None
    max_executions: Optional[int] = None
    max_iterations: Optional[int] = None
    initial_goal: Optional[str] = None


@dataclass
class WorkflowState:
    """Workflow state"""
    iteration: int = 0
    test_cases: List = field(default_factory=list)
    coverage: float = 0.0
    coverage_history: List[float] = field(default_factory=list)
    violations: List = field(default_factory=list)
    elapsed_time: float = 0.0
    execution_count: int = 0

    # Session paths
    session_dir: Optional[Path] = None
    st_path: Optional[Path] = None
    harness_path: Optional[Path] = None
    schema_path: Optional[Path] = None

    start_time: float = 0.0


@dataclass
class WorkflowResult:
    """Final workflow result"""
    success: bool
    test_cases: List = field(default_factory=list)
    coverage: float = 0.0
    violations: List = field(default_factory=list)
    iterations: int = 0
    elapsed_time: float = 0.0
    session_dir: Optional[Path] = None
    error: Optional[str] = None
    metadata: Dict = field(default_factory=dict)


def create_session_dir() -> Path:
    """Create unique session directory"""
    from harness.compiler.cache_manager import CacheManager
    return CacheManager.get_temp_dir("plchat_session")
