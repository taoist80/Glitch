"""MCP (Model Context Protocol) integration for Glitch.

This module provides support for connecting to external MCP servers
and exposing their tools to the Glitch agent.
"""

from glitch.mcp.types import MCPServerConfig, MCPConfig
from glitch.mcp.loader import load_mcp_config, get_default_mcp_config_path
from glitch.mcp.manager import MCPServerManager

__all__ = [
    "MCPServerConfig",
    "MCPConfig",
    "load_mcp_config",
    "get_default_mcp_config_path",
    "MCPServerManager",
]
