# AgentCore Glitch - Quick Start Guide

Get Glitch up and running in ~25 minutes.

## Prerequisites Check

Before starting, verify you have:

- [ ] AWS CLI configured for account `999776382415`, region `us-west-2`
- [ ] Tailscale subnet router running at `10.10.100.230`
- [ ] Ollama chat model at `10.10.110.202:11434`
- [ ] Ollama vision model (LLaVA) at `10.10.110.137:11434`
- [ ] Node.js 18+, pnpm, Docker installed
- [ ] Tailscale admin access to generate ephemeral auth keys

## 5-Step Deployment

### 1. Store Tailscale Auth Key (2 minutes)

```bash
# Generate ephemeral key from https://login.tailscale.com/admin/settings/keys
# Then store it:
aws secretsmanager create-secret \
    --name glitch/tailscale-auth-key \
    --secret-string "tskey-auth-YOUR-KEY-HERE" \
    --region us-west-2
```

### 2. Deploy Infrastructure (15 minutes)

```bash
cd infrastructure

# Install dependencies
pnpm install

# Bootstrap CDK (first time only)
npx cdk bootstrap aws://999776382415/us-west-2

# Deploy all stacks
pnpm deploy
```

Wait for all 4 stacks to complete:
- ✅ GlitchVpcStack
- ✅ GlitchSecretsStack  
- ✅ GlitchTailscaleStack
- ✅ GlitchAgentCoreStack

### 3. Approve Tailscale Routes (2 minutes)

1. Go to https://login.tailscale.com/admin/machines
2. Find device tagged `aws-agent`
3. Click "Review route" and approve:
   - ✅ `10.10.110.202/32` (Ollama chat)
   - ✅ `10.10.110.137/32` (Ollama vision)
   - ✅ `10.10.100.70/32` (Pi-hole, optional)

### 4. Build & Push Container (5 minutes)

```bash
# Get ECR URI from outputs
ECR_URI=$(aws cloudformation describe-stacks \
    --stack-name GlitchAgentCoreStack \
    --query 'Stacks[0].Outputs[?OutputKey==`EcrRepositoryUri`].OutputValue' \
    --output text)

cd agent

# Build container
docker build -t glitch-agent .

# Login and push
aws ecr get-login-password --region us-west-2 | \
    docker login --username AWS --password-stdin $ECR_URI

docker tag glitch-agent:latest ${ECR_URI}:latest
docker push ${ECR_URI}:latest
```

### 5. Create AgentCore Runtime (3 minutes)

Get required values:

```bash
aws cloudformation describe-stacks \
    --stack-name GlitchAgentCoreStack \
    --query 'Stacks[0].Outputs[?OutputKey==`VpcConfigForAgentCore`||OutputKey==`AgentRuntimeRoleArn`||OutputKey==`EcrRepositoryUri`].[OutputKey,OutputValue]' \
    --output table
```

**Via AWS Console:**
1. Go to Bedrock → AgentCore → Runtimes → Create Runtime
2. Name: `glitch-runtime`
3. Container image: `{EcrRepositoryUri}:latest`
4. Execution role: `{AgentRuntimeRoleArn}`
5. Network: VPC mode (paste subnets and security groups from VpcConfigForAgentCore)
6. Create

Wait for status: **READY** ✅

## Verify Deployment

### Check EC2 Connectivity

```bash
INSTANCE_ID=$(aws cloudformation describe-stacks \
    --stack-name GlitchTailscaleStack \
    --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' \
    --output text)

# Connect via SSM
aws ssm start-session --target $INSTANCE_ID

# Once connected, test:
tailscale status
curl http://10.10.110.202:11434/api/tags
curl http://10.10.110.137:11434/api/tags
```

Expected: ✅ Connected to Tailscale, ✅ Can reach both Ollama hosts

### Test AgentCore Runtime

```bash
RUNTIME_ARN="<your-runtime-arn-from-console>"

aws bedrock-agentcore invoke-agent-runtime \
    --runtime-arn $RUNTIME_ARN \
    --session-id "test-$(date +%s)" \
    --input-text "Check connectivity to Ollama hosts"
```

Expected: ✅ Response from Glitch with Ollama health status

## Test Locally (Optional)

```bash
cd agent
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

export AWS_REGION=us-west-2
export GLITCH_MODE=interactive

python -m src.main
```

Try these commands:
- `status` - View agent status
- `Check Ollama health` - Test connectivity
- `quit` - Exit

## What's Next?

**You now have:**
- ✅ Full AWS infrastructure deployed
- ✅ Tailscale bridge to on-prem
- ✅ Glitch agent container in ECR
- ✅ AgentCore Runtime ready to use

**Next steps:**
1. Integrate with your applications via AgentCore Runtime ARN
2. Monitor CloudWatch Logs for agent activity
3. Review OTEL traces for performance insights
4. Add network tools (Unifi, Protect, Pi-hole) in future iterations

## Common Issues

**"No credentials configured" during cdk synth**
- Expected if AWS CLI not configured - deployment will prompt for credentials

**Tailscale won't connect**
- Check secret value: `aws secretsmanager get-secret-value --secret-id glitch/tailscale-auth-key`
- View EC2 logs: `sudo cat /var/log/cloud-init-output.log`

**Can't reach Ollama from EC2**
- Verify routes approved in Tailscale admin
- Check from EC2: `curl http://10.10.110.202:11434/api/tags`

**AgentCore Runtime stuck in CREATING**
- Check IAM role permissions
- Verify VPC subnets are in supported AZs (usw2-az1, usw2-az2)

## Costs

Monthly estimate with light usage (cost optimized):
- EC2 t4g.nano (ARM64): ~$3.80
- VPC Endpoints (6 × 1 AZ): ~$43.80
- ECR: <$1
- AgentCore Runtime: Usage-based
- **Total: ~$47.60 + runtime usage**

**Savings from original design: ~$79.40/month (eliminated NAT Gateway, optimized instance type, single-AZ endpoints)**

## Cleanup

To remove everything:

```bash
# 1. Delete AgentCore Runtime (via console)

# 2. Delete CDK stacks
cd infrastructure
npx cdk destroy --all

# 3. Delete secrets (optional)
aws secretsmanager delete-secret \
    --secret-id glitch/tailscale-auth-key \
    --force-delete-without-recovery
```

---

**Need Help?** See full documentation in `README.md` and deployment details in `DEPLOYMENT.md`.
