# AgentCore Deployment Scripts

This directory contains deployment automation scripts that integrate VPC configuration and verification with AgentCore deployment.

## Quick Start

```bash
# Full deployment workflow (recommended)
./scripts/deploy.sh

# Or using make
make deploy
```

## Scripts

### `deploy.sh` - Unified Deployment Wrapper

Main deployment script that orchestrates the complete workflow:

1. **Pre-deploy**: Auto-configure VPC settings from CloudFormation
2. **Deploy**: Run `agentcore deploy`
3. **Post-deploy**: Verify deployment and connectivity

**Usage:**
```bash
./scripts/deploy.sh [options] [-- agentcore-args...]

Options:
  --skip-pre-check     Skip pre-deploy configuration
  --skip-post-check    Skip post-deploy verification
  --help               Show help message

Examples:
  ./scripts/deploy.sh                        # Full workflow
  ./scripts/deploy.sh --skip-post-check      # Skip verification
  ./scripts/deploy.sh -- --force             # Pass --force to agentcore
```

### `pre-deploy-configure.py` - VPC Auto-Configuration

Automatically fetches VPC configuration from CloudFormation and updates `.bedrock_agentcore.yaml`.

**What it does:**
- Reads subnet IDs from `GlitchVpcStack` outputs
- Reads security group ID from `GlitchAgentCoreStack` outputs
- Updates `network_mode_config` in the agent configuration
- Skips if already configured or not in VPC mode

**Usage:**
```bash
python3 scripts/pre-deploy-configure.py [--dry-run] [--region REGION]
```

### `post-deploy-verify.py` - Deployment Verification

Runs post-deployment checks to verify the agent is properly configured.

**What it checks:**
- VPC configuration (subnets, security groups)
- VPC endpoints (Bedrock, ECR, CloudWatch)
- Network connectivity (if applicable)

**Usage:**
```bash
python3 scripts/post-deploy-verify.py
```

## Makefile Targets

```bash
make deploy         # Full deployment workflow
make deploy-only    # Deploy without pre/post checks
make configure      # Run VPC configuration only
make verify         # Run verification only
make test           # Run agent unit tests
make clean          # Clean build artifacts
```

## Environment Variables

- `AWS_REGION` - AWS region (default: us-west-2)
- `AWS_PROFILE` - AWS profile to use
- `AWS_ACCOUNT_ID` - AWS account ID (optional)

## Integration with AgentCore CLI

The scripts work seamlessly with `agentcore` CLI:

```bash
# Standard deployment (manual)
cd agent
agentcore deploy

# Automated deployment (with pre/post checks)
cd agent
./scripts/deploy.sh
```

## Workflow Diagram

```
┌─────────────────────────────────────────┐
│  ./scripts/deploy.sh                    │
└─────────────────┬───────────────────────┘
                  │
      ┌───────────┴───────────┐
      │                       │
      ▼                       ▼
┌──────────────┐    ┌──────────────────┐
│ Pre-deploy   │    │ Skip if:         │
│ Configure    │───▶│ - Not VPC mode   │
│              │    │ - Already config │
└──────┬───────┘    └──────────────────┘
       │
       │ Updates .bedrock_agentcore.yaml
       │
       ▼
┌──────────────────┐
│ agentcore deploy │
└──────┬───────────┘
       │
       ▼
┌──────────────────┐
│ Post-deploy      │
│ Verify           │
│                  │
│ ✓ VPC config    │
│ ✓ Endpoints     │
│ ✓ Connectivity  │
└──────────────────┘
```

## Exit Codes

All scripts follow these exit code conventions:

- `0` - Success
- `1` - Error (deployment should abort)
- `2` - Warning (deployment can continue but issues detected)

## Troubleshooting

### "CloudFormation stacks not found"

Deploy the infrastructure first:
```bash
cd infrastructure
cdk deploy GlitchVpcStack GlitchAgentCoreStack
```

### "Agent not found in config"

Ensure your `.bedrock_agentcore.yaml` has a `default_agent` set:
```yaml
default_agent: Glitch
agents:
  Glitch:
    # ... agent configuration
```

### "VPC configuration incomplete"

Run the configuration script manually:
```bash
python3 scripts/pre-deploy-configure.py
```

Check the updated configuration:
```bash
cat .bedrock_agentcore.yaml | grep -A 5 network_mode_config
```

### "boto3 or pyyaml not available"

Install Python dependencies:
```bash
pip install boto3 pyyaml
```

## Manual Configuration

If you prefer manual configuration:

1. Get CloudFormation outputs:
```bash
aws cloudformation describe-stacks \
  --stack-name GlitchVpcStack \
  --query 'Stacks[0].Outputs'

aws cloudformation describe-stacks \
  --stack-name GlitchAgentCoreStack \
  --query 'Stacks[0].Outputs'
```

2. Update `.bedrock_agentcore.yaml`:
```yaml
agents:
  Glitch:
    aws:
      network_configuration:
        network_mode: VPC
        network_mode_config:
          subnet_ids:
            - subnet-xxx
            - subnet-yyy
          security_group_ids:
            - sg-zzz
```

3. Deploy:
```bash
agentcore deploy
```
