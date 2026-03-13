# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Workflow Rules

- **Never commit or push without explicit user direction.** Do not run `git add`, `git commit`, or `git push` unless the user explicitly asks. Readonly commands (`git status`, `git diff`, `git log`) are always fine.
- **Never create new `.md` files** without explicit user permission. Updating existing `.md` files (like this one, `Architecture.md`) when code changes is fine.
- **Check CloudWatch logs before adding debug instrumentation.** Always inspect existing logs first; only add new logging if the existing logs are insufficient to diagnose the issue.

## Commands

### Infrastructure (CDK TypeScript — `infrastructure/`)
```bash
cd infrastructure
pnpm install          # Install dependencies
pnpm build            # Compile TypeScript
pnpm test             # Run Jest tests
pnpm test -- --testPathPattern=vpc   # Run a single test file
pnpm cdk synth        # Synthesize CloudFormation
pnpm cdk diff         # Preview changes
pnpm cdk deploy --all # Deploy all stacks (requires AWS credentials)
pnpm cdk deploy GlitchEdgeStack --region us-east-1  # Edge stack must deploy to us-east-1
```

### Glitch Agent (Python — `agent/`)
```bash
cd agent
pip install -r requirements.txt
make deploy           # Full workflow: configure from SSM + agentcore deploy (recommended)
make deploy-only      # Deploy with existing .env.deploy (skip configure)
make configure        # Read SSM params and update .bedrock_agentcore.yaml
make verify           # Check runtime status (agentcore status)
make check-logs       # Inspect AgentCore runtime logs in CloudWatch
make telegram-troubleshoot  # Telegram webhook/runtime diagnostics
make test             # pytest tests/ -v
pytest tests/test_foo.py -v   # Run a single test file
agentcore status      # Check runtime status
agentcore invoke '{"prompt":"hello"}'  # Smoke test the running agent
```

### Sentinel Agent (archived — merged into Glitch)
The Sentinel agent has been merged into Glitch. The `monitoring-agent/` directory is archived as `_archived_monitoring-agent/`. All ops tools, the Protect subsystem, and skills now live in `agent/`.

### UI (React + Vite — `ui/`)
```bash
cd ui
pnpm install
pnpm dev              # Dev server (localhost)
pnpm build            # Production build to dist/
pnpm lint             # ESLint
```

## Architecture Overview

This is a **single-agent** AI system on AWS AgentCore Runtime:

- **Glitch** — unified conversational + ops agent (HTTP protocol, port 8080). Entry points: Telegram and Web UI (CloudFront → Gateway Lambda → AgentCore). Owns all monitoring, surveillance, networking, DNS, and infra ops capabilities (previously split across Sentinel).

Runs in **PUBLIC network mode** (no VPC ENIs, no VPC endpoints). The VPC exists only to host RDS (Protect DB) and the AWS Site-to-Site VPN.

### Key Design Decisions

1. **Single agent** — Glitch directly owns all ops tools (CloudWatch, UniFi Protect, UniFi Network, Pi-hole DNS, GitHub, CDK, CloudFormation) without A2A delegation.
2. **Strands Agents SDK** — Uses `strands-agents[otel]`. Tools are plain Python functions decorated with `@tool`.
3. **Skill system** — Keyword-based skill matching via `select_skills_for_message()` (from `agent/skills/`). Skills are plain folders with `skill.md` + `metadata.json`.
4. **Protect subsystem** — `agent/src/glitch/protect/` package with WebSocket poller, event processor, and DB CRUD. Started as an `asyncio.Task` from `main()` before `run_server_async()` so `/ping` health check responds immediately.
5. **PUBLIC mode + Ollama proxy** — Cannot reach `10.10.110.x` on-prem IPs directly. Ollama access requires a proxy; configure via `GLITCH_OLLAMA_PROXY_HOST` env var.
6. **`aws_utils.py` pattern** — `agent/src/glitch/aws_utils.py` provides `get_client(service)` factory with lazy-initialized boto3 client cache. Always use this instead of creating boto3 clients directly.

### CDK Stack Layout

All stacks are in `infrastructure/lib/stack.ts` except `UiBackendStack` (`ui-backend-stack.ts`). The `GlitchEdgeStack` (WAF + ACM) **must deploy to `us-east-1`** — all others deploy to `us-west-2`.

Stack dependency order: `GlitchFoundationStack` → `GlitchSecretsStack` / `GlitchStorageStack` → `GlitchGatewayStack` / `GlitchTelegramWebhookStack` → `GlitchAgentCoreStack` / `GlitchSentinelStack` → `GlitchUiHostingStack`.

Cross-stack references use SSM parameters (not `Fn.importValue`) to avoid circular dependency issues.

### Lambda Functions

All Lambda functions in `infrastructure/lambda/` use `Code.fromAsset`. They are:
- `gateway/index.py` — proxies CloudFront requests to AgentCore Runtime (AWS_IAM auth)
- `telegram-webhook/index.py` — receives Telegram updates, invokes AgentCore
- `telegram-keepalive/index.py` — 4-min EventBridge keepalive to keep Claude prompt cache warm
- `ui-backend/index.py` — optional UI backend

### Glitch Tool Groups

Tools in `agent/src/glitch/tools/` are registered in `registry.py` by group: `ollama`, `memory`, `telemetry`, `soul`, `ssh`, `secrets`, `deploy`, `cloudwatch`, `ops_telegram`, `github`, `protect`, `pihole`, `unifi_network`, `dns`, `infra_ops`, `compound`. The `ToolRegistry` singleton controls which groups are active.

### Observability

- Agent stdout → `/aws/bedrock-agentcore/runtimes/<AgentID>-DEFAULT` (CloudWatch)
- Custom telemetry → `/glitch/telemetry` (written by `telemetry.py`)
- Lambda logs → `/aws/lambda/glitch-*`

When debugging, query the AgentCore log group first.

### Auri memory (Protect DB) — verify migration

The `auri_memory` table is created by `db._run_migrations()` when the Protect DB pool is first established (inside `_apply_schema`). That only runs when **Protect is configured** and `init_pool_background()` succeeds. If you don’t see the migration in logs, either Protect isn’t configured or the DB connection never succeeded.

**CloudWatch (AgentCore log group):**

- Search for: `Protect not configured` — if present, the DB init task is never started; no migration runs.
- Search for: `Protect DB pool initialised` or `Connecting to Protect DB` — confirms the pool (and thus schema + migrations) ran.
- Search for: `auri_memory table not found` and `auri_memory migration complete` — confirms the auri_memory migration ran.

**Manual check/create on Protect RDS:**

1. **Check if the table exists** (any user with read access to `information_schema`):
   ```sql
   SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'auri_memory');
   ```
2. **Create the table if needed** (same SQL the runtime uses; idempotent):
   ```bash
   psql "$GLITCH_PROTECT_DB_URI" -f agent/scripts/auri_memory_migration.sql
   ```
   The script requires the `vector` extension; if missing, create it as the RDS master user: `CREATE EXTENSION IF NOT EXISTS vector;`
