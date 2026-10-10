"""
Tool Routing Module (R Component)

Provides unified tool routing and dispatch:
- BaseTool: Abstract interface for all tools
- ToolRouter: Main router for tool dispatch
- ToolRegistry: Tool registration and lookup
- Routing policies: Coverage-guided, prototype-aware, LLM-based, etc.

Usage:
    from harness.routing import ToolRouter, ToolType, register_tool, LLMPolicy
    from tools.smtsmt import SMTSolverTool

    # Register tools
    register_tool(ToolType.SMT_SOLVER, SMTSolverTool)

    # Create router with LLM policy
    router = ToolRouter(
        benchmark_root="path/to/benchmark",
        default_strategy=RoutingStrategy.LLM
    )

    # Route requests
    response = router.route(request)
"""

from .base import (
    ToolType,
    ToolMetadata,
    BaseTool,
    ToolExecutionError,
    ValidationError,
)

from .registry import (
    ToolRegistry,
    register_tool,
    get_tool,
    set_benchmark_root,
    list_tools,
)

from .policies import (
    RoutingStrategy,
    RoutingContext,
    BaseRoutingPolicy,
    CoverageGuidedPolicy,
    PrototypeAwarePolicy,
    RoundRobinPolicy,
    ManualPolicy,
    create_policy,
)

from .llm_policy import (
    LLMPolicy,
    LLMRoutingContext,
)

from .router import ToolRouter


__all__ = [
    # Base interface
    "ToolType",
    "ToolMetadata",
    "BaseTool",
    "ToolExecutionError",
    "ValidationError",

    # Registry
    "ToolRegistry",
    "register_tool",
    "get_tool",
    "set_benchmark_root",
    "list_tools",

    # Policies
    "RoutingStrategy",
    "RoutingContext",
    "BaseRoutingPolicy",
    "CoverageGuidedPolicy",
    "PrototypeAwarePolicy",
    "RoundRobinPolicy",
    "ManualPolicy",
    "create_policy",

    # LLM Policy
    "LLMPolicy",
    "LLMRoutingContext",

    # Router
    "ToolRouter",
]
