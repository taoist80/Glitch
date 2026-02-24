# AgentCore: No Logs Since [Time] — Troubleshooting

If you stop seeing "logging" in AgentCore (UI Telemetry tab, or CloudWatch) after a certain time (e.g. 11pm), use this checklist.

## "The specified log group does not exist" (ResourceNotFoundException)

The **runtime** log group `/aws/bedrock-agentcore/runtimes/<agent_id>-DEFAULT` is **created by the Bedrock AgentCore platform**, not by our CDK. It is created when the platform **starts a container** and begins capturing stdout/stderr. If you have never invoked the agent (or no container has started yet), this log group will not exist.

**Fix:** Trigger at least one invocation so the platform starts a container:

```bash
cd agent
agentcore invoke '{"prompt":"hello"}'
```

Or send a message via Telegram / Gateway so the runtime is invoked. Then list log groups to confirm creation:

```bash
aws logs describe-log-groups --log-group-name-prefix "/aws/bedrock-agentcore" --region us-west-2 --query 'logGroups[*].logGroupName' --output table
```

Then tail: `aws logs tail /aws/bedrock-agentcore/runtimes/Glitch-<your-agent-id>-DEFAULT --follow --region us-west-2`

## "Mistral request timed out after 120.0s" (or 180s)

This usually means the runtime container could not get a response from the local Ollama (Mistral) host within the request timeout. Common causes:

**1. Proxy host not set (most common)**  
The container talks to Ollama via the **Tailscale EC2** proxy. If `GLITCH_OLLAMA_PROXY_HOST` is not set in the runtime, the agent uses a default IP (e.g. `10.0.0.139`) which may be wrong or unreachable, so the connection hangs and times out.

**Fix:** Run the full deploy workflow so the proxy host is set from the Tailscale stack and the agent is redeployed:

```bash
cd agent
make deploy   # runs pre-deploy-configure.py (sets GLITCH_OLLAMA_PROXY_HOST from stack) then agentcore deploy
```

Ensure the **Tailscale stack** is deployed first (it must output `PrivateIp`). Check that `.bedrock_agentcore.yaml` has under `aws`:

```yaml
environment_variables:
  GLITCH_OLLAMA_PROXY_HOST: "<Tailscale EC2 private IP>"
```

**2. Slow response or return path**  
If the proxy host is correct but Ollama is slow (cold model, long generation) or the return path drops packets, the request can still time out.

**Fix:** Increase the timeout via environment (no code change). In `agent/.bedrock_agentcore.yaml` under `aws.environment_variables` add:

```yaml
GLITCH_MISTRAL_TIMEOUT: "240"
GLITCH_OLLAMA_TIMEOUT: "240"
```

Then run `agentcore deploy`. Defaults are 180s (Mistral) and 180s (Ollama tools) if not set.

**3. Tailscale / nginx proxy host offline**  
The AgentCore container reaches Ollama only via the **Tailscale EC2** instance (nginx proxies 11434 and 8080 to on-prem). If that EC2 is stopped or nginx is down, Mistral/local_chat will time out.

**Check EC2 state:**

```bash
# Get instance ID from stack output
INSTANCE_ID=$(aws cloudformation describe-stacks --stack-name GlitchTailscaleStack --region us-west-2 \
  --query "Stacks[0].Outputs[?OutputKey=='InstanceId'].OutputValue" --output text)

# Check state (running / stopped / stopped-terminated etc.)
aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region us-west-2 \
  --query "Reservations[0].Instances[0].State.Name" --output text
```

**If state is `stopped`:** Start the instance, then update the agent config with the **new** private IP (stopping/starting can change the private IP):

```bash
aws ec2 start-instances --instance-ids "$INSTANCE_ID" --region us-west-2
# Wait until state is running, then get new private IP:
aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region us-west-2 \
  --query "Reservations[0].Instances[0].PrivateIpAddress" --output text
```

Set that IP in `agent/.bedrock_agentcore.yaml` under `aws.environment_variables.GLITCH_OLLAMA_PROXY_HOST`, then `agentcore deploy`.

**If EC2 is running but nginx may be down:** Use SSM Session Manager to check and restart nginx:

```bash
aws ssm start-session --target "$INSTANCE_ID" --region us-west-2
# On the instance:
sudo systemctl status nginx
sudo systemctl start nginx   # if stopped
sudo systemctl restart nginx # if you changed config
```

