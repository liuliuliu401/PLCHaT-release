"""
PLCHaT Configuration Module

Hierarchical configuration loading:
1. Environment variables (highest priority)
2. config/local.yaml (if exists)
3. config/default.yaml (default settings)
4. Code-level defaults (fallback)

Usage:
    from config import get_config, get_model_config
    config = get_config()
    model_cfg = get_model_config("generator")
"""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional
import yaml

# Project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"


def _load_yaml_file(path: Path) -> Dict[str, Any]:
    """Load YAML file safely."""
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Warning: Failed to load {path}: {e}", file=sys.stderr)
        return {}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """Deep merge two dictionaries."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


# Cache for loaded configuration
_config_cache: Optional[Dict[str, Any]] = None


def reload_config() -> Dict[str, Any]:
    """Reload configuration from files and environment."""
    global _config_cache

    # 1. Load default configuration
    config = _load_yaml_file(CONFIG_DIR / "default.yaml")

    # 2. Override with local configuration (if exists)
    local_config = _load_yaml_file(CONFIG_DIR / "local.yaml")
    if local_config:
        config = _deep_merge(config, local_config)

    # 3. Override with environment variables
    env_overrides = {}

    # LLM settings
    if os.getenv("PLCHAT_MODEL"):
        env_overrides.setdefault("llm", {})["model"] = os.getenv("PLCHAT_MODEL")
    if os.getenv("PLCHAT_LLM_PROVIDER"):
        env_overrides.setdefault("llm", {})["provider"] = os.getenv("PLCHAT_LLM_PROVIDER")
    if os.getenv("PLCHAT_LLM_API_KEY"):
        env_overrides.setdefault("llm", {})["api_key"] = os.getenv("PLCHAT_LLM_API_KEY")
    if os.getenv("PLCHAT_LLM_BASE_URL"):
        env_overrides.setdefault("llm", {})["base_url"] = os.getenv("PLCHAT_LLM_BASE_URL")

    # Model-specific API keys (for convenience)
    if os.getenv("DEEPSEEK_API_KEY") and not os.getenv("PLCHAT_LLM_API_KEY"):
        env_overrides.setdefault("llm", {})["api_key"] = os.getenv("DEEPSEEK_API_KEY")
    if os.getenv("OPENAI_API_KEY"):
        # Store separately for profile switching
        env_overrides["_openai_api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("DASHSCOPE_API_KEY"):
        env_overrides["_dashscope_api_key"] = os.getenv("DASHSCOPE_API_KEY")

    # Execution settings
    if os.getenv("MATIEC_PATH"):
        env_overrides.setdefault("execution", {})["matiec_path"] = os.getenv("MATIEC_PATH")
    if os.getenv("CC"):
        env_overrides.setdefault("execution", {})["clang_path"] = os.getenv("CC")

    # Cache settings
    if os.getenv("PLCHAT_COMPILE_CACHE_DIR"):
        env_overrides.setdefault("cache", {})["compilation"] = {}
        env_overrides["cache"]["compilation"]["dir"] = os.getenv("PLCHAT_COMPILE_CACHE_DIR")

    if env_overrides:
        config = _deep_merge(config, env_overrides)

    _config_cache = config
    return config


def get_config() -> Dict[str, Any]:
    """Get current configuration (cached)."""
    if _config_cache is None:
        return reload_config()
    return _config_cache


def get_model_config(agent_type: str = "generator") -> Dict[str, Any]:
    """
    Get model configuration for a specific agent type.

    Args:
        agent_type: One of planner, generator, evaluator, router

    Returns:
        Dictionary with model configuration keys:
        - provider, model, api_key, base_url, temperature, max_tokens
    """
    config = get_config()

    # Check if agent has specific configuration
    agent_cfg = config.get("agents", {}).get(agent_type, {})

    # Resolve model profile if specified
    if "model_profile" in agent_cfg:
        profile_name = agent_cfg["model_profile"]
        profiles = config.get("model_profiles", {})

        if profile_name in profiles:
            # Merge base llm config with profile
            base_llm = config.get("llm", {})
            profile_cfg = profiles[profile_name]

            model_cfg = _deep_merge(base_llm.copy(), profile_cfg)

            # Apply model-specific API key from env if not set
            if profile_name == "openai" and not model_cfg.get("api_key"):
                model_cfg["api_key"] = os.getenv("OPENAI_API_KEY", "")
            if profile_name == "qwen_cloud" and not model_cfg.get("api_key"):
                model_cfg["api_key"] = os.getenv("DASHSCOPE_API_KEY", "")

            # Merge agent-specific overrides
            model_cfg.update({
                "temperature": agent_cfg.get("temperature", model_cfg.get("temperature", 0.3)),
                "max_tokens": agent_cfg.get("max_tokens", model_cfg.get("max_tokens", 4096)),
            })

            return model_cfg

    # Fallback to base llm configuration
    return config.get("llm", {})


def get_cache_config() -> Dict[str, Any]:
    """Get cache configuration."""
    return get_config().get("cache", {})


def get_execution_config() -> Dict[str, Any]:
    """Get execution environment configuration."""
    return get_config().get("execution", {})


def get_tool_config(tool_name: str) -> Dict[str, Any]:
    """Get configuration for a specific tool."""
    tools = get_config().get("tools", {})
    return tools.get(tool_name, {})


def get_benchmark_config() -> Dict[str, Any]:
    """Get benchmark configuration."""
    return get_config().get("benchmark", {})


def get_matiec_path() -> str:
    """Get MatIEC compiler path."""
    cfg = get_execution_config()
    path = cfg.get("matiec_path", "")

    if not path:
        # Try to find iec2c in PATH
        path = os.getenv("MATIEC_PATH", "")

    if not path:
        # Try default installation path
        default_path = "/usr/local/lib/matiec"
        if Path(default_path).exists():
            path = default_path
        elif Path("/usr/bin/iec2c").exists():
            path = "/usr/bin"

    return path


def get_direct_llm_config() -> Dict[str, Any]:
    """
    Get Direct LLM configuration for RQ2 experiments.

    Returns:
        Dictionary with model, api_key, base_url keys.
        Emits warning if api_key is not configured.
    """
    config = get_config()

    # Get tool-specific config
    tool_cfg = config.get("tools", {}).get("direct_llm", {})
    base_llm = config.get("llm", {})

    # Try to get API key from multiple sources (priority order)
    api_key = (
        os.getenv("OPENAI_API_KEY") or  # Direct env var (highest priority)
        os.getenv("PLCHAT_LLM_API_KEY") or  # Generic env var
        os.getenv("DEEPSEEK_API_KEY") or  # Provider-specific
        base_llm.get("api_key") or  # From base llm config
        tool_cfg.get("api_key") or  # From tool config
        ""
    )

    # Warn if API key is not set
    if not api_key:
        import warnings
        warnings.warn(
            "Direct LLM API key not configured. Set one of:\n"
            "  1. Environment variable: OPENAI_API_KEY\n"
            "  2. Environment variable: PLCHAT_LLM_API_KEY\n"
            "  3. In config/local.yaml: llm.api_key\n"
            "  4. In config/local.yaml: tools.direct_llm.api_key\n"
            "Or copy config/local.yaml.example to local.yaml and configure there.",
            RuntimeWarning,
            stacklevel=2
        )

    # Determine model and base_url
    model = tool_cfg.get("model") or base_llm.get("model", "deepseek-v3")
    base_url = tool_cfg.get("base_url") or base_llm.get("base_url", "https://api.deepseek.com")

    # Adjust base_url based on model if needed
    if model.startswith("gpt-") and "openai" not in base_url.lower():
        base_url = "https://api.openai.com/v1"
    elif model.startswith("deepseek") and "deepseek" not in base_url.lower():
        base_url = "https://api.deepseek.com"

    return {
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "max_cycles": tool_cfg.get("max_cycles", 30),
        "timeout_sec": tool_cfg.get("timeout_sec", 300),
    }


def get_cache_dir(cache_type: str) -> Path:
    """
    Get cache directory path for a specific cache type.

    Args:
        cache_type: One of compilation, coverage, schema, harness

    Returns:
        Path object for the cache directory
    """
    cache_cfg = get_cache_config()
    cache_info = cache_cfg.get(cache_type, {})

    dir_path = cache_info.get("dir", f"temp/{cache_type}_cache")

    # Allow environment override
    env_key = f"PLCHAT_{cache_type.upper()}_CACHE_DIR"
    if os.getenv(env_key):
        dir_path = os.getenv(env_key)

    return PROJECT_ROOT / dir_path


def get_experiment_config() -> Dict[str, Any]:
    """Get experiment configuration."""
    return get_config().get("experiments", {})


def get_results_dir(rq_type: str = "default") -> Path:
    """
    Get results directory for experiments.

    Args:
        rq_type: Research question type (rq1, rq2, rq3, default)

    Returns:
        Path object for the results directory
    """
    exp_cfg = get_experiment_config()

    # Get base results directory
    results_dir = exp_cfg.get("results_dir", "output")

    # Allow environment override
    if os.getenv("PLCHAT_RESULTS_DIR"):
        results_dir = os.getenv("PLCHAT_RESULTS_DIR")

    # If relative path, make it relative to project root
    if not Path(results_dir).is_absolute():
        results_path = PROJECT_ROOT / results_dir
    else:
        results_path = Path(results_dir)

    # Create RQ-specific subdirectory if needed
    if rq_type != "default":
        results_path = results_path / f"{rq_type}_results"

    results_path.mkdir(parents=True, exist_ok=True)
    return results_path


def get_temp_work_dir(rq_type: str = "default") -> Path:
    """
    Get temporary working directory for experiments.

    Args:
        rq_type: Research question type (rq1, rq2, rq3, default)

    Returns:
        Path object for the temporary directory
    """
    exp_cfg = get_experiment_config()

    # Get base temp directory
    temp_dir = exp_cfg.get("temp_dir", "temp")

    # Allow environment override
    if os.getenv("PLCHAT_TEMP_DIR"):
        temp_dir = os.getenv("PLCHAT_TEMP_DIR")

    # If relative path, make it relative to project root
    if not Path(temp_dir).is_absolute():
        temp_path = PROJECT_ROOT / temp_dir
    else:
        temp_path = Path(temp_dir)

    # Create RQ-specific subdirectory if needed
    if rq_type != "default":
        temp_path = temp_path / f"temp_{rq_type}"

    temp_path.mkdir(parents=True, exist_ok=True)
    return temp_path


def ensure_cache_dirs():
    """Ensure all cache directories exist."""
    for cache_type in ["compilation", "coverage", "schema", "harness"]:
        cache_dir = get_cache_dir(cache_type)
        cache_dir.mkdir(parents=True, exist_ok=True)


def resolve_model_by_name(model_name: str) -> Dict[str, Any]:
    """
    Resolve model configuration by name or profile.

    Args:
        model_name: Model name or profile name (e.g., "deepseek", "local_qwen_14b")

    Returns:
        Model configuration dictionary
    """
    config = get_config()

    # Check if it's a known profile
    profiles = config.get("model_profiles", {})
    if model_name in profiles:
        return profiles[model_name]

    # Check if it's the current llm config
    current_llm = config.get("llm", {})
    if current_llm.get("model") == model_name:
        return current_llm

    # Return as-is (assume it's a raw model name)
    return {
        "model": model_name,
        "provider": "unknown",
        "base_url": "",
        "api_key": os.getenv("PLCHAT_LLM_API_KEY", ""),
    }


# Initialize cache dirs on import
ensure_cache_dirs()

__all__ = [
    "get_config",
    "get_model_config",
    "get_cache_config",
    "get_execution_config",
    "get_tool_config",
    "get_benchmark_config",
    "get_matiec_path",
    "get_cache_dir",
    "ensure_cache_dirs",
    "reload_config",
    "resolve_model_by_name",
    "get_direct_llm_config",
    "get_experiment_config",
    "get_results_dir",
    "get_temp_work_dir",
]
