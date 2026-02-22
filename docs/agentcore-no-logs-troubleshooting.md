# AgentCore: No Logs Since [Time] — Troubleshooting

If you stop seeing "logging" in AgentCore (UI Telemetry tab, or CloudWatch) after a certain time (e.g. 11pm), use this checklist.

## Code change: 2/20 vs 2/21 (CloudWatch write path)

**Yesterday (2/20) ~7pm** logging worked because the code at that time (commit `af75e9b` and before) had:

- **`append_telemetry()`** writing every invocation to CloudWatch Logs via `_write_telemetry_to_cloudwatch()` (event_type `"invocation"`, stream `YYYY/MM/DD`).
- **`_ensure_log_group()`** and **`_ensure_log_stream()`** so `/glitch/telemetry` and the daily stream were created if missing.
- **`get_telemetry_history()`** could fall back to **`_read_telemetry_from_cloudwatch()`** when in-memory history was empty.

**Today (2/21)** after commit **`0bdbe75`** (Agent, UI, infra: session, tools, remove UI proxy…):

- The CloudWatch write was **removed from `append_telemetry()`**. It now only updates in-memory history and no longer calls `_write_telemetry_to_cloudwatch`.
- **`_read_telemetry_from_cloudwatch()`** and the CloudWatch fallback in **`get_telemetry_history()`** were removed.
- The **only** remaining write to `/glitch/telemetry` is **`log_invocation_metrics()` → `_put_invocation_metrics_to_cloudwatch()`** (event_type `"invocation_metrics"`, stream `invocations/YYYY-MM-DD`).
- Failures in **`_put_invocation_metrics_to_cloudwatch()`** were logged at **`logger.debug`**, so they did not show up in CloudWatch if the runtime only captures INFO and above.

So if the log group `/glitch/telemetry` did not exist (or the stream didn’t), PutLogEvents failed and the code only tried to create the **stream**, not the **group**. That could leave you with no visible errors and no new events in `/glitch/telemetry`.

**Fixes applied in code:**

- **Ensure log group exists:** `_put_invocation_metrics_to_cloudwatch()` now calls **`_ensure_log_group()`** on `ResourceNotFoundException` before creating the log stream, so the group is created if missing (runtime role has `logs:CreateLogGroup` for `/glitch/*`).
- **Surface failures:** CloudWatch write failures are now logged with **`logger.warning`** instead of `logger.debug`, so they appear in runtime/AgentCore logs when writes fail.

**OTEL / AgentCore Observability:**

- **`.bedrock_agentcore.yaml`** has **`observability: enabled: true`**. AgentCore Runtime then:
  - Captures **stdout/stderr** to `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>/...` (see [Observability Quickstart](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/observability/quickstart.md)).
  - Can send **OTEL traces** to Transaction Search (`/aws/spans/default`) when the agent uses `strands-agents[otel]` and the runtime config is set accordingly.
- **Application logs** (e.g. `logger.info("GLITCH_INVOKE_ENTRY" ...)`) only appear in CloudWatch if the runtime is actually capturing container stdout. If “no logs” means **no stdout at all**, the issue is runtime session / observability capture, not the agent’s direct CloudWatch write.
- **Telemetry tab** and **`query_cloudwatch_telemetry`** read from **`/glitch/telemetry`** and filter for **`event_type: "invocation_metrics"`** only. So the only code path that feeds the UI is **`log_invocation_metrics()` → `_put_invocation_metrics_to_cloudwatch()`**. Ensuring that path creates the log group and logs warnings on failure restores visibility when something goes wrong.

## Where "logging" comes from

| Source | What it is | When it appears |
|--------|------------|------------------|
| **UI Telemetry tab** | Fetches from `/glitch/telemetry` (CloudWatch Logs) or in-memory history | Only when the **agent processes a message** and completes (real user message or keepalive "ping") |
| **Runtime stdout/stderr** | AgentCore-managed log group (e.g. `/aws/bedrock/agentcore/...` or `/aws/bedrock-agentcore/...`) | Only while the **runtime container is running** and writing logs |
| **Lambda logs** | `/aws/lambda/glitch-telegram-webhook`, `/aws/lambda/glitch-agentcore-keepalive` | Every webhook request; every keepalive run (every 10 min) |

