"""
PLCHaT Compilation Cache Manager

Manage cross-iteration compilation cache to avoid recompiling the same ST and harness code.
Built based on CacheManager, following the same file management principles.
"""
import os
import sys
import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime, timedelta

# Add parent directory to path for imports
CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

from harness.compiler.cache_manager import CacheManager


class CompilationCacheManager:
    """
Compilation cache manager

Cache the compiled binary file, using the content hash of ST+harness as the key.
Follow the safety principles of CacheManager and do not pollute the benchmark directory.

Cache structure:
        /tmp/plchat_cache/compile_reuse/
            └── {cache_key}/
# compiled binary file
# Metadata (time, hash, etc.)
# ST source copy
# Copy of Harness source code
    """

    # cache root directory
    CACHE_ROOT = CacheManager.CACHE_ROOT / "compile_reuse"

    # Cache expiration time (seconds)
    CACHE_TTL = 24 * 3600  # 24 hours

    # Metadata filename
    METADATA_FILE = "metadata.json"
    BINARY_NAME = "plc_coverage_harness"

    @classmethod
    def initialize(cls):
        """# Initialize cache directory"""
        cls.CACHE_ROOT.mkdir(parents=True, exist_ok=True)

    @classmethod
    def compute_cache_key(cls, st_content: str, harness_content: str) -> str:
        """
Calculate cache key

Based on content hash of ST and harness, ensure recompilation when content changes.

        Args:
st_content: ST source code content
harness_content: Harness source code content

        Returns:
16-character cache key (8-bit ST hash + 8-bit Harness hash)
        """
        st_hash = hashlib.sha256(st_content.encode('utf-8')).hexdigest()[:8]
        harness_hash = hashlib.sha256(harness_content.encode('utf-8')).hexdigest()[:8]
        return f"{st_hash}_{harness_hash}"

    @classmethod
    def get_cache_dir(cls, cache_key: str) -> Path:
        """Get the directory of the specified cache key"""
        cls.initialize()
        cache_dir = cls.CACHE_ROOT / cache_key
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @classmethod
    def is_cache_valid(cls, cache_key: str) -> bool:
        """
# Check if cache is valid

Check condition:
1. The cache directory exists
2. Metadata file exists and is valid
3. Binary file exists
4. Not expired

        Args:
cache_key: cache key

        Returns:
Whether the cache is valid
        """
        cache_dir = cls.CACHE_ROOT / cache_key
        if not cache_dir.exists():
            return False

        metadata_path = cache_dir / cls.METADATA_FILE
        if not metadata_path.exists():
            return False

        binary_path = cache_dir / cls.BINARY_NAME
        if not binary_path.exists():
            return False

        # Check if expired
        try:
            mtime = binary_path.stat().st_mtime
            if time.time() - mtime > cls.CACHE_TTL:
                return False
        except OSError:
            return False

        return True

    @classmethod
    def get_cached_binary(cls, cache_key: str) -> Optional[Path]:
        """
Get the cached binary file path

        Args:
cache_key: cache key

        Returns:
Binary file path, returns None if cache is invalid
        """
        if not cls.is_cache_valid(cache_key):
            return None

        cache_dir = cls.CACHE_ROOT / cache_key
        binary_path = cache_dir / cls.BINARY_NAME
        return binary_path if binary_path.exists() else None

    @classmethod
    def save_compilation(
        cls,
        cache_key: str,
        binary_path: Path,
        st_content: str,
        harness_content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
Save the compilation result to cache

        Args:
cache_key: cache key
binary_path: Path to the compiled binary file
st_content: ST source code content
harness_content: Harness source code content
metadata: additional metadata

        Returns:
# whether save was successful
        """
        try:
            cache_dir = cls.get_cache_dir(cache_key)

            # Copy binary file
            cached_binary = cache_dir / cls.BINARY_NAME
            shutil.copy2(binary_path, cached_binary)

            # Save source code copy (for verification)
            (cache_dir / "st_source").write_text(st_content, encoding='utf-8')
            (cache_dir / "harness_source").write_text(harness_content, encoding='utf-8')

            # Save metadata
            meta = {
                "created_at": datetime.now().isoformat(),
                "cache_key": cache_key,
                "binary_size": cached_binary.stat().st_size,
            }
            if metadata:
                meta.update(metadata)

            (cache_dir / cls.METADATA_FILE).write_text(
                json.dumps(meta, indent=2),
                encoding='utf-8'
            )

            return True

        except Exception as e:
            # When it fails, it does not affect the main flow, only logs.
            print(f"Warning: Failed to save compilation cache: {e}")
            return False

    @classmethod
    def get_cache_info(cls, cache_key: str) -> Optional[Dict[str, Any]]:
        """
Get cache information

        Args:
cache_key: cache key

        Returns:
Cache info dictionary, returns None if cache does not exist.
        """
        if not cls.is_cache_valid(cache_key):
            return None

        cache_dir = cls.CACHE_ROOT / cache_key
        metadata_path = cache_dir / cls.METADATA_FILE

        try:
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)

            binary_path = cache_dir / cls.BINARY_NAME
            metadata["cached"] = True
            metadata["binary_path"] = str(binary_path)
            metadata["age_hours"] = (time.time() - binary_path.stat().st_mtime) / 3600

            return metadata

        except Exception:
            return None

    @classmethod
    def clean_expired_caches(cls) -> Dict[str, int]:
        """
Clear expired cache

        Returns:
Clear statistics
        """
        stats = {"deleted": 0, "kept": 0, "errors": 0}

        if not cls.CACHE_ROOT.exists():
            return stats

        now = time.time()

        try:
            for cache_dir in cls.CACHE_ROOT.iterdir():
                if not cache_dir.is_dir():
                    continue

                try:
                    # Check the time of the binary file
                    binary_path = cache_dir / cls.BINARY_NAME
                    if binary_path.exists():
                        mtime = binary_path.stat().st_mtime
                        if now - mtime > cls.CACHE_TTL:
                            shutil.rmtree(cache_dir)
                            stats["deleted"] += 1
                        else:
                            stats["kept"] += 1
                    else:
                        # Binary does not exist, clean the entire directory
                        shutil.rmtree(cache_dir)
                        stats["deleted"] += 1

                except Exception as e:
                    stats["errors"] += 1

        except Exception:
            stats["errors"] += 1

        return stats

    @classmethod
    def get_all_cache_stats(cls) -> Dict[str, Any]:
        """
Get all cached statistics

        Returns:
statistics dictionary
        """
        stats = {
            "cache_root": str(cls.CACHE_ROOT),
            "exists": cls.CACHE_ROOT.exists(),
            "total_size_mb": 0,
            "cache_count": 0,
            "caches": []
        }

        if not cls.CACHE_ROOT.exists():
            return stats

        try:
            for cache_dir in cls.CACHE_ROOT.iterdir():
                if not cache_dir.is_dir():
                    continue

                info = cls.get_cache_info(cache_dir.name)
                if info:
                    stats["cache_count"] += 1
                    stats["total_size_mb"] += info.get("binary_size", 0) / (1024 * 1024)
                    stats["caches"].append({
                        "key": cache_dir.name,
                        "age_hours": round(info.get("age_hours", 0), 1),
                        "size_mb": round(info.get("binary_size", 0) / (1024 * 1024), 2)
                    })

            stats["total_size_mb"] = round(stats["total_size_mb"], 2)

        except Exception:
            pass

        return stats


# Initialize
CompilationCacheManager.initialize()
