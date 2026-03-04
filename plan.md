# AgentCore-Glitch: Integration & Implementation Plan

Generated: 2026-03-03
Purpose: Document all system integrations, connected processes, gaps, dead code, and the implementation roadmap for the Protect surveillance feature and UI.

---

## 1. System Architecture Map

```
                      ┌─────────────────────────────────────────────────────┐
                      │                     AWS (us-west-2)                  │
                      │                                                       │
  USER ───────────────┤                                                       │
  (browser/Telegram)  │  CloudFront (WAF + ACM from us-east-1 GlitchEdgeStack)
                      │       ↓                                               │
                      │  Lambda: glitch-gateway (gateway/index.py)           │
                      │       ├─ /api/protect/*  → Lambda: glitch-protect-query ─→ Postgres (on-prem)
                      │       ├─ /api/*          → AgentCore: Glitch (port 8080)   │
                      │       └─ /invocations    → AgentCore: Glitch (port 8080)   │
                      │                                                       │
                      │  AgentCore: Glitch                                    │
                      │       ├─ skill injection (TaskPlanner → SkillSelector)│
                      │       ├─ tools: ollama, memory, telemetry, soul,      │
                      │       │         ssh, sentinel, secrets, deploy        │
                      │       └─ invoke_sentinel() → AgentCore: Sentinel ─────┤
                      │                                                       │
                      │  AgentCore: Sentinel (port 9000, A2A)                 │
                      │       ├─ tools: protect (48), pihole, unifi, dns,     │
                      │       │         cloudwatch, github, telegram,         │
                      │       │         infra_ops, compound                   │
                      │       ├─ WebSocket poller → UniFi Protect NVR ────────┤
                      │       └─ invoke_glitch_agent() → Glitch               │
                      │                                                       │
                      │  Lambda: sentinel-protect-eval (scheduled 15min)      │
                      │       └─ invokes Sentinel for periodic analysis        │
                      │                                                       │
                      │  Lambda: glitch-telegram-webhook                       │
                      │  Lambda: glitch-telegram-keepalive (10min EventBridge) │
                      │  S3 + CloudFront: UI static assets (React/Vite)        │
                      │  DynamoDB: glitch-telegram-config (sessions, skills)   │
                      │  SSM: /glitch/sentinel/runtime-arn (cached 5min)       │
                      │  Secrets Manager: glitch/protect-db (Postgres creds)   │
                      │                                                         │
                      └─────────────────────────────────────────────────────────┘
                                              │  Site-to-Site VPN (UDM-Pro)
                      ┌─────────────────────────────────────────────────────────┐
                      │               On-Premises Network                        │
                      │                                                           │
                      │  UniFi Protect NVR                                        │
                      │       ├─ REST API: http://<host>/proxy/protect/           │
                      │       └─ WebSocket: wss://<host>/proxy/protect/ws/updates │
                      │                                                           │
                      │  Postgres (on-prem, port 5432)                            │
                      │       └─ glitch_protect DB (schema: entities, events,     │
                      │          alerts, cameras, patterns, entity_appearances,   │
                      │          entity_baselines, hostile_list)                  │
                      │                                                           │
                      │  Ollama (10.10.110.x, port 11434)                         │
                      │       └─ accessed via GLITCH_OLLAMA_PROXY_HOST (PUBLIC mode)│
                      └─────────────────────────────────────────────────────────────┘
```

---

## 2. Connected Processes & Data Flows

### 2a. Protect Data Flow (Surveillance)

```
UniFi Protect NVR
    │
    ├─ WebSocket (real-time): wss://<host>/proxy/protect/ws/updates
    │       └─ Sentinel ProtectEventPoller (monitoring-agent/src/sentinel/protect/poller.py)
    │               └─ EventProcessor → Postgres: INSERT events, UPDATE entities
    │
    └─ REST API: http://<host>/proxy/protect/
            └─ Sentinel protect_tools.py (48 tools) — on-demand queries

Postgres (on-prem, glitch_protect DB)
    │
    ├─ Read path (fast, <500ms):
    │       CloudFront → Gateway Lambda
    │               └─ /api/protect/* → protect-query Lambda (pg8000 direct)
    │                       └─ Postgres: SELECT entities, events, alerts, patterns
    │                               └─ UI ProtectTab.tsx
    │
    └─ Read path (AI/NL, slow, 5-10s):
            Glitch (invoke_sentinel) → Sentinel protect_tools.py
                    └─ Postgres queries + NVR REST API
```

