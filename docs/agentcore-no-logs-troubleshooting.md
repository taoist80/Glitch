# AgentCore: No Logs Since [Time] — Troubleshooting

If you stop seeing "logging" in AgentCore (UI Telemetry tab, or CloudWatch) after a certain time (e.g. 11pm), use this checklist.

## Where "logging" comes from

| Source | What it is | When it appears |
|--------|------------|------------------|
| **UI Telemetry tab** | Fetches from `/glitch/telemetry` (CloudWatch Logs) or in-memory history | Only when the **agent processes a message** and completes (real user message or keepalive "ping") |
| **Runtime stdout/stderr** | AgentCore-managed log group (e.g. `/aws/bedrock/agentcore/...`) | Only while the **runtime container is running** and writing logs |
| **Lambda logs** | `/aws/lambda/glitch-telegram-webhook`, `/aws/lambda/glitch-agentcore-keepalive` | Every webhook request; every keepalive run (every 10 min) |

So "no logging since 11pm" usually means either **no new invocations** or **runtime no longer running**.

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
