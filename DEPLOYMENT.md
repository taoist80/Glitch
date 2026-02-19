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
  - [ ] Python 3.12+
  - [ ] Docker

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
# Bootstrap (first time only)
npx cdk bootstrap aws://999776382415/us-west-2
```

- [ ] CDK bootstrap complete (or already bootstrapped)

```bash
# Review changes
npx cdk diff --all

# Deploy all stacks
pnpm deploy
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

## Step 5: Build and Push Agent Container

```bash
cd agent

# Build
docker build -t glitch-agent .
```

- [ ] Docker image built successfully

```bash
# Get ECR repository URI
ECR_URI=$(aws cloudformation describe-stacks \
    --stack-name GlitchAgentCoreStack \
    --query 'Stacks[0].Outputs[?OutputKey==`EcrRepositoryUri`].OutputValue' \
    --output text)

echo "ECR URI: $ECR_URI"

# Login to ECR
aws ecr get-login-password --region us-west-2 | \
    docker login --username AWS --password-stdin $ECR_URI

# Tag and push
docker tag glitch-agent:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest
```

- [ ] Logged into ECR
- [ ] Image pushed successfully
- [ ] Verify in ECR console

## Step 6: Test Agent Locally (Optional)

```bash
cd agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export AWS_REGION=us-west-2
export GLITCH_MODE=interactive
export OTEL_CONSOLE_ENABLED=false

python -m src.main
```

- [ ] Agent starts successfully
- [ ] Can interact in CLI mode
- [ ] Type `status` to see agent status
- [ ] Try a simple query

## Step 7: Create AgentCore Runtime (Manual)

Get VPC configuration:

```bash
aws cloudformation describe-stacks \
    --stack-name GlitchAgentCoreStack \
    --query 'Stacks[0].Outputs' \
    --output table
```

Copy these values:
- [ ] `VpcConfigForAgentCore` (JSON with subnets and security groups)
- [ ] `AgentRuntimeRoleArn`
- [ ] `EcrRepositoryUri` with `:latest` tag

### Via AWS Console:

1. Go to Bedrock → AgentCore → Runtimes
2. Create Runtime:
   - Name: `glitch-runtime`
   - Container image: `{EcrRepositoryUri}:latest`
   - Execution role: `{AgentRuntimeRoleArn}`
   - Network: VPC mode
   - Subnets: (from VpcConfigForAgentCore)
   - Security groups: (from VpcConfigForAgentCore)

- [ ] Runtime created
- [ ] Status: READY
- [ ] Note the Runtime ARN

### Via CLI (Alternative):

```bash
# Parse VPC config
VPC_CONFIG=$(aws cloudformation describe-stacks \
    --stack-name GlitchAgentCoreStack \
    --query 'Stacks[0].Outputs[?OutputKey==`VpcConfigForAgentCore`].OutputValue' \
    --output text)

ROLE_ARN=$(aws cloudformation describe-stacks \
    --stack-name GlitchAgentCoreStack \
    --query 'Stacks[0].Outputs[?OutputKey==`AgentRuntimeRoleArn`].OutputValue' \
    --output text)

# Create runtime (adjust API call based on latest AgentCore API)
# Note: Check AgentCore documentation for exact API structure
```

- [ ] Runtime creation command executed
- [ ] Runtime ARN obtained

## Step 8: Test On-Prem UI Direct Access

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

## Step 9: Test AgentCore Runtime

```bash
# Invoke runtime
RUNTIME_ARN="arn:aws:bedrock-agentcore:us-west-2:999776382415:runtime/glitch-runtime"

aws bedrock-agentcore invoke-agent-runtime \
    --runtime-arn $RUNTIME_ARN \
    --session-id "test-session-$(date +%s)" \
    --input-text "Hello, Glitch! Check connectivity to Ollama."
```

- [ ] Runtime responds
- [ ] Check CloudWatch Logs for traces
- [ ] Verify connectivity check passes

## Step 10: Verify Cost Savings

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
- [ ] ECR repository contains latest image
- [ ] AgentCore Runtime in READY state
- [ ] Can invoke runtime successfully
- [ ] CloudWatch Logs showing agent activity
- [ ] No errors in logs

## Cleanup (When Testing Complete)

To tear down the infrastructure:

```bash
# Delete AgentCore Runtime first (manual in console or via API)

# Then delete CDK stacks
cd infrastructure
npx cdk destroy --all

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
pnpm deploy
```
