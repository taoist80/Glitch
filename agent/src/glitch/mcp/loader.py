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
    # Runtime packaging layout can differ (source tree, wheel/site-packages, container).
    # Prefer the first existing file from common locations, then return the most likely
    # project-root path for diagnostics.
    env_path = (os.environ.get("GLITCH_MCP_CONFIG_PATH") or "").strip()
    if env_path:
        return Path(env_path).expanduser()

    candidates = []
    cwd = Path.cwd()
    candidates.extend(
        [
            cwd / "mcp_servers.yaml",
            cwd / "agent" / "mcp_servers.yaml",
            Path("/app/mcp_servers.yaml"),
            Path("/app/agent/mcp_servers.yaml"),
        ]
    )

    here = Path(__file__).resolve()
    for parent in [here.parent, *here.parents]:
        candidates.append(parent / "mcp_servers.yaml")

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate

    # Fallback path used in warning messages if nothing exists.
    return here.parent.parent.parent.parent / "mcp_servers.yaml"


def _expand_env_vars(value: str, strict_env: bool = False) -> str:
    """Expand environment variables in string values.

    Supports ${VAR_NAME} syntax. When strict_env is False, missing variables
    are replaced with empty string. When strict_env is True, missing variables
    raise ValueError (fail fast for required vars).

    Args:
        value: String potentially containing ${VAR} placeholders
        strict_env: If True, raise ValueError when a referenced env var is unset

    Returns:
        String with environment variables expanded

    Raises:
        ValueError: If strict_env is True and a referenced variable is unset
    """
    pattern = r"\$\{([^}]+)\}"

    def replacer(match: re.Match[str]) -> str:
        var_name = match.group(1)
        val = os.environ.get(var_name)
        if val is None:
            if strict_env:
                raise ValueError(
                    f"Required environment variable ${{{var_name}}} is not set. "
                    "Set it or disable strict validation (GLITCH_MCP_STRICT_ENV=false)."
                )
            return ""
        return val

    return re.sub(pattern, replacer, value)


def _expand_env_vars_in_dict(data: Dict[str, Any], strict_env: bool = False) -> Dict[str, Any]:
    """Recursively expand environment variables in dictionary values.

    Args:
        data: Dictionary with potential environment variable references
        strict_env: If True, raise ValueError when a referenced env var is unset

    Returns:
        Dictionary with expanded values
    """
    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            result[key] = _expand_env_vars(value, strict_env=strict_env)
        elif isinstance(value, dict):
            result[key] = _expand_env_vars_in_dict(value, strict_env=strict_env)
        elif isinstance(value, list):
            result[key] = [
                _expand_env_vars(item, strict_env=strict_env) if isinstance(item, str) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def _load_remote_mcp_config_content() -> Optional[str]:
    """If GLITCH_MCP_CONFIG_REMOTE is set (host_alias:remote_path), fetch content via SSH."""
    remote = os.environ.get("GLITCH_MCP_CONFIG_REMOTE", "").strip()
    if not remote or ":" not in remote:
        return None
    host_alias, _, remote_path = remote.partition(":")
    host_alias = host_alias.strip()
    remote_path = remote_path.strip()
    if not host_alias or not remote_path:
        return None
    try:
        import asyncio
        from glitch.tools.ssh_tools import _resolve_host, _get_ssh_private_key
        import asyncssh

        resolved = _resolve_host(host_alias)
        if not resolved:
            logger.warning("GLITCH_MCP_CONFIG_REMOTE: unknown host alias %s", host_alias)
            return None
        key = _get_ssh_private_key()
        if not key:
            logger.warning("GLITCH_MCP_CONFIG_REMOTE: SSH key not configured")
            return None

        async def _fetch() -> str:
            conn = await asyncssh.connect(
                resolved["host"],
                port=resolved["port"],
                username=resolved["user"],
                client_keys=[key],
                known_hosts=None,
            )
            try:
                result = await conn.run(f"cat -- {remote_path!r}")
                if result.exit_status != 0:
                    raise RuntimeError(result.stderr or f"exit {result.exit_status}")
                return result.stdout or ""
            finally:
                conn.close()

        return asyncio.run(_fetch())
    except Exception as e:
        logger.warning("Failed to load remote MCP config from %s: %s", remote, e)
        return None


def load_mcp_config(path: Optional[Path] = None, strict_env: Optional[bool] = None) -> MCPConfig:
    """Load MCP server configuration from YAML file or from a remote host via SSH.

    If GLITCH_MCP_CONFIG_REMOTE is set to "host_alias:remote_path" (e.g. bastion:~/mcp_servers.yaml),
    that file is fetched via SSH and used instead of the local path.

    Args:
        path: Path to configuration file (defaults to agent/mcp_servers.yaml)
        strict_env: If True, raise when ${VAR} is unset. If None, use
            GLITCH_MCP_STRICT_ENV env var (default False).

    Returns:
        MCPConfig with loaded server configurations

    Raises:
        FileNotFoundError: If config file doesn't exist (local path only)
        ValueError: If config is invalid or (when strict_env) a required env var is unset
    """
    if strict_env is None:
        strict_env = os.environ.get("GLITCH_MCP_STRICT_ENV", "false").lower() in ("true", "1", "yes")

    raw_content: Optional[str] = None
    config_path = path or get_default_mcp_config_path()

    remote_content = _load_remote_mcp_config_content()
    if remote_content is not None:
        raw_content = remote_content
        logger.info("Loaded MCP config from remote (GLITCH_MCP_CONFIG_REMOTE)")
    elif config_path.exists():
        with open(config_path, "r") as f:
            raw_content = f.read()

    if not raw_content:
        logger.warning("MCP config file not found: %s", config_path)
        return MCPConfig(servers={})

    try:
        raw_config = yaml.safe_load(raw_content)

        if not raw_config:
            logger.warning("Empty MCP config")
            return MCPConfig(servers={})

        if not isinstance(raw_config, dict) or "mcp_servers" not in raw_config:
            raise ValueError("Config must contain 'mcp_servers' key")

        servers = {}
        for name, server_data in raw_config["mcp_servers"].items():
            if not isinstance(server_data, dict):
                logger.warning("Skipping invalid server config: %s", name)
                continue

            # Expand environment variables (fail fast if strict_env and var missing)
            server_data = _expand_env_vars_in_dict(server_data, strict_env=strict_env)
            
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
                    ssh_host=server_data.get('ssh_host'),
                )
                logger.info("Loaded MCP server config: %s", name)
            except ValueError as e:
                logger.error("Invalid config for server '%s': %s", name, e)
                continue
        
        return MCPConfig(servers=servers)
        
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse YAML config: {e}")
    except Exception as e:
        raise ValueError(f"Failed to load MCP config: {e}")
