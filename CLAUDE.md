# CLAUDE.md

Guidance for Claude Code when working in this repository. Follow these rules exactly.

## Workflow Rules

- **Never commit or push without explicit user direction.** Do not run `git add`, `git commit`, or `git push` unless the user explicitly asks. Readonly commands (`git status`, `git diff`, `git log`) are always fine.
- **Never create new `.md` files** without explicit user permission. Updating existing `.md` files (like this one, `Architecture.md`) when code changes is fine.
- **Check CloudWatch logs before adding debug instrumentation.** Always inspect existing logs first; only add new logging if the existing logs are insufficient to diagnose the issue.
- **Use `aws_utils.get_client(service)`** instead of creating boto3 clients directly. It provides a shared lazy-init cache.

---

## Commands

### Glitch Agent (Python — `agent/`)

```bash
cd agent
pip install -r requirements.txt
make deploy           # Full: configure from SSM + agentcore deploy (recommended)
make deploy-only      # Deploy with existing .env.deploy (skip configure)
make configure        # Read SSM params and update .bedrock_agentcore.yaml
make verify           # agentcore status
make check-logs       # AgentCore CloudWatch logs
make telegram-troubleshoot  # Telegram webhook/runtime diagnostics
make test             # pytest tests/ -v
pytest tests/test_foo.py -v
agentcore status
agentcore invoke '{"prompt":"hello"}'
agentcore stop-session   # Stop the current session (frees compute, restarts on next invoke)
```

### Infrastructure (CDK TypeScript — `infrastructure/`)

```bash
cd infrastructure
pnpm install && pnpm build
pnpm test
pnpm cdk synth
pnpm cdk diff
pnpm cdk deploy --all --require-approval never
pnpm cdk deploy GlitchEdgeStack --region us-east-1   # WAF + ACM — MUST be us-east-1
```

### UI (React + Vite — `ui/`)

```bash
cd ui && pnpm install && pnpm dev
```

---

## Architecture (Current State)

**Single agent** — Glitch is the only runtime. Sentinel was merged into Glitch. `_archived_monitoring-agent/` is reference-only.

**Stack:** AWS AgentCore Runtime → Docker container → Strands SDK → Bedrock Claude (Sonnet 4.5 primary, Haiku for roleplay, optional Ollama for roleplay via `LocalModel` branch).

**Network:** PUBLIC mode — no VPC ENIs. Agent reaches AWS services directly. Cannot reach on-prem `10.10.110.x` IPs without proxy. See `GLITCH_OLLAMA_PROXY_HOST`.

**Entry points:**

- Telegram: `glitch-telegram-webhook` Lambda → `glitch-telegram-processor` Lambda → AgentCore
- Web UI: CloudFront → `glitch-gateway` Lambda → AgentCore

See `Architecture.md` for full system diagram, stack layout, and flow details.

---

## Key Files

| File | Purpose |
| ---- | ------- |
| `agent/src/main.py` | Entrypoint: bootstrap agent, start Protect subsystem, run server |
| `agent/src/glitch/agent.py` | `GlitchAgent`: process_message, model swap, skill injection |
| `agent/src/glitch/server.py` | `BedrockAgentCoreApp` invocation handler; mode + model routing |
| `agent/src/glitch/modes.py` | `apply_mode_with_memories()`, `_ROLEPLAY_PREAMBLE`, mode constants |
| `agent/src/glitch/auri_context.py` | `AuriContextComposer.compose()`, `get_mountain_time_context()` |
| `agent/src/glitch/auri_memory.py` | Episodic memory via Titan Embed + protect-query Lambda bridge |
| `agent/src/glitch/auri_state.py` | `AuriState` + `SceneSummary` (DynamoDB per session) |
| `agent/src/glitch/routing/model_router.py` | `MODEL_REGISTRY`, `ModelRouter`, `CognitiveTier` |
| `agent/src/glitch/tools/registry.py` | Tool group registration (`ToolRegistry` singleton) |
| `agent/src/glitch/tools/soul_tools.py` | Auri memory tools + S3 persona file tools |
| `agent/src/glitch/aws_utils.py` | `get_client(service)` — always use this for boto3 |
| `infrastructure/lambda/telegram-webhook/index.py` | Receives Telegram, dedupes, dispatches async |
| `infrastructure/lambda/telegram-processor/index.py` | Invokes AgentCore, sends reply to Telegram |
| `infrastructure/lambda/protect-query/index.py` | VPC bridge: protect events + auri_memory RDS ops |
| `infrastructure/lib/stack.ts` | All CDK stacks |

