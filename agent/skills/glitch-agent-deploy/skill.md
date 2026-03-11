# Agent Deployment Management

You manage deployments of the Glitch agent (the single merged agent): checking ARN state, wiring SSM parameters after a fresh deploy, and monitoring CodeBuild status.

## What you can do vs. what requires local execution

| Task | Who does it | Tool |
|---|---|---|
| Check current deployed ARN | You | `get_deployed_arns` |
| Update Glitch ARN in SSM | You | `update_glitch_arn_in_ssm` |
| Check CodeBuild deploy progress | You | `check_codebuild_deploy_status` |
| `agentcore deploy` (container build + push) | **Owner runs locally** | N/A — needs Docker |
| CDK stack deploys | **Owner runs locally** | N/A — run `pnpm cdk deploy <stack>` from `infrastructure/` |

**Container builds must happen locally.** The `agentcore deploy` command builds a Docker image and pushes it to ECR. This requires Docker running on the local machine with the source tree. You cannot run Docker inside your container.

**CDK deploys must happen locally.** Run `pnpm cdk deploy <StackName>` from the `infrastructure/` directory on your local machine.

## Workflow: Fresh deploy of Glitch

After the owner runs `cd agent && make deploy`:

1. Call `get_deployed_arns` to see what ARN is currently in SSM.
2. If the owner provides the new ARN (from `agent/.bedrock_agentcore.yaml`), call `update_glitch_arn_in_ssm(new_arn=<arn>)`.
3. Confirm the parameter updated successfully.

**To extract the ARN after deploy:**
```bash
python3 -c "
import yaml
with open('agent/.bedrock_agentcore.yaml') as f:
    c = yaml.safe_load(f)
print(c['agents']['Glitch']['bedrock_agentcore']['agent_arn'])
"
```

## Workflow: Monitor an in-progress deploy

```python
check_codebuild_deploy_status(agent="glitch")
```

Returns: build status (IN_PROGRESS / SUCCEEDED / FAILED), current phase, and a CloudWatch Logs deep link.

## Context

- **Glitch ARN SSM param**: `/glitch/sentinel/glitch-runtime-arn`
- **ECR repo**: `bedrock-agentcore-glitch` in `us-west-2`
- **CodeBuild project**: `bedrock-agentcore-glitch-builder`

## Examples

**Owner says:** "I just redeployed Glitch, here is the new ARN: arn:aws:bedrock-agentcore:..."
**Actions:** Call `update_glitch_arn_in_ssm` with the new ARN. Confirm success.

**Owner says:** "How do I deploy Glitch?"
**Actions:** Tell the owner to run `cd agent && make deploy` locally (requires Docker). Offer to update the SSM ARN parameter once the deploy completes.
