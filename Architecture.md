# Glitch Agent Architecture

A hybrid AI agent system combining AWS AgentCore Runtime with on-premises Ollama models via Tailscale mesh VPN.

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud (us-west-2)                          │
│  ┌───────────────────────────────────────────────────────────────────────┐  │
│  │                         VPC (10.0.0.0/16)                             │  │
│  │                                                                       │  │
│  │  ┌─────────────────────┐    ┌─────────────────────────────────────┐  │  │
│  │  │   Public Subnet     │    │      Private Isolated Subnet        │  │  │
│  │  │   (10.0.0.0/24)     │    │         (10.0.1.0/24)               │  │  │
│  │  │                     │    │                                     │  │  │
│  │  │  ┌───────────────┐  │    │  ┌─────────────────────────────┐   │  │  │
│  │  │  │ EC2 Tailscale │  │    │  │    AgentCore Runtime        │   │  │  │
│  │  │  │  Connector    │◄─┼────┼──┤    (Glitch Agent)           │   │  │  │
│  │  │  │  (t4g.nano)   │  │    │  │                             │   │  │  │
│  │  │  └───────┬───────┘  │    │  └─────────────────────────────┘   │  │  │
│  │  │          │          │    │              │                     │  │  │
│  │  └──────────┼──────────┘    └──────────────┼─────────────────────┘  │  │
│  │             │                              │                        │  │
│  │             │ Tailscale                    │ VPC Endpoints          │  │
│  │             │ Mesh                         ▼                        │  │
│  │             │                   ┌─────────────────────┐             │  │
│  │             │                   │ • ECR               │             │  │
│  │             │                   │ • CloudWatch Logs   │             │  │
│  │             │                   │ • Secrets Manager   │             │  │
│  │             │                   │ • Bedrock Runtime   │             │  │
│  │             │                   │ • S3 (Gateway)      │             │  │
│  │             │                   └─────────────────────┘             │  │
│  └─────────────┼───────────────────────────────────────────────────────┘  │
└────────────────┼──────────────────────────────────────────────────────────┘
                 │
                 │ WireGuard (UDP 41641)
                 │
┌────────────────┼──────────────────────────────────────────────────────────┐
│                │              On-Premises Network                         │
│                ▼                                                          │
│  ┌─────────────────────┐                                                  │
│  │ Tailscale Subnet    │                                                  │
│  │ Router              │                                                  │
│  │ (10.10.100.230)     │                                                  │
│  └──────────┬──────────┘                                                  │
│             │                                                             │
│    ┌────────┴────────┬─────────────────┐                                  │
│    │                 │                 │                                  │
│    ▼                 ▼                 ▼                                  │
│ ┌──────────┐   ┌──────────┐    ┌──────────┐                               │
│ │ Ollama   │   │ Ollama   │    │ Pi-hole  │                               │
│ │ Chat     │   │ Vision   │    │ DNS      │                               │
│ │ llama3.2 │   │ LLaVA    │    │          │                               │
│ │ :11434   │   │ :11434   │    │ :53      │                               │
│ │10.10.110 │   │10.10.110 │    │10.10.100 │                               │
│ │   .202   │   │   .137   │    │   .70    │                               │
│ └──────────┘   └──────────┘    └──────────┘                               │
└───────────────────────────────────────────────────────────────────────────┘
```

### Recent Architecture and Behavior Updates

- **Dynamic ARN resolution:** `infrastructure/bin/app.ts` now reads the AgentCore runtime ARN and execution role from `agent/.bedrock_agentcore.yaml` automatically. No more hardcoded ARNs after agent destroy/recreate.
- **Step tracking for debugging:** `agent.py` and `server.py` now include `step=` prefixes in error messages to pinpoint exact failure locations.
- **Defensive memory handling:** `get_summary_for_context()` in `sliding_window.py` handles malformed data (strings instead of dicts) gracefully.
- **Session ID padding:** Telegram webhook pads session IDs to >= 33 characters (AgentCore requirement).
- **OTLP disabled by default:** OTLP export only enabled if `OTEL_EXPORTER_OTLP_ENDPOINT` is set or `OTEL_OTLP_ENABLED=true`, avoiding connection errors to localhost:4318 in AgentCore.
- **Tailscale EC2:** Optional nginx UI proxy with Let's Encrypt TLS (Porkbun DNS-01). User data installs Tailscale, nginx, certbot; configures HTTPS and proxy to S3 (UI) and Lambda (API). Fully automated on redeploy.
- **Pi-hole DNS:** Agent can manage custom DNS records on Pi-hole (10.10.100.70, 10.10.100.71) via tools `pihole_list_dns_records`, `pihole_add_dns_record`, `pihole_delete_dns_record`, `pihole_update_dns_record`. Credentials from Secrets Manager (`glitch/pihole-api`). Use case: update `glitch.awoo.agency` after EC2 redeploy.
- **Telegram:** Webhook is always external (Lambda); the runtime never runs a local webhook server. Config can be stored in DynamoDB (`glitch-telegram-config`) for webhook deployments. In groups, the bot responds only when @mentioned; in DMs, owner and allowlisted users can message without a mention.
- **Lambda webhook:** Retries setWebhook on 429; normalizes owner/user IDs for DynamoDB; always returns 200 to Telegram; does not send a per-message metrics line—only the agent reply is sent.
- **Tool use:** Agent calls tools only when the user’s request or an active skill requires it; telemetry/threshold tools are not invoked unless the user explicitly asks for metrics or alerts. `GLITCH_MAX_TURNS` (default 3) caps agent cycles per invocation.
- **Server:** HTTP access logging is disabled so runtime logs are not filled with `GET /ping` lines. Per-reply telemetry is not shown in chat.
- **MCP:** Optional integration via `mcp_servers.yaml` and `MCPServerManager`; stdio transport with env expansion and tool filters.
- **Cleaner UI (AgentCore-first):** To avoid making EC2 the central router for the web UI, a preferred approach is to serve the UI from S3 + CloudFront and use a **Lambda** as the backend-for-frontend (same `InvokeAgentRuntime` pattern as the Telegram webhook). EC2 then runs only Tailscale (and optionally a minimal Ollama-health endpoint). See [Cleaner UI Architecture: AgentCore-First](docs/cleaner-ui-architecture-agentcore-first.md).

## Communication Channels

### Telegram Channel Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                      Telegram Integration                           │
└────────────────────────────────────────────────────────────────────┘

        User sends message
              │
              ▼
    ┌──────────────────┐
    │  Telegram API    │
    └────────┬─────────┘
             │ Polling/Webhook
             ▼
    ┌──────────────────┐
    │ TelegramChannel  │
    │  (ChannelAdapter)│
    └────────┬─────────┘
             │
    ┌────────┴────────┬──────────────┐
    │                 │              │
    ▼                 ▼              ▼
┌─────────┐  ┌────────────┐  ┌──────────────┐
│Bootstrap│  │  Access    │  │   Command    │
│ (pairing│  │  Control   │  │   Handler    │
│  codes) │  │ (policies) │  │  (/config)   │
└─────┬───┘  └──────┬─────┘  └──────┬───────┘
      │             │               │
      └─────────────┴───────────────┘
                    │
                    ▼
          ┌──────────────────┐
          │   GlitchAgent    │
          │ .process_message │
          └──────────────────┘
```

### Telegram-First Configuration

**Bootstrap Process**:
1. Set `GLITCH_TELEGRAM_BOT_TOKEN` environment variable
2. Start Glitch agent
3. Pairing code generated and logged (e.g., `ABC12345`)
4. First user to send code becomes owner
5. Owner configures bot via `/config` commands in Telegram

**Configuration Storage**:
- **Production (webhook mode):** DynamoDB table `glitch-telegram-config` (pk/sk); config and webhook URL set by Lambda; owner, allowlist, and pairing stored in DynamoDB.
- **Local/polling:** `~/.glitch/config.json`; auto-saves on all changes; permissions: 600 (owner read/write only).

**Session Isolation**:
- DM: `telegram:dm:{user_id}` (padded to 33 chars)
- Group: `telegram:group:{chat_id}` (padded to 33 chars)
- Forum Topic: `telegram:group:{chat_id}:topic:{thread_id}`

**Note:** AgentCore requires session IDs to be at least 33 characters. The Telegram webhook Lambda pads shorter IDs with zeros using `.ljust(33, '0')`.

### Access Control Policies

**DM Policies**:
- `pairing` (default): Unknown users receive pairing instructions
- `allowlist`: Only approved user IDs can message
- `open`: Anyone can message
- `disabled`: All DMs rejected

**Group Policies**:
- `allowlist` (default): Only approved group IDs
- `open`: Any group (respects mention requirement)
- `disabled`: All groups rejected

**Mention Requirement** (groups):
- When enabled, bot must be @mentioned to respond (e.g. `@YourBotName hello`).
- Default: `true`
- **Private (DM):** No @mention needed; owner and allowlisted users can message directly.

### Telegram Webhook (Lambda) and External-Only Mode

