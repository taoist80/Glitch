# MCP Server Integration

This document describes the MCP (Model Context Protocol) server integration in the Glitch agent.

## Overview

The MCP integration allows Glitch to connect to external MCP servers and use their tools. This enables extending Glitch's capabilities with external services like UniFi Network Controller, AWS documentation, and more.

## Architecture

```
┌─────────────────────────────────────┐
│   mcp_servers.yaml (config)         │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│   MCPServerManager                  │
│   - Loads config                    │
│   - Creates MCPClient instances     │
│   - Manages lifecycle               │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│   Strands MCPClient (per server)    │
│   - Connects to MCP server          │
│   - Discovers tools                 │
│   - Exposes as ToolProvider         │
└────────────┬────────────────────────┘
             │
             ▼
┌─────────────────────────────────────┐
│   Strands Agent                     │
│   - Uses MCP tools + local tools    │
└─────────────────────────────────────┘
```

## Configuration

MCP servers are configured in `agent/mcp_servers.yaml`:

```yaml
mcp_servers:
  unifi:
    enabled: true
    transport: stdio
    command: npx
    args:
      - -y
      - unifi-mcp-server
    env:
      UNIFI_API_KEY: ${UNIFI_API_KEY}
      UNIFI_API_TYPE: ${UNIFI_API_TYPE}
    prefix: unifi
    tool_filters:
      allowed: []
      rejected: []
```

### Configuration Fields

- **enabled**: Whether to load this server (default: `true`)
- **transport**: Connection type (`stdio`, `sse`, `streamable_http`)
- **command**: Command to execute (for `stdio` transport)
- **args**: Arguments for the command
- **env**: Environment variables (supports `${VAR}` expansion)
- **prefix**: Tool name prefix (currently not applied by Strands)
- **tool_filters**: Control which tools to load
  - **allowed**: List of tool names or regex patterns to include
  - **rejected**: List of tool names or regex patterns to exclude

## Environment Variables

Environment variables can be referenced in config using `${VAR_NAME}` syntax:

```yaml
env:
  UNIFI_API_KEY: ${UNIFI_API_KEY}
  UNIFI_API_TYPE: cloud
```

Set these before running the agent:

```bash
export UNIFI_API_KEY=your_api_key_here
export UNIFI_API_TYPE=cloud
```

## UniFi MCP Server Setup

### Cloud Mode (Recommended)

1. Get an API key from [UniFi Site Manager](https://account.ui.com/api-keys)
2. Set environment variables:
   ```bash
   export UNIFI_API_KEY=your_key
   export UNIFI_API_TYPE=cloud
   ```
3. Restart the agent

### Local Mode

For on-premises UniFi controllers:

```bash
export UNIFI_API_KEY=your_local_admin_key
export UNIFI_API_TYPE=local
export UNIFI_LOCAL_HOST=192.168.1.1  # Your gateway IP
```

## Available Tools

Once configured, the UniFi MCP server provides 74 tools across categories:

- **Device Management**: List devices, get device details, restart devices
- **Network Configuration**: Manage networks, VLANs, port forwarding
- **Client Management**: List clients, block/unblock devices
- **WiFi/SSID Management**: Configure wireless networks
- **Security & Firewall**: Manage firewall rules
- **QoS**: Quality of service settings
- **Backup & Operations**: System backups, restores
- **Multi-Site Management**: Manage multiple sites
- **Network Topology**: Discover network structure

See the [UniFi MCP Server documentation](https://github.com/enuno/unifi-mcp-server) for complete tool reference.

## Usage in Agent Code

### Accessing MCP Status

```python
from glitch import create_glitch_agent

agent = create_glitch_agent()

# Get MCP server status
status = agent.get_status()
print(status["mcp_servers"])
# {
#   "total_servers": 1,
#   "enabled_servers": 1,
#   "connected_clients": 1,
#   "server_names": ["unifi"]
# }
```

### Custom Config Path

```python
from pathlib import Path
from glitch import AgentConfig, GlitchAgent

config = AgentConfig(
    session_id="test-session",
    memory_id="test-memory",
    mcp_config_path=Path("/custom/path/mcp_servers.yaml")
)

agent = GlitchAgent(config)
```

## Adding More MCP Servers

Example: Adding AWS documentation server:

```yaml
mcp_servers:
  unifi:
    # ... existing config ...
  
  aws-docs:
    enabled: true
    transport: stdio
    command: uvx
    args:
      - awslabs.aws-documentation-mcp-server@latest
    prefix: aws_docs
    tool_filters:
      allowed:
        - search_documentation
        - read_documentation
```

## Testing

Run MCP tests:

```bash
cd agent
PYTHONPATH=src python3 -m pytest tests/test_mcp_loader.py -v
```

Run integration test:

```bash
python3 tests/test_mcp_integration.py
```

## Troubleshooting

### "No servers connected"

Check that:
1. Required environment variables are set
2. MCP server package is installed (`npx unifi-mcp-server` works)
3. API credentials are valid

### "Command not found"

Ensure the MCP server package is available:

```bash
# Test UniFi server directly
npx -y unifi-mcp-server
```

### Tool filters not working

The `prefix` and advanced `tool_filters` features depend on Strands MCPClient support. Currently only basic tool filtering works.

## Module Reference

### `glitch.mcp.types`

- `MCPServerConfig`: Server configuration dataclass
- `MCPConfig`: Top-level configuration container

### `glitch.mcp.loader`

- `load_mcp_config(path)`: Load and parse YAML config
- `get_default_mcp_config_path()`: Get default config path

### `glitch.mcp.manager`

- `MCPServerManager`: Manages server lifecycle
- `get_tool_providers()`: Returns list of MCPClient instances
- `get_status()`: Returns server status dictionary

## Future Enhancements

- [ ] Support for SSE transport
- [ ] Support for Streamable HTTP transport
- [ ] Dynamic MCP server registration at runtime
- [ ] Tool name prefixing (depends on Strands support)
- [ ] Per-server health checks and reconnection
- [ ] UniFi-specific skills for common network operations
