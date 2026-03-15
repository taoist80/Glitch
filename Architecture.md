# Glitch Architecture

A unified AI agent system built on AWS AgentCore Runtime. Glitch is the single conversational + ops agent. The Sentinel agent was merged into Glitch; `_archived_monitoring-agent/` is kept for reference only.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud (us-west-2)                              │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  CloudFront (glitch.awoo.agency)                                         │  │
│  │  WAF WebACL (IP allowlist: home IP only)                                 │  │
│  │  ├── Origin 1: S3 bucket (OAC) → static UI assets                       │  │
│  │  └── Origin 2: Gateway Lambda (Lambda OAC + SigV4) → /api/*, /invocations│  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│            │                                                                    │
│            ▼                                                                    │
│  Lambda: glitch-gateway ──────────────────────────────────────────────────┐    │
│                                                                            │    │
│  Telegram path:                                                            │    │
│  glitch-telegram-webhook (async invoke) → glitch-telegram-processor ──────┤    │
│  glitch-agentcore-keepalive (EventBridge, every 4 min)                    │    │
│                                                                            │    │
│            ┌───────────────────────────────────────────────────────────────┘    │
│            ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐        │
│  │  Glitch Agent (PUBLIC mode, AgentCore Runtime)                      │        │
│  │  HTTP protocol, port 8080                                           │        │
│  │                                                                     │        │
│  │  Tools: SSH • Ollama (via proxy) • Memory • Soul • Telemetry       │        │
│  │         CloudWatch • UniFi Protect • UniFi Network • Pi-hole DNS   │        │
│  │         DNS Intelligence • CDK/CFN Infra Ops • GitHub • Telegram   │        │
│  │         Secrets Manager • Deploy management • Code Interpreter     │        │
│  │         Compound (security_correlation_scan, analyze_and_alert)    │        │
│  └─────────────────────────────────────────────────────────────────────┘        │
│                                                                                 │
│  DynamoDB: glitch-telegram-config   S3: glitch-agent-state-{acct}-{region}     │
│  Secrets Manager: glitch/*          SSM: /glitch/*                             │
│  RDS Postgres: protect DB + auri_memory (private VPC subnet, pgvector)         │
│  Lambda: glitch-protect-query (VPC, bridges agent → RDS)                       │
└─────────────────────────────────────────────────────────────────────────────────┘
                              │
                              │ IPsec Site-to-Site VPN (dual tunnels, HA)
                              │ VGW ↔ UDM-Pro Customer Gateway
                              │
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           On-Premises Network                                   │
│                                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Ollama Chat  │  │ Ollama Vision│  │  Pi-hole DNS │  │ UniFi Protect│       │
│  │ dolphin-mist │  │ LLaVA        │  │  10.10.100.70│  │  cameras     │       │
│  │ 10.10.110.202│  │ 10.10.110.137│  │  10.10.100.71│  │  UDM-Pro NVR │       │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                                                 │
│  nginx TCP proxy — 10.10.100.230                                               │
│  :443 → 192.168.1.1:443 (Protect API)   :7443 → 192.168.1.1:443 (legacy)     │
│                                                                                 │
│  UDM-Pro (192.168.1.1) — router, VPN endpoint, UniFi OS console               │
│  UDM-Pro port forward: WAN :32443 → LAN :443 (Protect API for PUBLIC agents)  │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Request Flows

### Web UI Flow
```
Browser → CloudFront (WAF IP check)
       → Gateway Lambda (SigV4 via Lambda OAC)
       → AgentCore Runtime /invocations
       → GlitchAgent.process_message()
       → InvocationResponse
```

### Telegram Flow
```
User → Telegram API
     → glitch-telegram-webhook Lambda
         validate secret, dedup update_id, load DynamoDB config
         extract mode_id (from session), participant_id (from sender)
         prefix group messages with [FirstName]:
         async invoke → glitch-telegram-processor Lambda
         return HTTP 200 immediately (avoids Telegram retry storm)
     → glitch-telegram-processor Lambda
         worker thread + 30s progress pings (max 280s)
         POST /invocations to AgentCore Runtime (SigV4 signed)
         payload: {prompt, session_id, mode_id, participant_id, agent_id}
     → GlitchAgent.process_message()
     → sendMessage to Telegram Bot API
```

### Protect Query Flow (agent → private RDS)
```
Agent (PUBLIC mode, no VPC) → cannot reach RDS directly
     → calls glitch-protect-query Lambda (AWS API, no VPC restriction)
     → protect-query Lambda (VPC, has DB access)
     → RDS Postgres (private subnet)
     → returns result to agent
```

---

## Key Design Decisions

1. **Single agent** — Glitch directly owns all tools (CloudWatch, UniFi Protect/Network, Pi-hole, GitHub, CDK/CFN, SSH) without A2A delegation.
2. **Strands Agents SDK** — `strands-agents[otel]`. Tools are plain Python functions decorated with `@tool`.
3. **Skill system** — Keyword-based skill matching via `select_skills_for_message()`. Skills are folders under `agent/skills/` with `skill.md` + `metadata.json`. Skills are suppressed in roleplay mode (`mode_context` present).
4. **PUBLIC mode + Ollama proxy** — Cannot reach `10.10.110.x` on-prem IPs directly. Ollama requires a proxy; set `GLITCH_OLLAMA_PROXY_HOST`.
5. **`aws_utils.py` pattern** — `get_client(service)` provides a lazy-init boto3 client cache. Always use this; never create boto3 clients directly.
6. **Protect subsystem** — `agent/src/glitch/protect/` package with WebSocket poller and DB CRUD. Started as an asyncio background task in `main()` before `run_server_async()`.
7. **Model routing** — Bedrock Sonnet 4.5 for main Glitch. Roleplay mode swaps to Haiku (cheap) or a local Ollama model (`LocalModel` branch). The `_alt_models` cache in `GlitchAgent` holds alternate `BedrockModel` or `OllamaModel` instances.
8. **Telegram → AgentCore chain** — Two Lambdas: webhook (immediate 200, async dispatch) → processor (actual invocation with progress pings). The webhook Lambda never blocks.

---

## Modes

| Mode | `mode_id` | Model | Behavior |
|------|-----------|-------|----------|
| Default | `default` | Sonnet 4.5 | Full Glitch persona, all tools, ops skills |
| Roleplay (Auri) | `roleplay` | Haiku / local Ollama | Auri persona, memory loaded, ops skills suppressed |
| Poet | `poet` | Sonnet 4.5 | Poet soul + story book injected |

Mode is stored per-session in DynamoDB (`glitch-telegram-config`). Changed by Telegram commands `/auri`, `/default`, `/poet`.

---

## Auri Roleplay Memory (Layered Architecture)

Context assembled by `AuriContextComposer.compose()` on every roleplay request. Target ~900–1,200 tokens vs ~3,800 for the old monolithic auri.md.

| Layer | Storage | Contents | When loaded |
|-------|---------|----------|-------------|
| Core persona | S3 (`auri-core.md`) | Identity, personality, voice | Always |
| Behavioral rules | S3 (`auri-runtime-rules.md`) | Protocols, escalation rules | Always |
| Session state | DynamoDB `AURI_STATE#<session>` | Mode, mood, sliders, dynamic level | Always |
| Scene summary | DynamoDB `AURI_SCENE#<session>` | Energy, recent events, open threads | Always |
| Participant profiles | RDS `auri_memory` (pgvector, `memory_type=participant_profile`) | Per-person profile | When `active_members` set |
| Episodic memories | RDS `auri_memory` (pgvector) | Memorable facts, story beats | Always (top-5 by cosine similarity) |
| Lore archive | S3 (`story-book.md`) | Origin/backstory | Only on lore keywords |

**participant_id propagation:** Telegram webhook extracts sender's first name → `participant_id` in payload → processor Lambda → AgentCore `/invocations` payload → `server.py` → `apply_mode_with_memories()` → `AuriContextComposer`. Without this, Auri loads no participant profile.

**VPC bridge:** Agent runs PUBLIC mode (no VPC). Auri memory R/W uses Bedrock Titan Embed v2 for embeddings then calls `glitch-protect-query` Lambda (which has VPC access to RDS). The pool parameter in `auri_memory.py` is unused (kept for API compat).

**Soul tools** (always-on, not keyword-gated):

| Tool | Purpose |
|------|---------|
| `remember_auri` | Store episodic fact (pgvector) — at most once per response |
| `search_auri_memory` | Retrieve memories — **NOT to be called during responses** (pre-loaded) |
| `store_session_moment` | Store current scene moment — at most once per response |
| `update_participant_profile` | Upsert participant profile (pgvector) |
| `get_participant_profile` | Load a participant's profile |
| `update_auri_state` | Update DynamoDB session state |
| `update_scene` | Update DynamoDB scene summary |
| `update_auri_core` | Overwrite `auri-core.md` in S3 |
| `update_auri_rules` | Overwrite `auri-runtime-rules.md` in S3 |

**Migration:** `make migrate-auri` is one-time (already run). Do not re-run — it overwrites runtime persona edits.

---

## CDK Stack Architecture

```
GlitchFoundationStack (us-west-2)
├── VPC (public + private subnets, no NAT Gateway)
├── Site-to-Site VPN (VGW + CGW + VPN Connection)
├── IAM Roles (RuntimeRole, CodeBuildRole)
└── SSM Parameters (/glitch/vpc/*, /glitch/iam/*)

GlitchSecretsStack (us-west-2)
└── Secrets Manager references (telegram-bot-token, api-keys, ssh-key, pihole-api, github-token, unifi-controller)

GlitchStorageStack (us-west-2)
├── DynamoDB: glitch-telegram-config
├── S3: glitch-agent-state-{account}-{region}
└── CloudWatch Log Group: /glitch/telemetry

GlitchProtectDbStack (us-west-2)
├── RDS Postgres t4g.micro (private VPC subnet, IAM auth)
│   Master creds: glitch/protect-db-master
└── Lambda: glitch-protect-query (VPC, pg8000, handles protect + auri_memory ops)

GlitchGatewayStack (us-west-2)
├── Lambda: glitch-gateway (AWS_IAM auth, fromAsset)
│   Routes /api/protect/* → glitch-protect-query (bypasses AgentCore for speed)
│   Routes everything else → AgentCore Runtime
└── EventBridge: 5-min keepalive rule

GlitchTelegramWebhookStack (us-west-2)
├── Lambda: glitch-telegram-webhook (NONE auth, fromAsset)
├── Lambda: glitch-telegram-processor (invoked async by webhook)
├── Lambda: glitch-agentcore-keepalive (4-min keepalive, fromAsset)
└── SSM: /glitch/telegram/webhook-url, /glitch/telegram/config-table

GlitchEdgeStack (us-east-1)  ← MUST deploy to us-east-1
├── WAF WebACL (CLOUDFRONT scope, IP allowlist)
└── ACM Certificate (glitch.awoo.agency)

GlitchUiHostingStack (us-west-2)
├── S3 bucket (private, OAC)
├── CloudFront distribution (WAF + ACM + S3 OAC + Lambda OAC)
└── S3 deployment (UI dist/)

GlitchAgentCoreStack (us-west-2)
└── Managed Policy on RuntimeRole (Bedrock, ECR, CW Logs, Secrets, DynamoDB, S3, SSM, Lambda invoke, RDS)
```

Cross-stack references use SSM parameters (not `Fn.importValue`) to avoid circular dependency issues.

---

## Lambda Functions

| Lambda | Auth | Purpose |
|--------|------|---------|
| `gateway/index.py` | AWS_IAM | Proxies CloudFront → AgentCore; routes /api/protect/* to protect-query |
| `telegram-webhook/index.py` | NONE (Telegram) | Receives updates, dedupes, dispatches to processor async |
| `telegram-processor/index.py` | (invoked async) | Invokes AgentCore with progress pings, sends Telegram reply |
| `telegram-keepalive/index.py` | (EventBridge) | 4-min ping to keep prompt cache warm |
| `protect-query/index.py` | (invoked direct) | VPC bridge: protect events + auri_memory R/W against RDS |
| `ui-backend/index.py` | (optional) | Optional UI backend |

---

## Glitch Tool Groups

Registered in `agent/src/glitch/tools/registry.py`:

| Group | Key Tools |
|-------|-----------|
| `ollama` | `local_chat`, `vision_agent`, `check_ollama_health` |
| `memory` | AgentCore memory create/retrieve |
| `telemetry` | Metrics logging |
| `soul` | `remember_auri`, `search_auri_memory`, `update_auri_*`, `store_session_moment` |
| `ssh` | `ssh_run_command`, `ssh_read_file`, `ssh_write_file`, `ssh_list_hosts`, etc. |
| `secrets` | `store_secret`, `list_secrets` |
| `deploy` | `get_deployed_arns`, `update_*_arn_in_ssm`, `check_codebuild_deploy_status` |
| `cloudwatch` | `get_my_recent_logs`, `tail_log_stream`, `scan_log_groups_for_errors`, `query_cloudwatch_insights` |
| `ops_telegram` | `send_telegram_alert`, `send_telegram_resolved` |
| `github` | `github_get_file`, `github_create_branch`, `github_commit_file`, `github_create_pr` |
| `protect` | 13 core tools: cameras, events, snapshots, DB ops, alerts, entity mgmt |
| `pihole` | `pihole_list_dns_records`, `pihole_add/delete/update_dns_record` |
| `unifi_network` | 12 tools: clients, APs, switches, firewall, VPN, alerts |
| `dns` | 7 tools: query patterns, suspicious domains, blocklists |
| `infra_ops` | `cdk_synth_and_validate`, `cdk_diff`, `cdk_deploy_stack`, `list_cfn_stacks_status`, `check_cfn_drift`, `rollback_stack` |
| `compound` | `security_correlation_scan`, `analyze_and_alert` |

---

## Memory Architecture

### Glitch Conversation Memory
- **Strands `SlidingWindowConversationManager`** — last N turns in-process, session-scoped (`GLITCH_WINDOW_SIZE`, default 10)
- **AgentCore Memory API** (`MemoryClient`) — persistent across sessions: `create_event()` for each turn, semantic retrieval via `retrieve()`

### Auri Episodic Memory
See [Auri Roleplay Memory](#auri-roleplay-memory-layered-architecture) above.

---

## Observability

| Log Group | Purpose |
|-----------|---------|
| `/aws/bedrock-agentcore/runtimes/Glitch-*-DEFAULT` | Agent stdout + OTEL |
| `/aws/lambda/glitch-gateway` | Gateway Lambda |
| `/aws/lambda/glitch-telegram-webhook` | Webhook Lambda |
| `/aws/lambda/glitch-telegram-processor` | Processor Lambda |
| `/aws/lambda/glitch-agentcore-keepalive` | Keepalive Lambda |
| `/glitch/telemetry` | Invocation metrics (tokens, cycles, duration, tools used) |

**Search strings (CloudWatch Insights):**

- `GLITCH_INVOKE_ENTRY` — confirms a request reached the container
- `GLITCH_INVOKE_DONE` — confirms successful completion
- `tokens:` — telemetry line with full metrics (input/output tokens, cache, cycles, duration)
- `AuriContextComposer:` — confirms Auri context assembled and token estimate

---

## SSM Parameters

| Parameter | Description |
|-----------|-------------|
| `/glitch/vpc/id` | VPC ID |
| `/glitch/vpc/private-subnet-ids` | Comma-separated private subnet IDs |
| `/glitch/iam/runtime-role-arn` | Runtime role ARN |
| `/glitch/telegram/webhook-url` | Telegram webhook Lambda URL |
| `/glitch/telegram/config-table` | DynamoDB config table name |
| `/glitch/protect/host` | UniFi Protect host (e.g. `home.awoo.agency:32443`) |
| `/glitch/protect/api-key` | Protect API key |
| `/glitch/ollama/proxy-host` | Ollama proxy base URL (e.g. `http://proxy.local:11434`) |
| `/glitch/roleplay-model` | Model key for roleplay: `haiku` or `local-roleplay` |
| `/glitch/roleplay-ollama-model` | Ollama model name for roleplay (e.g. `qwen2.5:32b`) |

---

## Secrets Reference

| Secret | Format | Used By |
|--------|--------|---------|
| `glitch/telegram-bot-token` | Plain text | Agent, webhook Lambda |
| `glitch/api-keys` | JSON | Agent |
| `glitch/ssh-key` | PEM private key | SSH tools |
| `glitch/porkbun-api` | JSON `{apikey, secretapikey}` | DDNS Lambda |
| `glitch/pihole-api` | JSON `{host, username, password}` | Pi-hole tools |
| `glitch/github-token` | Plain text PAT | GitHub tools |
| `glitch/unifi-controller` | JSON `{host, username, password, site}` | UniFi Network tools |
| `glitch/protect-db-master` | JSON `{username, password}` | RDS master creds |

---

## Deployment

### Prerequisites
- AWS CLI configured (us-west-2)
- Node.js 18+, pnpm, Python 3.10+
- Docker (for `agentcore deploy`)

### Deploy Agent
```bash
cd agent
make deploy           # configure from SSM + agentcore deploy (recommended)
make deploy-only      # skip configure, use existing .env.deploy
make configure        # update .bedrock_agentcore.yaml from SSM only
agentcore status      # verify runtime is healthy
agentcore invoke '{"prompt":"hello"}'  # smoke test
```

### Deploy Infrastructure
```bash
cd infrastructure
pnpm install && pnpm build && pnpm test
pnpm cdk deploy --all --require-approval never           # all us-west-2 stacks
pnpm cdk deploy GlitchEdgeStack --region us-east-1      # WAF + ACM (must be us-east-1)
```

### Full Deployment (New Account)
```bash
# 1. Foundation
cd infrastructure && pnpm cdk deploy GlitchFoundationStack GlitchSecretsStack GlitchStorageStack GlitchProtectDbStack

# 2. Application stacks
pnpm cdk deploy GlitchGatewayStack GlitchTelegramWebhookStack GlitchAgentCoreStack GlitchUiHostingStack

# 3. Edge (us-east-1)
pnpm cdk deploy GlitchEdgeStack --region us-east-1

# 4. Agent
cd ../agent && make deploy
```

---

## Project Structure

```
AgentCore-Glitch/
├── infrastructure/              # CDK TypeScript
│   ├── bin/app.ts
│   ├── lib/
│   │   ├── stack.ts            # All stacks (GlitchFoundationStack … GlitchAgentCoreStack)
│   │   └── ui-backend-stack.ts
│   ├── lambda/
│   │   ├── gateway/index.py
│   │   ├── telegram-webhook/index.py
│   │   ├── telegram-processor/index.py
│   │   ├── telegram-keepalive/index.py
│   │   ├── protect-query/index.py   # VPC bridge: protect events + auri_memory
│   │   └── ui-backend/index.py
│   └── test/
├── agent/                       # Glitch — Python Strands agent
│   ├── src/
│   │   ├── main.py             # Entrypoint: bootstrap + protect subsystem + run_server_async
│   │   └── glitch/
│   │       ├── agent.py        # GlitchAgent, _select_and_inject_skills, model swap
│   │       ├── server.py       # BedrockAgentCoreApp, invoke(), mode routing
│   │       ├── modes.py        # apply_mode_to_prompt, apply_mode_with_memories
│   │       ├── auri_context.py # AuriContextComposer, get_mountain_time_context
│   │       ├── auri_memory.py  # Episodic memory via Titan Embed + protect-query Lambda
│   │       ├── auri_state.py   # AuriState + SceneSummary (DynamoDB)
│   │       ├── aws_utils.py    # get_client() boto3 factory
│   │       ├── telemetry.py    # Metrics, log_invocation_metrics
│   │       ├── routing/
│   │       │   └── model_router.py  # MODEL_REGISTRY, ModelRouter, CognitiveTier
│   │       ├── memory/
│   │       │   └── sliding_window.py
│   │       ├── skills/
│   │       │   └── skills.py   # select_skills_for_message
│   │       ├── protect/        # WebSocket poller, event processor, DB CRUD
│   │       ├── channels/       # Telegram channel, DynamoDB config
│   │       └── tools/
│   │           ├── registry.py
│   │           ├── ollama_tools.py
│   │           ├── ssh_tools.py
│   │           ├── soul_tools.py      # Auri memory tools, S3 persona tools
│   │           ├── memory_tools.py
│   │           ├── protect_tools.py
│   │           ├── cloudwatch_tools.py
│   │           ├── pihole_tools.py
│   │           ├── unifi_network_tools.py
│   │           ├── dns_intelligence_tools.py
│   │           ├── infra_ops_tools.py
│   │           ├── github_tools.py
│   │           ├── deploy_tools.py
│   │           ├── secrets_tools.py
│   │           ├── telemetry_tools.py
│   │           ├── compound_tools.py
│   │           └── code_interpreter_tools.py
│   ├── skills/                  # Keyword-gated skill packs (suppressed in roleplay)
│   ├── tests/                   # pytest unit tests
│   ├── scripts/
│   │   ├── pre-deploy-configure.py
│   │   └── auri_memory_migration.sql
│   ├── Makefile
│   ├── Dockerfile
│   └── requirements.txt
├── ui/                         # React + Vite dashboard
│   └── src/
├── _archived_monitoring-agent/ # Sentinel (merged into Glitch, archived)
├── pnpm-workspace.yaml
├── Architecture.md
└── CLAUDE.md
```

---

## Troubleshooting

### Agent not responding to Telegram
1. Check webhook Lambda logs: `aws logs tail /aws/lambda/glitch-telegram-webhook --since 1h`
2. Check processor Lambda logs: `aws logs tail /aws/lambda/glitch-telegram-processor --since 1h`
3. Verify AgentCore runtime is healthy: `agentcore status`
4. Check agent logs: `make check-logs`

### Roleplay returns "Sorry, I couldn't process that request"
- Most likely cause: wrong Bedrock model ID. Haiku model must end in `-v1:0`: `us.anthropic.claude-haiku-4-5-20251001-v1:0`
- Check CloudWatch for the actual error — look for `ValidationException` or `ResourceNotFoundException`
- If using Ollama (`local-roleplay`): check that `GLITCH_OLLAMA_PROXY_HOST` is set and reachable

### Auri loading wrong participant profile
- Verify `participant_id` is in the AgentCore invocation payload (check processor Lambda logs)
- Confirm the webhook Lambda is extracting `from.first_name` for group messages
- Search CloudWatch for `active_members` to see what AuriContextComposer received

### High token usage / runaway tool loops in roleplay
- Check CloudWatch telemetry for `cycles:` count. >10 cycles in a single response is a loop.
- The roleplay preamble now instructs the model not to call `search_auri_memory` and to limit `remember_auri`/`store_session_moment` to once each.
- If still looping, check if ops skills are being injected (`skills_injected > 0` in logs) — should be 0 in roleplay.
- `max_turns` kwarg passed to Strands `Agent.__call__` is **silently ignored** — the preamble instruction is the only effective guardrail.

### Auri memory table missing
1. Check CloudWatch for `Protect not configured` — if present, DB pool never initialized
2. Check for `Protect DB pool initialised` and `auri_memory migration complete`
3. Manual create: `psql "$GLITCH_PROTECT_DB_URI" -f agent/scripts/auri_memory_migration.sql`
   (Requires `vector` extension: `CREATE EXTENSION IF NOT EXISTS vector;` as RDS master user)

### On-prem hosts unreachable
- Verify Site-to-Site VPN tunnels are UP: AWS Console > VPC > Site-to-Site VPN
- Check UDM-Pro: Network > VPN > Site-to-Site VPN
- PUBLIC mode agents cannot reach `10.10.110.x` directly — requires `GLITCH_OLLAMA_PROXY_HOST`

### Gateway timeout
- Lambda timeout: 300s; urllib timeout: 280s
- Keepalive Lambda runs every 4 min — cold starts should be rare
- If a roleplay invocation is slow, check for tool loop (cycles count in telemetry)

### CloudWatch logs not appearing
- Confirm log group matches agent ID in `.bedrock_agentcore.yaml`
- IAM must cover `/aws/bedrock-agentcore/*` (not `/aws/bedrock/agentcore/*`)
- Run `agentcore invoke '{"prompt":"test"}'` to verify container starts

---

## Security Model

- CloudFront WAF IP allowlist — blocks non-home IPs at the edge
- Lambda Function URL `AWS_IAM` auth — only CloudFront (via OAC) can invoke Gateway
- S3 OAC — bucket private; only CloudFront reads it
- Site-to-Site VPN IPsec — encrypted on-prem connectivity
- RDS in private VPC subnet — agent reaches it only via protect-query Lambda (VPC bridge)
- `cdk_deploy_stack` requires Telegram confirmation (`confirmed=True`) before executing

## Cost Profile

| Component | Monthly Cost |
|-----------|-------------|
| AgentCore Runtime | Pay-per-invocation |
| Site-to-Site VPN | ~$36 (2 tunnels × $0.05/hr) |
| RDS t4g.micro | ~$13 |
| CloudFront | ~$0 (low traffic) |
| WAF | ~$5 |
| Lambda, DynamoDB, S3 | ~$1 |
| **Total** | **~$56/month** |
| Bedrock (Sonnet 4.5) | Variable — $3/M input, $15/M output |
| Bedrock (Haiku 4.5, roleplay) | Variable — $0.8/M input, $4/M output |
| Local Ollama (roleplay, LocalModel branch) | $0 |
