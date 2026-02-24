# AgentCore Runtime Logging — Troubleshooting Guide

## How runtime logs work

AgentCore captures container **stdout/stderr** and writes them to a CloudWatch log group that is created automatically when the runtime is first deployed:

```
/aws/bedrock-agentcore/runtimes/<agent_id>-DEFAULT
```

Two log streams are written to this group:

| Stream prefix | Content |
|---|---|
| `YYYY/MM/DD/[runtime-logs]` | Application stdout/stderr (Python `print`, `logger`, etc.) |
| `otel-rt-logs` | OTEL collector internal logs |

The agent also writes its own telemetry to `/glitch/telemetry` (stream `invocations/YYYY-MM-DD`), which feeds the UI Telemetry tab.

---

## Required runtime execution role IAM policy

This is the exact policy the runtime role must have. Three separate statements are required because each action needs a different resource scope.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "ECRImageAccess",
      "Effect": "Allow",
      "Action": [
        "ecr:BatchGetImage",
        "ecr:GetDownloadUrlForLayer",
        "ecr:GetAuthorizationToken"
      ],
      "Resource": [
        "arn:aws:ecr:REGION:ACCOUNT:repository/bedrock-agentcore-glitch",
        "*"
      ]
    },
    {
      "Sid": "CloudWatchLogsDescribeGroups",
      "Effect": "Allow",
      "Action": ["logs:DescribeLogGroups"],
      "Resource": ["arn:aws:logs:REGION:ACCOUNT:log-group:*"]
    },
    {
      "Sid": "CloudWatchLogsGroup",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:DescribeLogStreams"],
      "Resource": [
        "arn:aws:logs:REGION:ACCOUNT:log-group:/aws/bedrock-agentcore/runtimes/*",
        "arn:aws:logs:REGION:ACCOUNT:log-group:/glitch/*"
      ]
    },
    {
      "Sid": "CloudWatchLogsStream",
      "Effect": "Allow",
      "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": [
        "arn:aws:logs:REGION:ACCOUNT:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
        "arn:aws:logs:REGION:ACCOUNT:log-group:/glitch/*:log-stream:*"
      ]
    },
    {
      "Sid": "XRayTracing",
      "Effect": "Allow",
      "Action": [
        "xray:PutTraceSegments",
        "xray:PutTelemetryRecords",
        "xray:GetSamplingRules",
        "xray:GetSamplingTargets"
      ],
      "Resource": ["*"]
    },
    {
      "Sid": "CloudWatchMetrics",
      "Effect": "Allow",
      "Action": ["cloudwatch:PutMetricData"],
      "Resource": ["*"]
    }
  ]
}
```

### Why `DescribeLogGroups` on `log-group:*` matters

The AWS SDK calls `DescribeLogGroups` before writing to verify the log group exists. If this permission is missing, the SDK fails silently **before** ever attempting `PutLogEvents` — even if `PutLogEvents` is allowed. An IAM simulation will show `PutLogEvents` as `allowed` but logs will never appear. This was the root cause of the Feb 2026 logging outage.

### Why three separate statements

CloudWatch Logs uses different resource ARN formats for different actions:

| Action | Resource ARN format |
|---|---|
| `DescribeLogGroups` | `log-group:*` (must be broad — SDK discovery call) |
| `CreateLogGroup`, `DescribeLogStreams` | `log-group:/path/*` (no `:log-stream:*` suffix) |
| `CreateLogStream`, `PutLogEvents` | `log-group:/path/*:log-stream:*` (stream suffix required) |

Combining them into one statement with `log-group:/path/*:*` does not correctly cover all three scopes.

---

## Required VPC endpoints (private isolated subnets)

The runtime runs in `PRIVATE_ISOLATED` subnets with no internet access. Every AWS API call must route through a VPC endpoint. The following are required per the [official VPC docs](https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/security/agentcore-vpc.md):

| Endpoint | Service | Required for |
|---|---|---|
| `ecr.dkr` | ECR Docker | Container image pull |
| `ecr.api` | ECR API | Container image pull |
| `s3` (gateway) | S3 | ECR layer storage |
| `logs` | CloudWatch Logs | Runtime log delivery |

Additional endpoints deployed in this project for OTEL observability:

| Endpoint | Service | Required for |
|---|---|---|
| `sts` | STS | SDK credential refresh in isolated subnets |
| `monitoring` | CloudWatch Metrics | OTEL ADOT metrics export |
| `xray` | X-Ray | OTEL ADOT trace export |
| `secretsmanager` | Secrets Manager | Agent secrets access |
| `bedrock-runtime` | Bedrock | Model invocation |
| `bedrock-agent-runtime` | Bedrock Agent Runtime | AgentCore control plane |
| `bedrock-agentcore` | AgentCore data plane | Runtime invocation |

All interface endpoints use `VpcEndpointsSG`, which allows inbound TCP 443 only from `AgentCoreSG` (the runtime's security group). This is least-privilege — CDK's default `open: true` would allow the entire VPC CIDR.

---

## Troubleshooting checklist

### Step 1 — Confirm the log group exists

```bash
aws logs describe-log-groups \
  --log-group-name-prefix "/aws/bedrock-agentcore/runtimes" \
  --region us-west-2 \
  --query 'logGroups[*].logGroupName' --output table
```

If the group doesn't exist, trigger an invocation — the platform creates it on first container start:

```bash
cd agent && agentcore invoke '{"prompt":"hello"}'
```

### Step 2 — Check if any log streams exist

```bash
aws logs describe-log-streams \
  --log-group-name "/aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT" \
  --order-by LastEventTime --descending --limit 5 \
  --region us-west-2
```

- **No streams at all** → the runtime has never written a log. Go to Step 3.
- **Streams exist but are old** → the runtime was running before but hasn't started since. Trigger an invocation.
- **Streams exist and are recent** → logs are flowing. Check the stream content.

### Step 3 — Verify IAM with simulation

```bash
aws iam simulate-principal-policy \
  --policy-source-arn "arn:aws:iam::999776382415:role/GlitchFoundationStack-RuntimeRoleFD8790A4-sLKBVjdrjs40" \
  --action-names "logs:DescribeLogGroups" "logs:CreateLogStream" "logs:PutLogEvents" \
  --resource-arns \
    "arn:aws:logs:us-west-2:999776382415:log-group:*" \
    "arn:aws:logs:us-west-2:999776382415:log-group:/aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT:log-stream:*" \
  --region us-west-2
```

All three actions must return `allowed`. If `DescribeLogGroups` is `implicitDeny`, redeploy `GlitchFoundationStack` — that's the missing permission.

### Step 4 — Tail logs after an invocation

```bash
# Tail runtime logs (today UTC)
aws logs tail /aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT \
  --log-stream-name-prefix "$(date -u +%Y/%m/%d)/[runtime-logs]" \
  --follow --region us-west-2

# Tail OTEL collector logs
aws logs tail /aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT \
  --log-stream-names "otel-rt-logs" \
  --since 1h --region us-west-2
```

### Step 5 — Check keepalive Lambda

If the runtime is idle for more than 15 minutes it shuts down. The keepalive Lambda pings it every 10 minutes. If keepalive is failing, the runtime won't be running when you check logs.

```bash
aws logs tail /aws/lambda/glitch-agentcore-keepalive --since 1h --region us-west-2
```

Look for `Keepalive invoke failed`. If present, check the runtime ARN in the Lambda environment and confirm the runtime status with `agentcore status`.

---

## Common symptoms and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| Log group doesn't exist | Runtime never started | `agentcore invoke '{"prompt":"hello"}'` |
| Log group exists, no streams | `DescribeLogGroups` missing from IAM | Redeploy `GlitchFoundationStack` |
| IAM simulation shows `allowed` but no logs | Missing `DescribeLogGroups` on `log-group:*` (not covered by simulation resource scope) | Same — redeploy Foundation with corrected policy |
| Logs worked before Feb 22, broken after | Stack consolidation dropped `DescribeLogGroups` | Redeploy `GlitchFoundationStack` |
| `aws logs tail` returns nothing | Wrong date prefix or no recent session | Use `$(date -u +%Y/%m/%d)` for prefix; check `describe-log-streams` |
| Mistral timeout | Wrong `GLITCH_OLLAMA_PROXY_HOST` or Tailscale EC2 stopped | Run `make deploy` to refresh from SSM; check EC2 state |
| No telemetry in UI tab | No completed invocations or keepalive failing | Check keepalive Lambda logs; send a test message |

---

## Deploy workflow reference

```bash
# Deploy infrastructure changes (VPC endpoints, IAM)
cd infrastructure && cdk deploy GlitchFoundationStack --require-approval never

# Redeploy agent (reads role ARN + subnet IDs from SSM, then agentcore deploy)
cd agent && make deploy

# Check status
agentcore status

# Tail logs immediately after invocation
aws logs tail /aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT \
  --log-stream-name-prefix "$(date -u +%Y/%m/%d)/[runtime-logs]" \
  --follow --region us-west-2
```
