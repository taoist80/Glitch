# AgentCore Deployment Scripts

This directory contains deployment automation scripts that integrate VPC configuration and verification with AgentCore deployment.

## ⚠️ IMPORTANT: Always Use `make deploy`

**Do NOT run `agentcore deploy` directly.** Always use one of these commands:

```bash
# From the agent/ directory:
make deploy           # Full workflow (recommended)
./scripts/deploy.sh   # Same as above
```

Running `agentcore deploy` directly **bypasses** the pre-deploy configuration script, which means:
- `GLITCH_OLLAMA_PROXY_HOST` won't be set (Ollama calls will fail)
- VPC configuration may be stale
- Timeouts won't be configured

## Quick Start

```bash
cd agent

# Full deployment workflow (recommended)
make deploy

# Or using the script directly
./scripts/deploy.sh
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

Automatically fetches VPC configuration from SSM Parameters and CloudFormation, then updates `.bedrock_agentcore.yaml`.

**What it configures:**

| Setting | Source | Purpose |
|---------|--------|---------|
| `subnets` | SSM `/glitch/vpc/private-subnet-ids` | VPC subnets for agent container |
| `security_groups` | SSM `/glitch/security-groups/agentcore` | Security group for agent container |
| `execution_role` | SSM `/glitch/iam/runtime-role-arn` | IAM role for agent runtime |
| `codebuild.execution_role` | SSM `/glitch/iam/codebuild-role-arn` | IAM role for CodeBuild |
| `GLITCH_OLLAMA_PROXY_HOST` | `GlitchTailscaleStack.PrivateIp` | VPC IP of nginx proxy for Ollama |
| `GLITCH_OLLAMA_TIMEOUT` | Default `180` | Timeout for Ollama requests |
| `GLITCH_MISTRAL_TIMEOUT` | Default `180` | Timeout for Mistral requests |

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

The scripts wrap `agentcore` CLI with pre/post hooks:

```bash
# ✅ CORRECT: Use the wrapper script
cd agent
make deploy
# or: ./scripts/deploy.sh

# ❌ WRONG: Direct agentcore deploy bypasses configuration
# agentcore deploy   # DON'T DO THIS
```

If you need to pass arguments to `agentcore deploy`:
```bash
./scripts/deploy.sh -- --force
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