**Quick connectivity test from your machine (if you have Tailscale and can reach the EC2):**  
`curl -s -o /dev/null -w "%{http_code}" --connect-timeout 5 http://100.110.172.11:11434/api/tags` (use the EC2’s Tailscale IP or private IP from the same VPC). Expect 200 if nginx and Ollama are reachable.

**4. Root-cause checklist when Mistral times out after a redeploy**

After a Tailscale stack or EC2 redeploy, the instance's **VPC private IP** can change (e.g. from `10.0.0.139` to `10.0.0.82`). If the runtime still uses the old IP, it will time out and no traffic will reach the on-prem subnet (e.g. SNAT counters on the subnet router stay at zero). Check in this order:

| Check | What to do | What it proves |
|-------|------------|----------------|
| **A. URL in runtime logs** | In CloudWatch → runtime log group → latest stream, search for `Mistral endpoint:` or `Mistral Ollama native request starting:`. Note the host in the URL. | If the URL shows `10.0.0.139` (or any IP other than the current EC2 private IP), the runtime has the wrong proxy host (stale env or no `environment_variables` in config). Fix: set `GLITCH_OLLAMA_PROXY_HOST` in `aws.environment_variables` to the **current** EC2 private IP and run **`make deploy`** (so pre-deploy script can refresh it from the stack). |
| **B. Agent config** | In `agent/.bedrock_agentcore.yaml` under `aws.environment_variables`, confirm `GLITCH_OLLAMA_PROXY_HOST` is the **current** Tailscale EC2 private IP (from `GlitchTailscaleStack` output `PrivateIp`). | Ensures the next deploy sends the correct IP to the runtime. After any EC2 replace, run **`make deploy`** so `pre-deploy-configure.py` updates this from the stack. |
| **C. Security group / NACL** | VPC Flow Logs: AgentCore ENI egress to EC2:11434, and EC2 ENI ingress on 11434 from AgentCore. | Confirms traffic is allowed from runtime to proxy. REJECT or missing flows → fix SGs or NACLs. |
| **D. Listener on EC2** | On the Tailscale EC2: `ss -lntp | grep 11434`, `sudo systemctl status nginx`, `sudo nginx -T` (and nginx access/error logs). | Confirms nginx is listening and proxying to on-prem. |
| **E. Tailscale routes** | On EC2: `tailscale status`, `tailscale debug prefs`, `ip route show table 52`. In Tailscale admin: which device advertises `10.10.110.0/24` (or /32s); which devices accept routes. | If EC2 should reach on-prem via Tailscale, it must have an approved route (e.g. accept routes from the subnet router). Conflicting advertise/accept between EC2 and the on-prem router can cause "works from one place, fails from another." |

**One-line summary:** If the runtime log shows a URL with an **old** EC2 private IP, the runtime is not reaching the current proxy; fix `GLITCH_OLLAMA_PROXY_HOST` and use **`make deploy`** so the correct IP is set from the stack.

## No logs after stack consolidation (Feb 22–23): runtime role missing `/aws/bedrock-agentcore/*`

**Symptom:** Logs last appeared around Feb 22, 2026; after refactors (consolidated foundation stack, SSM-based config) no application logs show up in `/aws/bedrock-agentcore/runtimes/...`.

**Root cause:** Before consolidation, the runtime role was created in **AgentCoreStack** with a **CloudWatchLogs** policy that included **both**:

- `arn:aws:logs:...:log-group:/aws/bedrock-agentcore/*` (AgentCore runtime application logs)
- `arn:aws:logs:...:log-group:/glitch/*` (telemetry)

After consolidation (commit `e7404fb` / `8d282b5`):

- The runtime role is created in **GlitchFoundationStack** with only **`/glitch/*`** (GlitchTelemetryLogs).
- **GlitchAgentCoreStack** attaches a ManagedPolicy that adds **`/aws/bedrock-agentcore/*`** (and the rest) to the same role.

Application logs (stdout/stderr) are written by the **platform** to `/aws/bedrock-agentcore/runtimes/<agent_id>-<endpoint>/...` using the **runtime execution role**. If that role only had `/glitch/*` (e.g. Foundation deployed but AgentCoreStack not deployed, or policy not attached), PutLogEvents to the bedrock-agentcore log group would fail and no runtime logs would appear.

