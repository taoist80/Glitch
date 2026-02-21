# Cleaner UI Architecture: AgentCore-First, No EC2 Proxy

This doc proposes a simpler way to deliver the Glitch UI while using AgentCore and AWS built-in capabilities instead of routing everything through the EC2 instance.

## Current Problem

- **EC2 is the central point**: The Tailscale EC2 instance runs a full Glitch server in **proxy mode** (`GLITCH_UI_MODE=proxy`). It serves the static UI, and every `/api/*` and `/invocations` request is proxied from the browser → EC2 → AgentCore Runtime (via `InvokeAgentRuntime`).
- **Workaround-heavy**: EC2 runs Python, builds the UI, maintains session state in memory, and acts as a BFF. Only Tailscale and (optionally) `/ollama/health` need to be on that box; the rest is duplicating what Lambda already does for Telegram.

## AgentCore and AWS Capabilities (from docs)

- **Runtime is the single agent**: The Bedrock AgentCore Runtime runs your agent (Strands + tools). It is invoked only via the **Bedrock AgentCore Data Plane API** (`InvokeAgentRuntime`). There is no “built-in” public URL for browsers; something with IAM must call that API.
- **Telegram already uses the right pattern**: The Telegram webhook **Lambda** calls `InvokeAgentRuntime` with the user message and session ID. No EC2 involved. Same pattern can serve the web UI.
- **Gateway**: AgentCore Gateway is for **MCP tools** (exposing APIs/Lambda as tools to agents). It does **not** expose the runtime’s invocations to a browser. So Gateway does not replace the need for a BFF for the UI.
- **Presigned WebSocket**: The Runtime SDK supports presigned WebSocket URLs for browser clients. That could be used later for streaming chat; for a first step, HTTP invocations via a Lambda BFF are sufficient and match the Telegram pattern.

## Recommended: Lambda as UI Backend (AgentCore-First)

Use the **same invocation pattern as the Telegram webhook**: a **Lambda** with IAM permission to call `InvokeAgentRuntime`. The runtime already accepts:

- **Chat**: `{"prompt": "..."}` and returns `InvocationResponse`.
- **UI API**: `{"_ui_api_request": {"path": "/status", "method": "GET"}}` (and other `/api/*` routes) and returns the JSON the UI expects.

So the flow becomes:

1. **Static UI**  
   - Host the built React app in **S3** and serve it via **CloudFront** (or a single Lambda URL that serves static assets).  
   - No agent code or proxy on EC2 for the UI.

2. **UI API and invocations**  
   - **Lambda (Function URL or behind API Gateway)**:
     - `POST /invocations` → body as payload, optional `session_id`; Lambda calls `InvokeAgentRuntime`, returns response; store/return `session_id` (e.g. DynamoDB keyed by `x-client-id` or Cognito identity).
     - `GET/POST /api/*` → build `_ui_api_request` payload, call `InvokeAgentRuntime`, return JSON.  
   - Session state: store `session_id` per client in **DynamoDB** (same table or a dedicated one) so it survives cold starts and scales.

3. **EC2 = Tailscale only**  
   - EC2 runs **only** Tailscale (and optional CloudWatch agent).  
   - **Remove** the Glitch UI server (`glitch-ui.service`), Python, and UI build from EC2.  
   - **Ollama health** (`/api/ollama/health`): only reachable from on-prem (Tailscale). Options:  
     - Omit from the “cloud” UI, or show “N/A when not on Tailscale”.  
     - Or keep a **small** HTTP service on EC2 that only serves `/ollama/health` to Tailscale clients and have the cloud UI call it only when the user is on Tailscale (e.g. same origin as EC2).  
   - No need for EC2 to have `InvokeAgentRuntime` or to run the full Glitch server.

4. **AgentCore remains the single runtime**  
   - Telegram: Lambda → `InvokeAgentRuntime`.  
   - Web UI: Lambda → `InvokeAgentRuntime`.  
   - One runtime, one agent; no proxy process in the middle except the minimal Lambda BFF.

## What Changes in Code / Infra

| Area | Current | Cleaner |
|------|--------|--------|
| UI hosting | EC2 serves `/ui` and proxy routes | S3 + CloudFront (or Lambda static) |
| `/api/*` and `/invocations` | EC2 proxy (server.py + ui_proxy_routes) | New Lambda: same logic as Telegram invoke, plus session in DynamoDB |
| EC2 | Tailscale + full Glitch server (proxy mode) | Tailscale only (optional tiny Ollama-health endpoint) |
| Session | In-memory on EC2 (`_proxy_sessions`) | DynamoDB (e.g. `client_id` → `session_id`) |

## Implementation Outline

1. **New CDK stack (or extend TelegramWebhookStack)**  
   - Lambda with:
     - Handler that routes `POST /invocations` and `GET/POST /api/*` to `InvokeAgentRuntime` (reuse payload shapes from `ui_proxy.py` / `ui_proxy_routes.py`).
     - IAM: `bedrock-agentcore:InvokeAgentRuntime` on the runtime ARN; `bedrock-agentcore-control:ListAgentRuntimes` if you resolve ARN by name.
     - Function URL (or API Gateway) for the UI origin.
   - DynamoDB table or attributes for UI session: key `client_id` (from header or Cognito), value `session_id`; TTL optional.

2. **UI build and deploy**  
   - Build: `pnpm build` in `ui/`; upload `ui/dist/*` to S3.  
   - CloudFront: origin S3 (and optionally the Lambda URL for `/api` and `/invocations` if you want a single domain), or separate origins (e.g. `api.example.com` → Lambda).

3. **Frontend config**  
   - Point `API_BASE` (or env) to the Lambda Function URL or API Gateway URL when in “cloud” mode. No more EC2 URL for API.

4. **Tailscale stack**  
   - Set `enableUiServer: false` (or equivalent) so EC2 user data no longer installs Python, Glitch, or the UI server.  
   - Keep Tailscale and, if desired, a minimal endpoint for Ollama health on Tailscale only.

## References

- **AgentCore Runtime**: [Runtime Overview](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/overview.html) – `/invocations`, session, auth; browser can use presigned WebSocket for streaming.  
- **AgentCore Gateway**: [Gateway Quickstart](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/gateway/quickstart.md) – MCP tools for agents, not for exposing runtime invocations to the UI.  
- **Invoke pattern**: Same as in `infrastructure/lib/telegram-webhook-stack.ts` (Lambda calling `InvokeAgentRuntime`) and `agent/src/glitch/ui_proxy.py` (building payload and calling runtime).  
- **Strands**: Agent remains Strands + `BedrockAgentCoreApp`; no change to agent code for this architecture.

## Summary

- **Deliver the UI** via S3 + CloudFront (or Lambda static).  
- **Keep capabilities** by using AgentCore’s only entrypoint, `InvokeAgentRuntime`, from a **Lambda UI backend** (same pattern as Telegram).  
- **Stop using EC2 as the router**: EC2 = Tailscale (and optional Ollama health); no proxy mode, no Glitch server on EC2.  
- **Result**: AgentCore and Lambda do the work; EC2 is no longer the central point for communications and routing.
