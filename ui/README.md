# Glitch Dashboard UI

A modern React + DaisyUI dashboard for the Glitch Agent system.

## Features

- **Chat with Glitch** - Real-time conversation with your AI orchestrator
- **Telegram** - Bot configuration and status monitoring
- **Ollama** - Local model health and available models
- **Memory** - Structured memory viewer
- **MCP** - Model Context Protocol server status
- **Skills** - Enable/disable agent skills
- **Unifi** - Network monitoring (Coming Soon)
- **Pi-hole** - DNS filtering stats (Coming Soon)
- **Settings** - Agent configuration

## Quick Start

### Prerequisites

- Node.js 18+
- pnpm
- AWS CLI configured with credentials
- AgentCore CLI (`pip install bedrock-agentcore-starter-toolkit`)

### Connecting to a Deployed Agent

The UI connects to your deployed Glitch agent via a local proxy that uses the AgentCore CLI.

```bash
cd ui

# Step 1: Check connection status
pnpm check

# Step 2: Start the proxy (in one terminal)
pnpm proxy

# Step 3: Start the UI (in another terminal)
pnpm dev

# Step 4: Open http://localhost:5173
```

### How It Works

```
┌─────────────┐     ┌─────────────┐     ┌──────────────────┐
│   Browser   │────▶│ Local Proxy │────▶│ AgentCore Runtime│
│ :5173       │     │ :8080       │     │ (AWS)            │
└─────────────┘     └─────────────┘     └──────────────────┘
                          │
                          ▼
                    agentcore invoke
```

1. The UI runs on `localhost:5173` (Vite dev server)
2. Vite proxies `/api/*` requests to `localhost:8080`
3. The local proxy (`pnpm proxy`) forwards requests to the deployed agent via `agentcore invoke`
4. The agent handles API requests and returns responses

### Local Development (Optional)

If you want to run the agent locally instead:

```bash
# Terminal 1: Start the agent locally
cd agent
agentcore deploy --local

# Terminal 2: Start the UI
cd ui
pnpm dev

# Open http://localhost:5173
```

When running locally, the agent serves on port 8080 directly, so no proxy is needed.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Agent status and info |
| `/api/telegram/config` | GET/POST | Telegram configuration |
| `/api/ollama/health` | GET | Ollama hosts health |
| `/api/memory/summary` | GET | Memory state |
| `/api/mcp/servers` | GET | MCP server status |
| `/api/skills` | GET | List all skills |
| `/api/skills/{id}/toggle` | POST | Enable/disable skill |
| `/invocations` | POST | Send message to Glitch |

## Scripts

| Command | Description |
|---------|-------------|
| `pnpm dev` | Start Vite dev server |
| `pnpm build` | Build for production |
| `pnpm check` | Check agent connection status |
| `pnpm proxy` | Start local proxy to deployed agent |
| `pnpm preview` | Preview production build |

## Configuration

### Proxy Settings

The Vite dev server proxies API requests. Configure in `vite.config.ts`:

```typescript
proxy: {
  '/api': {
    target: 'http://localhost:8080',
    changeOrigin: true,
  },
  '/invocations': {
    target: 'http://localhost:8080',
    changeOrigin: true,
  },
}
```

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GLITCH_AGENT_NAME` | `Glitch` | Agent name for agentcore CLI |
| `AWS_REGION` | `us-west-2` | AWS region |

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool
- **TailwindCSS** - Utility-first CSS
- **DaisyUI** - Component library
- **Zustand** - State management
- **Lucide React** - Icons
- **React Markdown** - Markdown rendering
