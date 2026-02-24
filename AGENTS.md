# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Glitch is a hybrid AI agent system (AWS Bedrock AgentCore + on-prem Ollama via Tailscale). It's a pnpm monorepo with three packages:

| Package | Path | Language | Purpose |
|---------|------|----------|---------|
| `glitch-agent` | `agent/` | Python 3.12+ | AI agent backend (Strands SDK + FastAPI) on port 8080 |
| `glitch-ui` | `ui/` | TypeScript (React/Vite) | Dashboard UI on port 5173, proxies API to agent |
| `agentcore-glitch-infrastructure` | `infrastructure/` | TypeScript | AWS CDK IaC stacks |

### Running services

- **UI dev server**: `cd ui && pnpm dev` (port 5173). Proxies `/api` and `/invocations` to localhost:8080.
- **Agent backend**: `cd agent && PYTHONPATH=src .venv/bin/python src/main.py` (port 8080). Requires AWS credentials and external services (Bedrock, DynamoDB, Secrets Manager) to fully start.
- The agent requires AWS credentials and Tailscale connectivity to on-prem hosts. In cloud VMs without these, the UI renders fully but backend API calls return HTTP 500.

### Build and test commands

- **Full workspace build** (user rule — run before commits): `pnpm -r build`
- **UI build**: `cd ui && pnpm build`
- **Infrastructure build**: `cd infrastructure && pnpm build`
- **Python tests**: `cd agent && PYTHONPATH=src .venv/bin/python -m pytest tests/ -v` (99 tests, all unit tests, no external deps needed)
- **Infrastructure tests**: `cd infrastructure && pnpm test` (Jest; some `.ts` test files fail due to missing jest.config.js with ts-jest transform — pre-existing issue; compiled `.js` tests work)

### Known issues

- **UI lint**: `pnpm lint` in `ui/` fails because no `eslint.config.js` exists (ESLint 9 flat config required). This is a pre-existing gap.
- **Infrastructure tests**: Jest attempts to run both `.ts` and compiled `.js` test files. The `.ts` files fail to parse (no ts-jest transform configured). One assertion in `vpc-stack.test.js` also fails due to a VPC endpoint count mismatch (expects 8, finds 11).
- **esbuild**: pnpm install will warn about ignored build scripts for esbuild. The root `package.json` has `pnpm.onlyBuiltDependencies: ["esbuild"]` to allow it.

### Python virtual environment

The agent's Python venv lives at `agent/.venv`. Activate with `source agent/.venv/bin/activate` or run directly via `agent/.venv/bin/python`.
