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

### Option C: Deployed Agent (Lambda UI Backend)

When deployed to AWS, the UI is served via a Lambda Function URL. The Lambda handles session management and proxies requests to the AgentCore Runtime. See `infrastructure/lib/ui-backend-stack.ts` for the CDK stack.

Set `VITE_API_BASE_URL` to the Lambda Function URL when building the UI for production deployment.

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

## Environment Variables

| Variable | Description |
|----------|-------------|
| `VITE_API_BASE_URL` | API base URL for production builds (Lambda Function URL) |

## Scripts

| Command | Description |
|---------|-------------|
| `pnpm dev` | Start Vite dev server |
| `pnpm build` | Build for production |
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