---

## Modes

Mode is stored per-session in DynamoDB `glitch-telegram-config`. Changed by Telegram commands `/auri`, `/default`, `/poet`.

| Mode | `mode_id` | Model | Notes |
| ---- | --------- | ----- | ----- |
| Default | `default` | Sonnet 4.5 | Full Glitch, all tools, ops skills |
| Roleplay (Auri) | `roleplay` | Haiku or `local-roleplay` Ollama | Auri persona, ops skills suppressed |
| Poet | `poet` | Sonnet 4.5 | Poet soul + story book injected |

**Roleplay model selection** (`server.py`):

```python
_ROLEPLAY_MODEL = os.getenv("GLITCH_ROLEPLAY_MODEL", "haiku")  # or "local-roleplay"
```

Set via SSM `/glitch/roleplay-model`. On `LocalModel` branch, default is `local-roleplay`.

---

## Auri Memory System (5 Layers)

All assembled by `AuriContextComposer.compose()` on every roleplay request (~900–1,200 tokens target):

1. **S3 static persona** — `auri-core.md` + `auri-runtime-rules.md`, 5-min in-process cache
2. **DynamoDB session state** — `AuriState` (mode, mood, sliders, dynamic_level) + `SceneSummary` (energy, recent events, open loops) per `session_id`
3. **RDS participant profiles** — Per-person profile text stored with pgvector embedding, filtered by `participant_id`
4. **RDS episodic memories** — Memorable facts stored via `remember_auri` tool; top-5 retrieved by cosine similarity to current user message
5. **S3 storybook** — `story-book.md`, loaded only when user message contains lore/backstory keywords

**VPC bridge:** Agent runs PUBLIC mode. All RDS operations go via `glitch-protect-query` Lambda (which has VPC access). Embeddings generated locally via Bedrock Titan Embed v2 (`amazon.titan-embed-text-v2:0`, 1024 dims), then the embedding is sent to the Lambda.

**participant_id flow:** Webhook Lambda extracts `from.first_name` (lowercased) → `participant_id` field → processor Lambda payload → AgentCore invocation payload → `server.py` extracts → `apply_mode_with_memories()` → `AuriContextComposer`. Without this, Auri loads no participant profile.

---

## Skill System

Skills live in `agent/skills/`. Each skill is a folder with `skill.md` (instructions) + `metadata.json` (keywords, description).

`select_skills_for_message(user_message, skills_dir)` matches keywords in the user message and returns a skill suffix to append to the system prompt.

**Skills are suppressed in roleplay mode.** In `GlitchAgent._select_and_inject_skills()`:

```python
if mode_context:
    skill_suffix = ""   # skip — irrelevant ops instructions waste tokens
else:
    skill_suffix = select_skills_for_message(user_message, self._skills_dir)
```

---

## Model Routing

`MODEL_REGISTRY` in `agent/src/glitch/routing/model_router.py` defines all models.

Bedrock model IDs use cross-region inference profile format: **must end in `-v1:0`**.
Example: `us.anthropic.claude-haiku-4-5-20251001-v1:0`

Missing `-v1:0` causes silent Bedrock API errors → "Sorry, I couldn't process that request".

**Model swap pattern** in `GlitchAgent.process_message()`:

- Saves original `self.agent.model` + `self._current_model_name`
- Swaps in alt model from `self._alt_models` cache (creates on first use)
- Restores original in `finally` block — always runs even on exception

**`local:` prefix** (LocalModel branch): model_id starting with `local:` triggers `OllamaModel` instantiation instead of `BedrockModel`. Host from `GLITCH_OLLAMA_PROXY_HOST`.

---

## Gotchas and Non-Obvious Behaviors

### Strands `max_turns` is silently ignored