**Fix applied:** GlitchFoundationStack’s runtime role now includes **both** `/glitch/*` and `/aws/bedrock-agentcore/*` in a single CloudWatch Logs policy, so application logs work even if GlitchAgentCoreStack is not yet deployed. After updating the stack, redeploy Foundation and ensure the runtime’s execution role in `.bedrock_agentcore.yaml` is the Foundation role ARN (from SSM `/glitch/iam/runtime-role-arn` or `make deploy`).

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

### 0. Runtime logs are created by default (no "Log delivery" required)

For **agent runtime** resources, AWS documents that the platform **creates a CloudWatch log group by default** for service-provided logs. You do **not** need to configure a "Log delivery" destination for runtime the way you do for Memory or Gateway—if you don't see a Log delivery section on your agent page, that's expected for many UIs; runtime logs should still flow to the default log group when IAM and network allow it.

Use the **Logs** link in the **Endpoints** table (next to your DEFAULT endpoint) to open the runtime log group in CloudWatch. If the group exists but stays empty after invocations, the problem is likely IAM (runtime role cannot write) or network (runtime cannot reach CloudWatch Logs). If the group doesn't exist at all, the first write may be failing (check IAM below).

### 0b. Log group exists but is empty (worked before Feb 22, broken after)

This matches the post–consolidation case: the **runtime execution role** lost (or never got) permission to write to `/aws/bedrock-agentcore/*` because the role is created in **GlitchFoundationStack** and only **GlitchAgentCoreStack** had been adding that permission. If you deploy only Foundation (or deploy Foundation first and never deploy AgentCoreStack), the role had only `/glitch/*` until we added `/aws/bedrock-agentcore/*` to Foundation.

**Do this:**

1. **Redeploy Foundation** so the runtime role gets the updated policy (CloudWatch Logs for `/aws/bedrock-agentcore/*`):
   ```bash
   cdk deploy GlitchFoundationStack --require-approval never
   ```
   No need to redeploy the agent; the same role ARN is used, with updated permissions.

2. **Confirm the runtime is using that role**  
   Your `agent/.bedrock_agentcore.yaml` should have `aws.execution_role` equal to the Foundation runtime role ARN (e.g. `GlitchFoundationStack-RuntimeRoleFD8790A4-...`). If you use `make deploy`, the pre-deploy script sets this from SSM. If the runtime was created with a different role, run `make deploy` once so the config (and runtime) use the Foundation role.

3. **Verify the role has the permission in AWS** (optional):
   ```bash
   ROLE_ARN="arn:aws:iam::999776382415:role/GlitchFoundationStack-RuntimeRoleFD8790A4-sLKBVjdrjs40"  # from agent .bedrock_agentcore.yaml
   # List inline policy name, then inspect (policy name is often DefaultPolicy or similar)
   aws iam list-role-policies --role-name "GlitchFoundationStack-RuntimeRoleFD8790A4-sLKBVjdrjs40" --region us-west-2
   # aws iam get-role-policy --role-name "GlitchFoundationStack-RuntimeRoleFD8790A4-sLKBVjdrjs40" --policy-name "<name-from-above>" --region us-west-2
   ```
   The inline policy should include `logs:PutLogEvents`, `CreateLogGroup`, `CreateLogStream`, `DescribeLogStreams` with resources `arn:aws:logs:us-west-2:999776382415:log-group:/aws/bedrock-agentcore/*` (and `...:*`). Or run a policy simulation:
   ```bash
   aws iam simulate-principal-policy \
     --policy-source-arn "arn:aws:iam::999776382415:role/GlitchFoundationStack-RuntimeRoleFD8790A4-sLKBVjdrjs40" \
     --action-names "logs:PutLogEvents" "logs:CreateLogStream" \
     --resource-arns "arn:aws:logs:us-west-2:999776382415:log-group:/aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT:*"
   ```
   Expect `allowed` for both actions.

4. **Trigger an invocation** (e.g. send a message or run keepalive), then check the runtime log group again for new streams/events.