When the bot is deployed with the Telegram webhook stack, Telegram sends updates to an **AWS Lambda Function URL** (not to the agent runtime). **Troubleshooting:** If the UI shows Telegram as offline or the bot does not respond, see [docs/telegram-troubleshooting.md](docs/telegram-troubleshooting.md). The runtime never runs a local webhook server.

**Flow:**
1. User sends a message in Telegram (DM or group).
2. Telegram POSTs the update to the Lambda Function URL (`glitch-telegram-webhook`).
3. Lambda validates the webhook secret, loads config from DynamoDB, and applies access rules (owner/allowed DMs; in groups, bot must be @mentioned).
4. Lambda invokes the AgentCore Runtime with the message and session ID.
5. Lambda sends the agent’s reply back to the user via the Telegram API and returns 200 to Telegram.

**Behavior:**
- **Webhook is always external:** The agent process does not start a local webhook listener (no `python-telegram-bot[webhooks]` extra required). Updates are received only by the Lambda.
- **Acknowledgment:** Lambda always returns 200 to Telegram (even on errors) so Telegram does not retry; on failure the user receives an error message in chat.
- **Rate limits:** Lambda retries webhook registration (setWebhook) on HTTP 429 with exponential backoff.
- **IDs:** Owner and user IDs from DynamoDB are normalized to integers so owner/allowed checks work (DynamoDB may return numeric types that would otherwise break equality).

**Stack:** `TelegramWebhookStack` (CDK) creates the Lambda, Function URL, DynamoDB config table, and S3 soul bucket; the Lambda receives `AGENTCORE_RUNTIME_ARN` and invokes the runtime via the Bedrock AgentCore API.

### Unified Session Management

Sessions are managed consistently across all channels using the `SESSION#{channel}:{identity}` pattern in DynamoDB:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Session Key Structure                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  DynamoDB Partition Key Pattern:                                │
│  SESSION#{channel}:{identity}                                  │
│                                                                 │
│  Examples:                                                      │
│  SESSION#telegram#dm:123456789 (Telegram DM)                    │
│  SESSION#telegram#group:-100123456 (Telegram group)             │
│  SESSION#ui#client:abc123 (Web UI)                             │
│  SESSION#api#key:xyz789 (API key)                              │
│                                                                 │
│  Dataflow:                                                      │
│  Channel + Identity -> SessionKey -> SessionManager             │
│       |                                                         │
│       v                                                         │
│  DynamoDB get_item                                              │
│       |                                                         │
│  ┌────┴────┐                                                    │
│  v         v                                                    │
│  Existing  New session                                          │
│  session   (put_item)                                           │
│  (return)                                                       │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

This enables:
- Single session view per user across channels
- Future cross-channel identity linking
- Consistent memory context regardless of channel

### Telegram Commands

**Owner Commands**:
| Command | Description |
|---------|-------------|
| `/config show` | Display current configuration |
| `/config dm <policy>` | Set DM policy |
| `/config group <policy>` | Set group policy |
| `/config mention <on\|off>` | Toggle mention requirement |
| `/config allow <user_id>` | Add user to DM allowlist |
| `/config deny <user_id>` | Remove user from allowlist |
| `/config allowgroup <chat_id>` | Add group to allowlist |
| `/config denygroup <chat_id>` | Remove group from allowlist |
| `/config lock` | Lock configuration |
| `/config unlock` | Unlock configuration |
| `/config transfer <user_id>` | Transfer ownership |
| `/status` | Show bot health and status |
| `/help` | Show available commands |

**User Commands**:
| Command | Description |
|---------|-------------|
| `/new` | Start new conversation (clear session) |
| `/status` | Show bot status |
| `/help` | Show help message |

### Vision Integration

**Image Processing**:
1. User sends image via Telegram (photo or document)
2. Channel downloads image (max 5MB by default)
3. Converts to base64
4. Routes to agent with prompt:
   - If caption provided: `[Image attached] {caption}`
   - If no caption: `[Image attached] Please describe this image in detail.`
5. Agent invokes `vision_agent` tool with LLaVA model
6. Response sent back to user

**Supported Formats**: JPEG, PNG, GIF, WebP

### Telegram Message Flow

```
┌────────────────────────────────────────────────────────────────────┐
│                    Telegram Message Processing                      │
└────────────────────────────────────────────────────────────────────┘

User sends message
      │
      ▼
┌─────────────┐
│  Unclaimed? │
├─────────────┤
│ Yes: Check  │──► Valid pairing code? ──► Claim ownership
│     pairing │                        ──► Invalid? Reject
│             │
│ No: Check   │──► Owner? ──► Always allowed
│     access  │           ──► User allowed? ──► Process
│     policy  │                            ──► Denied? Reject
└─────────────┘
      │
      ▼
┌─────────────┐
│  Command?   │
├─────────────┤
│ Yes: Route  │──► /config ──► Owner check ──► Execute
│     to      │──► /status ──► Execute
│     handler │──► /help   ──► Execute
│             │
│ No: Message │──► Extract text/media
│             │──► Generate session_id
│             │──► Download images (if present)
│             │──► Call agent.process_message()
└─────────────┘
      │
      ▼
┌─────────────┐
│   Chunk     │──► Split if > 4000 chars
│  response   │──► Send all chunks
└─────────────┘
```

### Configuration File Schema

```json
{
  "version": 1,
  "owner": {
    "telegram_id": 123456789,
    "claimed_at": "2026-02-19T10:30:00Z"
  },
  "channels": {
    "telegram": {
      "owner_id": 123456789,
      "dm_policy": "pairing",
      "dm_allowlist": [123456789, 987654321],
      "group_policy": "allowlist",
      "group_allowlist": [-1001234567890],
      "require_mention": true,
      "mode": "polling",
      "text_chunk_limit": 4000,
      "media_max_mb": 5
    }
  },
  "locked": false
}
```

### CLI Management

