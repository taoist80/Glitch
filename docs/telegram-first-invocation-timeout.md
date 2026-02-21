# First invocation after idle times out – diagnosis

## Flow

1. **Telegram** → POST to **Lambda** (glitch-telegram-webhook) → Lambda calls **AgentCore data plane** (`InvokeAgentRuntime` via HTTP POST, `timeout=90` s).
2. **AgentCore** routes the request to a runtime **container**. If no container is warm (e.g. scaled down after idle), a **cold start** runs (new container start).
3. **Lambda** waits up to **90 s** for the HTTP response. If the runtime does not respond in time, `urllib.request.urlopen` raises and the user sees an error.

## Hypotheses (use CloudWatch to confirm)

| # | Hypothesis | What to check in CloudWatch |
|---|------------|-----------------------------|
| **H1** | **AgentCore idle timeout (15 min default)** – After ~15 min idle, the runtime session/container is terminated ([lifecycle docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-lifecycle-settings.html)). The next request triggers a **cold start**. | **Runtime logs** (`/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>/...` or similar): For a request that “timed out” from the user’s perspective, see if there is a **new** container start (e.g. “Starting HTTP server”, “Application startup complete”) with a timestamp **after** the Lambda “Invoking agent” log. If the first “Received invocation” appears **after** the Lambda has already timed out (~90 s later), H1 is supported. |
| **H2** | **Lambda HTTP timeout (90 s)** – Cold start (image pull + process init + Telegram + server) takes **longer than 90 s**, so Lambda’s `urlopen(req, timeout=90)` raises before the runtime responds. | **Lambda logs** (`/aws/lambda/glitch-telegram-webhook`): Search for **“Failed to invoke agent”** and in the same log line **“timed out”** or **“timeout”** (e.g. `URLError: <urlopen timed out>`). If you see that on the first request after idle and not on subsequent ones, H2 is supported. |
| **H3** | **504 from AgentCore** – The AgentCore data plane returns **504 Gateway Timeout** to Lambda before the runtime is ready (service-side timeout). | **Lambda logs**: Look for **“Failed to invoke agent”** with an HTTPError or response body indicating **504**. Distinguishes service timeout from Lambda client timeout. |
| **H4** | **Container startup slow** – Main process (Telegram channel init, DynamoDB, secrets, server, `set_agent`, API routes) is slow and adds to time-to-ready. | **Runtime logs**: Measure time from the **first** log line of a new container (e.g. “GLITCH AGENT STARTUP” or “Starting HTTP server”) to **“Received invocation”**. If that gap is large (e.g. 60+ s), H4 is supported. |

## CloudWatch checks (existing logs)

- **Lambda**
  - Log group: `/aws/lambda/glitch-telegram-webhook`
  - Filter: `"Invoking agent"` → get request ID / timestamp.
  - Filter: `"Failed to invoke agent"` → check exception message for `timed out`, `timeout`, `504`, `URLError`.
  - Filter: `"Invoke agent success"` → if this appears only on later requests (not the first after idle), the first request is failing in Lambda or upstream.

- **Runtime**
  - Log group: as in your AgentCore runtime (e.g. `/aws/bedrock-agentcore/...` or per [troubleshooting](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-troubleshooting.html)).
  - Filter: `"Received invocation"` → when does the first one appear after a long idle?
  - Filter: `"Starting HTTP server"` or `"Application startup complete"` → when does the container become ready? Compare with Lambda “Invoking agent” time; if >90 s later, cold start exceeds Lambda timeout.

## Mitigations (after you confirm with logs)

1. **Increase Lambda→runtime timeout** in the webhook Lambda (e.g. from 90 s to 120–180 s) so one slow cold start can complete. Lambda function timeout is already 120 s; consider raising it if you increase the HTTP timeout.
2. **Increase AgentCore idle timeout** – Increase `idleRuntimeSessionTimeout` (e.g. to 1800–3600 s) so containers stay warm longer and cold starts are rarer.
3. **Retry on timeout/504** – In the Lambda, if the invoke call fails with timeout or 504, retry once or twice with backoff so the first request after idle can succeed on retry after the container is ready.

## Optional: extra CloudWatch logging in Lambda

To make timeouts easy to filter, the Lambda can log explicitly when the failure is a timeout (see code change below). Then in CloudWatch filter for e.g. `"Invoke agent failed"` and `timeout=True`.
