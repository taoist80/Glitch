"""MCP configuration loader.

This module handles loading and parsing MCP server configurations
from YAML files with environment variable expansion.
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, Dict, Any

import yaml

from glitch.mcp.types import MCPServerConfig, MCPConfig

logger = logging.getLogger(__name__)


def get_default_mcp_config_path() -> Path:
    """Get the default path for MCP server configuration.
    
    Returns:
        Path to agent/mcp_servers.yaml
    """
    # From agent/src/glitch/mcp/loader.py -> agent/src/glitch/mcp -> agent/src/glitch -> agent/src -> agent
    return Path(__file__).parent.parent.parent.parent / "mcp_servers.yaml"


def _expand_env_vars(value: str) -> str:
    """Expand environment variables in string values.
    
    Supports ${VAR_NAME} syntax. Missing variables are replaced with empty string.
    
    Args:
        value: String potentially containing ${VAR} placeholders
        
    Returns:
        String with environment variables expanded
    """
    pattern = r'\$\{([^}]+)\}'
    
    def replacer(match):
        var_name = match.group(1)
        return os.environ.get(var_name, '')
    
    return re.sub(pattern, replacer, value)


def _expand_env_vars_in_dict(data: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively expand environment variables in dictionary values.
    
    Args:
        data: Dictionary with potential environment variable references
        
    Returns:
        Dictionary with expanded values
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = _expand_env_vars(value)
        elif isinstance(value, dict):
            result[key] = _expand_env_vars_in_dict(value)
        elif isinstance(value, list):
            result[key] = [
                _expand_env_vars(item) if isinstance(item, str) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def load_mcp_config(path: Optional[Path] = None) -> MCPConfig:
    """Load MCP server configuration from YAML file.
    
    Args:
        path: Path to configuration file (defaults to agent/mcp_servers.yaml)
        
    Returns:
        MCPConfig with loaded server configurations
        
    Raises:
        FileNotFoundError: If config file doesn't exist
        ValueError: If config is invalid
    """
    config_path = path or get_default_mcp_config_path()
    
    if not config_path.exists():
        logger.warning(f"MCP config file not found: {config_path}")
        return MCPConfig(servers={})
    
    try:
        with open(config_path, 'r') as f:
            raw_config = yaml.safe_load(f)
        
        if not raw_config:
            logger.warning(f"Empty MCP config file: {config_path}")
            return MCPConfig(servers={})
        
        if not isinstance(raw_config, dict) or 'mcp_servers' not in raw_config:
            raise ValueError("Config must contain 'mcp_servers' key")
        
        servers = {}
        for name, server_data in raw_config['mcp_servers'].items():
            if not isinstance(server_data, dict):
                logger.warning(f"Skipping invalid server config: {name}")
                continue
            
            # Expand environment variables
            server_data = _expand_env_vars_in_dict(server_data)
            
            # Create server config
            try:
                servers[name] = MCPServerConfig(
                    name=name,
                    enabled=server_data.get('enabled', True),
                    transport=server_data.get('transport', 'stdio'),
                    command=server_data.get('command', ''),
                    args=server_data.get('args', []),
                    env=server_data.get('env', {}),
                    prefix=server_data.get('prefix'),
                    tool_filters=server_data.get('tool_filters', {"allowed": [], "rejected": []}),
                )
                logger.info(f"Loaded MCP server config: {name}")
            except ValueError as e:
                logger.error(f"Invalid config for server '{name}': {e}")
                continue
        
        return MCPConfig(servers=servers)
        
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML config: {e}")
    except Exception as e:
        raise ValueError(f"Failed to load MCP config: {e}")
