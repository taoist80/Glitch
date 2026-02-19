# Deployment Checklist

Follow this checklist to deploy AgentCore Glitch infrastructure with full cost optimization.

## Architecture Changes (Cost Optimized)

**Total Savings:** ~$79.59/month from original design

### Changes Made:
1. **Removed NAT Gateway** - Tailscale EC2 in public subnet (direct egress via IGW)
2. **Simplified architecture** - No nginx proxy (direct routing via Tailscale mesh)
3. **ARM64 Graviton instance** - t4g.nano instead of t3.micro
4. **Single-AZ VPC endpoints** - Interface endpoints in one AZ only
5. **Private subnets ISOLATED** - No internet route, only VPC endpoints
6. **Removed unnecessary IAM** - EC2 doesn't need AgentCore invoke permissions

### Traffic Flows:
1. **On-Prem UI → AgentCore:** UI → Tailscale mesh → AgentCore private IPs (direct routing)
2. **AgentCore → Ollama:** AgentCore → EC2 (private IP) → Tailscale mesh → On-prem Ollama
3. **Tailscale coordination:** EC2 (public IP) → IGW → Internet (free egress)

### Cost Comparison:
| Component | Original | Optimized | Savings |
|-----------|----------|-----------|---------|
| NAT Gateway | $32/mo | $0 | **$32.00** |
| EC2 instance | $7.59 (t3.micro) | $3.80 (t4g.nano ARM) | **$3.79** |
| VPC Endpoints (6×2 AZ) | $87.60 | $43.80 (6×1 AZ) | **$43.80** |
| **Total** | **~$127** | **~$47.60** | **~$79.40/mo** |

**Annual Savings:** ~$953

### Security Improvements:
- No nginx complexity or additional attack surface
- EC2 inbound limited to: UDP 41641 (WireGuard) + traffic from AgentCore SG only
- IAM follows strict least-privilege (removed unnecessary permissions)
- Tailscale provides encrypted mesh routing without HTTP layer

## Pre-Deployment

- [ ] Verify AWS CLI is configured for account 999776382415, region us-west-2
- [ ] Confirm Tailscale subnet router is running at 10.10.100.230
- [ ] Verify Ollama hosts are accessible:
  - [ ] Chat model at 10.10.110.202:11434
  - [ ] Vision model (LLaVA) at 10.10.110.137:11434
- [ ] Generate ephemeral Tailscale auth key from admin console
- [ ] Install required tools:
  - [ ] Node.js 18+
  - [ ] pnpm
  - [ ] AWS CDK CLI
  - [ ] Python 3.10+
  - [ ] (Optional) Docker - only needed for `--local` or `--local-build` modes

## Step 1: Store Secrets

```bash
# Store Tailscale auth key
aws secretsmanager create-secret \
    --name glitch/tailscale-auth-key \
    --description "Ephemeral Tailscale auth key" \
    --secret-string "tskey-auth-YOUR-KEY-HERE" \
    --region us-west-2
```

- [ ] Secret created successfully
- [ ] Verified secret exists: `aws secretsmanager describe-secret --secret-id glitch/tailscale-auth-key`

## Step 2: Deploy CDK Infrastructure

```bash
cd infrastructure
pnpm install
pnpm build
```

- [ ] Dependencies installed
- [ ] TypeScript compiled successfully

```bash
# Bootstrap CDK (first time only)
pnpm run cdk bootstrap aws://999776382415/us-west-2
```

- [ ] CDK bootstrap complete (or already bootstrapped)

```bash
# Review changes
pnpm run diff

# Deploy all stacks
pnpm run deploy
```

- [ ] GlitchVpcStack deployed
- [ ] GlitchSecretsStack deployed
- [ ] GlitchTailscaleStack deployed
- [ ] GlitchAgentCoreStack deployed

## Step 3: Verify Tailscale Connection

```bash
# Get EC2 instance ID and public IP
INSTANCE_ID=$(aws cloudformation describe-stacks \
    --stack-name GlitchTailscaleStack \
    --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' \
    --output text)

PUBLIC_IP=$(aws cloudformation describe-stacks \
    --stack-name GlitchTailscaleStack \
    --query 'Stacks[0].Outputs[?OutputKey==`PublicIp`].OutputValue' \
    --output text)

echo "Instance ID: $INSTANCE_ID"
echo "Public IP: $PUBLIC_IP"

# Connect via SSM
aws ssm start-session --target $INSTANCE_ID
```

Once connected to EC2:

```bash
# Check Tailscale status
tailscale status

# Verify IP forwarding enabled
sysctl net.ipv4.ip_forward
sysctl net.ipv6.conf.all.forwarding

# Test connectivity to Ollama
curl http://10.10.110.202:11434/api/tags
curl http://10.10.110.137:11434/api/tags
```

- [ ] Tailscale connected
- [ ] Device appears in Tailscale admin console with tag `aws-agent`
- [ ] IP forwarding enabled (should be 1)
- [ ] Can reach Ollama chat host
- [ ] Can reach Ollama vision host
- [ ] NO nginx installed (simplified architecture)

