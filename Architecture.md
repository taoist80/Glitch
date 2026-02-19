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

## Agent Architecture

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
│                   Three-Layer Memory System                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Layer 1: Active Window (Strands SDK)                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Sliding window of last N conversation turns              │  │
│  │  • Default: 20 turns                                      │  │
│  │  • Managed by SlidingWindowConversationManager            │  │
│  │  • In-memory, session-scoped                              │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  Layer 2: Structured Memory (Local)                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  JSON state maintained across turns                       │  │
│  │  • session_goal: Current objective                        │  │
│  │  • facts: Accumulated knowledge                           │  │
│  │  • constraints: Rules to respect                          │  │
│  │  • decisions: Choices made with rationale                 │  │
│  │  • open_questions: Unresolved items                       │  │
│  │  • tool_results_summary: Tool execution history           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                              │                                  │
│                              ▼                                  │
│  Layer 3: AgentCore Memory (Persistent)                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  AWS AgentCore Memory API                                 │  │
│  │  • Short-term: Recent events via create_event()           │  │
│  │  • Long-term: Semantic search via retrieve()              │  │
│  │  • Cross-session persistence                              │  │
│  │  • Namespaced storage (/user/facts/, /user/preferences/)  │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

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
│ BedrockAgentCoreApp │  Built-in /ping, /invocations, /ws handlers
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
├── RouterConfig
│   ├── confidence_threshold: float
│   ├── context_threshold_pct: float
│   ├── max_escalations_per_turn: int
│   └── max_escalations_per_session: int
└── MemoryConfig
    ├── session_id: str
    ├── memory_id: str
    ├── region: str
    ├── window_size: int
    ├── compression_threshold_pct: float
    └── actor_id: str

API Types (TypedDict)
├── InvocationRequest
│   ├── prompt: str (required)
│   ├── session_id: Optional[str]
│   └── context: Optional[Dict]
├── InvocationResponse
│   ├── message: str
│   ├── session_id: str
│   ├── memory_id: str
│   ├── metrics: InvocationMetrics
│   └── error: Optional[str]
├── InvocationMetrics
│   ├── duration_seconds: float
│   ├── token_usage: TokenUsage
│   ├── cycle_count: int
│   ├── latency_ms: int
│   ├── stop_reason: str
│   └── tool_usage: Dict[str, ToolUsageStats]
├── TokenUsage
│   ├── input_tokens: int
│   ├── output_tokens: int
│   ├── total_tokens: int
│   ├── cache_read_tokens: int
│   └── cache_write_tokens: int
└── ToolUsageStats
    ├── call_count: int
    ├── success_count: int
    ├── error_count: int
    └── total_time: float

Enums
├── EventType: USER_MESSAGE, AGENT_RESPONSE, TOOL_CALL, TOOL_RESULT, SYSTEM
├── MetricType: COUNTER, GAUGE, HISTOGRAM
├── CognitiveTier: LOCAL, TIER_1, TIER_2, TIER_3
└── IntegrationStatus: NOT_IMPLEMENTED, CONFIGURED, CONNECTED, ERROR
```

## Infrastructure Components

### CDK Stacks

| Stack | Purpose | Key Resources |
|-------|---------|---------------|
| `GlitchVpcStack` | Network foundation | VPC, Subnets, VPC Endpoints |
| `GlitchSecretsStack` | Credential management | Secrets Manager secrets |
| `GlitchTailscaleStack` | Hybrid connectivity | EC2 instance, Security Groups |
| `GlitchAgentCoreStack` | Agent runtime | IAM roles, Security Groups |

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
- All secrets in AWS Secrets Manager with rotation support

## Project Structure

```
AgentCore-Glitch/
├── infrastructure/              # CDK TypeScript
│   ├── bin/app.ts              # CDK app entry
│   ├── lib/
│   │   ├── vpc-stack.ts        # VPC, subnets, endpoints
│   │   ├── secrets-stack.ts    # Secrets Manager
│   │   ├── tailscale-stack.ts  # EC2 Tailscale connector
│   │   └── agentcore-stack.ts  # IAM, security groups
│   └── package.json
├── agent/                       # Python Strands agent
│   ├── src/
│   │   ├── main.py             # Entry point
│   │   └── glitch/
│   │       ├── __init__.py     # Package exports
│   │       ├── types.py        # Type definitions
│   │       ├── agent.py        # GlitchAgent orchestrator
│   │       ├── server.py       # HTTP server
│   │       ├── telemetry.py    # OpenTelemetry setup
│   │       ├── memory/
│   │       │   └── sliding_window.py
│   │       ├── routing/
│   │       │   └── model_router.py
│   │       └── tools/
│   │           ├── ollama_tools.py
│   │           └── network_tools.py
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── SOUL.md                 # Agent personality
│   └── .bedrock_agentcore.yaml # Toolkit config
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

### Quick Start

```bash
# 1. Deploy infrastructure
cd infrastructure
pnpm install && pnpm build
pnpm run cdk bootstrap aws://999776382415/us-west-2
pnpm run deploy

# 2. Deploy agent
cd ../agent
python -m venv venv && source venv/bin/activate
pip install bedrock-agentcore-starter-toolkit
agentcore launch

# 3. Test
agentcore invoke '{"prompt": "Hello, Glitch!"}'
```

### Verify Deployment

```bash
# Check agent status
agentcore status

# View logs
aws logs tail /aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT --follow

# Test Tailscale connectivity (from EC2)
aws ssm start-session --target <instance-id>
tailscale status
curl http://10.10.110.202:11434/api/tags
```

## License

MIT
