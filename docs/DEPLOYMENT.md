# AgentCore Glitch - Deployment Guide

Complete deployment guide for the VPC/Tailscale/AgentCore infrastructure with automated configuration and testing.

## Quick Start

### 1. Deploy Infrastructure

```bash
cd infrastructure
pnpm install
pnpm build
cdk deploy --all
```

This deploys:
- `GlitchVpcStack` - VPC with endpoints
- `GlitchSecretsStack` - Secrets Manager secrets
- `GlitchTailscaleStack` - Tailscale EC2 gateway
- `GlitchAgentCoreStack` - Security groups and IAM roles

### 2. Approve Tailscale Route

1. Go to [admin.tailscale.com](https://admin.tailscale.com)
2. Find the `glitch-tailscale` node
3. Approve the `10.10.110.0/24` subnet route

### 3. Deploy Agent (Automated)

```bash
cd agent
make deploy
```

This automatically:
1. **Configures** VPC settings from CloudFormation
2. **Deploys** the agent with `agentcore deploy`
3. **Verifies** deployment and connectivity

**That's it!** No manual configuration needed.

## Deployment Workflows

### Option 1: Fully Automated (Recommended)

```bash
# Deploy everything
./infrastructure/scripts/deploy-and-verify.sh

# Or step by step
cd infrastructure && cdk deploy --all
cd agent && make deploy
```

### Option 2: Manual with Auto-Configuration

```bash
# 1. Deploy infrastructure
cd infrastructure
cdk deploy --all

# 2. Approve Tailscale route (manual)
# Visit admin.tailscale.com

# 3. Deploy agent (auto-configures VPC)
cd agent
./scripts/deploy.sh
```

### Option 3: Fully Manual

```bash
# 1. Deploy infrastructure
cd infrastructure
cdk deploy --all

# 2. Get CloudFormation outputs
aws cloudformation describe-stacks --stack-name GlitchVpcStack
aws cloudformation describe-stacks --stack-name GlitchAgentCoreStack

# 3. Update agent/.bedrock_agentcore.yaml manually
# Set network_mode_config.subnet_ids and security_group_ids

# 4. Deploy agent
cd agent
agentcore deploy
```

## Testing

### Unit Tests (CDK Infrastructure)

```bash
cd infrastructure
pnpm test
```

Tests 47 assertions across:
- VPC configuration and endpoints
- Tailscale EC2 instance and security groups
- AgentCore IAM roles and permissions

### Integration Tests (Deployed Infrastructure)

```bash
cd infrastructure
pytest test/test_integration.py -v
```

Verifies:
- VPC and subnets exist
- VPC endpoints are configured
- Tailscale instance is running
- VPC routes to on-prem CIDR
- AgentCore security groups and IAM roles

### Agent Deployment Verification

Automatic verification runs after `make deploy`:
- VPC configuration is complete
- VPC endpoints are accessible
- Security groups are properly configured

## Scripts

### Infrastructure Scripts

**`infrastructure/scripts/deploy-and-verify.sh`** - Full deployment orchestration
```bash
./scripts/deploy-and-verify.sh [--skip-deploy] [--skip-tests]
```

**`infrastructure/scripts/configure_agentcore_vpc.py`** - Manual VPC configuration
```bash
python3 scripts/configure_agentcore_vpc.py [--dry-run]
```

### Agent Scripts

**`agent/scripts/deploy.sh`** - Automated deployment wrapper
```bash
./scripts/deploy.sh [--skip-pre-check] [--skip-post-check]
```

**`agent/scripts/pre-deploy-configure.py`** - VPC auto-configuration
```bash
python3 scripts/pre-deploy-configure.py
```

**`agent/scripts/post-deploy-verify.py`** - Post-deployment verification
```bash
python3 scripts/post-deploy-verify.py
```

## Makefile Targets

### Infrastructure
```bash
cd infrastructure
make test          # Run CDK unit tests
make build         # Build TypeScript
make deploy        # Deploy all stacks
```

### Agent
```bash
cd agent
make deploy        # Full deployment workflow
make deploy-only   # Deploy without checks
make configure     # Configure VPC only
make verify        # Verify deployment only
make test          # Run agent tests
```

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    AWS Account                           │
│                                                           │
│  ┌────────────────────────────────────────────────────┐ │
│  │ VPC (10.0.0.0/16)                                  │ │
│  │                                                     │ │
│  │  ┌──────────────────┐    ┌──────────────────┐    │ │
│  │  │ Public Subnets   │    │ Private Subnets  │    │ │
│  │  │                  │    │                  │    │ │
│  │  │ Tailscale EC2 ───┼────▶ AgentCore       │    │ │
│  │  │ (t4g.nano)       │    │ Runtime (VPC)    │    │ │
│  │  │                  │    │                  │    │ │
│  │  └────────┬─────────┘    └────────┬─────────┘    │ │
│  │           │                       │              │ │
│  │           │ Routes                │              │ │
│  │           │ 10.10.110.0/24        │              │ │
│  │           │                       │              │ │
│  │  ┌────────▼───────────────────────▼────────┐    │ │
│  │  │ VPC Endpoints                          │    │ │
│  │  │ - Bedrock Runtime                       │    │ │
│  │  │ - Bedrock AgentCore                     │    │ │
│  │  │ - ECR (Docker + API)                    │    │ │
│  │  │ - CloudWatch Logs                       │    │ │
│  │  │ - Secrets Manager                       │    │ │
│  │  │ - S3 (Gateway)                          │    │ │
│  │  └─────────────────────────────────────────┘    │ │
│  └─────────────────────────────────────────────────┘ │
│                                                        │
└────────────────────────────────────────────────────────┘
                       │
                       │ Tailscale Tunnel
                       │
                       ▼
              ┌─────────────────┐
              │ On-Prem Network │
              │ 10.10.110.0/24  │
              │                 │
              │ - Ollama hosts  │
              │ - MCP servers   │
              │ - Pi-hole       │
              │ - UniFi         │
              └─────────────────┘
```

## Configuration Files

### `.bedrock_agentcore.yaml`

Auto-configured by deployment scripts:

```yaml
agents:
  Glitch:
    aws:
      network_configuration:
        network_mode: VPC
        network_mode_config:
          subnet_ids:
            - subnet-xxx  # From GlitchVpcStack
            - subnet-yyy
          security_group_ids:
            - sg-zzz      # From GlitchAgentCoreStack
```

## Troubleshooting

### Pre-Deploy Configuration Failed

**Error:** "CloudFormation stacks not found"

**Solution:** Deploy infrastructure first:
```bash
cd infrastructure
cdk deploy GlitchVpcStack GlitchAgentCoreStack
```

### Deployment Verification Warnings

**Warning:** "Some VPC endpoints missing"

**Solution:** Verify VPC stack deployment:
```bash
cd infrastructure
pytest test/test_integration.py::TestVpcStack -v
```

### Agent Not Accessible

**Check:**
1. Tailscale route approved (10.10.110.0/24)
2. VPC endpoints exist
3. Security group rules correct

**Debug:**
```bash
cd infrastructure
pytest test/test_integration.py -v
```

### Manual Configuration Needed

If auto-configuration fails, configure manually:

```bash
# Get configuration values
aws cloudformation describe-stacks \
  --stack-name GlitchVpcStack \
  --query 'Stacks[0].Outputs[?OutputKey==`PrivateSubnetIds`].OutputValue' \
  --output text

aws cloudformation describe-stacks \
  --stack-name GlitchAgentCoreStack \
  --query 'Stacks[0].Outputs[?OutputKey==`AgentCoreSecurityGroupId`].OutputValue' \
  --output text

# Edit configuration
vim agent/.bedrock_agentcore.yaml
```

## Environment Variables

- `AWS_REGION` - AWS region (default: us-west-2)
- `AWS_PROFILE` - AWS CLI profile to use
- `AWS_ACCOUNT_ID` - AWS account ID (optional)

## Next Steps

After successful deployment:

1. **Test agent invocation:**
   ```bash
   cd agent
   agentcore invoke --message "Hello, Glitch!"
   ```

2. **View logs:**
   ```bash
   agentcore logs
   # Or in AWS Console: CloudWatch → Log Groups → /aws/bedrock-agentcore/
   ```

3. **Install MCP servers on local host (optional):**
   ```bash
   # On 10.10.110.230
   pip install unifi-mcp-server
   npm install -g mcp-pihole-server
   ```
   See [docs/mcp-servers-local-install.md](docs/mcp-servers-local-install.md)

4. **Monitor:**
   - CloudWatch Logs: Runtime logs and errors
   - CloudWatch Metrics: Invocation count, latency
   - Tailscale Admin: Network connectivity

## Additional Documentation

- [VPC Tailscale Deployment](docs/vpc-tailscale-deploy-verify.md)
- [MCP Servers Local Install](docs/mcp-servers-local-install.md)
- [Agent Scripts README](agent/scripts/README.md)
- [Infrastructure Tests](infrastructure/test/)

## Support

For issues or questions:
1. Check CloudWatch logs for runtime errors
2. Run integration tests for infrastructure verification
3. Review Tailscale admin for connectivity issues
4. Verify VPC endpoints are in "available" state
