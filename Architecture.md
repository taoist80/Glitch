# Glitch + Sentinel Architecture

A hybrid AI agent system built on AWS AgentCore Runtime. Glitch is the user-facing conversational agent; Sentinel is the autonomous operations brain. They communicate bidirectionally via A2A (Agent-to-Agent) protocol over `InvokeAgentRuntime`.

---

## System Overview

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud (us-west-2)                              │
│                                                                                 │
│  ┌─────────────────────────────────────────────────────────────────────────┐   │
│  │                       VPC (10.0.0.0/16)                                 │   │
│  │  Public Subnets + Private Subnets (no NAT Gateway)                      │   │
│  │  Site-to-Site VPN Gateway (VGW) ↔ UDM-Pro Customer Gateway              │   │
│  └─────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  ┌──────────────────────────────┐   ┌──────────────────────────────────────┐   │
│  │  Glitch Agent (PUBLIC mode)  │   │  Sentinel Agent (PUBLIC mode)        │   │
│  │  AgentCore Runtime           │◄──►  AgentCore Runtime                   │   │
│  │  HTTP protocol, port 8080    │   │  A2A protocol, port 9000             │   │
│  │                              │   │                                      │   │
│  │  Tools:                      │   │  Tools:                              │   │
│  │  • SSH (remote hosts)        │   │  • CloudWatch log scanning           │   │
│  │  • Ollama (on-prem LLMs)     │   │  • UniFi Protect (cameras, alerts)   │   │
│  │  • Memory / Soul             │   │  • UniFi Network (clients, APs)      │   │
│  │  • Code Interpreter          │   │  • Pi-hole / DNS Intelligence        │   │
│  │  • Secrets Manager           │   │  • Infrastructure Ops (CDK/CFN)      │   │
│  │  • Deploy management         │   │  • GitHub (branches, PRs)            │   │
│  │  • invoke_sentinel →         │   │  • Telegram alerting                 │   │
│  └──────────────────────────────┘   │  • invoke_glitch_agent →             │   │
│                                     │  • security_correlation_scan         │   │
│                                     │  • analyze_and_alert                 │   │
│                                     └──────────────────────────────────────┘   │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────────┐  │
│  │  CloudFront (glitch.awoo.agency)                                         │  │
│  │  WAF WebACL (IP allowlist: home IP only)                                 │  │
│  │  ├── Origin 1: S3 bucket (OAC) → static UI assets                       │  │
│  │  └── Origin 2: Gateway Lambda (Lambda OAC + SigV4) → /api/*, /invocations│  │
│  └──────────────────────────────────────────────────────────────────────────┘  │
│                                                                                 │
│  Lambda: glitch-gateway (AWS_IAM auth)  Lambda: glitch-telegram-webhook        │
│  Lambda: glitch-agentcore-keepalive     Lambda: glitch-ui-backend              │
│  DynamoDB: glitch-telegram-config       S3: glitch-agent-state-{acct}-{region} │
│  Secrets Manager: glitch/*              SSM: /glitch/*                         │
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
│  │ llama3.2     │  │ LLaVA        │  │  10.10.100.70│  │  cameras     │       │
│  │ 10.10.110.202│  │ 10.10.110.137│  │  10.10.100.71│  │  UDM-Pro NVR │       │
│  └──────────────┘  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                                                 │
│  ┌──────────────────────────────────────────────────────────────────────┐      │
│  │ nginx TCP stream proxy — 10.10.100.230                               │      │
│  │  :443  → 192.168.1.1:443  (Protect API + WS, WAN:13443 port fwd)   │      │
│  │  :7443 → 192.168.1.1:443  (legacy cookie auth, local only)         │      │
│  │  :80   → HTTP proxy for Glitch UI (S3) and Lambda gateway           │      │
│  └──────────────────────────────────────────────────────────────────────┘      │
│                                                                                 │
│  UDM-Pro (192.168.1.1) — router, VPN endpoint, UniFi OS console               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## Agent Responsibility Split

### Glitch (user-facing, HTTP protocol)
- **Keeps:** SSH tools, Ollama tools, Memory tools, Telemetry tools, Soul tools, Code Interpreter, MCP servers, Secrets Manager write
- **Delegates to Sentinel:** All operational queries via `invoke_sentinel`
- **Entry points:** Telegram (via webhook Lambda), Web UI (via CloudFront → Gateway Lambda)

### Sentinel (operations brain, A2A protocol)
- **Owns:** CloudWatch log scanning, UniFi Protect, UniFi Network, Pi-hole DNS, DNS Intelligence, Infrastructure Ops (CDK/CFN), GitHub, Telegram alerting
- **Compound tools:** `security_correlation_scan` (protect + network + DNS in one call), `analyze_and_alert` (full surveillance pipeline)
- **Invokes Glitch:** For SSH/SSM remediation tasks via `invoke_glitch_agent`

---

## Network Architecture

### PUBLIC AgentCore Mode
Both agents run in `PUBLIC` network mode — no VPC ENIs, no VPC endpoints required. Agents reach AWS services directly over the internet.

**What this eliminates:**
- 14 VPC interface endpoints (Secrets Manager, ECR, CloudWatch Logs, Bedrock, STS, SSM, X-Ray, etc.)
- `AgentCoreSG` security group
- Private-isolated subnet dependency
- All the "missing endpoint" silent failures

### VPC (retained for on-prem connectivity)
The VPC exists solely to host the Site-to-Site VPN. It has:
- Public subnets (for VPN Gateway attachment)
- Private subnets for VPN route propagation only (no NAT Gateway, no internet egress)
- **No VPC endpoints** — agents use PUBLIC mode

### Site-to-Site VPN (replaces Tailscale EC2)
- **VPN Gateway (VGW)** attached to VPC
- **Customer Gateway (CGW)** pointing to UDM-Pro WAN IP
- **Dual IPsec tunnels** for HA (AWS provides two endpoints automatically)
- Routes `10.10.110.0/24` via VGW route propagation to private route tables
- Configured on UDM-Pro via: Network > VPN > Site-to-Site VPN

**What this eliminates:**
- Tailscale EC2 t4g.nano instance
- Nginx UI proxy + LLM proxy
- certbot / Porkbun DNS-01 / TLS cron
- `write-glitch-proxy-conf.sh`, `ensure-glitch-tls.sh`, `renew-glitch-tls.sh`
- Tailscale auth key secret
- Manual route table entries

### On-Premises nginx Reverse/TCP Proxy (10.10.100.230)

An nginx instance at `10.10.100.230` acts as the on-prem ingress point for `home.awoo.agency`:

- **Port 443 → `192.168.1.1:443`** (TCP stream passthrough): UniFi Protect integration API and WebSocket endpoints. Receives traffic from the UDM-Pro port forward (WAN `13443` → LAN `10.10.100.230:443`), enabling Sentinel containers in PUBLIC mode to reach Protect via the public internet at `home.awoo.agency:13443`.
- **Port 7443 → `192.168.1.1:443`** (TCP stream passthrough): Legacy path for cookie-based auth to the private Protect API (`/proxy/protect/api/...`). Kept as fallback; not used in API key mode.
- **Port 80**: HTTP reverse proxy for Glitch UI (S3 bucket) and Lambda gateway. Config in `infrastructure/scripts/glitch-proxy.conf`.

The TCP stream blocks live in `/etc/nginx/nginx.conf` (not in `conf.d/`). The HTTP server block lives in `/etc/nginx/conf.d/glitch-proxy.conf`.

### Ollama Access from PUBLIC Mode Agents
Agents in PUBLIC mode cannot directly reach `10.10.110.x` (private IPs). Access requires a proxy reachable from the public internet that routes to on-prem via VPN. Configure via `GLITCH_OLLAMA_PROXY_HOST` environment variable.

---

## UI and Access Control

### CloudFront + S3 + WAF
The web UI is served via CloudFront with defense-in-depth access control:

1. **WAF IP allowlist** — blocks all non-allowed IPs at the CloudFront edge (home IP only)
2. **S3 OAC** — S3 bucket is private; only CloudFront can read it
3. **Lambda IAM auth + OAC** — Gateway Lambda Function URL uses `AWS_IAM` auth; CloudFront signs every origin request with SigV4 via Lambda OAC
4. **No direct origin access** — S3 website hosting disabled; Lambda FURL requires SigV4

**Access:** Any device on the home network (or connected via Site-to-Site VPN) originates from the UDM-Pro WAN IP, which is in the WAF allowlist. Update the IP via `cdk deploy GlitchEdgeStack` if the home IP changes.

### Request Routing Chain

```
User (browser)
    │
    ▼
CloudFront (glitch.awoo.agency)
    │  WAF IP check (block non-allowed IPs)
    ├── Static assets → S3 (OAC)
    └── /api/*, /invocations → Gateway Lambda (SigV4 via Lambda OAC)
                                    │
                                    ▼
                              AgentCore Runtime (Glitch)
                                    │
                              process_message()
```

### Protect tab (Surveillance UI)
The Glitch UI includes a **Protect** tab (sidebar: “Protect”, Camera icon) that shows:
- **Entities** — registered people/vehicles, trust level, last seen, sightings
- **Events** — recent motion/person/vehicle events (e.g. last 24h)
- **Alerts** — with priority and user response status
- **Behaviours** — patterns/baselines (frequency, confidence)

The tab calls REST endpoints under `/api/protect/*` (summary, entities, events, alerts, patterns). **These endpoints are not yet implemented in the Gateway/Glitch stack.** To populate the tab with real data, a backend must:

1. Implement GET `/api/protect/summary`, `/api/protect/entities`, `/api/protect/events`, `/api/protect/alerts`, `/api/protect/patterns` (query params: `limit`, `hours`, `unack_only` as used by the UI client).
2. Read from the same Protect Postgres DB that Sentinel uses (schema in `monitoring-agent/src/sentinel/protect/schema.sql`), e.g. via a small Lambda or service with VPC/DB access, or by proxying through the Glitch agent’s `invoke_sentinel` and parsing structured responses.

Until that backend exists, the Protect tab still loads and shows an empty/error state with a short message that the Protect API must be connected.

---

## A2A Communication (Agent-to-Agent)

### Resilience Design
- **TTL-based ARN cache (5 min):** Both `sentinel_tools.py` and `glitch_invoke_tools.py` cache the peer ARN with a 5-minute TTL. Stale ARNs self-heal within minutes.
- **Cache-bust on `ResourceNotFoundException`:** If an invoke fails with a not-found error, the cache is cleared and SSM is re-queried before one retry.
- **Tag-based IAM policies:** Both agents use wildcard + tag conditions for `InvokeAgentRuntime` — no pinned ARNs in IAM policies.
- **ARN stability:** `agentcore deploy` uses `UpdateAgentRuntime` (not delete+recreate), so ARNs remain stable across redeploys.

### SSM Parameters for A2A
| Parameter | Value |
|-----------|-------|
| `/glitch/sentinel/runtime-arn` | Sentinel runtime ARN (read by Glitch) |
| `/glitch/sentinel/glitch-runtime-arn` | Glitch runtime ARN (read by Sentinel) |

### Enriched Return Values
- `invoke_sentinel` returns structured JSON: `{status, response, session_id, latency_ms}`
- `get_deployed_arns` compares SSM values against live `.bedrock_agentcore.yaml` ARNs and reports `stale: true/false`

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

GlitchGatewayStack (us-west-2)
├── Lambda: glitch-gateway (AWS_IAM auth, fromAsset)
└── EventBridge: 5-min keepalive rule

GlitchTelegramWebhookStack (us-west-2)
├── Lambda: glitch-telegram-webhook (NONE auth, fromAsset)
├── Lambda: glitch-agentcore-keepalive (10-min keepalive, fromAsset)
└── SSM: /glitch/telegram/webhook-url, /glitch/telegram/config-table

GlitchEdgeStack (us-east-1)  ← must deploy to us-east-1
├── WAF WebACL (CLOUDFRONT scope, IP allowlist)
└── ACM Certificate (glitch.awoo.agency)

GlitchUiHostingStack (us-west-2)
├── S3 bucket (private, OAC)
├── CloudFront distribution (WAF + ACM + S3 OAC + Lambda OAC)
└── S3 deployment (UI dist/)

GlitchAgentCoreStack (us-west-2)
└── Managed Policy on RuntimeRole (Bedrock, ECR, CW Logs, Secrets, DynamoDB, S3, SSM, CodeBuild, InvokeSentinelAgent)

GlitchSentinelStack (us-west-2)
├── Managed Policy on RuntimeRole (Bedrock, ECR, CW Logs read/write, CW Metrics, X-Ray, CFN, Secrets, DynamoDB, SSM, InvokeGlitchAgent)
└── SSM Parameters (/glitch/sentinel/*)

UiBackendStack (us-west-2)  [optional, separate UI backend]
└── Lambda: glitch-ui-backend (fromAsset)
```

### Key Design Principles
1. **PUBLIC AgentCore mode** — no VPC ENIs, no VPC endpoints, no security groups for agents
2. **No hardcoded IAM role names** — CloudFormation generates unique names
3. **SSM Parameters for cross-stack references** — no `Fn.importValue` circular deps
4. **Lambda code from asset** — all Lambda functions use `Code.fromAsset`, no inline code
5. **Least-privilege IAM** — `secretsmanager:ListSecrets` removed (unused), `bedrock-agentcore:*` narrowed to specific actions, namespace conditions on CloudWatch metrics

### SSM Parameters
| Parameter | Description |
|-----------|-------------|
| `/glitch/vpc/id` | VPC ID |
| `/glitch/vpc/private-subnet-ids` | Comma-separated private subnet IDs |
| `/glitch/vpc/public-subnet-ids` | Comma-separated public subnet IDs |
| `/glitch/iam/runtime-role-arn` | Runtime role ARN |
| `/glitch/iam/codebuild-role-arn` | CodeBuild role ARN |
| `/glitch/telegram/webhook-url` | Telegram webhook Lambda URL |
| `/glitch/telegram/config-table` | DynamoDB config table name |
| `/glitch/sentinel/runtime-arn` | Sentinel runtime ARN (for Glitch A2A) |
| `/glitch/sentinel/glitch-runtime-arn` | Glitch runtime ARN (for Sentinel A2A) |
| `/glitch/sentinel/monitored-log-groups` | JSON array of log groups for Sentinel |

---

## Sentinel Tools Reference

### CloudWatch Tools (5 tools)
| Tool | Purpose |
|------|---------|
| `scan_log_groups_for_errors` | Scan all monitored log groups for errors |
| `get_log_group_errors` | Deep-dive into a specific log group |
| `list_monitored_log_groups` | List configured groups with last-scan timestamps |
| `get_lambda_metrics` | Errors, Throttles, Duration P99 for a Lambda |
| `query_cloudwatch_insights` | Run arbitrary Insights query |

**Monitored log groups** (from SSM `/glitch/sentinel/monitored-log-groups`):
- `/aws/bedrock-agentcore/runtimes/*`
- `/aws/lambda/glitch-telegram-webhook`
- `/aws/lambda/glitch-gateway`
- `/aws/lambda/glitch-agentcore-keepalive`
- `/glitch/telemetry`

### UniFi Protect Tools (48 tools — 13 core + 35 extended)
Core tools always registered: `protect_get_cameras`, `protect_get_events`, `protect_get_snapshot`, `protect_db_store_observation`, `protect_db_get_baseline`, `protect_db_record_alert`, `protect_should_alert`, `protect_send_telegram_alert`, `protect_start_monitoring`, `protect_stop_monitoring`, `protect_get_monitoring_status`, `protect_register_entity`, `protect_search_entities`

Extended tools (35) available for deep investigations: entity management, analytics, heatmaps, reports, tuning.

### UniFi Network Tools (12 tools)
| Tool | Purpose |
|------|---------|
| `unifi_list_clients` | Connected clients with IPs, MACs, signal |
| `unifi_get_device_status` | AP/switch/gateway status |
| `unifi_get_ap_stats` | Access point performance |
| `unifi_get_switch_ports` | Switch port status, PoE |
| `unifi_get_firewall_rules` | Active firewall/traffic rules |
| `unifi_block_client` | Block a client MAC |
| `unifi_get_traffic_stats` | Aggregate traffic stats |
| `unifi_get_network_health` | Overall network health score |
| `unifi_get_vpn_status` | VPN connection status and throughput |
| `unifi_get_wifi_networks` | SSIDs, channels, client counts |
| `unifi_get_alerts_events` | Recent UniFi alerts |
| `unifi_get_network_topology` | Device interconnection map |

### DNS Intelligence Tools (7 tools)
| Tool | Purpose |
|------|---------|
| `dns_analyze_query_patterns` | Query volume by client/domain/time |
| `dns_detect_suspicious_domains` | Check against malicious domain lists |
| `dns_get_top_blocked` | Top blocked domains with counts |
| `dns_get_client_query_stats` | Per-client query stats |
| `dns_monitor_live_queries` | Tail live DNS queries in real-time |
| `dns_get_query_trends` | Historical trends over days/weeks |
| `dns_manage_blocklists` | Add/remove blocklists, whitelist domains |

### Pi-hole DNS Tools (4 tools)
| Tool | Purpose |
|------|---------|
| `pihole_list_dns_records` | List custom DNS records |
| `pihole_add_dns_record` | Add a custom DNS record |
| `pihole_delete_dns_record` | Delete a custom DNS record |
| `pihole_update_dns_record` | Update a record |

### Infrastructure Ops Tools (6 tools)
| Tool | Purpose |
|------|---------|
| `cdk_synth_and_validate` | Run cdk synth + cfn-lint (read-only) |
| `cdk_diff` | Preview changes for a stack |
| `cdk_deploy_stack` | Deploy a stack (requires Telegram confirmation) |
| `list_cfn_stacks_status` | List all CloudFormation stacks |
| `check_cfn_drift` | Detect configuration drift |
| `rollback_stack` | Cancel update or trigger rollback |

### GitHub Tools (4 tools)
| Tool | Purpose |
|------|---------|
| `github_get_file` | Read a file from the repo |
| `github_create_branch` | Create a fix branch from main |
| `github_commit_file` | Commit a file change to a branch |
| `github_create_pr` | Open a PR with title, body, labels |

### Compound Tools (2 tools — saves 2-3 LLM round-trips)
| Tool | Purpose |
|------|---------|
| `security_correlation_scan` | Protect events + network clients + DNS logs in one call |
| `analyze_and_alert` | Full pipeline: fetch events → analyze → decide → alert |

---

## Glitch Tools Reference

### Ollama Tools
| Tool | Host | Model | Purpose |
|------|------|-------|---------|
| `local_chat` | 10.10.110.202:11434 | mistral-nemo:12b | Lightweight chat tasks |
| `vision_agent` | 10.10.110.137:8080 | LLaVA | Image analysis |
| `check_ollama_health` | Both | N/A | Connectivity check |

### Deploy Management Tools
| Tool | Purpose |
|------|---------|
| `get_deployed_arns` | Read SSM ARNs + compare to live YAML (staleness diff) |
| `update_glitch_arn_in_ssm` | Update Glitch ARN in SSM after redeploy |
| `update_sentinel_arn_in_ssm` | Update Sentinel ARN in SSM after redeploy |
| `update_both_arns_in_ssm` | Update both ARNs at once |
| `check_codebuild_deploy_status` | Check CodeBuild project status |

### Secrets Management Tools
| Tool | Purpose |
|------|---------|
| `store_secret` | Create/update a `glitch/*` secret in Secrets Manager |
| `list_secrets` | List `glitch/*` secret names (never values) |

### A2A Tool
| Tool | Purpose |
|------|---------|
| `invoke_sentinel` | Send operational query to Sentinel; returns `{status, response, session_id, latency_ms}` |

---

## Communication Channels

### Telegram
- **Webhook Lambda** (`glitch-telegram-webhook`): Receives updates from Telegram, invokes AgentCore Runtime
- **Session IDs** padded to ≥33 chars (AgentCore requirement)
- **Config storage**: DynamoDB `glitch-telegram-config`
- **Access control**: Owner + allowlist; groups require @mention by default

### Web UI
- **CloudFront** → **Gateway Lambda** → **AgentCore Runtime**
- WAF IP allowlist blocks non-home IPs before content is served
- Lambda OAC signs all requests to Gateway with SigV4

### Telegram Flow
```
User → Telegram API → Lambda (glitch-telegram-webhook)
    → validate webhook secret
    → load config from DynamoDB
    → apply access rules (owner/allowlist)
    → InvokeAgentRuntime (Glitch)
    → send reply via Telegram Bot API
    → return 200 to Telegram
```

---

## Memory Architecture

```
Layer 1: Sliding Window (Strands SDK)
    Last 20 conversation turns, in-memory, session-scoped

Layer 2: AgentCore Memory (Persistent)
    Short-term: create_event() for recent events
    Long-term: retrieve() for semantic search
    Structured: session_goal, facts, constraints, decisions, open_questions
    Cross-session persistence, namespaced storage
```

---

## Observability

### Log Groups
| Log Group | Purpose | Writer |
|-----------|---------|--------|
| `/aws/bedrock-agentcore/runtimes/Glitch-*-DEFAULT` | Container stdout/OTEL | AgentCore platform |
| `/aws/bedrock-agentcore/runtimes/Sentinel-*-DEFAULT` | Sentinel container logs | AgentCore platform |
| `/aws/lambda/glitch-gateway` | Gateway Lambda logs | Lambda service |
| `/aws/lambda/glitch-telegram-webhook` | Telegram webhook logs | Lambda service |
| `/aws/lambda/glitch-agentcore-keepalive` | Keepalive Lambda logs | Lambda service |
| `/glitch/telemetry` | Invocation metrics | Agent code |

### CloudWatch Insights Quick Queries

**Find errors in last hour:**
```
fields @timestamp, @message
| filter @message like /ERROR/ or @message like /Exception/
| sort @timestamp desc
| limit 50
```

**Find chat invocations:**
```
fields @timestamp, @message
| filter @message like /GLITCH_INVOKE_ENTRY/
| sort @timestamp desc
| limit 100
```

**Measure invocation duration:**
```
fields @timestamp, @message
| filter @message like /Invocation completed successfully/
| parse @message /\((?<duration>[\d.]+)s\)/
| filter duration > 0.1
| sort @timestamp desc
```

---

## Secrets Reference

| Secret Name | Format | Used By |
|-------------|--------|---------|
| `glitch/telegram-bot-token` | Plain text | Glitch, Telegram webhook Lambda |
| `glitch/api-keys` | JSON | Glitch |
| `glitch/ssh-key` | PEM private key | Glitch SSH tools |
| `glitch/porkbun-api` | JSON: `{apikey, secretapikey}` — Porkbun API keys for DNS / DDNS | Porkbun DDNS script, cert/DNS automation |
| `glitch/pihole-api` | JSON: `{host, username, password}` | Sentinel Pi-hole tools |
| `glitch/github-token` | Plain text PAT (repo scope) | Sentinel GitHub tools |
| `glitch/unifi-controller` | JSON: `{host, username, password, site}` | Sentinel UniFi Network tools |

**Store credentials via Glitch (Telegram):**
```
"Store the UniFi controller credentials: host=10.10.100.1, user=admin, pass=..."
→ Glitch calls store_secret(name="glitch/unifi-controller", value={...})
```

---

## Deployment

### Prerequisites
- AWS CLI configured for the target account, region `us-west-2`
- Node.js 18+, pnpm, Python 3.10+
- Docker (for `agentcore deploy`)
- Telegram bot token (optional, from @BotFather)

### Full Deployment (New Account)

```bash
# Phase 1: Foundation
cd infrastructure
pnpm install && pnpm build
pnpm cdk deploy GlitchFoundationStack --require-approval never

# Phase 2: Deploy Glitch agent
cd ../agent
make deploy  # Runs pre-deploy-configure.py + agentcore deploy

# Phase 3: Deploy Sentinel agent
cd ../monitoring-agent
agentcore deploy

# Phase 4: Update cross-agent ARN SSM parameters
# (Glitch reads Sentinel ARN from SSM; Sentinel reads Glitch ARN from SSM)
# Ask Glitch via Telegram: "Update both ARNs in SSM"
# Or manually:
aws ssm put-parameter --name /glitch/sentinel/runtime-arn --value <sentinel-arn> --overwrite
aws ssm put-parameter --name /glitch/sentinel/glitch-runtime-arn --value <glitch-arn> --overwrite

# Phase 5: Deploy application stacks
cd ../infrastructure
pnpm cdk deploy --all --require-approval never

# Phase 6: Deploy Edge stack (us-east-1 — WAF + ACM)
pnpm cdk deploy GlitchEdgeStack --region us-east-1 --require-approval never
```

### Update Existing Deployment

```bash
# Update infrastructure
cd infrastructure && pnpm build && pnpm cdk deploy --all --require-approval never

# Update Glitch agent
cd agent && make deploy

# Update Sentinel agent
cd monitoring-agent && agentcore deploy
```

### ARN Management After Redeploy
ARNs are **stable across `agentcore deploy`** (uses `UpdateAgentRuntime`, not delete+recreate). SSM parameters only need updating if an agent is destroyed and recreated from scratch.

`get_deployed_arns` now reports a `stale` flag by comparing SSM values to live `.bedrock_agentcore.yaml` ARNs — no guesswork needed.

### Site-to-Site VPN Setup (one-time)
After deploying `GlitchFoundationStack` with `-c onPremPublicIp=<UDM-Pro WAN IP>`:
1. Download the VPN configuration from AWS Console (VPC > Site-to-Site VPN Connections)
2. Configure UDM-Pro: Network > VPN > Site-to-Site VPN
3. Use the pre-shared keys and tunnel IPs from the downloaded config

---

## Project Structure

```
AgentCore-Glitch/
├── infrastructure/              # CDK TypeScript
│   ├── bin/app.ts              # CDK app entry
│   ├── lib/
│   │   ├── stack.ts            # All stacks:
│   │   │                       #   GlitchFoundationStack (VPC, VPN, IAM, SSM)
│   │   │                       #   GlitchSecretsStack
│   │   │                       #   GlitchStorageStack (DynamoDB, S3, logs)
│   │   │                       #   GlitchGatewayStack (Lambda, AWS_IAM auth)
│   │   │                       #   GlitchTelegramWebhookStack
│   │   │                       #   GlitchEdgeStack (WAF + ACM, us-east-1)
│   │   │                       #   GlitchUiHostingStack (CloudFront + S3 OAC)
│   │   │                       #   GlitchAgentCoreStack (runtime IAM policies)
│   │   │                       #   GlitchSentinelStack (Sentinel IAM policies)
│   │   └── ui-backend-stack.ts # UiBackendStack (optional UI backend Lambda)
│   ├── lambda/                 # Lambda function code (fromAsset)
│   │   ├── gateway/index.py
│   │   ├── telegram-webhook/index.py
│   │   ├── telegram-keepalive/index.py
│   │   └── ui-backend/index.py
│   └── test/                   # Jest unit tests
├── agent/                       # Glitch — Python Strands agent
│   ├── src/
│   │   ├── main.py
│   │   └── glitch/
│   │       ├── agent.py        # GlitchAgent orchestrator
│   │       ├── aws_utils.py    # Shared REGION, CLIENT_CONFIG, get_client()
│   │       ├── server.py       # HTTP server
│   │       ├── telemetry.py    # OpenTelemetry + CloudWatch
│   │       ├── channels/       # Telegram, DynamoDB config
│   │       ├── memory/         # Sliding window memory
│   │       ├── skills/         # Skill loader, registry, selector
│   │       └── tools/
│   │           ├── registry.py
│   │           ├── ollama_tools.py
│   │           ├── ssh_tools.py
│   │           ├── soul_tools.py
│   │           ├── memory_tools.py
│   │           ├── telemetry_tools.py
│   │           ├── deploy_tools.py     # ARN management, CodeBuild status
│   │           ├── secrets_tools.py    # store_secret, list_secrets
│   │           ├── sentinel_tools.py   # invoke_sentinel (A2A)
│   │           └── code_interpreter_tools.py
│   ├── skills/
│   │   ├── glitch-protect-surveillance/ # Delegation stub → invoke_sentinel
│   │   ├── glitch-agent-deploy/
│   │   └── glitch-telemetry-maintainer/
│   ├── scripts/pre-deploy-configure.py
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── SOUL.md
│   └── .bedrock_agentcore.yaml
├── monitoring-agent/            # Sentinel — Python Strands agent
│   ├── src/
│   │   ├── main.py             # A2A server entry point
│   │   └── sentinel/
│   │       ├── agent.py        # SentinelAgent (all tool groups + skill loader)
│   │       ├── aws_utils.py    # Shared REGION, CLIENT_CONFIG, CLIENT_CONFIG_LONG, get_client()
│   │       ├── protect/        # UniFi Protect client, config, DB
│   │       └── tools/
│   │           ├── cloudwatch_tools.py
│   │           ├── protect_tools.py    # 48 tools (13 core + 35 extended)
│   │           ├── pihole_tools.py
│   │           ├── unifi_network_tools.py
│   │           ├── dns_intelligence_tools.py
│   │           ├── infra_ops_tools.py
│   │           ├── telegram_tools.py
│   │           ├── github_tools.py
│   │           ├── glitch_invoke_tools.py  # invoke_glitch_agent (A2A)
│   │           └── compound_tools.py       # security_correlation_scan, analyze_and_alert
│   ├── skills/
│   │   ├── log-monitoring/
│   │   ├── incident-response/
│   │   ├── unifi-operations/
│   │   └── infrastructure-ops/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── SOUL.md
│   └── .bedrock_agentcore.yaml
├── ui/                         # React + DaisyUI dashboard
│   └── src/
├── pnpm-workspace.yaml
└── Architecture.md             # This file
```

---

## Security Model

### Network Security
- AgentCore runtimes in PUBLIC mode — no VPC ENIs, no network attack surface
- CloudFront WAF IP allowlist — blocks all non-home IPs at the edge
- Lambda Function URL with `AWS_IAM` auth — only CloudFront (via OAC) can invoke
- S3 OAC — bucket is private; only CloudFront can read
- Site-to-Site VPN with IPsec — encrypted on-prem connectivity

### IAM Least Privilege
- AgentCore roles: scoped to specific actions and resource ARNs
- `secretsmanager:ListSecrets` removed (unused)
- `bedrock-agentcore:*` narrowed to specific actions per Lambda
- CloudWatch metrics scoped to known namespaces via conditions
- A2A invocation uses tag-based wildcard conditions (not pinned ARNs)

### Secrets Management
| Secret | Purpose |
|--------|---------|
| `glitch/telegram-bot-token` | Telegram bot token |
| `glitch/api-keys` | API credentials |
| `glitch/ssh-key` | SSH private key for remote hosts |
| `glitch/pihole-api` | Pi-hole admin credentials |
| `glitch/github-token` | GitHub PAT (repo scope) |
| `glitch/unifi-controller` | UniFi Network controller credentials |

---

## Cost Profile

| Component | Monthly Cost |
|-----------|-------------|
| AgentCore Runtime (Glitch + Sentinel) | Pay-per-invocation |
| CloudFront | ~$0 (free tier for low traffic) |
| NAT Gateway | $0 (removed) |
| Site-to-Site VPN | ~$36 (2 tunnels × $0.05/hr) |
| Lambda (Gateway + Webhook + Keepalive) | ~$0 (free tier) |
| DynamoDB | ~$0 (free tier) |
| S3 | ~$1 |
| WAF | ~$5/month (WebACL + 1 rule) |
| **Total** | **~$43/month** |

*NAT Gateway (~$32), Tailscale EC2 ($3.80), and 14 VPC endpoints (~$87) eliminated.*

---

## Troubleshooting

### Dashboard shows "disconnected" / 400 Bad Request
- Check that `AGENTCORE_RUNTIME_ARN` in the Gateway Lambda environment matches the current Glitch ARN
- Redeploy CDK: `pnpm cdk deploy GlitchGatewayStack`
- Verify the Glitch agent is running: `agentcore status`

### Telegram not responding
- Check Lambda logs: `aws logs tail /aws/lambda/glitch-telegram-webhook --since 1h`
- Verify webhook is registered: check DynamoDB `glitch-telegram-config` for `webhook_url`
- Check AgentCore runtime is healthy: `agentcore status`

### A2A invocation fails (Sentinel ↔ Glitch)
- `get_deployed_arns` will show if SSM params are stale
- If stale: `update_both_arns_in_ssm` (ask Glitch via Telegram)
- Check IAM: Sentinel role needs `bedrock-agentcore:InvokeAgentRuntime` on Glitch ARN

### No CloudWatch logs appearing
- Verify the runtime log group name matches the agent ID in `.bedrock_agentcore.yaml`
- Check IAM policy covers `/aws/bedrock-agentcore/*` (not `/aws/bedrock/agentcore/*`)
- Run `agentcore invoke '{"prompt":"test"}'` to verify container starts

### On-prem hosts unreachable
- Verify Site-to-Site VPN tunnels are UP in AWS Console (VPC > Site-to-Site VPN)
- Check UDM-Pro VPN status: Network > VPN > Site-to-Site VPN
- Confirm VPN route propagation is enabled on private route tables
- Note: PUBLIC mode agents cannot reach `10.10.110.x` directly — requires a proxy

### Gateway timeout on chat invocations
- Gateway Lambda timeout: 300s; `invoke_agent()` / `invoke_api()` urllib timeout: 280s (20s buffer)
- AgentCore keepalive Lambda runs every 10 min to keep containers warm
- Cold start: ~2s; total time dominated by LLM processing

## License

MIT