```bash
# Show status
python -m glitch.cli status

# Show configuration
python -m glitch.cli config

# Show detailed status
python -m glitch.cli status --verbose
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `GLITCH_TELEGRAM_BOT_TOKEN` | No | None | Bot token (direct, not recommended for production) |
| `GLITCH_TELEGRAM_SECRET_NAME` | No | `glitch/telegram-bot-token` | Secrets Manager secret name |
| `GLITCH_CONFIG_DIR` | No | `~/.glitch` | Configuration directory (local/polling) |
| `GLITCH_CONFIG_BACKEND` | No | `dynamodb` | `dynamodb` or file-based config for Telegram |
| `GLITCH_CONFIG_TABLE` | No | `glitch-telegram-config` | DynamoDB table for Telegram config (webhook mode) |
| `GLITCH_TELEGRAM_WEBHOOK_URL` | No | (from Lambda) | Override webhook URL for Telegram |
| `GLITCH_MAX_TURNS` | No | `3` | Max agent/tool cycles per invocation (0 = no limit) |
| `GLITCH_MCP_CONFIG_PATH` | No | `agent/mcp_servers.yaml` | Path to MCP servers YAML |
| `GLITCH_SOUL_S3_BUCKET` | No | (or SSM) | S3 bucket for SOUL.md, poet-soul.md, and story-book.md; required for persisting `update_soul` and loading personality from S3 |
| `GLITCH_SOUL_S3_KEY` | No | `soul.md` | S3 object key for SOUL.md |
| `GLITCH_POET_SOUL_S3_KEY` | No | (SSM or `poet-soul.md`) | S3 object key for poet-soul.md (Poet sub-agent) |
| `GLITCH_STORY_BOOK_S3_KEY` | No | (SSM or `story-book.md`) | S3 object key for story-book.md (Poet long-running story details) |
| `AWS_REGION` | No | `us-west-2` | AWS region |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | No | None | OTLP collector endpoint; if set, enables OTLP export |
| `OTEL_OTLP_ENABLED` | No | `false` | Explicitly enable/disable OTLP export (`true`/`false`) |
| `OTEL_CONSOLE_ENABLED` | No | `false` | Enable console telemetry output |

**SOUL and poet-soul S3 configuration**

When the CDK `TelegramWebhookStack` is deployed, it creates an S3 bucket for agent state and writes the bucket name (and default keys) to SSM Parameter Store. The runtime role is granted read/write access to that bucket and read access to these parameters. So **you do not need to set any env vars** for S3 if the stack is deployed and the agent runs with that role: the agent will read `/glitch/soul/s3-bucket` and `/glitch/soul/s3-key` (and `/glitch/soul/poet-soul-s3-key`) from SSM and use them automatically.

- **With CDK stack:** After deploying `GlitchTelegramWebhookStack`, the runtime discovers the bucket via SSM. Ensure the runtime uses the same execution role that the stack attached policies to (`defaultExecutionRoleArn` in the CDK app).
- **Without CDK / override:** Set `GLITCH_SOUL_S3_BUCKET` (and optionally `GLITCH_SOUL_S3_KEY`, `GLITCH_POET_SOUL_S3_KEY`) in the runtime environment. The bucket must allow the runtime role `s3:GetObject` and `s3:PutObject`.
- **Poet sub-agent:** Uses the same bucket as SOUL; key is `GLITCH_POET_SOUL_S3_KEY` or SSM `poet-soul-s3-key`, default `poet-soul.md`. If the object is missing in S3, Poet falls back to file paths (`agent/poet-soul.md`, `/app/poet-soul.md`, `~/poet-soul.md`). Poet can read/write **story-book.md** (same bucket; key `GLITCH_STORY_BOOK_S3_KEY` or SSM `story-book-s3-key`, default `story-book.md`) for long-running story summaries and key details via `get_story_book` and `update_story_book`.

**S3 soul bucket verification (when the agent says the bucket is not found)**

1. **Bucket exists:** The stack creates `glitch-agent-state-{account}-{region}`. Confirm with: `aws s3 ls | grep glitch-agent-state`.
2. **Runtime has the bucket name:** The agent reads `GLITCH_SOUL_S3_BUCKET` first, then SSM `/glitch/soul/s3-bucket`. Set the env var in `agent/.bedrock_agentcore.yaml` under `aws.environment_variables.GLITCH_SOUL_S3_BUCKET` (must match the bucket name above), then run `agentcore deploy` so the runtime gets it. Alternatively, ensure SSM parameters exist (deploy `GlitchTelegramWebhookStack`) and the runtime role has policy `GlitchSoulSsmRead`.
3. **Runtime has S3 access:** The execution role must have `GlitchSoulS3Access` (s3:GetObject, s3:PutObject on the bucket). The stack attaches this via AwsCustomResource to `defaultExecutionRoleArn`; use the same role in `.bedrock_agentcore.yaml` and deploy the stack.
4. **Redeploy after config change:** After editing `.bedrock_agentcore.yaml` (e.g. adding `environment_variables`), run `agentcore deploy` so the runtime is updated with the new env.

**Token Priority:**
1. `GLITCH_TELEGRAM_BOT_TOKEN` environment variable (checked first)
2. AWS Secrets Manager `glitch/telegram-bot-token` (fallback)

**Recommendation**: Use Secrets Manager for production, environment variable for local testing.

### Server and Observability Behavior

- **HTTP access log:** Request logging (e.g. `GET /ping`) is disabled so runtime logs are not flooded; the Uvicorn access logger is disabled at server startup.
- **Per-message telemetry in chat:** The agent and Lambda do not send a follow-up message with token/cycle metrics after each reply; only the main reply text is sent. Telemetry tools remain available when the user explicitly asks for metrics or alerts.

## Agent Architecture

### Tool Use Policy

The agent is instructed to call tools only when:
1. **The user’s request requires it** (e.g. “what’s in this image?” → `vision_agent`, “is Ollama up?” → `check_ollama_health`, “remember I prefer X” → `update_soul`, or routing a task → `local_chat`), or
2. **An active skill instructs it.**

The agent does **not** call tools on its own for side tasks (e.g. telemetry, thresholds, metrics) unless the user explicitly asks for metrics, usage, or alert configuration. For greetings and simple conversation, the agent responds without using any tools. This reduces unnecessary tool cycles and token usage.

**Turn limit:** `GLITCH_MAX_TURNS` (default `3`) limits the number of agent/tool cycles per invocation. Set in the runtime environment to cap cost and latency.

### Tiered Model System

```
┌─────────────────────────────────────────────────────────────────┐
│                     Model Routing System                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐     ┌─────────────┐     ┌─────────────┐       │
│  │   LOCAL     │     │   TIER 1    │     │   TIER 2    │       │
│  │   (Tier 0)  │     │   Primary   │     │  Escalation │       │
│  ├─────────────┤     ├─────────────┤     ├─────────────┤       │
│  │ llama3.2    │     │ Claude      │     │ Claude      │       │
│  │ LLaVA       │     │ Sonnet 4    │     │ Sonnet 4.5  │       │
│  │             │     │             │     │             │       │
│  │ Cost: $0    │     │ Cost: $3/M  │     │ Cost: $5/M  │       │
│  │ Context: 8K │     │ Context:200K│     │ Context:200K│       │
│  └──────┬──────┘     └──────┬──────┘     └──────┬──────┘       │
│         │                   │                   │               │
│         │    ┌──────────────┴───────────────────┘               │
│         │    │                                                  │
│         │    │         ┌─────────────┐                          │
│         │    │         │   TIER 3    │                          │
│         │    │         │   Premium   │                          │
│         │    │         ├─────────────┤                          │
│         │    │         │ Claude      │                          │
│         │    │         │ Opus 4      │                          │
│         │    │         │             │                          │
│         │    │         │ Cost: $15/M │                          │
│         │    │         │ Context:200K│                          │
│         │    │         └─────────────┘                          │
│         │    │                                                  │
│  ┌──────┴────┴──────────────────────────────────────────────┐  │
│  │                    Escalation Triggers                    │  │
│  │  • Confidence < 0.7                                       │  │
│  │  • Context usage > 70%                                    │  │
│  │  • Manual complexity flag                                 │  │
│  │  • Max 1 escalation/turn, 2/session                       │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Memory Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                   Two-Layer Memory System                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Layer 1: Active Window (Strands SDK)                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Sliding window of last N conversation turns               │  │
│  │  • Default: 20 turns                                       │  │
│  │  • Managed by SlidingWindowConversationManager             │  │
│  │  • In-memory, session-scoped                               │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  Layer 2: AgentCore Memory (Persistent + Structured)           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  AWS AgentCore Memory API with structured data             │  │
│  │  • Short-term: Recent events via create_event()            │  │
│  │  • Long-term: Semantic search via retrieve()               │  │
│  │  • Structured: session_goal, facts, constraints,           │  │
│  │    decisions, open_questions persisted as special events   │  │
│  │  • Cross-session persistence                               │  │
│  │  • Namespaced storage (/session/{id}/, /user/facts/)        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  Dataflow:                                                      │
│  User Message -> create_event() -> AgentCore Memory             │
│  Structured update -> create_structured_event() -> Memory       │
│  Startup -> load_structured_from_agentcore() -> Hydrate         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Note:** Structured memory (session_goal, facts, constraints, decisions, open_questions) is persisted directly to AgentCore Memory and hydrated on startup.

## Data Flow

### Request Processing Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Request Processing Pipeline                        │
└──────────────────────────────────────────────────────────────────────────┘

    HTTP POST /invocations
           │
           ▼
┌─────────────────────┐
│  InvocationRequest  │  { prompt: string, session_id?: string }
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ BedrockAgentCoreApp │  Built-in /ping, /invocations, /ws handlers (access log disabled)
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│   invoke() handler  │  Extract prompt, validate request
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│ GlitchAgent         │
│ .process_message()  │
└──────────┬──────────┘
           │
           ├──────────────────────────────────────┐
           │                                      │
           ▼                                      ▼
┌─────────────────────┐              ┌─────────────────────┐
│ Memory: Store       │              │ Memory: Get Context │
│ user_message event  │              │ get_summary_for_    │
│ via create_event()  │              │ context()           │
└─────────────────────┘              └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │ Enrich message with │
                                    │ structured memory   │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │   Strands Agent     │
                                    │   (Claude Sonnet)   │
                                    └──────────┬──────────┘
                                               │
                              ┌────────────────┼────────────────┐
                              │                │                │
                              ▼                ▼                ▼
                    ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
                    │ Tool: local_ │  │ Tool: vision │  │ Tool: check_ │
                    │ chat (Ollama)│  │ _agent       │  │ ollama_health│
                    └──────────────┘  └──────────────┘  └──────────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │    AgentResult      │
                                    │  (Strands response) │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │ extract_metrics_    │
                                    │ from_result()       │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │ InvocationMetrics   │
                                    │ • token_usage       │
                                    │ • duration_seconds  │
                                    │ • cycle_count       │
                                    │ • tool_usage        │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │ Memory: Store       │
                                    │ agent_response      │
                                    └──────────┬──────────┘
                                               │
                                               ▼
                                    ┌─────────────────────┐
                                    │ InvocationResponse  │
                                    │ { message, metrics, │
                                    │   session_id, ...}  │
                                    └─────────────────────┘
