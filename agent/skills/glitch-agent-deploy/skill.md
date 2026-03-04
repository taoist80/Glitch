# Agent Deployment Management

You manage deployments of the Glitch and Sentinel agents: checking ARN state, wiring cross-agent SSM parameters after a fresh deploy, and monitoring CodeBuild status.

## What you can do vs. what requires local execution

| Task | Who does it | Tool |
|---|---|---|
| Check current deployed ARNs | You | `get_deployed_arns` |
| Update Glitch ARN in SSM | You | `update_glitch_arn_in_ssm` |
| Update Sentinel ARN in SSM | You | `update_sentinel_arn_in_ssm` |
| Update both ARNs at once | You | `update_both_arns_in_ssm` |
| Check CodeBuild deploy progress | You | `check_codebuild_deploy_status` |
| `agentcore deploy` (container build + push) | **Owner runs locally** | N/A — needs Docker |
| CDK stack deploys | **Owner runs locally** | N/A — run `npx cdk deploy <stack>` from `infrastructure/` |

**Container builds must happen locally.** The `agentcore deploy` command builds a Docker image and pushes it to ECR. This requires Docker running on the local machine with the source tree. You cannot run Docker inside your container.

**CDK deploys must happen locally.** Run `npx cdk deploy <StackName>` from the `infrastructure/` directory on your local machine.

## Workflow 1: Fresh deploy of both agents (owner just ran agentcore deploy twice)

After the owner runs:
```bash
cd agent && agentcore deploy           # deploys Glitch
cd monitoring-agent && agentcore deploy # deploys Sentinel
```

Both agents get new ARNs. The owner will provide the new ARNs (or you can ask them to paste the `agent_arn` values from their `.bedrock_agentcore.yaml` files).

1. Call `get_deployed_arns` to see what's currently in SSM.
2. Call `update_both_arns_in_ssm(glitch_arn=<new>, sentinel_arn=<new>)` with the new ARNs.
3. Confirm both parameters updated successfully.
4. Remind the owner that Glitch and Sentinel will pick up the new ARNs on their next cold start (no redeploy needed — the cache clears automatically).

**Full command sequence to give the owner:**
```bash
# Extract ARNs from yaml files
GLITCH_ARN=$(python3 -c "
import yaml
with open('agent/.bedrock_agentcore.yaml') as f:
    c = yaml.safe_load(f)
print(c['agents']['Glitch']['bedrock_agentcore']['agent_arn'])
")

SENTINEL_ARN=$(python3 -c "
import yaml
with open('monitoring-agent/.bedrock_agentcore.yaml') as f:
    c = yaml.safe_load(f)
print(c['agents']['Sentinel']['bedrock_agentcore']['agent_arn'])
")

echo "Glitch ARN:   $GLITCH_ARN"
echo "Sentinel ARN: $SENTINEL_ARN"
```

Then paste both ARNs to you and you will call `update_both_arns_in_ssm`.

## Workflow 2: Only Glitch was redeployed

1. Ask the owner for the new Glitch ARN (from `agent/.bedrock_agentcore.yaml`).
2. Call `update_glitch_arn_in_ssm(new_arn=<arn>)`.
3. Sentinel reads this SSM param to invoke Glitch — it will pick up the new ARN after cache expiry (~5 min).

## Workflow 3: Only Sentinel was redeployed

1. Ask the owner for the new Sentinel ARN (from `monitoring-agent/.bedrock_agentcore.yaml`).
2. Call `update_sentinel_arn_in_ssm(new_arn=<arn>)`.
3. Glitch will pick it up at next cold start or after the in-process cache clears (up to 5 minutes).

## Workflow 4: Check if agents can talk to each other

1. Call `get_deployed_arns` to see what ARNs are currently in SSM.
2. If either value is "missing", prompt the owner to run `agentcore deploy` for that agent and then provide the ARN.
3. If values look stale (contain "PLACEHOLDER"), the agent has never been deployed — full deploy required.

## Workflow 5: Monitor an in-progress agentcore deploy

If the owner is running `agentcore deploy` in another terminal and wants a status update:

```python
check_codebuild_deploy_status(agent="glitch")   # or "sentinel"
```

Returns: build status (IN_PROGRESS / SUCCEEDED / FAILED), current phase, and a CloudWatch Logs deep link.

## Context

- **Glitch ARN SSM param**: `/glitch/sentinel/glitch-runtime-arn` (read by Sentinel's `invoke_glitch_agent`)
- **Sentinel ARN SSM param**: `/glitch/sentinel/runtime-arn` (read by Glitch's `invoke_sentinel`)
- **Both use in-process caches** — changes take effect on next cold start or after ~5 min
- **ECR repos**: `bedrock-agentcore-glitch` and `bedrock-agentcore-sentinel` in `us-west-2`
- **CodeBuild projects**: `bedrock-agentcore-glitch-builder` and `bedrock-agentcore-sentinel-builder`

## Examples

**Owner says:** "I just redeployed both agents, here are the ARNs: Glitch=arn:aws:bedrock-agentcore:... Sentinel=arn:aws:bedrock-agentcore:..."
**Actions:** Call `update_both_arns_in_ssm` with both ARNs. Confirm success. Tell the owner the agents will pick up the new ARNs on their next cold start.

**Owner says:** "How do I deploy Sentinel?"
**Actions:** Explain that `agentcore deploy` must be run locally from the `monitoring-agent/` directory since it requires Docker. Provide the exact command sequence (Workflow 1). Offer to update the SSM parameters once the deploy completes.

**Owner says:** "Sentinel can't reach Glitch" or "invoke_glitch_agent is failing"
**Actions:** Call `get_deployed_arns`. Check if the Glitch ARN in SSM matches the currently deployed runtime (owner may need to provide the current ARN from their yaml). Update if stale.
