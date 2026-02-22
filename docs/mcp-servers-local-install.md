# MCP Servers on Local Host (10.10.110.230)

Per the [VPC Tailscale MCP Routing plan](.cursor/plans/vpc_tailscale_mcp_routing_1b7b125b.plan.md), UniFi and Pi-hole MCP servers run on the local machine **10.10.110.230** (not on the Tailscale EC2 instance) for direct network access to Pi-hole and UniFi and to avoid overloading the t4g.nano gateway.

## Prerequisites

- Python 3.10+ (for UniFi MCP)
- Node.js 18+ (for Pi-hole MCP)
- Network access from 10.10.110.230 to your UniFi controller and Pi-hole instance

## 1. UniFi MCP Server

**Source:** [enuno/unifi-mcp-server](https://github.com/enuno/unifi-mcp-server)

```bash
pip install unifi-mcp-server
```

**Environment:**

- `UNIFI_API_KEY` – from UniFi Site Manager → Settings → Control Plane → Integrations
- `UNIFI_API_TYPE=local`
- `UNIFI_LOCAL_HOST=<your-unifi-gateway-ip>`
- Optional: `UNIFI_LOCAL_PORT=443`, `UNIFI_LOCAL_VERIFY_SSL=false`

**Run once:** `unifi-mcp-server`

## 2. Pi-hole MCP Server

**Source:** [aplaceforallmystuff/mcp-pihole](https://github.com/aplaceforallmystuff/mcp-pihole)

```bash
npm install -g mcp-pihole-server
```

**Environment:**

- `PIHOLE_URL` – e.g. `http://pihole.local:8080` or your Pi-hole host:port
- `PIHOLE_PASSWORD` – app password from Pi-hole v6 (Settings → API)

**Run once:** `mcp-pihole-server` (or `npx mcp-pihole-server`)

## 3. Optional: systemd services (always-on)

Create these on 10.10.110.230 so both MCP servers start on boot and restart on failure.

### UniFi MCP – `/etc/systemd/system/unifi-mcp.service`

```ini
[Unit]
Description=UniFi MCP Server
After=network.target

[Service]
Type=simple
Environment="UNIFI_API_KEY=your-api-key-here"
Environment="UNIFI_API_TYPE=local"
Environment="UNIFI_LOCAL_HOST=your-unifi-gateway-ip"
ExecStart=/usr/local/bin/unifi-mcp-server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable unifi-mcp
sudo systemctl start unifi-mcp
```

### Pi-hole MCP – `/etc/systemd/system/pihole-mcp.service`

```ini
[Unit]
Description=Pi-hole MCP Server
After=network.target

[Service]
Type=simple
Environment="PIHOLE_URL=http://your-pihole-host:8080"
Environment="PIHOLE_PASSWORD=your-app-password"
ExecStart=/usr/bin/mcp-pihole-server
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable pihole-mcp
sudo systemctl start pihole-mcp
```

**Security:** Do not commit API keys or passwords. Use a secrets store or `EnvironmentFile=/etc/glitch/mcp.env` (mode 0600) and reference variables in the unit files.

## 4. MCP client configuration (Cursor / Claude Desktop)

Point your MCP client at 10.10.110.230 only if the servers are exposed (e.g. SSE or stdio over SSH). For local use on 10.10.110.230, configure the client to run the commands above (e.g. `unifi-mcp-server` and `mcp-pihole-server`) with the same env vars.
