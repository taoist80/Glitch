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

1. **Configures** env vars from SSM into `.env.deploy`
2. **Deploys** the agent with `agentcore deploy --env ...`

**That's it!** No manual configuration needed.

## Deployment Workflows

### Option 1: Step by Step (Recommended)

```bash
# Deploy infrastructure
cd infrastructure && pnpm cdk deploy --all

# Deploy agent (configure from SSM + agentcore deploy)
cd agent && make deploy
```

### Option 2: New AWS Account

Use the phased deploy script which ensures foundation stacks exist before deploying the agent:

```bash
cd infrastructure
./scripts/new-account-deploy.sh
```

This runs: Phase 1 (VPC + IAM stacks) → Phase 2 (agent deploy) → Phase 3 (remaining stacks).

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

Check runtime status after deploy:

```bash
make -C agent verify      # runs: agentcore status
make -C agent check-logs  # inspect CloudWatch runtime logs
```

## Scripts

### Infrastructure Scripts

**`infrastructure/scripts/new-account-deploy.sh`** - Phased deploy for a new AWS account
```bash
./scripts/new-account-deploy.sh [--skip-phase1] [--skip-phase2] [--dry-run]
```

**`infrastructure/scripts/enable-https-glitch-proxy.sh`** - EC2 TLS setup (certbot + Porkbun). Run on the EC2 when setting up HTTPS for the Ollama proxy.

### Agent Scripts

**`agent/scripts/deploy.sh`** - Automated deployment wrapper (called by `make deploy`)
```bash
./scripts/deploy.sh [--skip-pre-check] [-- agentcore-args...]
```

**`agent/scripts/pre-deploy-configure.py`** - Reads SSM params, writes `.env.deploy`, updates `.bedrock_agentcore.yaml`
```bash
python3 scripts/pre-deploy-configure.py
```

**DDNS:** The `ddns-updater` Lambda (deployed with `GlitchEdgeStack`) handles home IP updates automatically. The UDM-Pro calls the Lambda's Function URL every 5 minutes with a bearer token. No manual script needed.

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