### 2b. Chat Flow

```
Telegram / Web UI
    └─ Gateway Lambda → AgentCore Glitch
            ├─ TaskPlanner → SkillSelector (inject up to 3 skill prompts)
            ├─ Strands SDK → Claude claude-sonnet-4-6
            └─ Tools:
                    ├─ invoke_sentinel() → Sentinel (protect, network, pihole, DNS, infra)
                    ├─ ssh_execute() → on-prem hosts via SSH
                    ├─ vision_agent() / local_chat() → Ollama (via proxy)
                    ├─ memory tools → AgentCore memory API
                    ├─ telemetry tools → CloudWatch /glitch/telemetry
                    ├─ deploy tools → CDK deploy, agentcore deploy
                    └─ secrets tools → Secrets Manager
```

### 2c. Sentinel Protect Scheduled Evaluation

```
EventBridge (15-min schedule)
    └─ Lambda: sentinel-protect-eval/index.py
            └─ InvokeAgentRuntime (A2A) → Sentinel
                    └─ "Run scheduled Protect evaluation: check cameras, analyze anomalies..."
                            └─ Sentinel protect_tools → NVR + Postgres → Telegram alerts
```

### 2d. UI API Flow

```
React UI (CloudFront S3)
    │
    ├─ Chat: POST /invocations → Gateway Lambda → Glitch
    │
    ├─ Protect: GET /api/protect/* → Gateway Lambda → protect-query Lambda → Postgres
    │
    └─ Other API: GET/POST /api/* → Gateway Lambda → Glitch _handle_ui_api_request()
            Routes:
            ├─ /api/status
            ├─ /api/telegram/config
            ├─ /api/ollama/health
            ├─ /api/memory/summary
            ├─ /api/telemetry
            ├─ /api/mcp/servers
            ├─ /api/skills[/:id/toggle]
            ├─ /api/agents
            ├─ /api/modes
            ├─ /api/sessions/:id/agent
            └─ /api/sessions/:id/mode
```

---

## 3. Current State: What's Working

| Component | File | Status |
|-----------|------|--------|
| Gateway Lambda routing `/api/protect/*` → protect-query | `infrastructure/lambda/gateway/index.py:295` | ✅ Working |
| protect-query Lambda (direct Postgres reader) | `infrastructure/lambda/protect-query/index.py` | ✅ Deployed |
| Sentinel WebSocket poller (real-time event ingestion) | `monitoring-agent/src/sentinel/protect/poller.py` | ✅ Working |
| Sentinel protect tools (48 tools) | `monitoring-agent/src/sentinel/tools/protect_tools.py` | ✅ Working |
| Sentinel protect module (client, db, entity intel, etc.) | `monitoring-agent/src/sentinel/protect/` | ✅ Working |
| sentinel-protect-eval scheduled Lambda | `infrastructure/lambda/sentinel-protect-eval/index.py` | ✅ Deployed |
| UI ProtectTab component | `ui/src/tabs/ProtectTab.tsx` | ✅ Implemented |
| UI Protect types | `ui/src/types/index.ts` | ✅ Defined |
| UI API client protect methods | `ui/src/api/client.ts` | ✅ Defined |
| Glitch protect skill (delegation to Sentinel) | `agent/skills/glitch-protect-surveillance/` | ✅ Working |
| A2A Glitch → Sentinel via invoke_sentinel | `agent/src/glitch/tools/sentinel_tools.py` | ✅ Working |
| All other UI tabs (Chat, Telegram, Ollama, Memory, etc.) | `ui/src/tabs/` | ✅ Working |

---

## 4. Bugs & Missing Pieces (Must Fix)

### 4a. CRITICAL: protect functions imported but not defined in router.py

