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
- DM: `telegram:dm:{user_id}`
- Group: `telegram:group:{chat_id}`
- Forum Topic: `telegram:group:{chat_id}:topic:{thread_id}`

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

When the bot is deployed with the Telegram webhook stack, Telegram sends updates to an **AWS Lambda Function URL** (not to the agent runtime). The runtime never runs a local webhook server.

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
| `GLITCH_SOUL_S3_BUCKET` | No | (or SSM) | S3 bucket for SOUL.md and poet-soul.md; required for persisting `update_soul` and loading personality from S3 |
| `GLITCH_SOUL_S3_KEY` | No | `soul.md` | S3 object key for SOUL.md |
| `GLITCH_POET_SOUL_S3_KEY` | No | (SSM or `poet-soul.md`) | S3 object key for poet-soul.md (Poet sub-agent) |
| `AWS_REGION` | No | `us-west-2` | AWS region |

**SOUL and poet-soul S3 configuration**

When the CDK `TelegramWebhookStack` is deployed, it creates an S3 bucket for agent state and writes the bucket name (and default keys) to SSM Parameter Store. The runtime role is granted read/write access to that bucket and read access to these parameters. So **you do not need to set any env vars** for S3 if the stack is deployed and the agent runs with that role: the agent will read `/glitch/soul/s3-bucket` and `/glitch/soul/s3-key` (and `/glitch/soul/poet-soul-s3-key`) from SSM and use them automatically.

- **With CDK stack:** After deploying `GlitchTelegramWebhookStack`, the runtime discovers the bucket via SSM. Ensure the runtime uses the same execution role that the stack attached policies to (`defaultExecutionRoleArn` in the CDK app).
- **Without CDK / override:** Set `GLITCH_SOUL_S3_BUCKET` (and optionally `GLITCH_SOUL_S3_KEY`, `GLITCH_POET_SOUL_S3_KEY`) in the runtime environment. The bucket must allow the runtime role `s3:GetObject` and `s3:PutObject`.
- **Poet sub-agent:** Uses the same bucket as SOUL; key is `GLITCH_POET_SOUL_S3_KEY` or SSM `poet-soul-s3-key`, default `poet-soul.md`. If the object is missing in S3, Poet falls back to file paths (`agent/poet-soul.md`, `/app/poet-soul.md`, `~/poet-soul.md`).

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
│ Ollama Chat      │    │ Ollama Vision    │    │ Both endpoints   │
│ /api/generate    │    │ /api/generate    │    │ /api/tags        │
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

### CDK Stacks

| Stack | Purpose | Key Resources |
|-------|---------|---------------|
| `GlitchVpcStack` | Network foundation | VPC, Subnets, VPC Endpoints (S3, ECR, CloudWatch, Secrets Manager, Bedrock) |
| `GlitchSecretsStack` | Credential management | Secrets Manager secrets (Tailscale auth, API keys, Telegram token) |
| `GlitchTailscaleStack` | Hybrid connectivity | EC2 t4g.nano instance, Security Groups (no dedicated EBS—uses AMI root volume only) |
| `GlitchAgentCoreStack` | Agent runtime support | IAM roles, Security Groups |
| `GlitchStorageStack` | Persistent storage | DynamoDB config table, S3 soul bucket, SSM parameters, CloudWatch telemetry log group |
| `GlitchGatewayStack` | Gateway | Lambda Function URL (invocations, /api/*, keepalive) |

**Note:** The Tailscale EC2 instance uses only the minimal root volume from the AMI. No dedicated EBS volumes are provisioned.

### Potentially Unused Resources

Resources that may exist from earlier architectures or one-off setups and are not currently referenced by the CDK app:

- **Telegram webhook stack**: If a standalone `TelegramWebhookStack` (or similar) was previously deployed, it may still exist in the account. The current app uses `GlitchGatewayStack` for the UI; Telegram webhook could be consolidated into the gateway in a future change (see below).

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

| Tool | Host | Model | Purpose |
|------|------|-------|---------|
| `local_chat` | 10.10.110.202:11434 | llama3.2 | Lightweight chat tasks |
| `vision_agent` | 10.10.110.137:11434 | LLaVA | Image analysis |
| `check_ollama_health` | Both | N/A | Connectivity verification |

### Network Tools (Planned)

| Tool | Service | Status |
|------|---------|--------|
| `query_pihole_stats` | Pi-hole DNS | Not implemented |
| `check_unifi_network` | Unifi Controller | Not implemented |
| `query_protect_cameras` | Unifi Protect | Not implemented |

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
- All secrets in AWS Secrets Manager with rotation support

## Project Structure

```
AgentCore-Glitch/
├── infrastructure/              # CDK TypeScript
│   ├── bin/app.ts              # CDK app entry
│   ├── lib/
│   │   ├── vpc-stack.ts        # VPC, subnets, endpoints
│   │   ├── secrets-stack.ts    # Secrets Manager
│   │   ├── tailscale-stack.ts  # EC2 Tailscale connector (no dedicated EBS)
│   │   ├── agentcore-stack.ts  # IAM, security groups
│   │   ├── storage-stack.ts    # DynamoDB, S3, SSM, CloudWatch logs
│   │   └── gateway-stack.ts   # Gateway Lambda (invocations, /api/*, keepalive)
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
│   │           ├── soul_tools.py
│   │           ├── memory_tools.py
│   │           ├── telemetry_tools.py
│   │           └── code_interpreter_tools.py
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

### Quick Start

```bash
# 1. Deploy infrastructure
cd infrastructure
pnpm install && pnpm build
pnpm run cdk bootstrap aws://999776382415/us-west-2
pnpm run deploy

# 2. Create Telegram bot and store token in Secrets Manager
# - Message @BotFather on Telegram
# - Create new bot with /newbot
# - Store the bot token in Secrets Manager:
aws secretsmanager create-secret \
  --name glitch/telegram-bot-token \
  --secret-string "your-bot-token" \
  --region us-west-2

# 3. Deploy agent
cd ../agent
python -m venv venv && source venv/bin/activate
pip install bedrock-agentcore-starter-toolkit

agentcore launch

# 4. Claim Telegram bot
# - Check startup logs for pairing code
# - Send code to your bot on Telegram
# - Bot confirms ownership

# 5. Test
agentcore invoke '{"prompt": "Hello, Glitch!"}'

# Or test via Telegram
# - Send message to your bot
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
| Pi-hole | DNS filtering stats (Coming Soon) |
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

## License

MIT
