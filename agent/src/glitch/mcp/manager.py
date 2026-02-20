"""MCP server manager.

This module manages the lifecycle of MCP server connections,
creating MCPClient instances and providing them to the agent.
"""

import logging
from typing import List, Optional
from pathlib import Path

from mcp import stdio_client, StdioServerParameters
from strands.tools.mcp import MCPClient

from glitch.mcp.types import MCPConfig, MCPServerConfig
from glitch.mcp.loader import load_mcp_config

logger = logging.getLogger(__name__)


class MCPServerManager:
    """Manages MCP server connections and client lifecycle.
    
    Attributes:
        config: MCPConfig with server definitions
        clients: Dictionary of MCPClient instances by server name
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """Initialize the MCP server manager.
        
        Args:
            config_path: Optional path to MCP config file
        """
        self.config = load_mcp_config(config_path)
        self.clients: dict[str, MCPClient] = {}
        self._initialize_clients()
    
    def _initialize_clients(self) -> None:
        """Create MCPClient instances for all enabled servers."""
        enabled_servers = self.config.get_enabled_servers()
        
        if not enabled_servers:
            logger.info("No enabled MCP servers found")
            return
        
        for server in enabled_servers:
            try:
                client = self._create_client(server)
                self.clients[server.name] = client
                logger.info(f"Initialized MCP client: {server.name}")
            except Exception as e:
                logger.error(f"Failed to create MCP client for '{server.name}': {e}")
    
    def _create_client(self, config: MCPServerConfig) -> MCPClient:
        """Create an MCPClient for the given server configuration.
        
        Args:
            config: Server configuration
            
        Returns:
            Configured MCPClient instance
            
        Raises:
            ValueError: If transport type is unsupported
        """
        if config.transport == "stdio":
            # Create stdio transport parameters
            server_params = StdioServerParameters(
                command=config.command,
                args=config.args,
                env=config.env if config.env else None,
            )
            
            # Build tool filters (convert empty lists to None for MCPClient)
            tool_filters = None
            if config.tool_filters:
                filters = {}
                if config.tool_filters.get("allowed"):
                    filters["allowed"] = config.tool_filters["allowed"]
                if config.tool_filters.get("rejected"):
                    filters["rejected"] = config.tool_filters["rejected"]
                if filters:
                    tool_filters = filters
            
            # Create MCPClient with stdio transport
            # Note: prefix parameter is passed separately, not to MCPClient constructor
            client_kwargs = {"tool_filters": tool_filters} if tool_filters else {}
            
            client = MCPClient(
                lambda: stdio_client(server_params),
                **client_kwargs,
            )
            
            # Store prefix for later use if needed
            if config.prefix:
                # Note: Strands MCPClient may not support runtime prefix modification
                # This would need to be handled by wrapping tool names in the agent
                logger.debug(f"Tool prefix '{config.prefix}' configured for {config.name} (may not be applied)")
            
            return client
        
        elif config.transport == "sse":
            # Future: implement SSE transport
            raise ValueError(f"SSE transport not yet implemented for '{config.name}'")
        
        elif config.transport == "streamable_http":
            # Future: implement streamable HTTP transport
            raise ValueError(f"Streamable HTTP transport not yet implemented for '{config.name}'")
        
        else:
            raise ValueError(f"Unknown transport type: {config.transport}")
    
    def get_tool_providers(self) -> List[MCPClient]:
        """Get list of MCPClient instances to pass to Agent.
        
        Returns:
            List of MCPClient tool providers
        """
        return list(self.clients.values())
    
    def get_server_names(self) -> List[str]:
        """Get list of connected server names.
        
        Returns:
            List of server names with active clients
        """
        return list(self.clients.keys())
    
    def get_status(self) -> dict[str, any]:
        """Get status information about MCP servers.
        
        Returns:
            Dictionary with server status information
        """
        return {
            "total_servers": len(self.config.servers),
            "enabled_servers": len(self.config.get_enabled_servers()),
            "connected_clients": len(self.clients),
            "server_names": self.get_server_names(),
        }
