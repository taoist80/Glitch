"""Type definitions for MCP server configuration.

This module defines the data structures for configuring and managing
MCP (Model Context Protocol) servers in the Glitch agent.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Literal, Optional


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server.
    
    Attributes:
        name: Unique identifier for this server
        enabled: Whether this server should be loaded
        transport: Transport type (stdio, sse, streamable_http)
        command: Command to execute for stdio transport
        args: Arguments for the command
        env: Environment variables for the server process
        prefix: Prefix for tool names to avoid conflicts
        tool_filters: Filter configuration for tools
    """
    name: str
    enabled: bool = True
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    command: str = ""
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    prefix: Optional[str] = None
    tool_filters: Dict[str, List[str]] = field(default_factory=lambda: {"allowed": [], "rejected": []})
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if self.enabled and self.transport == "stdio" and not self.command:
            raise ValueError(f"MCP server '{self.name}': command is required for stdio transport")


@dataclass
class MCPConfig:
    """Top-level MCP configuration.
    
    Attributes:
        servers: Dictionary of MCP server configurations keyed by name
    """
    servers: Dict[str, MCPServerConfig] = field(default_factory=dict)
    
    def get_enabled_servers(self) -> List[MCPServerConfig]:
        """Get list of enabled server configurations.
        
        Returns:
            List of enabled MCPServerConfig instances
        """
        return [server for server in self.servers.values() if server.enabled]