So "no logging since 11pm" usually means either **no new invocations** or **runtime no longer running**.

---

## I redeployed the agent but still don't see logs

Do these in order.

### 1. Confirm where to look (two places)

Logs can appear in **two different** CloudWatch locations:

| What you want | Where to look |
|---------------|----------------|
| **Application logs** (e.g. `GLITCH_AGENT_READY`, `GLITCH_INVOKE_ENTRY`, Python `logger` output) | **Runtime log group** – AgentCore writes container **stdout/stderr** here. In CloudWatch → **Log groups**, search for a name containing your **agent id** (e.g. `Glitch-78q5TgEa8M`) or prefix `/aws/bedrock` / `/aws/bedrock-agentcore`. Open the runtime log group and the latest **log stream** (one per container run). |
| **Telemetry events** (invocation metrics, UI Telemetry tab) | **`/glitch/telemetry`** – The agent writes these itself. In CloudWatch → **Log groups** → **`/glitch/telemetry`**. Streams are named **`invocations/YYYY-MM-DD`** (UTC). |

If you only checked one of these, check the other.

### 2. Trigger a new session and a startup heartbeat

After redeploying, the runtime container starts only when the first **invocation** happens (e.g. a Telegram message or the keepalive Lambda). Until then there is no container and no logs.

- **Send one message** to the bot (or wait for the next keepalive run).
- Then check:
  - **`/glitch/telemetry`** → open stream **`invocations/<today-UTC>`**. You should see at least one event with **`"event_type": "agent_startup"`** (written once when the agent process starts). If that event is there, the CloudWatch write path and IAM are working.
  - **Runtime log group** → latest log stream. Look for lines like `GLITCH AGENT STARTUP`, `Starting Glitch agent...`, or `Startup heartbeat written to /glitch/telemetry`.

### 3. Redeploy **infrastructure** (IAM) as well as the agent image

The runtime role must allow CloudWatch Logs. If you only rebuilt and pushed the **container image** but did not redeploy the **CDK stack** that defines the role, the role might be missing `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents` for `/glitch/*`.

- From the repo root: **`cd infrastructure && pnpm cdk deploy`** (or whatever stack defines `GlitchAgentCoreRuntimeRole`).
- Confirm the role has a policy with:
  - `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`
  - Resource: `arn:aws:logs:REGION:ACCOUNT:log-group:/glitch/*` (and optionally `.../log-group:/glitch/*:*`).

### 4. Check for warnings in the runtime log stream

If the agent starts but CloudWatch writes fail, the code now logs **warnings** (e.g. `Failed to write telemetry to CloudWatch`, `Startup heartbeat failed`). So:

- Open the **runtime** log group and the **latest** log stream (container stdout).
- Search for **"warning"** or **"Failed"** or **"heartbeat"**. If you see `Startup heartbeat failed` or `Failed to create log group`, fix IAM or the log group name and redeploy.

### 5. Region and account

Ensure you are looking in the **same region and account** as the runtime. Your `.bedrock_agentcore.yaml` has **region: us-west-2** and **account: 999776382415**. In the CloudWatch console, confirm the region (e.g. us-west-2) and that `/glitch/telemetry` and the runtime log group are in that account.

### 6. `aws logs tail` shows nothing

Runtime log streams are named **`YYYY/MM/DD/[runtime-logs]<UUID>`** (UTC date). If you tail with a specific prefix and get no output:

1. **Use today’s date in UTC** for the prefix. Example (from repo root):
   ```bash
   # UTC date for the prefix (e.g. 2026/02/22 if it’s already Feb 22 UTC)
   aws logs tail /aws/bedrock-agentcore/runtimes/Glitch-78q5TgEa8M-DEFAULT \
     --log-stream-name-prefix "$(date -u +%Y/%m/%d)/[runtime-logs]" --since 1h
   ```
