"""
Protocol Adapters

Provides adapters for integrating PLCHaT with different protocols:
- MCP Adapter: Model Context Protocol support
- Native Adapter: Direct Python API support
"""

from .mcp_adapter import (
    MCPTool,
    MCPToolCall,
    MCPToolResult,
    MCPAdapter,
)

__all__ = [
    "MCPTool",
    "MCPToolCall",
    "MCPToolResult",
    "MCPAdapter",
]