**File**: [agent/src/glitch/server.py:92-96](agent/src/glitch/server.py#L92)

```python
# These are imported but DO NOT EXIST in agent/src/glitch/api/router.py:
from glitch.api.router import (
    get_protect_summary,    # ❌ not defined
    get_protect_entities,   # ❌ not defined
    get_protect_events,     # ❌ not defined
    get_protect_alerts,     # ❌ not defined
    get_protect_patterns,   # ❌ not defined
)
```

**Impact**: `ImportError` at runtime when any protect API endpoint is called in local dev mode or via direct AgentCore access (not through the Gateway Lambda path). In production the Gateway Lambda bypasses this path for `/api/protect/*`, so it silently fails only in dev.

**Fix options**:
- **Option A (recommended)**: Add the 5 functions to `router.py` that call the protect-query Lambda directly (same approach as the Gateway Lambda, using boto3 Lambda invoke).
- **Option B**: Remove the imports + the protect routing block from `server.py` entirely (safe in production, but breaks local dev).

### 4b. BUG: SQL INTERVAL parameterization in protect-query Lambda

**File**: [infrastructure/lambda/protect-query/index.py:152-176](infrastructure/lambda/protect-query/index.py#L152)

```python
# BROKEN: ':hours' is inside a string literal — pg8000 does not substitute inside literals
"WHERE timestamp > NOW() - INTERVAL ':hours hours'"
```

**Fix**:
```python
# CORRECT: multiply interval by a parameter
"WHERE timestamp > NOW() - (:hours * INTERVAL '1 hour')"
```
Same bug exists in the count query on line 172-175.

### 4c. SSL config for on-prem Postgres

**File**: [infrastructure/lambda/protect-query/index.py:73](infrastructure/lambda/protect-query/index.py#L73)

```python
ssl_context=True,  # requires SSL on Postgres server
```

On-prem Postgres accessed via the VPN tunnel may not have TLS enabled. The connection is already encrypted at the VPN layer. Need to make SSL configurable via an env var or secret field.

**Fix**: Add `PROTECT_DB_SSL` env var (default `"false"` since VPN encrypts the tunnel); set `ssl_context=True` only when `PROTECT_DB_SSL=true`.

### 4d. Cameras table missing from Postgres schema

**File**: [infrastructure/lambda/protect-query/index.py:103-104](infrastructure/lambda/protect-query/index.py#L103)

```sql
(SELECT COUNT(*) FROM cameras) AS cameras_online
```

The `cameras` table is queried but may not be present in the schema or populated by the poller. The `schema.sql` in Sentinel defines the schema — verify `cameras` table exists and the poller writes to it.

**Fix**: Audit `monitoring-agent/src/sentinel/protect/schema.sql` and ensure the cameras table is created and populated. Fallback: change the query to `COUNT(*) FROM events WHERE timestamp > NOW() - INTERVAL '1 hour'` as a proxy for "active cameras".

### 4e. Postgres schema must be applied to on-prem server

Sentinel's `db.py` creates the schema on first `get_pool()` call. The protect-query Lambda assumes the schema exists but will fail on fresh Postgres with "table does not exist".

**Fix**: Sentinel must be running and have connected to Postgres at least once before protect-query Lambda is invoked. Document this dependency. Add a schema-check fallback in protect-query (return empty results with `schema_ready: false` instead of 503).

### 4f. Duplicate debug route registration

**File**: [agent/src/glitch/server.py:311,315](agent/src/glitch/server.py#L311)

```python
app.add_route("/debug/routes", debug_routes, methods=["GET"])  # line 311
# ... more code ...
app.add_route("/debug/routes", debug_routes, methods=["GET"])  # line 315 — DUPLICATE
```

**Fix**: Remove the duplicate `app.add_route` at line 315.

---

## 5. Dead Code to Remove

| File | Lines | Description | Action |
|------|-------|-------------|--------|
| [agent/src/glitch/server.py:92-96](agent/src/glitch/server.py#L92) | 92–96 | Import of 5 non-existent protect functions from router | Add the functions to router.py (fix 4a) OR remove imports + routing block |
| [agent/src/glitch/server.py:315](agent/src/glitch/server.py#L315) | 315 | Duplicate `app.add_route("/debug/routes", ...)` | Remove duplicate |
| `infrastructure/test/tailscale-stack.test.d.ts` | — | TypeScript declaration for deleted Tailscale test | Delete file |
| `infrastructure/test/tailscale-stack.test.js` | — | Compiled JS for deleted Tailscale test | Delete file |
| `infrastructure/test/tailscale-stack.test.ts` | — | Tailscale stack test (stack deleted) | Delete file |
| `infrastructure/1]` | — | Stray file (mistyped command artifact?) | Delete file |

**Already correctly deleted (no action needed):**
- `agent/src/glitch/protect/` — correctly delegated to Sentinel
- `agent/src/glitch/tools/protect_tools.py` — correctly delegated
- `agent/src/glitch/tools/pihole_tools.py` — correctly delegated to Sentinel
- `agent/src/glitch/tools/network_tools.py` — correctly delegated to Sentinel
- `agent/src/glitch/tools/tailscale_tools.py` — correctly removed
- `agent/skills/glitch-nginx-tailscale/` — correctly removed

---

## 6. Protect Functionality: On-Premises Postgres Setup

### 6a. Postgres configuration

Postgres runs on-prem, accessed via the Site-to-Site VPN. Steps to configure:

1. **Install Postgres** on the on-prem host (or use existing instance).
2. **Create database and user**:
   ```sql
   CREATE DATABASE glitch_protect;
   CREATE USER glitch_protect WITH PASSWORD '<password>';
   GRANT ALL PRIVILEGES ON DATABASE glitch_protect TO glitch_protect;
   ```
3. **Apply schema**: Run `monitoring-agent/src/sentinel/protect/schema.sql` against the database. Sentinel auto-creates it on first startup too.
4. **Configure pg_hba.conf**: Allow connections from the VPN CIDR range:
   ```
   host  glitch_protect  glitch_protect  <vpc-cidr>/16  md5
   ```
5. **Network**: Postgres must be reachable from AWS via the VPN. The UDM-Pro port-forward rule must forward port 5432 to the Postgres host. Alternatively, bind Postgres to the VPN interface IP directly.
6. **SSL**: Since the VPN encrypts traffic, SSL at the Postgres level is optional. Set `PROTECT_DB_SSL=false` in the Lambda env var (see fix 4c).

### 6b. Secrets Manager entry

Store credentials as secret `glitch/protect-db` (JSON):
```json
{
  "host": "<ddns-hostname-or-vpn-ip>",
  "port": 5432,
  "dbname": "glitch_protect",
  "username": "glitch_protect",
  "password": "<password>"
}
```

### 6c. Sentinel configuration

Sentinel reads Protect credentials from env vars → SSM → Secrets Manager:
- `PROTECT_HOST` — UniFi Protect NVR host (for WebSocket poller and REST API)
- `PROTECT_PORT` — typically 443
- `PROTECT_USERNAME` — UniFi local admin username
- `PROTECT_PASSWORD` — UniFi local admin password
- `PROTECT_DB_HOST`, `PROTECT_DB_PORT`, `PROTECT_DB_NAME`, `PROTECT_DB_USER`, `PROTECT_DB_PASSWORD` — Postgres credentials (or use the same Secrets Manager secret)

### 6d. DDNS for on-prem host

The Porkbun DDNS script (`infrastructure/scripts/porkbun-ddns-update.sh`) keeps a DNS record pointing to the on-prem public IP. Use this hostname in `PROTECT_HOST` and `PROTECT_DB_HOST` to survive IP changes.

---

## 7. Implementation Checklist

### Phase 1: Fix blocking bugs (protect UI broken in dev)

- [ ] **Fix 4a**: Add 5 protect handler functions to `agent/src/glitch/api/router.py`
  - Each function should invoke the protect-query Lambda via boto3 (same as gateway does)
  - Fallback: call `invoke_sentinel()` with a structured query prompt if Lambda fails
  - Response types: return `ProtectSummaryResponse`, `ProtectEntitiesResponse`, etc. (Pydantic models)

- [ ] **Fix 4b**: Fix SQL INTERVAL parameterization in protect-query Lambda
  - Change `INTERVAL ':hours hours'` → `(:hours * INTERVAL '1 hour')` in both queries

- [ ] **Fix 4c**: Make SSL configurable in protect-query Lambda
  - Add `PROTECT_DB_SSL` env var; read in `_get_connection()`
  - Deploy new Lambda env var via CDK stack

- [ ] **Fix 4f**: Remove duplicate `app.add_route` in `server.py` line 315

### Phase 2: On-prem Postgres setup

- [ ] Set up Postgres on-prem (install + create DB + user)
- [ ] Apply `monitoring-agent/src/sentinel/protect/schema.sql`
- [ ] Add `glitch/protect-db` secret to Secrets Manager
- [ ] Verify VPN route allows Lambda → on-prem:5432
- [ ] Test protect-query Lambda connectivity: `aws lambda invoke --function-name glitch-protect-query ...`

### Phase 3: Sentinel configuration

- [ ] Set Sentinel env vars for UniFi Protect NVR (`PROTECT_HOST`, `PROTECT_USERNAME`, `PROTECT_PASSWORD`)
- [ ] Set Sentinel env vars for Postgres (or use Secrets Manager reference)
- [ ] Deploy Sentinel: `cd monitoring-agent && agentcore deploy`
- [ ] Verify poller starts: check Sentinel CloudWatch logs for "Protect poller started"
- [ ] Verify schema auto-created: check Postgres for tables

### Phase 4: Infrastructure CDK updates

- [ ] Add `PROTECT_DB_SSL` env var to `glitch-protect-query` Lambda in `infrastructure/lib/stack.ts`
- [ ] Verify `PROTECT_QUERY_FUNCTION_NAME` env var is set on gateway Lambda (check stack.ts)
- [ ] Verify `sentinel-protect-eval` Lambda is scheduled and has Sentinel ARN in SSM
- [ ] Run CDK diff and deploy: `pnpm cdk diff && pnpm cdk deploy --all`

### Phase 5: UI enhancements (optional)

- [ ] Add alert acknowledgment UI: `POST /api/protect/alerts/:id/ack` → invoke_sentinel to update DB
- [ ] Add entity labeling UI: allow naming/tagging entities from the Protect tab
- [ ] Add camera live view: embed RTSP/snapshot URLs from NVR in ProtectTab
- [ ] Add real-time updates: WebSocket or polling interval for ProtectTab (currently manual refresh only)
- [ ] Add Protect tab to Sidebar as a top-level nav item (verify it's already in Sidebar.tsx)

### Phase 6: Dead code cleanup

- [ ] Delete `infrastructure/test/tailscale-stack.test.{ts,js,d.ts}`
- [ ] Delete `infrastructure/1]` (stray file)
- [ ] Remove duplicate `app.add_route` at server.py:315 (part of fix 4f)

---

## 8. File-to-Function Reference

### Protect data path (production)

```
UI ProtectTab.tsx
  → api.getProtect*()           ui/src/api/client.ts
  → GET /api/protect/*          CloudFront
  → Gateway Lambda              infrastructure/lambda/gateway/index.py:295
  → invoke_protect_query()      infrastructure/lambda/gateway/index.py:208
  → protect-query Lambda        infrastructure/lambda/protect-query/index.py
  → pg8000 connection           protect-query/index.py:48-74
  → Postgres on-prem            glitch_protect DB
```

### Protect data path (local dev / fallback, currently broken)

```
UI ProtectTab.tsx
  → api.getProtect*()           ui/src/api/client.ts
  → GET /api/protect/*          direct to Glitch container
  → FastAPI router              agent/src/glitch/api/router.py  ← MISSING HANDLERS
  → get_protect_summary() etc.  ← NEED TO ADD
  → boto3 lambda.invoke()       ← protect-query Lambda
  → Postgres on-prem
```

### Protect ingestion path (Sentinel)

```
UniFi NVR WebSocket
  → ProtectEventPoller          monitoring-agent/src/sentinel/protect/poller.py
  → _handle_message()           poller.py
  → EventProcessor.process()    monitoring-agent/src/sentinel/protect/event_processor.py
  → db.insert_event()           monitoring-agent/src/sentinel/protect/db.py
  → Postgres on-prem
```

### Protect AI analysis path (Sentinel tools)

```
User chat / scheduled eval
  → Glitch invoke_sentinel()    agent/src/glitch/tools/sentinel_tools.py
  → A2A → Sentinel              monitoring-agent/src/sentinel/agent.py
  → protect_tools.py (48 tools) monitoring-agent/src/sentinel/tools/protect_tools.py
  → protect/client.py           monitoring-agent/src/sentinel/protect/client.py
  → UniFi NVR REST API
  AND/OR
  → protect/db.py               monitoring-agent/src/sentinel/protect/db.py
  → Postgres on-prem
```

---

## 9. CDK Stack Dependencies

```
GlitchFoundationStack (VPC, VGW, VPN)
    ↓
GlitchSecretsStack (Secrets Manager: protect-db, telegram, etc.)
GlitchStorageStack (S3, DynamoDB: glitch-telegram-config)
    ↓
GlitchGatewayStack (gateway Lambda, protect-query Lambda, Function URLs)
GlitchTelegramWebhookStack (telegram-webhook Lambda, telegram-keepalive Lambda)
    ↓
GlitchAgentCoreStack (Glitch container, AgentCore Runtime)
GlitchSentinelStack (Sentinel container, AgentCore Runtime, SSM ARN)
    ↓
GlitchUiHostingStack (CloudFront + S3 for UI)

GlitchEdgeStack ← MUST DEPLOY TO us-east-1 (WAF + ACM)
```

---

## 10. Environment Variables Reference

### protect-query Lambda

| Variable | Required | Description |
|----------|----------|-------------|
| `PROTECT_DB_SECRET_NAME` | No (default: `glitch/protect-db`) | Secrets Manager secret name |
| `PROTECT_DB_SSL` | No (default: `false`) | Enable TLS to Postgres |

### Sentinel (AgentCore container)

| Variable | Required | Description |
|----------|----------|-------------|
| `PROTECT_HOST` | Yes | UniFi Protect NVR hostname |
| `PROTECT_PORT` | No (default: 443) | NVR port |
| `PROTECT_USERNAME` | Yes | NVR local admin username |
| `PROTECT_PASSWORD` | Yes | NVR local admin password |
| `PROTECT_DB_HOST` | Yes | Postgres hostname (DDNS or VPN IP) |
| `PROTECT_DB_PORT` | No (default: 5432) | Postgres port |
| `PROTECT_DB_NAME` | No (default: `glitch_protect`) | Postgres database name |
| `PROTECT_DB_USER` | Yes | Postgres username |
| `PROTECT_DB_PASSWORD` | Yes | Postgres password |

### Glitch (AgentCore container)

| Variable | Required | Description |
|----------|----------|-------------|
| `GLITCH_OLLAMA_PROXY_HOST` | Yes (PUBLIC mode) | Proxy for on-prem Ollama access |
| `GLITCH_CONFIG_TABLE` | Yes | DynamoDB table name |
| `GLITCH_TELEGRAM_WEBHOOK_URL` | Yes | Telegram webhook URL |
| `AWS_REGION` | Auto-set | Used for DynamoDB, SSM, STS |

---

## 11. Summary: Priority Order

1. **Fix protect-query SQL bug** (4b) — data will be wrong/empty with current INTERVAL parameterization
2. **Fix SSL config** (4c) — Lambda will fail to connect if on-prem Postgres has no TLS
3. **Set up on-prem Postgres** (Phase 2) — prerequisite for everything
4. **Configure Sentinel with NVR + Postgres creds** (Phase 3) — starts the data ingestion pipeline
5. **Add router.py protect handlers** (4a) — fixes local dev and provides a fallback path
6. **CDK deploy** (Phase 4) — pushes SSL env var and verifies Lambda wiring
7. **Clean up dead code** (Phase 6) — polish after functionality is verified
8. **UI enhancements** (Phase 5) — optional but improves usability