`Agent.__call__` signature does not accept `max_turns`. Passing `max_turns=5` in `run_kwargs` has zero effect — Strands ignores unknown kwargs silently. The tool call loop runs via `event_loop_cycle()` with no per-invocation cap. The only effective guardrail is the system prompt instruction in the roleplay preamble.

### Bedrock model IDs must end in `-v1:0`

All Bedrock cross-region inference profile IDs must end with `-v1:0`. Omitting it causes Bedrock to return a validation error that surfaces as "Sorry, I couldn't process that request" in Telegram with no useful error in the agent logs. Always check `MODEL_REGISTRY` entries.

### PUBLIC mode cannot reach on-prem IPs

The agent container runs in PUBLIC network mode. `10.10.110.x` addresses are unreachable. Ollama proxy must be configured via `GLITCH_OLLAMA_PROXY_HOST`. The protect-query Lambda is used as a VPC bridge for RDS access.

### OTEL `KeyError: 'output'` crash after tool use

`opentelemetry-instrumentation-botocore` crashes with `KeyError('output')` when the final post-tool model response has a non-standard structure. The agent's actual response was already generated. `agent.py` has salvage logic that recovers the last assistant message from `conversation_manager.messages` and returns it instead of raising.

### Telegram webhook returns 200 immediately

The webhook Lambda returns HTTP 200 to Telegram before the agent processes anything. Actual invocation happens in the processor Lambda (async). This prevents Telegram's retry storm. If a message never gets a reply, check processor Lambda logs, not webhook logs.

### Group chat speaker identity

In group chats, the webhook Lambda prefixes messages with `[FirstName]:` so conversation history shows who's talking. Without this, Auri can't distinguish speakers. The `participant_id` is also included in the payload for profile loading.

### Auri memory tool loop (3.6M tokens incident)

Without the system prompt constraint, Auri called `store_session_moment`, `remember_auri`, `search_auri_memory` in a 184-cycle loop (3.6M tokens, 806 seconds). Fixed by adding to roleplay preamble: "do NOT call search_auri_memory during a response — memories are pre-loaded. Use remember_auri/store_session_moment at most once each."

### `auri_memory.py` pool parameter is unused

The `pool` parameter in `store_memory()`, `retrieve_memories()` etc. is kept for API compatibility but ignored. Always pass `None`.

### AgentCore keepalive is critical for Bedrock prompt cache

`glitch-agentcore-keepalive` runs every 4 minutes via EventBridge. Bedrock prompt cache (tool definitions, ~$0.30/M) has a 5-minute TTL. Without keepalive, cache misses cost ~$1.20/M instead of $0.30/M for every cold invocation.

### CDK `GlitchEdgeStack` must deploy to `us-east-1`

WAF WebACL with `CLOUDFRONT` scope must be in us-east-1. All other stacks deploy to us-west-2. Deploying EdgeStack to the wrong region silently succeeds but CloudFront can't find the ACL.

### Cross-stack references use SSM, not `Fn.importValue`

CloudFormation `Fn.importValue` creates circular dependencies when stacks reference each other. All cross-stack values go through SSM parameters (`/glitch/*`).

### `agentcore deploy` uses `UpdateAgentRuntime` (ARNs are stable)

`agentcore deploy` does NOT delete and recreate the runtime — it calls `UpdateAgentRuntime`. ARNs remain stable across redeploys. Only destroy+recreate changes the ARN.

### `migrate-auri` is one-time

`make migrate-auri` copies the monolithic `auri.md` to split S3 files (`auri-core.md`, `auri-runtime-rules.md`). Do not re-run — it overwrites any runtime persona edits Auri has made via `update_auri_core` / `update_auri_rules`.

### System commands bypass the AI model

`server.py` intercepts `/haltprotect` → `__system:halt_protect` and `/stop` → `__system:shutdown` before calling the agent. These are handled directly and return structured responses. The AI model never sees them.

---

