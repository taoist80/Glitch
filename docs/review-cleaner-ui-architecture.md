# Review: Cleaner UI Architecture (AgentCore-First)

Review of `docs/cleaner-ui-architecture-agentcore-first.md` with recommendations and analysis of Lambda vs CloudFront for static hosting.

**Sources:**
- [AgentCore Runtime API Reference](https://aws.github.io/bedrock-agentcore-starter-toolkit/api-reference/runtime.md)
- [AgentCore Session Management](https://aws.github.io/bedrock-agentcore-starter-toolkit/examples/session-management.md)
- [Lambda Provisioned Concurrency](https://docs.aws.amazon.com/lambda/latest/dg/provisioned-concurrency.html)
- [Lambda Function URL CORS](https://docs.aws.amazon.com/lambda/latest/api/API_Cors.html)

---

## Overall Opinion

**The plan is sound and well-aligned with AWS best practices.** It removes EC2 as the central router, reuses the proven Telegram Lambda pattern, and keeps AgentCore as the single runtime. The result is simpler, more scalable, and easier to maintain.

**Recommendation: Proceed with Lambda for both static UI and API/invocations.** This avoids CloudFront complexity and keeps everything in one stack.

---

## Summary of the Proposal

| Component | Current | Proposed |
|-----------|---------|----------|
| Static UI | EC2 serves `/ui` | S3 + CloudFront (or Lambda) |
| `/api/*` and `/invocations` | EC2 proxy (Python) | Lambda → `InvokeAgentRuntime` |
| Session state | In-memory on EC2 | DynamoDB |
| EC2 | Tailscale + full Glitch server | Tailscale only (optional Ollama health) |

---

## Lambda vs CloudFront for Static UI

You asked about using Lambda instead of CloudFront. Here's the comparison:

### Option A: S3 + CloudFront (doc's default)

**Pros:**
- CloudFront is optimized for static assets (caching, edge locations, low latency).
- S3 + CloudFront is the canonical AWS pattern for SPAs.
- Separates concerns: CloudFront for static, Lambda for API.

**Cons:**
- Two origins to configure (S3 for static, Lambda for API).
- CloudFront distribution adds complexity (behaviors, cache policies, OAC for S3).
- Longer deploy times (CloudFront propagation can take minutes).
- More moving parts to debug.

### Option B: Lambda serves everything (your preference)

**Pros:**
- **Single endpoint**: One Lambda Function URL serves both static assets and API routes. Simpler to reason about.
- **Faster iteration**: No CloudFront propagation; deploy Lambda and it's live.
- **Unified stack**: One CDK construct, one IAM role, one log group.
- **No S3 bucket for UI**: Assets can be bundled in the Lambda deployment package (up to 250 MB unzipped) or fetched from S3 at runtime.

**Cons / Drawbacks:**
1. **Cold starts for static assets**: Every request (including `index.html`, JS, CSS) goes through Lambda. Cold starts add 100–500 ms on first request after idle. Provisioned concurrency mitigates this but adds cost.
2. **No edge caching**: Lambda runs in one region; users far from `us-west-2` see higher latency for static assets. CloudFront caches at edge.
3. **Cost at scale**: Lambda charges per request and duration. For a low-traffic dashboard this is negligible; for high traffic, CloudFront + S3 is cheaper for static assets.
4. **Payload size**: Lambda response payload is limited to 6 MB (sync) or 20 MB (streaming). UI bundles are typically <1 MB, so this is fine.
5. **Routing logic**: Lambda must route `/`, `/ui/*`, `/api/*`, `/invocations` correctly. A small router (e.g. Python or Node) is needed.

**Verdict:** For a personal/team dashboard with low traffic, **Lambda-only is a good choice**. It's simpler, faster to deploy, and the drawbacks (cold starts, no edge cache) are acceptable for this use case.

---

## Recommendations

### 1. Use a single Lambda with Function URL

- **Handler routes:**
  - `GET /` and `GET /ui/*` → serve static assets (from bundled files or S3).
  - `POST /invocations` → build payload, call `InvokeAgentRuntime`, return response.
  - `GET|POST /api/*` → build `_ui_api_request`, call `InvokeAgentRuntime`, return JSON.
- **Session:** Store `client_id → session_id` in DynamoDB (same table as Telegram config or a new one).
- **CORS:** Allow the Function URL origin (or `*` if public).

### 2. Bundle static assets in Lambda or fetch from S3

**Option 2a: Bundle in Lambda**
- Include `ui/dist/*` in the Lambda deployment package.
- Serve files from disk (e.g. `/var/task/ui/dist/index.html`).
- Pros: No S3 bucket, single artifact.
- Cons: Larger deployment package; redeploy Lambda to update UI.

**Option 2b: Fetch from S3 at runtime**
- Upload `ui/dist/*` to an S3 bucket.
- Lambda reads from S3 and returns the file (with caching headers).
- Pros: UI updates don't require Lambda redeploy.
- Cons: Extra S3 bucket; slight latency for S3 fetch (mitigated by Lambda caching).

For simplicity, **Option 2a (bundle)** is fine for a dashboard that changes infrequently. If you want to update the UI without redeploying Lambda, use **Option 2b**.

### 3. Reuse Telegram Lambda patterns

The Telegram webhook Lambda already:
- Signs requests with SigV4.
- Calls `InvokeAgentRuntime`.
- Stores session state in DynamoDB.

Copy that logic into the UI Lambda. The only additions are:
- Static file serving (or S3 fetch).
- Routing for `/api/*` and `/invocations`.
- CORS headers.

### 4. CDK stack structure

Extend `TelegramWebhookStack` or create a new `UiBackendStack`:

```ts
// New Lambda for UI backend
const uiBackendFunction = new lambda.Function(this, 'UiBackendFunction', {
  functionName: 'glitch-ui-backend',
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: 'index.handler',
  code: lambda.Code.fromAsset('lambda/ui-backend'),  // or fromInline
  timeout: cdk.Duration.seconds(30),
  memorySize: 512,
  environment: {
    AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
    SESSION_TABLE_NAME: sessionTable.tableName,
  },
});

// IAM: InvokeAgentRuntime
uiBackendFunction.addToRolePolicy(
  new iam.PolicyStatement({
    actions: ['bedrock-agentcore:InvokeAgentRuntime'],
    resources: [agentCoreRuntimeArn, `${agentCoreRuntimeArn}/*`],
  })
);

// DynamoDB for session
sessionTable.grantReadWriteData(uiBackendFunction);

// Function URL (public)
const functionUrl = uiBackendFunction.addFunctionUrl({
  authType: lambda.FunctionUrlAuthType.NONE,
  cors: {
    allowedOrigins: ['*'],
    allowedMethods: [lambda.HttpMethod.GET, lambda.HttpMethod.POST, lambda.HttpMethod.OPTIONS],
    allowedHeaders: ['Content-Type', 'X-Client-Id'],
  },
});
```

### 5. EC2 changes

- Remove `glitch-ui.service` and Python from EC2 user data.
- Keep Tailscale and (optionally) a minimal HTTP server for `/ollama/health` (only reachable via Tailscale).
- Update `tailscale-stack.ts` to skip UI server setup.

### 6. Frontend config

- Set `VITE_API_BASE` (or similar) to the Lambda Function URL when building for production.
- In dev mode, keep Vite proxy to `localhost:8080` (or point to the Lambda URL).

---

## Drawbacks of Lambda (Summary)

| Drawback | Impact | Mitigation |
|----------|--------|------------|
| Cold starts | 100–500 ms on first request | Provisioned concurrency (adds cost) or accept the latency |
| No edge caching | Higher latency for users far from region | Acceptable for a personal/team dashboard |
| Cost at scale | Higher than S3 + CloudFront for static assets | Negligible for low traffic |
| Routing logic | Must implement in Lambda | Small router; reuse existing patterns |
| Payload size limit | 6 MB sync / 20 MB streaming | UI bundles are typically <1 MB |

For a low-traffic dashboard, these drawbacks are minor. If you later need global edge caching or high traffic, you can add CloudFront in front of the Lambda Function URL (CloudFront can use a Lambda Function URL as an origin).

---

## Final Recommendation

1. **Proceed with Lambda-only** for both static UI and API/invocations.
2. **Bundle UI assets in Lambda** (or use S3 if you want independent UI deploys).
3. **Reuse Telegram Lambda patterns** for `InvokeAgentRuntime` and DynamoDB session.
4. **Remove UI server from EC2**; keep Tailscale only.
5. **Optionally add CloudFront later** if you need edge caching or custom domain with ACM cert.

The plan is solid. Lambda-only is simpler and fits the use case well.

---

## AgentCore-Specific Considerations (from MCP docs)

### Session Management

AgentCore Runtime natively supports session IDs via the `X-Amzn-Bedrock-AgentCore-Runtime-Session-Id` header. The `RequestContext` object passed to your entrypoint includes `session_id`:

```python
@app.entrypoint
def chat_handler(payload, context: RequestContext):
    session_id = context.session_id or "default"
    # AgentCore manages session state internally
```

**Implication for Lambda BFF:** The Lambda should:
1. Accept a `client_id` from the browser (cookie or header).
2. Look up or create a `session_id` in DynamoDB for that `client_id`.
3. Pass the `session_id` to `InvokeAgentRuntime` via the header.

This matches the Telegram Lambda pattern where each Telegram user ID maps to a session.

### Presigned WebSocket URLs (Future Enhancement)

AgentCore provides `AgentCoreRuntimeClient.generate_presigned_url()` for browser-direct WebSocket connections:

```python
client = AgentCoreRuntimeClient('us-west-2')
presigned_url = client.generate_presigned_url(
    runtime_arn='arn:aws:bedrock-agentcore:us-west-2:123:runtime/my-runtime',
    session_id='user-session-123',
    expires=300  # max 300 seconds
)
# Browser connects directly to wss://... with SigV4 auth in query params
```

**Implication:** For streaming chat, the Lambda BFF could generate a presigned WebSocket URL and return it to the browser. The browser then connects directly to AgentCore for streaming, bypassing Lambda for the actual chat. This eliminates Lambda as a bottleneck for long-running streaming responses.

**Recommendation:** Start with HTTP invocations via Lambda (simpler). Add presigned WebSocket support later if streaming latency becomes an issue.

### InvokeAgentRuntime Contract

The AgentCore Runtime exposes:
- `POST /invocations` — main entrypoint, accepts JSON payload
- `GET /ping` — health check, returns `{"status": "Healthy"}` or `{"status": "HealthyBusy"}`
- `WebSocketRoute /ws` — for streaming (requires presigned URL or SigV4 headers)

Your Lambda BFF calls `InvokeAgentRuntime` (the AWS API), which internally routes to `/invocations` on the runtime. The payload shapes (`{"prompt": "..."}` and `{"_ui_api_request": {...}}`) are already defined in your agent code.

---

## Lambda Function URL CORS (from AWS docs)

Lambda Function URLs support built-in CORS configuration:

```ts
const functionUrl = uiBackendFunction.addFunctionUrl({
  authType: lambda.FunctionUrlAuthType.NONE,
  cors: {
    allowedOrigins: ['*'],  // or specific origins
    allowedMethods: [lambda.HttpMethod.GET, lambda.HttpMethod.POST, lambda.HttpMethod.OPTIONS],
    allowedHeaders: ['Content-Type', 'X-Client-Id'],
    allowCredentials: false,
    maxAge: cdk.Duration.hours(1),
  },
});
```

**Key points:**
- `allowedOrigins: ['*']` is fine for a public dashboard; restrict to specific origins if needed.
- `allowedHeaders` must include any custom headers your UI sends (e.g., `X-Client-Id`).
- Lambda handles preflight `OPTIONS` requests automatically when CORS is configured.

---

## Cold Start Mitigation (from AWS docs)

Per [Lambda Provisioned Concurrency](https://docs.aws.amazon.com/lambda/latest/dg/provisioned-concurrency.html):

> Lambda pre-initializes execution environments for functions using provisioned concurrency, reducing cold start latencies for interactive workloads.

**Options:**
1. **Accept cold starts:** For a personal dashboard, 100–500 ms on first request is acceptable.
2. **Provisioned concurrency:** Set 1–2 instances to eliminate cold starts. Cost: ~$0.015/hour per instance (varies by memory).
3. **SnapStart (Java only):** Not applicable for Python Lambda.
4. **Keepalive pings:** Schedule a CloudWatch Events rule to invoke the Lambda every 5–10 minutes (same pattern as your AgentCore keepalive Lambda).

**Recommendation:** Start without provisioned concurrency. Add it later if cold starts are noticeable.

---

## Revised Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              AWS Cloud (us-west-2)                          │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         Lambda UI Backend                            │   │
│  │  Function URL: https://xxx.lambda-url.us-west-2.on.aws              │   │
│  │                                                                      │   │
│  │  Routes:                                                             │   │
│  │    GET /           → serve index.html (bundled or from S3)          │   │
│  │    GET /assets/*   → serve static assets                            │   │
│  │    POST /invocations → InvokeAgentRuntime(prompt)                   │   │
│  │    GET|POST /api/* → InvokeAgentRuntime(_ui_api_request)            │   │
│  │                                                                      │   │
│  │  Session: DynamoDB (client_id → session_id)                         │   │
│  └──────────────────────────────┬──────────────────────────────────────┘   │
│                                 │                                           │
│                                 │ InvokeAgentRuntime                        │
│                                 ▼                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    AgentCore Runtime (Glitch Agent)                  │   │
│  │                                                                      │   │
│  │  POST /invocations → @app.entrypoint                                │   │
│  │  GET /ping         → health check                                   │   │
│  │  WS /ws            → streaming (future)                             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                    EC2 (Tailscale only)                              │   │
│  │                                                                      │   │
│  │  - Tailscale mesh VPN                                               │   │
│  │  - Optional: /ollama/health (Tailscale-only access)                 │   │
│  │  - NO Glitch server, NO UI proxy                                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Final Recommendation

1. **Proceed with Lambda-only** for both static UI and API/invocations.
2. **Bundle UI assets in Lambda** (or use S3 if you want independent UI deploys).
3. **Reuse Telegram Lambda patterns** for `InvokeAgentRuntime` and DynamoDB session.
4. **Remove UI server from EC2**; keep Tailscale only.
5. **Consider presigned WebSocket URLs** for streaming chat in a future iteration.
6. **Optionally add CloudFront later** if you need edge caching or custom domain with ACM cert.

The plan is solid. Lambda-only is simpler and fits the use case well.