2. **If still empty**, there may be no new runtime session. List streams and check the latest “Last event time”:
   ```bash
   aws logs describe-log-streams \
     --log-group-name /aws/bedrock-agentcore/runtimes/Glitch-78q5TgEa8M-DEFAULT \
     --order-by LastEventTime --descending --limit 5
   ```
   If the top stream’s `lastEventTimestamp` is from yesterday (or older), no container has written logs since then. Trigger an invocation (send a message or run keepalive), then tail again.
3. **Tail without a prefix** to see any recent activity in the log group:
   ```bash
   aws logs tail /aws/bedrock-agentcore/runtimes/Glitch-78q5TgEa8M-DEFAULT --since 24h
   ```

---

## 1. Check keepalive Lambda (most common cause)

The keepalive runs every **10 minutes** and invokes the runtime with `prompt: "ping"` so the session does not hit **idleRuntimeSessionTimeout** (~15 min). If keepalive fails, the session tears down and you get no runtime (and no telemetry) until the next successful invoke.

**In AWS Console:**

1. **CloudWatch → Log groups** → `/aws/lambda/glitch-agentcore-keepalive`
2. Open the **latest log stream** and look for:
   - **"Keepalive invoke failed: ..."** → Invoke is failing (timeout, 4xx, network, wrong ARN).
   - No recent streams at all → EventBridge rule might be disabled or Lambda not triggered.

**Fixes:**

- Confirm **AGENTCORE_RUNTIME_ARN** is set for the keepalive Lambda (same as webhook Lambda).
- If the runtime was recreated, update the ARN in CDK/config and redeploy so both Lambdas use the new ARN.
- Check **EventBridge (CloudWatch Events)** rule that targets the keepalive Lambda (schedule ~every 10 min).

---

## 2. Confirm there is traffic

- **Telemetry tab** only shows entries when the agent **completes** an invocation (user message or keepalive "ping"). If no one sent Telegram messages and keepalive is failing, there will be no new rows.
- In **CloudWatch → Log groups** → `/aws/lambda/glitch-telegram-webhook`: check whether any **Invoke agent** log lines appear after 11pm. If there are none, no user traffic reached the agent.

---

## 3. Runtime session and log groups

- If the runtime session was torn down (idle timeout, crash), the **AgentCore runtime** container stops. Then:
  - No new logs under the **Bedrock AgentCore** log group (e.g. `/aws/bedrock/agentcore/...`).
  - No new entries in **/glitch/telemetry** (those are written by the agent process on each completed invocation).
- The next successful invoke (user or keepalive) will **cold-start** a new session; after that you should see logs again.

---

## 4. Telemetry log group and stream

- **Log group:** `/glitch/telemetry` (or value of **GLITCH_TELEMETRY_LOG_GROUP** in the runtime).
- **Streams:** One per day in UTC: `YYYY/MM/DD`. If you’re in another timezone, "11pm my time" might be the next UTC day — check the stream for that UTC date.
- In **CloudWatch → Log groups** → `/glitch/telemetry`: open the stream for the date you care about and see if the last event is before 11pm (in the timestamp in the event).

---

## 5. Quick verification

1. **Send a Telegram message** to the bot. Then:
   - Check **Telemetry tab** (refresh) for a new entry.
   - Check **/glitch/telemetry** in CloudWatch for a new log event.
2. If that works, the runtime is up; the gap was likely **no traffic + keepalive failing**. Fix keepalive (step 1) so the session stays up.
3. If that doesn’t work, the runtime may be down or unreachable — check IAM, VPC, and AgentCore runtime status/ARN.

---

## Summary

| Symptom | Likely cause | Action |
|--------|----------------|--------|
| No new rows in Telemetry tab since 11pm | No completed invocations | Check keepalive Lambda logs; send a test message |
| No new events in `/glitch/telemetry` | Same as above | Same |
| No logs in `/aws/bedrock/agentcore/...` | Runtime session not running | Fix keepalive; trigger an invoke to cold-start |
| Keepalive log: "Keepalive invoke failed" | Invoke failing | Fix ARN, timeout, permissions, or network (VPC/endpoints) |
