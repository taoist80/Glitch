"""Unit tests for MCP configuration loader.

Tests YAML parsing, environment variable expansion, and validation.
"""

import os
import tempfile
from pathlib import Path
import pytest
import yaml

from glitch.mcp.loader import (
    load_mcp_config,
    _expand_env_vars,
    _expand_env_vars_in_dict,
)
from glitch.mcp.types import MCPServerConfig, MCPConfig


class TestEnvVarExpansion:
    """Test environment variable expansion."""
    
    def test_expand_simple_var(self):
        """Test expanding a single environment variable."""
        os.environ["TEST_VAR"] = "test_value"
        result = _expand_env_vars("prefix_${TEST_VAR}_suffix")
        assert result == "prefix_test_value_suffix"
    
    def test_expand_multiple_vars(self):
        """Test expanding multiple environment variables."""
        os.environ["VAR1"] = "value1"
        os.environ["VAR2"] = "value2"
        result = _expand_env_vars("${VAR1}_middle_${VAR2}")
        assert result == "value1_middle_value2"
    
    def test_expand_missing_var(self):
        """Test expanding missing variable returns empty string."""
        result = _expand_env_vars("${NONEXISTENT_VAR}")
        assert result == ""
    
    def test_expand_no_vars(self):
        """Test string without variables is unchanged."""
        result = _expand_env_vars("no variables here")
        assert result == "no variables here"
    
    def test_expand_dict(self):
        """Test expanding variables in nested dictionary."""
        os.environ["TEST_KEY"] = "test_api_key"
        os.environ["TEST_TYPE"] = "cloud"
        
        data = {
            "key": "${TEST_KEY}",
            "type": "${TEST_TYPE}",
            "nested": {
                "value": "${TEST_KEY}"
            },
            "list": ["${TEST_TYPE}", "static"]
        }
        
        result = _expand_env_vars_in_dict(data)
        
        assert result["key"] == "test_api_key"
        assert result["type"] == "cloud"
        assert result["nested"]["value"] == "test_api_key"
        assert result["list"] == ["cloud", "static"]


class TestMCPConfigLoader:
    """Test MCP configuration loading."""
    
    def test_load_valid_config(self, tmp_path):
        """Test loading a valid configuration file."""
        config_file = tmp_path / "mcp_servers.yaml"
        config_file.write_text("""
mcp_servers:
  test_server:
    enabled: true
    transport: stdio
    command: npx
    args:
      - -y
      - test-server
    prefix: test
""")
        
        config = load_mcp_config(config_file)
        
        assert len(config.servers) == 1
        assert "test_server" in config.servers
        
        server = config.servers["test_server"]
        assert server.name == "test_server"
        assert server.enabled is True
        assert server.transport == "stdio"
        assert server.command == "npx"
        assert server.args == ["-y", "test-server"]
        assert server.prefix == "test"
    
    def test_load_with_env_vars(self, tmp_path):
        """Test loading config with environment variable expansion."""
        os.environ["TEST_API_KEY"] = "secret_key_123"
        os.environ["TEST_HOST"] = "192.168.1.1"
        
        config_file = tmp_path / "mcp_servers.yaml"
        config_file.write_text("""
mcp_servers:
  test_server:
    enabled: true
    transport: stdio
    command: npx
    args:
      - test-server
    env:
      API_KEY: ${TEST_API_KEY}
      HOST: ${TEST_HOST}
""")
        
        config = load_mcp_config(config_file)
        server = config.servers["test_server"]
        
        assert server.env["API_KEY"] == "secret_key_123"
        assert server.env["HOST"] == "192.168.1.1"
    
    def test_load_disabled_server(self, tmp_path):
        """Test that disabled servers are loaded but not enabled."""
        config_file = tmp_path / "mcp_servers.yaml"
        config_file.write_text("""
mcp_servers:
  enabled_server:
    enabled: true
    transport: stdio
    command: test
  disabled_server:
    enabled: false
    transport: stdio
    command: test
""")
        
        config = load_mcp_config(config_file)
        
        assert len(config.servers) == 2
        assert config.servers["enabled_server"].enabled is True
        assert config.servers["disabled_server"].enabled is False
        
        enabled = config.get_enabled_servers()
        assert len(enabled) == 1
        assert enabled[0].name == "enabled_server"
    
    def test_load_missing_file(self):
        """Test loading missing config file returns empty config."""
        config = load_mcp_config(Path("/nonexistent/path/config.yaml"))
        
        assert len(config.servers) == 0
    
    def test_load_empty_file(self, tmp_path):
        """Test loading empty config file returns empty config."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")
        
        config = load_mcp_config(config_file)
        
        assert len(config.servers) == 0
    
    def test_load_invalid_yaml(self, tmp_path):
        """Test loading invalid YAML raises error."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: syntax: [")
        
        with pytest.raises(ValueError, match="Failed to parse YAML"):
            load_mcp_config(config_file)
    
    def test_load_missing_command_for_stdio(self, tmp_path):
        """Test that stdio transport requires command."""
        config_file = tmp_path / "mcp_servers.yaml"
        config_file.write_text("""
mcp_servers:
  bad_server:
    enabled: true
    transport: stdio
    args:
      - test
""")
        
        config = load_mcp_config(config_file)
        
        # Server should be skipped due to validation error
        assert "bad_server" not in config.servers
    
    def test_load_with_tool_filters(self, tmp_path):
        """Test loading config with tool filters."""
        config_file = tmp_path / "mcp_servers.yaml"
        config_file.write_text("""
mcp_servers:
  filtered_server:
    enabled: true
    transport: stdio
    command: npx
    args:
      - test-server
    tool_filters:
      allowed:
        - tool1
        - tool2
      rejected:
        - tool3
""")
        
        config = load_mcp_config(config_file)
        server = config.servers["filtered_server"]
        
        assert server.tool_filters["allowed"] == ["tool1", "tool2"]
        assert server.tool_filters["rejected"] == ["tool3"]


class TestMCPServerConfig:
    """Test MCPServerConfig dataclass validation."""
    
    def test_valid_stdio_config(self):
        """Test creating valid stdio config."""
        config = MCPServerConfig(
            name="test",
            transport="stdio",
            command="npx",
            args=["-y", "test"],
        )
        
        assert config.name == "test"
        assert config.transport == "stdio"
        assert config.enabled is True
    
    def test_missing_command_raises_error(self):
        """Test that enabled stdio transport without command raises error."""
        with pytest.raises(ValueError, match="command is required"):
            MCPServerConfig(
                name="test",
                enabled=True,
                transport="stdio",
                command="",
            )
    
    def test_disabled_server_no_validation(self):
        """Test that disabled servers skip validation."""
        config = MCPServerConfig(
            name="test",
            enabled=False,
            transport="stdio",
            command="",
        )
        
        assert config.enabled is False


class TestMCPConfig:
    """Test MCPConfig dataclass."""
    
    def test_get_enabled_servers(self):
        """Test filtering enabled servers."""
        config = MCPConfig(servers={
            "enabled1": MCPServerConfig(name="enabled1", enabled=True, command="test"),
            "disabled": MCPServerConfig(name="disabled", enabled=False, command="test"),
            "enabled2": MCPServerConfig(name="enabled2", enabled=True, command="test"),
        })
        
        enabled = config.get_enabled_servers()
        
        assert len(enabled) == 2
        assert all(s.enabled for s in enabled)
        assert set(s.name for s in enabled) == {"enabled1", "enabled2"}
