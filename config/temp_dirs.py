"""
Temporary directory configuration

All temporary files should be stored in project temp/ directory.
"""

from pathlib import Path
import uuid

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Temporary file root directory
TEMP_ROOT = PROJECT_ROOT / "temp"

# Subdirectories
TEMP_COMPILE = TEMP_ROOT / "compile"
TEMP_EXEC = TEMP_ROOT / "exec"
TEMP_MUTATION = TEMP_ROOT / "mutation"
TEMP_TEST = TEMP_ROOT / "test"
TEMP_COVERAGE = TEMP_ROOT / "coverage"
TEMP_HARNESS = TEMP_ROOT / "harness"


def ensure_temp_dirs():
    """Create all temporary directories."""
    for dir_path in [TEMP_COMPILE, TEMP_EXEC, TEMP_MUTATION, TEMP_TEST, TEMP_COVERAGE, TEMP_HARNESS]:
        dir_path.mkdir(parents=True, exist_ok=True)


def get_temp_dir(subdir: str) -> Path:
    """
    Get temporary file path for a specific subdirectory.

    Args:
        subdir: Subdirectory name

    Returns:
        Path object
    """
    path = TEMP_ROOT / subdir
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_compile_temp_dir() -> Path:
    """Get compilation temporary directory."""
    ensure_temp_dirs()
    return TEMP_COMPILE


def get_exec_temp_dir() -> Path:
    """Get execution temporary directory."""
    ensure_temp_dirs()
    return TEMP_EXEC


def get_unique_temp_path(subdir: str, prefix: str, suffix: str) -> Path:
    """
    Generate unique temporary file path.

    Args:
        subdir: Subdirectory name
        prefix: File name prefix
        suffix: File name suffix (including extension)

    Returns:
        Unique Path object
    """
    temp_dir = get_temp_dir(subdir)
    unique_name = f"{prefix}_{uuid.uuid4().hex[:8]}{suffix}"
    return temp_dir / unique_name


# Initialize
ensure_temp_dirs()