## Step 4: Approve Tailscale Routes

In Tailscale admin console:

- [ ] Find device tagged `aws-agent`
- [ ] Approve route: 10.10.110.202/32
- [ ] Approve route: 10.10.110.137/32
- [ ] Approve route: 10.10.100.70/32 (optional, for Pi-hole)

## Step 5: Install AgentCore Starter Toolkit

```bash
cd agent
python -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install bedrock-agentcore strands-agents bedrock-agentcore-starter-toolkit

# Verify installation
agentcore --help
```

- [ ] Virtual environment created
- [ ] Toolkit installed successfully
- [ ] `agentcore --help` shows available commands

## Step 6: Configure Agent Project

```bash
# Create agent project with Strands framework
agentcore create
```

When prompted:
- Framework: **Strands Agents**
- Project name: **glitch**
- Configure additional options as needed

This generates:
- Agent code with Strands framework
- `.bedrock_agentcore.yaml` configuration file
- `requirements.txt` with dependencies

- [ ] Project created successfully
- [ ] `.bedrock_agentcore.yaml` exists

## Step 7: Test Agent Locally (Optional)

```bash
# Start local development server
agentcore dev
```

In a separate terminal:

```bash
# Test locally
agentcore invoke --dev "Hello, Glitch!"
```

- [ ] Local server starts on http://localhost:8080
- [ ] Agent responds to test invocation
- [ ] No errors in console

## Step 8: Configure Custom Execution Role (Optional)

If you want to use the CDK-managed IAM role with additional permissions:

```bash
# Get the role ARN from CDK stack
ROLE_ARN=$(aws cloudformation describe-stacks \
    --stack-name GlitchAgentCoreStack \
    --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeRoleArn`].OutputValue' \
    --output text)

echo "Role ARN: $ROLE_ARN"

# Configure toolkit to use custom role
agentcore configure -e src/glitch/agent.py --execution-role $ROLE_ARN
```

- [ ] Role ARN retrieved
- [ ] Toolkit configured with custom role

## Step 9: Deploy to AgentCore Runtime

```bash
# Deploy agent (builds container via CodeBuild, pushes to ECR, creates runtime)
agentcore launch
```

This command automatically:
1. Builds ARM64 container using AWS CodeBuild (no local Docker required)
2. Creates ECR repository (`bedrock-agentcore-glitch`)
3. Pushes container to ECR
4. Creates AgentCore Runtime
5. Configures CloudWatch logging

- [ ] CodeBuild started
- [ ] Container built successfully
- [ ] ECR repository created
- [ ] Runtime deployed
- [ ] Note the **Agent Runtime ARN** from output

### Deployment Options

```bash
# Default: CodeBuild + Cloud Runtime (recommended, no Docker needed)
agentcore launch

# Local build + Cloud Runtime (requires Docker)
agentcore launch --local-build

# Fully local (requires Docker, for development only)
agentcore launch --local
```

## Step 10: Verify Deployment

```bash
# Check deployment status
agentcore status

# Test deployed agent
agentcore invoke '{"prompt": "Hello, Glitch! Check your status."}'
```

- [ ] Status shows runtime is READY
- [ ] Agent responds to invocation
- [ ] Check CloudWatch Logs for traces

### Find Your Resources

After deployment, view your resources in the AWS Console:

| Resource | Location |
|----------|----------|
| **Agent Logs** | CloudWatch → Log groups → `/aws/bedrock-agentcore/runtimes/{agent-id}-DEFAULT` |
| **Container Images** | ECR → Repositories → `bedrock-agentcore-glitch` |
| **Build Logs** | CodeBuild → Build history |
| **IAM Role** | IAM → Roles → Search for "BedrockAgentCore" |
| **Agent Config** | `.bedrock_agentcore.yaml` in your project |

## Step 11: Test On-Prem UI Direct Access

From your on-premises machine (connected via Tailscale):

```bash
# On-prem UI can reach AgentCore directly via Tailscale routing
# No proxy needed - Tailscale mesh provides direct IP routing

# If using AWS SDK from on-prem:
# Configure AWS credentials and endpoint
# The UI will reach AgentCore via its private IPs through Tailscale

# Test Tailscale connectivity to AWS VPC
ping <tailscale-ec2-private-ip>
```

- [ ] Can reach Tailscale EC2 from on-prem
- [ ] Tailscale routing allows access to VPC private IPs
- [ ] No nginx proxy needed (simplified architecture)

## Step 12: Invoke Agent Programmatically

Get the Agent ARN from `.bedrock_agentcore.yaml` or the `agentcore launch` output:

```bash
# Using agentcore CLI
agentcore invoke '{"prompt": "Hello, Glitch! Check connectivity to Ollama."}'
```

Or programmatically with boto3:

```python
import json
import uuid
import boto3

