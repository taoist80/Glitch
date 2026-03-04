# Log Monitoring Skill

## Purpose
Systematically scan CloudWatch log groups for errors and provide structured triage.

## Log Groups to Monitor
- `/aws/bedrock-agentcore/runtimes/*` — AgentCore runtime container logs
- `/aws/lambda/glitch-telegram-webhook` — Telegram webhook Lambda
- `/aws/lambda/glitch-gateway` — Gateway Lambda (UI backend)
- `/aws/lambda/glitch-agentcore-keepalive` — Keepalive Lambda
- `/glitch/telemetry` — Agent telemetry metrics

## Scanning Workflow

1. **Start broad**: Use `scan_log_groups_for_errors(hours=3)` for a quick overview
2. **Drill down**: Use `get_log_group_errors(log_group, hours=6)` on groups with hits
3. **Check metrics**: Use `get_lambda_metrics(function_name)` for Lambda error/throttle rates
4. **Ad-hoc queries**: Use `query_cloudwatch_insights` for specific patterns

## Error Classification

| Pattern | Likely Cause | Action |
|---------|-------------|--------|
| `TimeoutError` / `asyncio.TimeoutError` | SSM unreachable, cold start, network | Check SSM VPC endpoints, verify instance health via Glitch |
| `HTTP Error 4xx` from Bedrock | IAM permissions, session issues | Check IAM policies, session ID format |
| `HTTP Error 5xx` from Bedrock | AgentCore service issue | Monitor for recurrence, alert if persistent |
| `InvocationDoesNotExist` (SSM) | SSM command completed before poll | Benign race condition, ignore |
| `Missing credentials` / `Access Denied` | IAM role missing permission | Check CloudTrail, update IAM |
| `ImportError` / `ModuleNotFoundError` | Dependency issue in container | Check requirements.txt, rebuild container |
| Repeated Lambda cold starts (>30s init) | Memory, package size | Check Lambda memory and package |

## Severity Levels

- **HIGH**: Error rate >10% over last hour, repeated identical errors, complete service unavailability
- **MEDIUM**: Sporadic errors (<10%), timeout patterns, new error types
- **LOW**: Single-occurrence errors, warnings, benign race conditions

## Reporting Format

When reporting to Glitch or Telegram, include:
1. Which log groups have errors
2. Error type and count
3. Sample error messages (truncated)
4. Probable root cause
5. Recommended action
