# Infrastructure Operations Skill

## Stack Overview

Glitch system stacks (in dependency order):
1. `GlitchFoundationStack` — VPC (no NAT Gateway), IAM roles, Site-to-Site VPN, SSM params
2. `GlitchSecretsStack` — Secrets Manager references
3. `GlitchStorageStack` — DynamoDB, S3, log groups
4. `GlitchGatewayStack` — Gateway Lambda Function URL (IAM auth)
5. `GlitchTelegramWebhookStack` — Telegram webhook + keepalive Lambda
6. `GlitchTelegramSsmStack` — Telegram webhook URL SSM param
7. `GlitchEdgeStack` — WAF WebACL (us-east-1) with IP allowlist
8. `GlitchUiHostingStack` — CloudFront + S3 + Lambda origin for UI
9. `GlitchAgentCoreStack` — AgentCore runtime IAM policies
10. `GlitchAgentCoreStack` — Glitch runtime IAM policies (ops policy split into `GlitchAgentOpsPolicy`)

## Read-Only Operations (safe, no confirmation needed)

```python
list_cfn_stacks_status()          # Current status of all stacks
check_cfn_drift("StackName")      # Detect configuration drift
cdk_synth_and_validate("Stack")   # Preview template + lint
cdk_diff("StackName")             # Preview what would change
```

## Deployment Workflow (requires Telegram confirmation)

1. Run `cdk_diff(stack_name)` to preview changes
2. Run `cdk_synth_and_validate(stack_name)` to check for errors
3. Send Telegram alert: "About to deploy X, changes: [diff summary]. Reply to confirm."
4. Wait for human confirmation signal
5. Call `cdk_deploy_stack(stack_name, confirmed=True)`
6. Monitor with `list_cfn_stacks_status()` and send resolution notification

**NEVER call `cdk_deploy_stack(confirmed=True)` without human Telegram confirmation.**

## Failure Recovery

| Stack Status | Action |
|-------------|--------|
| `UPDATE_ROLLBACK_FAILED` | `rollback_stack(stack_name)` — attempts continue_update_rollback |
| `UPDATE_IN_PROGRESS` (stuck) | `rollback_stack(stack_name)` — cancels in-progress update |
| `ROLLBACK_COMPLETE` | Stack needs manual deletion before re-deploy |
| `CREATE_FAILED` | Check `list_cfn_stacks_status()` status_reason, alert human |

## Drift Response

If drift detected on a Glitch stack:
1. `check_cfn_drift(stack_name)` — identify drifted resources
2. Assess impact: IAM drift is high severity, tag drift is low
3. If IAM or security group drift: HIGH alert immediately
4. If config drift on remediable resources: `cdk_deploy_stack` to restore state
5. Document in Telegram notification what drifted and why

## Integration with Log Monitoring

After any deployment, automatically:
1. Wait 2-3 minutes
2. Run `scan_log_groups_for_errors(hours=1)` to check for deployment-caused errors
3. If new errors appear after deployment: alert with correlation context