## Environment Variables (agent)

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `GLITCH_OLLAMA_PROXY_HOST` | — | Ollama proxy base URL (required for Ollama tools in PUBLIC mode) |
| `GLITCH_OLLAMA_CHAT_HOST` | `http://10.10.110.202:11434` | Direct Ollama chat host (on-prem, unreachable from PUBLIC) |
| `GLITCH_ROLEPLAY_MODEL` | `haiku` | Model key for roleplay: `haiku` or `local-roleplay` |
| `GLITCH_ROLEPLAY_OLLAMA_MODEL` | `dolphin-mistral` | Ollama model name when using `local-roleplay` |
| `GLITCH_PROTECT_HOST` | — | UniFi Protect host (e.g. `home.awoo.agency:32443`) |
| `GLITCH_PROTECT_API_KEY` | — | UniFi Protect API key |
| `GLITCH_PROTECT_DB_URI` | — | Protect RDS connection URI |
| `GLITCH_PROTECT_QUERY_LAMBDA` | `glitch-protect-query` | Lambda name for VPC bridge |
| `GLITCH_MEMORY_ID` | — | AgentCore memory ID (set by make configure) |
| `GLITCH_WINDOW_SIZE` | `10` | Strands sliding window conversation size |
| `GLITCH_MAX_TURNS` | `3` | Max tool call turns (NOTE: silently ignored by Strands) |
| `GLITCH_CONFIG_TABLE` | `glitch-telegram-config` | DynamoDB table for Telegram config + Auri state |
| `AWS_REGION` | `us-west-2` | AWS region |

---

## Observability

**Primary log group:** `/aws/bedrock-agentcore/runtimes/<AgentID>-DEFAULT`

Key search strings:

- `GLITCH_INVOKE_ENTRY` — request received by container
- `GLITCH_INVOKE_DONE` — successful completion
- `tokens:` — full telemetry line (input/output tokens, cache reads/writes, cycles, duration, tools_used)
- `AuriContextComposer:` — Auri context assembly log with token estimate
- `model_override=` — confirms model swap is active
- `OllamaModel` — confirms local model is being used

**`/glitch/telemetry`** — structured invocation metrics written by `telemetry.py`. Contains `skills_injected`, tool usage counts, model name.

---

## Testing

```bash
cd agent && pytest tests/ -v
pytest tests/test_model_routing.py -v   # Model routing, Auri preambles, skill suppression
pytest tests/test_auri_integration.py -v  # AuriContextComposer integration tests
```

Tests do not require AWS credentials. They use AST inspection and source-text assertions. Do not add `unittest.mock` patches for things that can be verified structurally.

---

## Branches

| Branch | Purpose |
| ------ | ------- |
| `main` | Production — deployed to AgentCore |
| `LocalModel` | WIP: route Auri roleplay to local Ollama model (OllamaModel via Strands) |
| `protect` | Archived Protect subsystem work |

**LocalModel branch plan:** Add `local-roleplay` to `MODEL_REGISTRY` with `model_id="local:qwen2.5:32b"` (or configurable). Extend `GlitchAgent._get_or_create_alt_model()` to instantiate `OllamaModel` when model_id starts with `"local:"`. Change `GLITCH_ROLEPLAY_MODEL` default to `local-roleplay`. See `~/.claude/plans/wise-mapping-sunrise.md`.

---

## Protect Subsystem

`agent/src/glitch/protect/` — WebSocket poller connects to UniFi Protect, streams motion/person/vehicle events, stores in RDS via direct pool connection (agent is in PUBLIC mode but accesses RDS via Protect DB URI when configured — the protect DB path is direct, not via Lambda).

Started as `asyncio.create_task(_start_protect_subsystem())` in `main.py` before `run_server_async()` so `/ping` health check responds immediately even while Protect initializes.

**`glitch-protect-query` Lambda** serves two purposes:

1. Fast direct Protect data reads for the UI `/api/protect/*` endpoints (<500ms from VPC)
2. VPC bridge for Auri memory R/W (auri_memory.py calls it via `lambda:InvokeFunction`)

---

## Auri `auri_memory` Table Verification

The table is created by `db._run_migrations()` when Protect DB pool is first established.

```bash
# Check if table exists
psql "$GLITCH_PROTECT_DB_URI" -c "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'auri_memory');"

# Create if missing
psql "$GLITCH_PROTECT_DB_URI" -f agent/scripts/auri_memory_migration.sql
# Requires pgvector: CREATE EXTENSION IF NOT EXISTS vector; (as RDS master user)
```

CloudWatch search: `Protect not configured` → DB never initialized. `auri_memory migration complete` → migration ran successfully.