If after redeploying Foundation you still see no logs, the next suspect is **network**: the runtime runs in a VPC and must reach the CloudWatch Logs API (via the CloudWatch Logs interface endpoint or NAT). Check that the runtime’s security group allows egress to the endpoint and that the VPC has the CloudWatch Logs endpoint (or a NAT route).

### 0c. IAM simulation shows "allowed" but the runtime log group is still empty

If you ran `simulate-principal-policy` for the runtime role on `logs:PutLogEvents` / `logs:CreateLogStream` and both show **allowed** (see e.g. `agent/iam-simulation-results.json`), then permissions are not the blocker.

**Remaining possibilities:**

1. **Who writes the logs?**  
   Application logs (stdout/stderr) may be delivered by the **AgentCore platform** (control plane) using the runtime’s execution role, not by the container itself. In that case the write happens from AWS infrastructure to CloudWatch, so **VPC/endpoints are not involved**. If IAM is allowed and the platform is supposed to write, the issue may be platform-side (feature flag, log delivery configuration in the console if it exists for your agent type, or a service issue). Re-check the agent’s **Log delivery** / **Observability** section in the console in case your UI has an option to enable or confirm APPLICATION_LOGS for this runtime.

2. **Network (if the write path goes from the runtime VPC)**  
   If the writer is the container or a component that runs in your VPC, it must reach `logs.<region>.amazonaws.com`. The stack was updated so that **all interface endpoints** (including CloudWatch Logs) use a dedicated **VpcEndpointsSG** that allows **inbound TCP 443 only from the AgentCore runtime SG**. Previously, endpoints may have used the VPC default SG, which often does not allow traffic from the runtime’s security group. **Redeploy GlitchFoundationStack** to apply this change, then trigger an invocation and check the runtime log group again.

3. **Container not producing stdout**  
   If the process exits before flushing logs or crashes very early, the platform may have nothing to deliver. Less likely if invocations return success and you see responses.

4. **Different log group or region**  
   Confirm you’re looking at the log group for **this** runtime (e.g. `/aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT`) in **us-west-2** and that the **Logs** link in the console points to the same group.

If you’ve confirmed IAM (simulation allowed), network (endpoint SG allows runtime SG), and the correct log group, and logs still don’t appear, consider opening an AWS support case or checking AgentCore release notes / known issues for your region.

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

### 3. AgentCore observability: OTEL config and log delivery

For logs and telemetry to appear in CloudWatch, two things must be in place.

**A. Container must run with ADOT auto-instrumentation**

The [AgentCore observability docs](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html) require:

- **aws-opentelemetry-distro** in the image (we have it in the Dockerfile).
- **Launch with `opentelemetry-instrument`** so OTEL traces/metrics are sent to CloudWatch.

The Dockerfile must use:

```dockerfile
CMD ["opentelemetry-instrument", "python", "-m", "main"]
```

If the image still uses `CMD ["python", "-m", "main"]`, rebuild and redeploy the agent so the new CMD is used. Without this, the platform does not receive OTEL data and automatic collection will not work as documented.

**B. Runtime log group (default)**

For agent runtime, the platform creates a CloudWatch log group by default; you do not need to configure "Log delivery" in the console for basic runtime logs. Use the **Logs** link in the Endpoints table on your agent page to open the log group. If that group exists but has no streams or no new events, the blocker is likely IAM (runtime role needs `logs:PutLogEvents` etc. for `/aws/bedrock-agentcore/*`) or VPC/network (runtime must reach the CloudWatch Logs endpoint).

**C. One-time: CloudWatch Transaction Search**

For traces/spans, [enable Transaction Search](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-configure.html) once in CloudWatch (Application Signals → Transaction search → Enable).

**Where data appears after the above**

| Data | Where |
|------|--------|
| Standard logs (stdout/stderr) | `/aws/bedrock-agentcore/runtimes/<agent_id>-DEFAULT/[runtime-logs]` |
| OTEL structured logs | Same runtime log group / otel-rt-logs (with ADOT) |
| Traces | CloudWatch Transaction Search, `/aws/spans/default` |
| Metrics | CloudWatch Metrics, namespace `bedrock-agentcore` |

**If you also use app-level writes to `/glitch/telemetry`**, the runtime role needs CloudWatch Logs permissions; **GlitchFoundationStack** attaches `GlitchTelemetryLogs` for `/glitch/*`. Redeploy Foundation if needed.

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
