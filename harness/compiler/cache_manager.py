"""
PLCHaT Compilation Cache Manager

Manage temporary files and caches during compilation:
- All temporary files are uniformly stored in the system cache directory.
Supports on-demand cleanup and automatic expiration
- Prevent contamination of benchmark dataset
"""

import os
import tempfile
import shutil
import hashlib
import time
from pathlib import Path
from typing import Optional, Dict, List
from datetime import datetime, timedelta


class CacheManager:
    """
compilation cache manager

Principle:
# 1. Never write any content to the benchmark source directory.
2. All temporary files are stored in the system cache directory
3. Support automatic cleanup and manual cleanup.
    """

    # Cache root directory
    CACHE_ROOT = Path(tempfile.gettempdir()) / "plchat_cache"

    # Different types of cache subdirectories
    COMPILE_CACHE = CACHE_ROOT / "compile"
    HARNESS_CACHE = CACHE_ROOT / "harness"
    EXEC_CACHE = CACHE_ROOT / "exec"
    TEMP_CACHE = CACHE_ROOT / "temp"

    # Cache expiration time (seconds)
    COMPILE_CACHE_TTL = 7 * 24 * 3600  # 7 days
    HARNESS_CACHE_TTL = 30 * 24 * 3600  # 30 days
    EXEC_CACHE_TTL = 1 * 24 * 3600  # 1 day
    TEMP_CACHE_TTL = 1 * 3600  # 1 hour

    @classmethod
    def initialize(cls):
        """Initialize cache directory structure"""
        for cache_dir in [cls.COMPILE_CACHE, cls.HARNESS_CACHE,
                          cls.EXEC_CACHE, cls.TEMP_CACHE]:
            cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def get_compile_cache_dir(cls, benchmark_name: str, st_hash: Optional[str] = None) -> Path:
        """
# Get the compilation cache directory

        Args:
benchmark_name: Benchmark name
st_hash: ST file hash (optional, used to distinguish different versions)

        Returns:
# cache directory path
        """
        cls.initialize()

        if st_hash:
            cache_dir = cls.COMPILE_CACHE / benchmark_name / st_hash[:8]
        else:
            cache_dir = cls.COMPILE_CACHE / benchmark_name

        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @classmethod
    def get_harness_cache_dir(cls, benchmark_name: str) -> Path:
        """Get harness cache directory"""
        cls.initialize()
        cache_dir = cls.HARNESS_CACHE / benchmark_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @classmethod
    def get_exec_cache_dir(cls, session_id: str) -> Path:
        """Get the execution cache directory"""
        cls.initialize()
        cache_dir = cls.EXEC_CACHE / session_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @classmethod
    def get_temp_dir(cls, prefix: str = "plchat_temp") -> Path:
        """# Get temporary directory"""
        cls.initialize()
        temp_dir = cls.TEMP_CACHE / f"{prefix}_{int(time.time())}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        return temp_dir

    @classmethod
    def compute_st_hash(cls, st_path: Path) -> str:
        """Compute the hash value of the ST file"""
        with open(st_path, 'rb') as f:
            content = f.read()
        return hashlib.sha256(content).hexdigest()

    @classmethod
    def is_benchmark_path(cls, path: Path) -> bool:
        """
Check if the path belongs to the benchmark directory

Prevent writing anything to the benchmark directory.
        """
        path_str = str(path.resolve())
        return "/benchmark/" in path_str or "\\benchmark\\" in path_str

    @classmethod
    def safe_mkdir(cls, path: Path, check_benchmark: bool = True) -> Path:
        """
Create directory safely to avoid polluting the benchmark directory.

        Args:
path: the directory path to create
check_benchmark: whether to check if in the benchmark directory

        Returns:
The created directory path

        Raises:
ValueError: if the path is in the benchmark directory
        """
        if check_benchmark and cls.is_benchmark_path(path):
            raise ValueError(f"Refusing to create directory in benchmark path: {path}")

        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def get_cleaned_st_path(cls, st_path: Path, output_dir: Optional[Path] = None) -> Path:
        """
Get the output path of the cleaned ST file

# Always write to cache directory, never write to source directory

        Args:
st_path: Original ST file path
output_dir: specifies the output directory (optional)

        Returns:
Output path of cleaned ST file
        """
        if output_dir:
            # If an output directory is specified, ensure it is not in the benchmark
            if cls.is_benchmark_path(output_dir):
                raise ValueError(f"Refusing to write to benchmark directory: {output_dir}")
            return output_dir / f"{st_path.stem}.cleaned.st"

        # Default write to temporary cache directory
        temp_dir = cls.get_temp_dir("cleaned_st")
        return temp_dir / f"{st_path.stem}.cleaned.st"

    @classmethod
    def clean_expired_caches(cls, cache_type: Optional[str] = None) -> Dict[str, int]:
        """
Clean up expired cache

        Args:
cache_type: Specify the cache type to clean (compile/harness/exec/temp/all)
Clean all types when None

        Returns:
Clear statistics
        """
        now = time.time()
        stats = {"deleted": 0, "kept": 0, "errors": 0}

        cache_configs = {
            "compile": (cls.COMPILE_CACHE, cls.COMPILE_CACHE_TTL),
            "harness": (cls.HARNESS_CACHE, cls.HARNESS_CACHE_TTL),
            "exec": (cls.EXEC_CACHE, cls.EXEC_CACHE_TTL),
            "temp": (cls.TEMP_CACHE, cls.TEMP_CACHE_TTL),
        }

        if cache_type and cache_type != "all":
            cache_configs = {k: v for k, v in cache_configs.items() if k == cache_type}

        for cache_name, (cache_dir, ttl) in cache_configs.items():
            if not cache_dir.exists():
                continue

            try:
                for item in cache_dir.iterdir():
                    try:
                        # Check modification time
                        mtime = item.stat().st_mtime
                        if now - mtime > ttl:
                            if item.is_dir():
                                shutil.rmtree(item)
                            else:
                                item.unlink()
                            stats["deleted"] += 1
                        else:
                            stats["kept"] += 1
                    except Exception as e:
                        stats["errors"] += 1
            except Exception as e:
                stats["errors"] += 1

        return stats

    @classmethod
    def clean_all(cls) -> Dict[str, int]:
        """Clear all caches"""
        stats = {"deleted": 0, "kept": 0, "errors": 0}

        if cls.CACHE_ROOT.exists():
            try:
                for item in cls.CACHE_ROOT.iterdir():
                    try:
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
                        stats["deleted"] += 1
                    except Exception:
                        stats["errors"] += 1
            except Exception:
                stats["errors"] += 1

        return stats

    @classmethod
    def get_cache_stats(cls) -> Dict[str, any]:
        """Get cache statistics"""
        stats = {
            "cache_root": str(cls.CACHE_ROOT),
            "exists": cls.CACHE_ROOT.exists(),
            "total_size_mb": 0,
            "file_count": 0,
            "dirs": {}
        }

        if not cls.CACHE_ROOT.exists():
            return stats

        try:
            for cache_dir in [cls.COMPILE_CACHE, cls.HARNESS_CACHE,
                              cls.EXEC_CACHE, cls.TEMP_CACHE]:
                if cache_dir.exists():
                    size = 0
                    count = 0
                    for item in cache_dir.rglob("*"):
                        if item.is_file():
                            size += item.stat().st_size
                            count += 1

                    stats["dirs"][cache_dir.name] = {
                        "size_mb": round(size / 1024 / 1024, 2),
                        "file_count": count
                    }
                    stats["total_size_mb"] += size
                    stats["file_count"] += count

            stats["total_size_mb"] = round(stats["total_size_mb"] / 1024 / 1024, 2)
        except Exception:
            pass

        return stats


# Global cache manager instance
cache_manager = CacheManager()


def ensure_safe_output_path(output_path: Path) -> Path:
    """
Ensure the output path is safe (not in the benchmark directory)

    Args:
output_path: expected output path

    Returns:
# Safe output path (if the original path is not safe, return the path in the cache directory)
    """
    if CacheManager.is_benchmark_path(output_path):
        # If the path is in the benchmark, redirect to the cache directory
        cache_dir = CacheManager.get_temp_dir("safe_output")
        safe_path = cache_dir / output_path.name
        return safe_path
    return output_path


def cleanup_session_cache(session_id: str):
    """# Clear cache for a specific session"""
    session_cache = CacheManager.EXEC_CACHE / session_id
    if session_cache.exists():
        shutil.rmtree(session_cache)


# Initialize
CacheManager.initialize()
