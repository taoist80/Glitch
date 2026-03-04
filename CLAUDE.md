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
make deploy           # Full workflow: pre-configure + agentcore deploy + verify
make deploy-only      # Deploy without pre/post checks
make configure        # Run pre-deploy-configure.py to sync VPC config from CloudFormation
make test             # pytest tests/ -v
pytest tests/test_foo.py -v   # Run a single test file
agentcore deploy      # Deploy directly (bypasses Makefile checks)
agentcore status      # Check runtime status
agentcore invoke '{"prompt":"hello"}'  # Smoke test the running agent
```

### Sentinel Agent (Python — `monitoring-agent/`)
```bash
cd monitoring-agent
pip install -r requirements.txt
agentcore deploy      # Deploy Sentinel
agentcore status
```

### UI (React + Vite — `ui/`)
```bash
cd ui
pnpm install
pnpm dev              # Dev server (localhost)
pnpm build            # Production build to dist/
pnpm lint             # ESLint
```

## Architecture Overview

This is a two-agent hybrid AI system on AWS AgentCore Runtime:

- **Glitch** — user-facing conversational agent (HTTP protocol, port 8080). Entry points: Telegram and Web UI (CloudFront → Gateway Lambda → AgentCore).
- **Sentinel** — autonomous operations brain (A2A protocol, port 9000). Owns all monitoring, networking, and infra ops. Triggered by Glitch via `invoke_sentinel`, can invoke Glitch back via `invoke_glitch_agent`.

Both agents run in **PUBLIC network mode** (no VPC ENIs, no VPC endpoints). The VPC exists only to host the AWS Site-to-Site VPN connecting to the on-premises UDM-Pro/network.

### Key Design Decisions

1. **A2A via InvokeAgentRuntime** — Glitch and Sentinel communicate over `bedrock-agentcore:InvokeAgentRuntime`. ARNs are stored in SSM (`/glitch/sentinel/runtime-arn` and `/glitch/sentinel/glitch-runtime-arn`) with a 5-minute TTL cache in each agent. A `ResourceNotFoundException` busts the cache and re-queries SSM before one retry.
2. **Strands Agents SDK** — Both agents use the `strands-agents` library. Tools are plain Python functions decorated with `@tool`. Glitch uses `strands-agents[otel]`; Sentinel uses `strands-agents[a2a,otel]`.
3. **Skill system** — At request time, Glitch runs a `TaskPlanner` → `SkillSelector` pipeline that injects up to 3 skill prompts (from `agent/skills/`) into the system prompt before passing to the Strands agent.
4. **PUBLIC mode + Ollama proxy** — Agents in PUBLIC mode cannot reach `10.10.110.x` on-prem IPs directly. Ollama access requires a proxy; configure via `GLITCH_OLLAMA_PROXY_HOST` env var.
5. **`aws_utils.py` pattern** — Both `agent/src/glitch/aws_utils.py` and `monitoring-agent/src/sentinel/aws_utils.py` provide a shared `get_client(service)` factory with a lazy-initialized boto3 client cache. Always use this instead of creating boto3 clients directly in tool files.

### CDK Stack Layout

All stacks are in `infrastructure/lib/stack.ts` except `UiBackendStack` (`ui-backend-stack.ts`). The `GlitchEdgeStack` (WAF + ACM) **must deploy to `us-east-1`** — all others deploy to `us-west-2`.

Stack dependency order: `GlitchFoundationStack` → `GlitchSecretsStack` / `GlitchStorageStack` → `GlitchGatewayStack` / `GlitchTelegramWebhookStack` → `GlitchAgentCoreStack` / `GlitchSentinelStack` → `GlitchUiHostingStack`.

Cross-stack references use SSM parameters (not `Fn.importValue`) to avoid circular dependency issues.

### Lambda Functions

All Lambda functions in `infrastructure/lambda/` use `Code.fromAsset`. They are:
- `gateway/index.py` — proxies CloudFront requests to AgentCore Runtime (AWS_IAM auth)
- `telegram-webhook/index.py` — receives Telegram updates, invokes AgentCore
- `telegram-keepalive/index.py` — 10-min EventBridge keepalive to prevent cold starts
- `ui-backend/index.py` — optional UI backend

### Glitch Tool Groups

Tools in `agent/src/glitch/tools/` are registered in `registry.py` by group: `ollama`, `memory`, `telemetry`, `soul`, `ssh`, `sentinel`, `secrets`, `deploy`. The `ToolRegistry` singleton controls which groups are active.

### Observability

- Agent stdout → `/aws/bedrock-agentcore/runtimes/<AgentID>-DEFAULT` (CloudWatch)
- Custom telemetry → `/glitch/telemetry` (written by `telemetry.py`)
- Lambda logs → `/aws/lambda/glitch-*`

When debugging, query the AgentCore log group for the agent under investigation first.