agent_arn = "YOUR_AGENT_ARN"  # From agentcore launch output
prompt = "Hello, Glitch! Check connectivity to Ollama."

client = boto3.client('bedrock-agentcore')

response = client.invoke_agent_runtime(
    agentRuntimeArn=agent_arn,
    runtimeSessionId=str(uuid.uuid4()),
    payload=json.dumps({"prompt": prompt}).encode(),
    qualifier="DEFAULT"
)

content = []
for chunk in response.get("response", []):
    content.append(chunk.decode('utf-8'))
print(json.loads(''.join(content)))
```

- [ ] Runtime responds
- [ ] Check CloudWatch Logs for traces
- [ ] Verify connectivity check passes

## Step 13: Verify Cost Savings

After 24-48 hours, check billing:

```bash
# Check for NAT Gateway charges (should be $0)
aws ce get-cost-and-usage \
    --time-period Start=2026-02-20,End=2026-02-21 \
    --granularity DAILY \
    --metrics BlendedCost \
    --group-by Type=SERVICE | grep -E "EC2|VPC"
```

Expected charges:
- [ ] No "Amazon EC2 - NAT Gateway" charges (saved $32/mo)
- [ ] VPC Endpoint charges ~$43.80/month (single AZ, saved $43.80/mo)
- [ ] EC2 t4g.nano charges ~$3.80/month (ARM64, saved $3.79/mo)
- [ ] **Total: ~$47.60/month (was ~$127, saved ~$79/month)**

## Post-Deployment Verification

- [ ] All CloudFormation stacks in CREATE_COMPLETE status
- [ ] EC2 instance running and connected to Tailscale
- [ ] `agentcore status` shows runtime is READY
- [ ] Can invoke runtime successfully via `agentcore invoke`
- [ ] CloudWatch Logs showing agent activity
- [ ] No errors in logs

## Cleanup (When Testing Complete)

To tear down the infrastructure:

```bash
# Delete AgentCore resources (runtime, ECR, IAM)
cd agent
agentcore destroy

# Then delete CDK stacks
cd ../infrastructure
pnpm run cdk destroy --all

# Delete secrets (optional, they have retention)
aws secretsmanager delete-secret \
    --secret-id glitch/tailscale-auth-key \
    --force-delete-without-recovery

aws secretsmanager delete-secret \
    --secret-id glitch/api-keys \
    --force-delete-without-recovery
```

## Troubleshooting

### EC2 Won't Connect to Tailscale

```bash
# Check user data logs
aws ssm start-session --target $INSTANCE_ID
sudo cat /var/log/cloud-init-output.log

# Check if EC2 has public IP
aws ec2 describe-instances --instance-ids $INSTANCE_ID \
    --query 'Reservations[0].Instances[0].PublicIpAddress'
```

### nginx Proxy Not Working

**Not applicable** - nginx removed from architecture for simplicity. On-prem UI accesses AgentCore via direct Tailscale routing.

### AgentCore Runtime Creation Fails

- Verify IAM role has correct permissions
- Check VPC configuration (subnets in supported AZs: usw2-az1, usw2-az2)
- Ensure ECR image is accessible
- Verify private subnets are ISOLATED (no NAT route)

### Agent Can't Reach Ollama

- Verify Tailscale routes are approved in admin console
- Check security group rules on EC2
- Test connectivity from EC2: `curl http://10.10.110.202:11434/api/tags`
- Verify Tailscale mesh is working: `tailscale status`

### Can't Reach Proxy from On-Prem

**Not applicable** - No proxy in simplified architecture. On-prem UI routes directly to AgentCore private IPs via Tailscale mesh.

## Notes

- Keep your Tailscale auth key secure and rotate it regularly
- Monitor CloudWatch Logs for agent activity
- Review OTEL traces for performance insights
- Estimated deployment time: 15-20 minutes
- **Estimated monthly cost: ~$47.60 (was ~$127, saved ~$79.40)**
- **Instance:** t4g.nano ARM64 Graviton (cheaper, energy efficient)
- **VPC Endpoints:** Single AZ only (accepts AZ outage risk for cost savings)
- **Architecture:** Simplified - no nginx proxy, direct Tailscale routing
- EC2 is in public subnet with public IP (only Tailscale ports + AgentCore SG exposed)
- Private subnets are fully isolated (no internet route, VPC endpoints only)

## Rollback to Original Architecture (If Needed)

If issues arise, rollback to previous architecture:

```bash
cd infrastructure

# In vpc-stack.ts:
# - Set natGateways: 1
# - Change PRIVATE_ISOLATED → PRIVATE_WITH_EGRESS
# - Change singleAzSubnet back to all AZs

# In tailscale-stack.ts:
# - Change T4G.NANO → T3.MICRO
# - Change cpuType: ARM_64 → remove (default x86)
# - Change vpcSubnets to PRIVATE_WITH_EGRESS
# - Remove associatePublicIpAddress

pnpm build
npx cdk deploy --all
```