```

### Tool Execution Flow

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         Tool Execution Dataflow                           │
└──────────────────────────────────────────────────────────────────────────┘

                    Strands Agent decides to use tool
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │      Tool Selection         │
                    └──────────────┬──────────────┘
                                   │
          ┌────────────────────────┼────────────────────────┐
          │                        │                        │
          ▼                        ▼                        ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│   local_chat()   │    │  vision_agent()  │    │check_ollama_     │
│                  │    │                  │    │health()          │
│ OllamaGenerate   │    │ OllamaGenerate   │    │                  │
│ Payload:         │    │ Payload:         │    │ HealthCheck      │
│ • model          │    │ • model          │    │ Result:          │
│ • prompt         │    │ • prompt         │    │ • name           │
│ • options        │    │ • images         │    │ • host           │
└────────┬─────────┘    └────────┬─────────┘    │ • healthy        │
         │                       │              │ • models[]       │
         │                       │              └────────┬─────────┘
         ▼                       ▼                       │
┌──────────────────┐    ┌──────────────────┐             │
│ httpx.AsyncClient│    │ httpx.AsyncClient│             │
│ POST to Ollama   │    │ POST to Ollama   │             │
│ Chat Host        │    │ Vision Host      │             │
│ 10.10.110.202    │    │ 10.10.110.137    │             │
└────────┬─────────┘    └────────┬─────────┘             │
         │                       │                       │
         │    ┌──────────────────┘                       │
         │    │                                          │
         ▼    ▼                                          ▼
┌──────────────────────────────────────────────────────────────┐
│                    Tailscale Mesh Network                    │
│              (Encrypted WireGuard tunnels)                   │
└──────────────────────────────────────────────────────────────┘
         │    │                                          │
         ▼    ▼                                          ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ Chat host        │    │ Vision host      │    │ Health checks    │
│ .202:11434       │    │ .137:8080        │    │ Chat: /api/tags  │
│ /api/generate    │    │ /v1/chat/...     │    │ Vision: /v1/models│
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│ OllamaGenerate   │    │ OllamaGenerate   │    │ OllamaTags       │
│ Response:        │    │ Response:        │    │ Response:        │
│ • response       │    │ • response       │    │ • models[]       │
│ • done           │    │ • done           │    │                  │
└────────┬─────────┘    └────────┬─────────┘    └────────┬─────────┘
         │                       │                       │
         └───────────────────────┴───────────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────────┐
                    │   Return to Strands Agent   │
                    │   (string response)         │
                    └─────────────────────────────┘
```

## Type System

### Core Types

```
┌─────────────────────────────────────────────────────────────────┐
│                        Type Hierarchy                           │
└─────────────────────────────────────────────────────────────────┘

Session Management Types
├── Channel (Enum): TELEGRAM_DM, TELEGRAM_GROUP, UI, API
├── SessionKey (dataclass)
│   ├── channel: Channel
│   ├── identity: str
│   └── pk: str (property -> SESSION#{channel}:{identity})
├── SessionRecord (TypedDict)
│   ├── pk, sk: str
│   ├── session_id: str
│   ├── channel, identity: str
│   └── created_at, ttl: int
└── SessionManager (class)
    └── get_or_create_session(key) -> session_id

Gateway Lambda Types
├── GatewayEvent (TypedDict)
│   ├── rawPath, body: str
│   ├── headers: Dict[str, str]
│   └── source, detail_type: str (EventBridge)
├── GatewayResponse (TypedDict)
│   ├── statusCode: int
│   ├── body: str
│   └── headers: Dict[str, str]
└── GatewayRouteResult (TypedDict)
    ├── status: int
    └── body: str

Configuration Types (dataclass)
├── TelemetryConfig
│   ├── service_name: str
│   ├── otlp_endpoint: Optional[str]
│   ├── enable_console: bool
│   └── enable_otlp: bool
├── AgentConfig
│   ├── session_id: str
│   ├── memory_id: str
│   ├── region: str
│   └── window_size: int
├── ServerConfig
│   ├── host: str
│   ├── port: int
│   └── debug: bool
└── MemoryConfig
    ├── session_id, memory_id: str
    ├── region: str
    ├── window_size: int
    ├── compression_threshold_pct: float
    └── actor_id: str

API Types (TypedDict)
├── InvocationRequest
│   ├── prompt: str (required)
│   ├── session_id: Optional[str]
│   ├── context: Optional[Dict]
│   ├── stream: bool
│   └── _ui_api_request: UiApiRequest
├── InvocationResponse
│   ├── message: str
│   ├── session_id, memory_id: str
│   ├── metrics: InvocationMetrics
│   └── error: Optional[str]
├── InvocationMetrics
│   ├── duration_seconds: float
│   ├── token_usage: TokenUsage
│   ├── cycle_count, latency_ms: int
│   ├── stop_reason: str
│   └── tool_usage: Dict[str, ToolUsageStats]
├── TokenUsage
│   ├── input_tokens, output_tokens, total_tokens: int
│   └── cache_read_tokens, cache_write_tokens: int
└── ToolUsageStats
    ├── call_count, success_count, error_count: int
    └── total_time: float

Telemetry Types (TypedDict)
├── TelemetryThreshold
│   ├── metric, period: str
│   └── limit: float
├── TelemetryHistoryEntry
│   ├── timestamp: float
│   ├── metrics: InvocationMetrics
│   └── custom_metrics: Dict[str, float] (optional)
├── PeriodAggregates
│   ├── invocation_count: int
│   ├── input/output/total_tokens: int
│   ├── duration_seconds, latency_ms_avg: float
│   └── custom_metrics: Dict[str, float] (optional)
├── CloudWatchQueryResult
│   ├── status: str
│   ├── results: List[Dict]
│   └── statistics: Dict
└── CloudWatchAggregates
    ├── invocation_count: int
    ├── total_input/output_tokens: int
    ├── avg_duration_seconds: float
    └── query_time_range: str

Tool Registry Types
├── ToolGroupInfo (TypedDict)
│   ├── name: str
│   ├── tool_count: int
│   └── enabled: bool
├── ToolRegistryStatus (TypedDict)
│   ├── total_tools, enabled_tools: int
│   ├── groups: List[ToolGroupInfo]
│   └── disabled_groups: List[str]
└── ToolRegistry (class)
    ├── register_group(name, tools)
    ├── disable_group(name) / enable_group(name)
    ├── get_all_tools() -> List[Callable]
    └── list_groups() -> Dict[str, int]

Enums
├── EventType: USER_MESSAGE, AGENT_RESPONSE, TOOL_CALL, TOOL_RESULT, SYSTEM
├── MetricType: COUNTER, GAUGE, HISTOGRAM
├── CognitiveTier: LOCAL, TIER_1, TIER_2, TIER_3
└── IntegrationStatus: NOT_IMPLEMENTED, CONFIGURED, CONNECTED, ERROR
```

## MCP (Model Context Protocol)

Glitch can connect to external MCP servers to expose their tools to the agent (e.g. AWS Knowledge, Context7, custom MCP servers).

**Configuration:** `agent/mcp_servers.yaml` (or path set via `GLITCH_MCP_CONFIG_PATH`). The file uses a top-level key `mcp_servers`; each entry is a server name with:

| Field | Description |
|-------|-------------|
| `enabled` | Whether to load this server (default: true) |
| `transport` | `stdio`, `sse`, or `streamable_http` (stdio is the primary supported transport) |
| `command` | Command to run for stdio (e.g. `npx`, `python`) |
| `args` | Arguments (e.g. `["-y", "some-mcp-server"]`) |
| `env` | Optional env vars for the server process |
| `prefix` | Optional prefix for tool names to avoid collisions |
| `tool_filters` | Optional `allowed` / `rejected` lists to limit which tools are exposed |

**Env expansion:** Values in the YAML can use `${VAR_NAME}`; they are expanded from the environment at load time.

**Runtime:** `MCPServerManager` (in `glitch.mcp`) loads the config, creates Strands `MCPClient` instances over stdio for each enabled server, and provides them as tool providers to the agent. The model router can route tasks to `mcp_use` (e.g. primary model `mcp_agent`) when MCP tools are in use.

**Example `mcp_servers.yaml`:**

```yaml
mcp_servers:
  my_server:
    enabled: true
    transport: stdio
    command: npx
    args: ["-y", "my-mcp-server"]
    env:
      API_KEY: "${MY_API_KEY}"
    tool_filters:
      allowed: ["tool_a", "tool_b"]
```

## Infrastructure Components

### CDK Stack Architecture

The infrastructure uses a **consolidated foundation stack** design that eliminates cross-stack dependency issues:

