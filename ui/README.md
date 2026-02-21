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
- AWS CLI configured with credentials (for deployed agent / proxy mode)

### Option A: Local Development (hot reload)

Run the agent locally and the UI with Vite dev server.

```bash
# From the repo root (parent of agent/ and ui/)

# Terminal 1: Start the agent locally
cd agent && PYTHONPATH=src python3 src/main.py

# Terminal 2: Start the UI
cd ui && pnpm dev

# Open http://localhost:5173
```

Vite proxies `/api` and `/invocations` to `http://localhost:8080`.

### Option B: Production (built UI served by agent)

Build the UI once, then the agent serves it at `/ui`. No separate UI process.

```bash
# From the repo root
cd ui && pnpm build
cd ../agent && PYTHONPATH=src python3 src/main.py

# Open http://localhost:8080/ui
```

### Option C: Deployed Agent (proxy mode)

Use the agent process as a local server that proxies all API and chat traffic to your deployed AgentCore runtime (boto3). No AgentCore CLI needed.

```bash
# Set proxy mode and deployed agent name
export GLITCH_UI_MODE=proxy
export GLITCH_DEPLOYED_AGENT_NAME=Glitch
export AWS_REGION=us-west-2

# Optional: set runtime ARN to skip control-plane lookup
# export GLITCH_AGENT_RUNTIME_ARN=arn:aws:bedrock-agentcore:us-west-2:ACCOUNT:runtime/Glitch-XXX

# From the repo root: build UI and start agent (serves UI at /ui, proxies to deployed agent)
cd ui && pnpm build
cd ../agent && GLITCH_UI_MODE=proxy PYTHONPATH=src python3 src/main.py

# Open http://localhost:8080/ui
```

### Legacy: Node.js proxy (deprecated)

The standalone Node.js proxy (`pnpm proxy`) is deprecated. Use Option C (Python proxy) instead. See `ui/scripts/agent-proxy.cjs` for the deprecated script.

## UI modes (environment)

| Variable | Values | Description |
|----------|--------|-------------|
| `GLITCH_UI_MODE` | `local` (default), `proxy`, `dev` | `local`: direct `/api` from this process. `proxy`: proxy `/api` and `/invocations` to deployed agent. `dev`: do not mount static UI (use Vite). |
| `GLITCH_DEPLOYED_AGENT_NAME` | e.g. `Glitch` | Agent name when in `proxy` mode (used to resolve runtime ARN). |
| `GLITCH_AGENT_RUNTIME_ARN` | Full ARN | Optional; skip control-plane lookup when set. |
| `AWS_REGION` | e.g. `us-west-2` | AWS region for proxy mode. |

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

When in proxy mode, `/ui-proxy/api/*` and `/ui-proxy/invocations` are also available and behave the same as `/api` and `/invocations`.

## Scripts

| Command | Description |
|---------|-------------|
| `pnpm dev` | Start Vite dev server |
| `pnpm build` | Build for production |
| `pnpm check` | Check agent connection status (legacy) |
| `pnpm proxy` | Start legacy Node proxy (deprecated) |
| `pnpm preview` | Preview production build |

## Tech Stack

- **React 18** - UI framework
- **TypeScript** - Type safety
- **Vite** - Build tool
- **TailwindCSS** - Utility-first CSS
- **DaisyUI** - Component library
- **Zustand** - State management
- **Lucide React** - Icons
- **React Markdown** - Markdown rendering