```
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 1: FOUNDATION                          │
│  GlitchFoundationStack                                          │
│  ├── VPC + Subnets + VPC Endpoints                              │
│  ├── Security Groups (AgentCore)                                │
│  ├── IAM Roles (Runtime, CodeBuild) - auto-generated names      │
│  └── SSM Parameters (role ARNs, VPC IDs, SG IDs)                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 2: AGENT                               │
│  make deploy (runs pre-deploy-configure.py + agentcore deploy)  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PHASE 3: APPLICATION                         │
│  GlitchSecretsStack, GlitchStorageStack, GlitchGatewayStack,    │
│  GlitchTelegramWebhookStack, GlitchTailscaleStack,              │
│  GlitchUiHostingStack, GlitchCertificateStack, GlitchAgentCoreStack │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **No hardcoded IAM role names** - CloudFormation generates unique names, preventing conflicts
2. **SSM Parameters for cross-stack references** - No `Fn.importValue` dependencies that block updates
3. **Single foundation stack** - VPC + IAM in one stack, simpler to manage and recover
4. **Idempotent deployment** - Can be run multiple times without manual intervention

### SSM Parameters

The foundation stack creates these SSM parameters for cross-stack communication:

| Parameter | Description |
|-----------|-------------|
| `/glitch/vpc/id` | VPC ID |
| `/glitch/vpc/private-subnet-ids` | Comma-separated private subnet IDs |
| `/glitch/vpc/public-subnet-ids` | Comma-separated public subnet IDs |
| `/glitch/security-groups/agentcore` | AgentCore security group ID |
| `/glitch/iam/runtime-role-arn` | Runtime role ARN |
| `/glitch/iam/codebuild-role-arn` | CodeBuild role ARN |

### CDK Stacks

| Stack | Purpose | Key Resources |
|-------|---------|---------------|
| `GlitchFoundationStack` | Foundation infrastructure | VPC, Subnets, VPC Endpoints, Security Groups, IAM Roles (Runtime + CodeBuild), SSM Parameters |
| `GlitchSecretsStack` | Credential management | Secrets Manager references (Tailscale auth, API keys, Telegram token, Porkbun API, Pi-hole API) |
| `GlitchTailscaleStack` | Hybrid connectivity | EC2 t4g.nano, Security Groups; optional nginx UI proxy + Let's Encrypt (Porkbun DNS) |
| `GlitchUiHostingStack` | UI static hosting | S3 bucket for built UI, CloudFront distribution |
| `GlitchAgentCoreStack` | Agent runtime policies | Managed policies attached to runtime role |
| `GlitchStorageStack` | Persistent storage | DynamoDB config table, S3 soul bucket, CloudWatch telemetry log group |
| `GlitchGatewayStack` | Gateway | Lambda Function URL (invocations, /api/*, keepalive) |
| `GlitchTelegramWebhookStack` | Telegram integration | Lambda Function URL for Telegram webhook |
| `GlitchCertificateStack` | TLS certificates | ACM certificate in us-east-1 for CloudFront |

**Note:** The Tailscale EC2 instance uses only the minimal root volume from the AMI. No dedicated EBS volumes are provisioned.

### Dynamic Configuration Resolution

Configuration is resolved through two mechanisms:

**1. SSM Parameters (Infrastructure → Agent)**

The `GlitchFoundationStack` writes VPC, security group, and IAM role information to SSM Parameter Store. The `pre-deploy-configure.py` script reads these parameters and updates `agent/.bedrock_agentcore.yaml` before `agentcore deploy`:

```python
# SSM Parameters read by pre-deploy-configure.py
SSM_PRIVATE_SUBNET_IDS = '/glitch/vpc/private-subnet-ids'
SSM_AGENTCORE_SG_ID = '/glitch/security-groups/agentcore'
SSM_RUNTIME_ROLE_ARN = '/glitch/iam/runtime-role-arn'
SSM_CODEBUILD_ROLE_ARN = '/glitch/iam/codebuild-role-arn'
```

**2. YAML Config (Agent → Infrastructure)**

`infrastructure/bin/app.ts` reads the AgentCore runtime ARN from `agent/.bedrock_agentcore.yaml` at synth/deploy time. This ensures the Gateway and Telegram stacks always use the current agent ARN after `agentcore deploy`:

```typescript
function getAgentCoreRuntimeArn(agentName: string = 'Glitch'): string | null {
  const configPath = path.resolve(__dirname, '../../agent/.bedrock_agentcore.yaml');
  const config = yaml.parse(fs.readFileSync(configPath, 'utf8'));
  return config?.agents?.[agentName]?.bedrock_agentcore?.agent_arn ?? null;
}
```

This two-way configuration flow eliminates hardcoded values and ensures consistency between infrastructure and agent deployments.

### Potentially Unused Resources

Resources that may exist from earlier architectures or one-off setups and are not currently referenced by the CDK app:

- **Old AgentCore runtimes**: After `agentcore destroy` and recreate, old runtime log groups (e.g., `/aws/bedrock-agentcore/runtimes/Glitch-OLD_ID-DEFAULT`) may remain in CloudWatch. These can be deleted manually.

### Future Gateway Consolidation

The gateway Lambda (`GlitchGatewayStack`) currently serves the web UI (invocations, `/api/*`, keepalive). A possible next step is to consolidate the Telegram webhook into the same gateway: one Lambda handling both UI traffic and Telegram webhook callbacks, reducing stacks and simplifying routing. This would require adding a webhook path (e.g. `/webhook/telegram`), DynamoDB config access, and Telegram API permissions to the gateway function.

### VPC Endpoints (Single AZ for cost optimization)

| Endpoint | Service | Purpose |
|----------|---------|---------|
| S3 Gateway | `s3` | ECR image layers |
| ECR Docker | `ecr.dkr` | Container registry |
| ECR API | `ecr.api` | Registry API |
| CloudWatch Logs | `logs` | Agent logging |
| Secrets Manager | `secretsmanager` | Credential access |
| Bedrock Runtime | `bedrock-agent-runtime` | AgentCore API |

## Tools Reference

### Ollama Tools

| Tool | Host | Port / API | Model | Purpose |
|------|------|------------|-------|---------|
| `local_chat` | 10.10.110.202 | 11434 (Ollama /api/generate) | mistral-nemo:12b | Lightweight chat tasks |
| `vision_agent` | 10.10.110.137 | 8080 (OpenAI /v1/chat/completions) | LLaVA | Image analysis |
| `check_ollama_health` | Both | 11434 + 8080 | N/A | Connectivity (Chat: /api/tags, Vision: /v1/models) |

### Pi-hole DNS Tools

| Tool | Hosts | Purpose |
|------|-------|---------|
| `pihole_list_dns_records` | 10.10.100.70, 10.10.100.71 | List custom DNS records from both Pi-hole servers |
| `pihole_add_dns_record` | Both | Add a custom DNS record (domain → IP) |
| `pihole_delete_dns_record` | Both | Delete a custom DNS record |
| `pihole_update_dns_record` | Both | Update a record (delete old IP, add new IP) |

Credentials from Secrets Manager (`glitch/pihole-api`). Agent reaches Pi-hole via Tailscale mesh. Skill: `.cursor/skills/pihole-dns/SKILL.md`.

### Network Tools

| Tool | Service | Status |
|------|---------|--------|
| `query_pihole_stats` | Pi-hole DNS stats | Placeholder / planned |
| `check_unifi_network` | Unifi Controller | Placeholder / planned |
| `query_protect_cameras` | Unifi Protect | Placeholder / planned |

## Observability

### OpenTelemetry Metrics (via Strands SDK)

| Metric | Type | Description |
|--------|------|-------------|
| `strands.event_loop.input.tokens` | Counter | Input tokens consumed |
| `strands.event_loop.output.tokens` | Counter | Output tokens generated |
| `strands.event_loop.cache_read.input.tokens` | Counter | Cached input tokens |
| `strands.event_loop.cache_write.input.tokens` | Counter | Tokens written to cache |
| `strands.event_loop.cycle_count` | Counter | Agent reasoning cycles |
| `strands.event_loop.cycle_duration` | Histogram | Time per cycle |
| `strands.event_loop.latency` | Histogram | Total latency |
| `strands.tool.call_count` | Counter | Tool invocations |
| `strands.tool.duration` | Histogram | Tool execution time |
| `strands.tool.success_count` | Counter | Successful tool calls |
| `strands.tool.error_count` | Counter | Failed tool calls |
| `strands.model.time_to_first_token` | Histogram | Model response latency |

### CloudWatch Integration

- **Log Group**: `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT`
- **Metrics Namespace**: `glitch-agent`
- **Trace Service**: `glitch-agent`

## Logging Reference

### Log Groups Overview

| Log Group | Purpose | Who Writes | Retention |
|-----------|---------|------------|-----------|
| `/aws/bedrock-agentcore/runtimes/Glitch-TeGZF0HlNC-DEFAULT` | Container stdout/stderr, OTEL logs | AgentCore platform | Platform-managed |
| `/aws/lambda/glitch-gateway` | Gateway Lambda execution logs | Lambda service | 14 days |
| `/aws/lambda/glitch-telegram-webhook` | Telegram webhook Lambda logs | Lambda service | 14 days |
| `/glitch/telemetry` | Invocation metrics (tokens, duration) | Agent code (direct writes) | 30 days |

### Finding Logs - Quick Commands

**1. List recent AgentCore runtime log streams:**
```bash
aws logs describe-log-streams \
  --log-group-name "/aws/bedrock-agentcore/runtimes/Glitch-TeGZF0HlNC-DEFAULT" \
  --order-by LastEventTime --descending --limit 10 \
  --region us-west-2 --output table
```

**2. Tail the most recent runtime log stream:**
```bash
# Get the latest stream name first, then:
aws logs tail "/aws/bedrock-agentcore/runtimes/Glitch-TeGZF0HlNC-DEFAULT" \
  --log-stream-name-prefix "$(date -u +%Y/%m/%d)/[runtime-logs]" \
  --since 1h --follow --region us-west-2
```

**3. Search for chat invocations (should show `GLITCH_INVOKE_ENTRY`):**
```bash
aws logs filter-log-events \
  --log-group-name "/aws/bedrock-agentcore/runtimes/Glitch-TeGZF0HlNC-DEFAULT" \
  --filter-pattern "GLITCH_INVOKE_ENTRY" \
  --start-time $(($(date +%s) - 3600))000 \
  --region us-west-2
```

**4. Check Gateway Lambda for errors:**
```bash
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-gateway" \
  --filter-pattern "ERROR" \
  --start-time $(($(date +%s) - 3600))000 \
  --region us-west-2
```

**5. Check for timeout errors specifically:**
```bash
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-gateway" \
  --filter-pattern "timed out" \
  --start-time $(($(date +%s) - 86400))000 \
  --region us-west-2
```

### Runtime Log Streams Explained

The AgentCore runtime log group contains multiple stream types:

**`YYYY/MM/DD/[runtime-logs]<UUID>`** - Container stdout/stderr
- A **new stream** is created each time a **new container** starts
- Contains: startup logs, `logger.info()` output, print statements
- Short-lived containers (terminated after idle timeout) create many streams
- Example: `2026/02/21/[runtime-logs]5a972b74-1b1d-408b-921a-d78661dc2997`

**`otel-rt-logs`** - OpenTelemetry structured logs
- Single persistent stream for all OTEL-formatted logs
- Contains: structured JSON logs with trace IDs, span IDs
- Updated continuously as containers process requests

### Why You Might Not See Logs

**Symptom: No `GLITCH_INVOKE_ENTRY` logs after sending a chat message**

This means chat invocations are NOT reaching the container. Check:

1. **Gateway Lambda timeout** - The gateway may be timing out before the container responds
   ```bash
   aws logs filter-log-events \
     --log-group-name "/aws/lambda/glitch-gateway" \
     --filter-pattern "timed out" \
     --start-time $(($(date +%s) - 3600))000 \
     --region us-west-2
   ```

2. **Gateway Lambda errors** - Check for any errors in the gateway
   ```bash
   aws logs filter-log-events \
     --log-group-name "/aws/lambda/glitch-gateway" \
     --filter-pattern "ERROR" \
     --start-time $(($(date +%s) - 3600))000 \
     --region us-west-2
   ```

3. **nginx proxy errors** - SSH to Tailscale EC2 and check nginx logs
   ```bash
   sudo tail -f /var/log/nginx/error.log
   ```

**Symptom: Only startup logs, no invocation logs**

The container is starting but not receiving requests. This happens when:
- Containers are being churned (created/terminated rapidly)
- Health checks are the only traffic reaching containers
- The "Invocation completed (0.000s)" logs are health checks, not real chat

**Symptom: Logs exist but are from hours/days ago**

Check if containers are running:
```bash
# Look for recent log streams (last hour)
aws logs describe-log-streams \
  --log-group-name "/aws/bedrock-agentcore/runtimes/Glitch-TeGZF0HlNC-DEFAULT" \
  --order-by LastEventTime --descending --limit 5 \
  --region us-west-2 \
  --query 'logStreams[*].[logStreamName,lastEventTimestamp]'
```

### What Each Log Contains

**Container startup sequence (in `[runtime-logs]<UUID>`):**
```
============================================================
GLITCH AGENT STARTUP
============================================================
GLITCH_MODE env var: NOT_SET
Python version: 3.10.19
Current working directory: /app
============================================================
2026-02-21 06:00:29 - __main__ - INFO - Starting Glitch agent...
2026-02-21 06:00:29 - strands.telemetry.config - INFO - Initializing tracer
2026-02-21 06:00:29 - glitch.telemetry - INFO - OTLP exporter enabled
2026-02-21 06:00:29 - bedrock_agentcore.memory.client - INFO - Initialized MemoryClient
2026-02-21 06:00:29 - glitch.server - INFO - Starting AgentCore HTTP server
INFO:     Uvicorn running on http://0.0.0.0:8080 (Press CTRL+C to quit)
```

**Chat invocation (when working):**
```
2026-02-21 06:05:00 - glitch.server - INFO - GLITCH_INVOKE_ENTRY session_id=abc123...
2026-02-21 06:05:00 - glitch.agent - INFO - Processing message: "Hello"
2026-02-21 06:05:05 - strands.agent - INFO - Agent response generated
2026-02-21 06:05:05 - glitch.telemetry - INFO - {"event_type": "invocation_metrics", ...}
2026-02-21 06:05:05 - bedrock_agentcore.app - INFO - Invocation completed successfully (5.123s)
```

**Health check (0.000s duration = NOT a real chat):**
```
2026-02-21 06:00:33 - bedrock_agentcore.app - INFO - Invocation completed successfully (0.000s)
```

### CloudWatch Logs Insights Queries

**Find all chat invocations in last 24 hours:**
```
fields @timestamp, @message
| filter @message like /GLITCH_INVOKE_ENTRY/
| sort @timestamp desc
| limit 100
```

**Find errors in last hour:**
```
fields @timestamp, @message
| filter @message like /ERROR/ or @message like /Exception/ or @message like /Traceback/
| sort @timestamp desc
| limit 50
```

**Measure invocation duration:**
```
fields @timestamp, @message
| filter @message like /Invocation completed successfully/
| parse @message /\((?<duration>[\d.]+)s\)/
| filter duration > 0.1
| sort @timestamp desc
| limit 50
```

**Where logs go (summary)**

| What | Log group | Who writes | Who reads |
|------|-----------|------------|-----------|
| **Invocation telemetry** (metrics, token counts, duration) | `/glitch/telemetry` | Agent code: `log_invocation_metrics()` → direct `put_log_events` + `logger.info()`. Stream: `invocations/YYYY-MM-DD`. | `query_persistent_telemetry` / `query_cloudwatch_telemetry` using `GLITCH_TELEMETRY_LOG_GROUP` (default `/glitch/telemetry`). |
| **Runtime logs** (startup, reasoning, tool calls, stdout) | `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT` | AgentCore platform (captures container stdout/OTEL). Not written by our IAM role. | You (tail, Logs Insights). |
| **Gateway Lambda logs** | `/aws/lambda/glitch-gateway` | Lambda service | You (check for routing/timeout errors). |
| **Telegram webhook logs** | `/aws/lambda/glitch-telegram-webhook` | Lambda service | You (check for webhook errors). |

- **Telemetry log group** is created/referenced in `storage-stack.ts` (`/glitch/telemetry`); runtime role has `GlitchTelemetryAccess` (PutLogEvents, etc.). `GLITCH_TELEMETRY_LOG_GROUP` is not set in `.bedrock_agentcore.yaml`, so the agent defaults to `/glitch/telemetry`.
- **Runtime log group** is created and owned by the Bedrock AgentCore service. Our CDK grants the runtime role access to `/aws/bedrock/agentcore/*` (different path); the runtime log group is `/aws/bedrock-agentcore/...`. If that group exists but stays empty after invocations, the platform is not delivering container logs there (or they are routed elsewhere / buffered).

### Request Routing Chain

Chat messages from the UI follow this path:

```
┌─────────┐    ┌─────────────┐    ┌─────────────────┐    ┌──────────────────┐    ┌───────────────┐
│   UI    │───▶│   nginx     │───▶│ Gateway Lambda  │───▶│ AgentCore        │───▶│  Container    │
│ (React) │    │ (Tailscale) │    │ (glitch-gateway)│    │ Runtime API      │    │  (Glitch)     │
└─────────┘    └─────────────┘    └─────────────────┘    └──────────────────┘    └───────────────┘
     │               │                    │                      │                      │
     │  POST /invocations                 │                      │                      │
     │──────────────▶│                    │                      │                      │
     │               │  proxy_pass        │                      │                      │
     │               │─────────────────▶  │                      │                      │
     │               │                    │  invoke_agent()      │                      │
     │               │                    │  timeout=90s         │                      │
     │               │                    │─────────────────────▶│                      │
     │               │                    │                      │  /invocations        │
     │               │                    │                      │─────────────────────▶│
     │               │                    │                      │                      │ process_message()
     │               │                    │                      │◀─────────────────────│
     │               │                    │◀─────────────────────│                      │
     │               │◀───────────────────│                      │                      │
     │◀──────────────│                    │                      │                      │
```

**Timeout Configuration:**

| Component | Timeout | Config Location |
|-----------|---------|-----------------|
| UI fetch | None (browser default) | `ui/src/api/client.ts` |
| nginx proxy_read_timeout | 300s | `infrastructure/lib/tailscale-stack.ts` |
| Gateway Lambda function | 300s | `infrastructure/lib/gateway-stack.ts` (line 32) |
| Gateway `invoke_agent()` urllib | 180s | `gateway-stack.ts` inline code (line 182) |
| Gateway `invoke_api()` urllib | 180s | `stack.ts` GlitchGatewayStack inline Lambda (invoke_api) |
| AgentCore Runtime | Platform-managed | N/A |

**UI API requests** (`/api/status`, `/api/memory/summary`, etc.) use `invoke_api()` with 180s timeout and go through the same chain but call `_ui_api_request` handler in the container.

**Known Issue: Gateway Timeout on Chat Invocations**

The Gateway Lambda's `invoke_agent()` has a 90-second timeout for the HTTP request to AgentCore Runtime. If the container takes longer than 90 seconds to respond (due to cold start + LLM processing time), the gateway returns a timeout error even though the container may still be processing.

Symptoms:
- Gateway Lambda logs show: `Failed to invoke agent: The read operation timed out`
- No `GLITCH_INVOKE_ENTRY` logs in runtime log group
- UI receives 504 Gateway Timeout (from nginx) or error response

Diagnosis commands:
```bash
# Check for timeout errors in gateway
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-gateway" \
  --filter-pattern "timed out" \
  --start-time $(($(date +%s) - 3600))000 \
  --region us-west-2

# Check for actual chat invocations reaching container
aws logs filter-log-events \
  --log-group-name "/aws/bedrock-agentcore/runtimes/Glitch-TeGZF0HlNC-DEFAULT" \
  --filter-pattern "GLITCH_INVOKE_ENTRY" \
  --start-time $(($(date +%s) - 3600))000 \
  --region us-west-2
```

**Fix Options:**

1. **Increase Gateway timeout** (applied): Changed `timeout=90` to `timeout=180` in `invoke_agent()` and Lambda function timeout from 120s to 300s in `gateway-stack.ts`.

2. **Keep containers warm**: The 5-minute EventBridge keepalive rule keeps the Gateway Lambda warm, but doesn't keep AgentCore containers warm. Consider adding a periodic `/invocations` call with a simple prompt to keep containers alive.

3. **Optimize cold start**: Current cold start is ~2 seconds (fast). The issue is not cold start time but total request processing time for LLM calls.

## Troubleshooting

### Common Issues

**HTTP 404: Agent not found**
- **Cause:** Gateway or Telegram Lambda configured with old AgentCore runtime ARN after `agentcore destroy`/recreate.
- **Fix:** Redeploy CDK stacks (`pnpm cdk deploy GlitchGatewayStack GlitchTelegramWebhookStack`). The ARN is now read dynamically from `.bedrock_agentcore.yaml`.

**HTTP 400: Bad Request from Telegram**
- **Cause:** Session ID shorter than 33 characters (AgentCore requirement).
- **Fix:** Telegram webhook now pads session IDs with `.ljust(33, '0')`.

**"string indices must be integers" error**
- **Cause:** Code expecting a dict received a string (often in memory/telemetry processing).
- **Fix:** Defensive `isinstance` checks added in `sliding_window.py`. Error messages now include `step=` prefix to pinpoint location.

**Container crash on startup (no logs)**
- **Cause:** Import error or missing dependency (e.g., `model_validator` not imported from Pydantic).
- **Fix:** Check `agentcore invoke` output for `RuntimeClientError`. Fix import errors and redeploy.

**OTLP connection refused (localhost:4318)**
- **Cause:** OpenTelemetry OTLP exporter trying to connect to non-existent local collector.
- **Fix:** OTLP now disabled by default unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set or `OTEL_OTLP_ENABLED=true`.

**No CloudWatch logs appearing**
- **Cause:** Multiple possible causes: IAM policy incorrect, container crashing, or stale AgentCore runtime.
- **Fix:** 
  1. Check IAM policy uses `/aws/bedrock-agentcore/*` (not `/aws/bedrock/agentcore/*`).
  2. Verify container starts with `agentcore invoke '{"prompt":"test"}'`.
  3. If persistent, run `agentcore destroy` then `agentcore deploy --auto-update-on-conflict`.

## Cost Optimization

| Component | Original | Optimized | Monthly Savings |
|-----------|----------|-----------|-----------------|
| NAT Gateway | $32.00 | $0 (public subnet) | $32.00 |
| EC2 Instance | $7.59 (t3.micro) | $3.80 (t4g.nano ARM) | $3.79 |
| VPC Endpoints | $87.60 (6×2 AZ) | $43.80 (6×1 AZ) | $43.80 |
| **Total** | ~$127 | ~$47.60 | **~$79.40** |

**Annual Savings**: ~$953

## Security Model

### Network Security
- AgentCore Runtime in private isolated subnets (no internet route)
- Tailscale EC2 in public subnet with minimal inbound rules
- VPC endpoints for all AWS service access
- WireGuard encryption for all on-prem traffic

### IAM Least Privilege
- AgentCore role: Bedrock invoke, Memory API, Secrets read
- EC2 role: SSM access, Secrets read (Tailscale key only)
- No cross-account access

### Secrets Management
- `glitch/tailscale-auth-key`: Ephemeral Tailscale auth key
- `glitch/api-keys`: API credentials (if needed)
- `glitch/telegram-bot-token`: Telegram bot token from @BotFather
- `glitch/porkbun-api`: Porkbun API key/secret for Let's Encrypt DNS-01 (Tailscale EC2 TLS)
- `glitch/pihole-api`: Pi-hole admin credentials (username, password, hosts) for DNS record management by agent
- All secrets in AWS Secrets Manager with rotation support

## Project Structure

```
AgentCore-Glitch/
├── infrastructure/              # CDK TypeScript
│   ├── bin/app.ts              # CDK app entry (reads runtime ARN from yaml)
│   ├── lib/
│   │   └── stack.ts            # All stacks in single file:
│   │                           #   - GlitchFoundationStack (VPC, IAM, SSM)
│   │                           #   - GlitchSecretsStack
│   │                           #   - GlitchTailscaleStack (EC2, nginx, TLS)
│   │                           #   - GlitchUiHostingStack (S3, CloudFront)
│   │                           #   - GlitchAgentCoreStack (runtime policies)
│   │                           #   - GlitchStorageStack (DynamoDB, S3, logs)
│   │                           #   - GlitchGatewayStack (Lambda gateway)
│   │                           #   - GlitchTelegramWebhookStack
│   │                           #   - GlitchCertificateStack (ACM)
│   ├── docs/
│   │   └── DEPLOYMENT.md       # Deployment guide
│   ├── test/                   # Jest unit tests
│   └── package.json
├── agent/                       # Python Strands agent
│   ├── src/
│   │   ├── main.py             # Entry point
│   │   └── glitch/
│   │       ├── __init__.py     # Package exports
│   │       ├── types.py        # Type definitions (TypedDict, dataclass, Enum)
│   │       ├── agent.py        # GlitchAgent orchestrator
│   │       ├── server.py       # HTTP server (access log disabled)
│   │       ├── telemetry.py    # OpenTelemetry + CloudWatch Logs Insights
│   │       ├── cli.py          # CLI commands
│   │       ├── channels/       # Communication channels
│   │       │   ├── __init__.py
│   │       │   ├── base.py              # ChannelAdapter ABC
│   │       │   ├── types.py             # Channel types
│   │       │   ├── config_manager.py    # Config persistence
│   │       │   ├── dynamodb_config.py   # DynamoDB config (webhook mode)
│   │       │   ├── bootstrap.py         # Owner pairing codes
│   │       │   ├── telegram.py          # Telegram channel
│   │       │   └── telegram_commands.py # /config handlers
│   │       ├── memory/
│   │       │   └── sliding_window.py   # Two-layer memory (Active + AgentCore)
│   │       ├── mcp/                      # MCP (Model Context Protocol)
│   │       │   ├── __init__.py
│   │       │   ├── types.py              # MCPServerConfig, MCPConfig
│   │       │   ├── loader.py             # YAML loader, env expansion
│   │       │   └── manager.py            # MCPServerManager
│   │       ├── routing/
│   │       │   └── model_router.py
│   │       ├── skills/                   # Skill system
│   │       │   ├── types.py
│   │       │   ├── loader.py, registry.py, selector.py, planner.py, prompt_builder.py
│   │       └── tools/
│   │           ├── registry.py           # ToolRegistry (grouped tools)
│   │           ├── ollama_tools.py
│   │           ├── network_tools.py
│   │           ├── pihole_tools.py       # Pi-hole DNS record management
│   │           ├── soul_tools.py
│   │           ├── memory_tools.py
│   │           ├── telemetry_tools.py
│   │           └── code_interpreter_tools.py
│   ├── scripts/
│   │   └── pre-deploy-configure.py  # Reads SSM, updates yaml before deploy
│   ├── mcp_servers.yaml        # MCP server definitions (optional)
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── SOUL.md                 # Agent personality
│   └── .bedrock_agentcore.yaml # Toolkit config
├── ui/                         # React + DaisyUI dashboard
│   ├── src/
│   │   ├── App.tsx
│   │   ├── api/client.ts
│   │   ├── components/
│   │   ├── tabs/
│   │   └── store/
│   └── package.json
├── .gitignore
├── pnpm-workspace.yaml
└── Architecture.md             # This file
```

## Deployment

### Prerequisites
- AWS CLI configured for account 999776382415, region us-west-2
- Node.js 18+, pnpm, Python 3.10+
- Tailscale subnet router at 10.10.100.230
- Ollama hosts accessible on local network
- Telegram bot token (optional, from @BotFather)

### Quick Start (New Account)

**Phase 1: Deploy Foundation Stack**

```bash
cd infrastructure
pnpm install && pnpm build
pnpm run cdk bootstrap aws://999776382415/us-west-2
pnpm cdk deploy GlitchFoundationStack --require-approval never
```

This creates VPC, IAM roles, security groups, and SSM parameters.

**Phase 2: Deploy Agent**

```bash
cd ../agent
make deploy  # Runs pre-deploy-configure.py + agentcore deploy
```

**Phase 3: Deploy Application Stacks**

```bash
cd ../infrastructure
pnpm cdk deploy --all --require-approval never
```

**Phase 4: Configure Telegram (Optional)**

```bash
# Create Telegram bot and store token in Secrets Manager
aws secretsmanager create-secret \
  --name glitch/telegram-bot-token \
  --secret-string "your-bot-token" \
  --region us-west-2

# Check startup logs for pairing code, send to bot on Telegram
```

### Existing Account (Updates)

After initial deployment:

```bash
cd infrastructure
pnpm build
pnpm cdk deploy --all --require-approval never
```

If you need to update the agent:

```bash
cd agent
make deploy  # Runs pre-deploy-configure.py + agentcore deploy
```

### Verify Deployment

```bash
# Check SSM parameters
aws ssm get-parameters-by-path --path /glitch --recursive --output table

# Check agent status
agentcore status

# View logs
aws logs tail /aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT --follow

# Test Tailscale connectivity (from EC2)
aws ssm start-session --target <instance-id>
tailscale status
curl http://10.10.110.202:11434/api/tags
```

### Telegram Configuration

After claiming the bot, configure access policies via Telegram:

```
/config dm pairing          # Set DM policy to pairing mode
/config group allowlist     # Only allow specific groups
/config mention on          # Require @mention in groups
/config allow 987654321     # Add user to allowlist
/config show                # View current configuration
```

### Verify Deployment

```bash
# Check agent status
agentcore status

# Check Telegram configuration (if enabled)
python -m glitch.cli status --verbose

# View logs
aws logs tail /aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT --follow

# Test Tailscale connectivity (from EC2)
aws ssm start-session --target <instance-id>
tailscale status
curl http://10.10.110.202:11434/api/tags
```

## Dashboard UI

A React + DaisyUI dashboard for monitoring and interacting with Glitch.

### Running Modes

| Mode | When | How to run |
|------|------|------------|
| **Local dev** | UI development with hot reload | From repo root: Agent: `cd agent && PYTHONPATH=src python3 src/main.py`. UI: `cd ui && pnpm dev`. Open http://localhost:5173. |
| **Production** | Single process, built UI | From repo root: `cd ui && pnpm build` then `cd agent && PYTHONPATH=src python3 src/main.py`. Open http://localhost:8080/ui. |
| **Deployed** | Gateway Lambda | When deployed to AWS, the UI is served via a Lambda Function URL. See `infrastructure/lib/gateway-stack.ts`. |

### Environment (UI)

- `GLITCH_UI_MODE`: `local` (default) or `dev` (skip static UI mount for Vite dev server).
- `VITE_API_BASE_URL`: API base URL for production builds (Lambda Function URL).

### Features

| Tab | Description |
|-----|-------------|
| Chat | Real-time conversation with Glitch orchestrator |
| Telegram | Bot configuration and status |
| Ollama | Local model health and available models |
| Memory | Structured memory viewer |
| MCP | Model Context Protocol server status |
| Skills | Enable/disable agent skills |
| Unifi | Network monitoring (Coming Soon) |
| Pi-hole | DNS record management via agent tools (e.g. update glitch.awoo.agency after redeploy); stats tab (Coming Soon) |
| Settings | Agent configuration |

### API Endpoints

The UI uses REST endpoints at `/api`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Agent status and info |
| `/api/telegram/config` | GET/POST | Telegram configuration |
| `/api/ollama/health` | GET | Ollama hosts health |
| `/api/memory/summary` | GET | Memory state |
| `/api/mcp/servers` | GET | MCP server status |
| `/api/skills` | GET | List all skills |
| `/api/skills/{id}/toggle` | POST | Enable/disable skill |
| `/api/streaming-info` | GET | Streaming capabilities info |
| `/invocations` | POST | Send message to Glitch |

## Testing & Deployment Automation

### Overview

The project uses a three-phase deployment model with SSM Parameter Store for cross-stack communication, eliminating manual configuration and circular dependencies.

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Automated Deployment Workflow                   │
└─────────────────────────────────────────────────────────────┘

Phase 1: Foundation                Phase 2: Agent
         │                                   │
         ▼                                   ▼
┌──────────────────┐              ┌─────────────────────┐
│ CDK Deploy       │              │ pre-deploy-configure│
│ Foundation Stack │              │ (reads SSM params)  │
│                  │              └──────────┬──────────┘
│ • VPC + Subnets  │                         │
│ • VPC Endpoints  │                         ▼
│ • Security Groups│              ┌─────────────────────┐
│ • IAM Roles      │              │ make deploy         │
│ • SSM Parameters │              │ (pre-config + deploy│
└────────┬─────────┘              └──────────┬──────────┘
         │                                   │
         │    ┌──────────────────────────────┘
         │    │
         ▼    ▼
┌──────────────────────────────────────────────────────────────┐
│                    Phase 3: Application                       │
│  CDK Deploy (reads runtime ARN from yaml)                     │
│  • SecretsStack, StorageStack, GatewayStack                   │
│  • TelegramWebhookStack, TailscaleStack, UiHostingStack       │
└──────────────────────────────────────────────────────────────┘
```

### Unit Tests (Infrastructure)

**Location:** `infrastructure/test/`

Tests covering CDK infrastructure:

```typescript
// vpc-stack.test.ts → foundation-stack.test.ts
- VPC configuration (CIDR, DNS)
- Subnet creation (2 AZs)
- VPC endpoints (8 endpoints)
- Security group creation
- IAM role creation (no hardcoded names)
- SSM parameter creation

// agentcore-stack.test.ts
- Policy attachments
- No duplicate resource creation
```

**Run tests:**
```bash
cd infrastructure
pnpm test
```

### Auto-Configuration System

**Location:** `agent/scripts/`

#### Pre-Deploy Configuration (`pre-deploy-configure.py`)

Automatically fetches VPC configuration from SSM Parameter Store and updates `.bedrock_agentcore.yaml`:

**What it does:**
1. Reads SSM parameters created by `GlitchFoundationStack`
2. Updates `network_mode_config` with subnet IDs and security group IDs
3. Updates `execution_role` with the runtime role ARN
4. Skips if already configured

**SSM Parameters read:**
```python
SSM_VPC_ID = '/glitch/vpc/id'
SSM_PRIVATE_SUBNET_IDS = '/glitch/vpc/private-subnet-ids'
SSM_AGENTCORE_SG_ID = '/glitch/security-groups/agentcore'
SSM_RUNTIME_ROLE_ARN = '/glitch/iam/runtime-role-arn'
SSM_CODEBUILD_ROLE_ARN = '/glitch/iam/codebuild-role-arn'
```

**Configuration updated:**
```yaml
agents:
  Glitch:
    aws:
      execution_role: arn:aws:iam::...:role/GlitchFoundation...  # From SSM
      network_configuration:
        network_mode: VPC
        network_mode_config:
          subnet_ids:
            - subnet-xxx  # From SSM
            - subnet-yyy
          security_group_ids:
            - sg-zzz      # From SSM
```

### Deployment Workflows

#### Option 1: Full Deployment (New Account)

```bash
# Phase 1: Foundation
cd infrastructure
pnpm install && pnpm build
pnpm cdk deploy GlitchFoundationStack --require-approval never

# Phase 2: Agent
cd ../agent
make deploy  # Runs pre-deploy-configure.py + agentcore deploy

# Phase 3: Application
cd ../infrastructure
pnpm cdk deploy --all --require-approval never
```

#### Option 2: Update Existing Deployment

```bash
cd infrastructure
pnpm build
pnpm cdk deploy --all --require-approval never
```

### Benefits

✅ **No Manual Configuration** - VPC settings fetched from SSM automatically  
✅ **No Circular Dependencies** - SSM parameters decouple stacks  
✅ **No Hardcoded Role Names** - CloudFormation generates unique names  
✅ **Recoverable** - Foundation stack can be deleted and recreated cleanly  
✅ **Repeatable Process** - Same commands every time  
✅ **Clear Errors** - Meaningful error messages with solutions

### Troubleshooting

#### "SSM parameter not found"

Deploy foundation stack first:
```bash
cd infrastructure
pnpm cdk deploy GlitchFoundationStack
```

#### "Stack in ROLLBACK_COMPLETE state"

Delete the failed stack and redeploy:
```bash
aws cloudformation delete-stack --stack-name GlitchFoundationStack
# Wait for deletion to complete
pnpm cdk deploy GlitchFoundationStack
```

#### "Role already exists"

This shouldn't happen with the new architecture (no hardcoded role names). If it does, the old role may need manual deletion:
```bash
aws iam delete-role --role-name <old-role-name>
```

### Documentation

- **[infrastructure/docs/DEPLOYMENT.md](infrastructure/docs/DEPLOYMENT.md)** - Complete deployment guide
- **[agent/scripts/README.md](agent/scripts/README.md)** - Script usage

## License

MIT
