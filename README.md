# AgentCore Glitch - Hybrid AI Agent Infrastructure

A sophisticated hybrid AI agent system combining AWS AgentCore Runtime with on-premises Ollama models via Tailscale for secure, cost-effective AI operations.

## Architecture

Glitch is a tiered agent orchestrator that:
- **Tier 1 (Primary)**: Claude Sonnet 4.5 in AWS AgentCore Runtime
- **Tier 2 (Escalation)**: Claude Sonnet 4.6 for complex tasks
- **Tier 3 (Escalation)**: Claude Opus 4.5 for highest complexity
- **Local Subagents**: Ollama models (LLaVA for vision, Llama for chat) via Tailscale

### Key Features

- **Hybrid Execution**: Local-first approach for cost optimization and privacy
- **Intelligent Escalation**: Automatic tier escalation based on confidence, context, and complexity
- **Secure Connectivity**: Tailscale mesh network for private AWS-to-on-prem communication
- **Memory Management**: Three-layer memory (Active Window + Structured State + AgentCore Memory)
- **Full Observability**: OpenTelemetry instrumentation with CloudWatch integration

## Project Structure

```
AgentCore-Glitch/
├── infrastructure/          # CDK TypeScript infrastructure
│   ├── bin/app.ts          # CDK app entry point
│   ├── lib/
│   │   ├── vpc-stack.ts           # VPC with NAT and endpoints
│   │   ├── secrets-stack.ts       # Secrets Manager
│   │   ├── tailscale-stack.ts     # EC2 Tailscale connector
│   │   └── agentcore-stack.ts     # AgentCore Runtime resources
│   └── package.json
├── agent/                   # Python Strands agent
│   ├── src/
│   │   ├── glitch/
│   │   │   ├── agent.py           # Main orchestrator
│   │   │   ├── tools/             # Ollama & network tools
│   │   │   ├── routing/           # Model routing logic
│   │   │   ├── memory/            # Memory management
│   │   │   ├── telemetry.py       # OTEL configuration
│   │   │   └── server.py          # HTTP server (placeholder)
│   │   └── main.py                # Entry point
│   ├── Dockerfile
│   ├── requirements.txt
│   └── pyproject.toml
└── README.md
```

## Prerequisites

### AWS Account
- Account ID: 999776382415
- Region: us-west-2
- AWS CLI configured with appropriate credentials

### Local Environment
- Node.js 18+ (for CDK)
- pnpm package manager
- Python 3.12+
- Docker (for building agent container)
- AWS CDK CLI: `npm install -g aws-cdk`

### On-Premises Infrastructure
- Tailscale subnet router at 10.10.100.230
- Ollama chat host at 10.10.110.202:11434
- Ollama vision host (LLaVA) at 10.10.110.137:11434
- Pi-hole DNS at 10.10.100.70 (optional)

## Deployment

### Step 1: Store Tailscale Auth Key

Generate an ephemeral auth key from your Tailscale admin console and store it:

```bash
aws secretsmanager create-secret \
    --name glitch/tailscale-auth-key \
    --description "Ephemeral Tailscale auth key for EC2 connector" \
    --secret-string "tskey-auth-xxxxx" \
    --region us-west-2
```

### Step 2: Deploy CDK Infrastructure

```bash
cd infrastructure
pnpm install
pnpm build

# Bootstrap CDK (first time only)
npx cdk bootstrap aws://999776382415/us-west-2

# Deploy all stacks
pnpm deploy
```

This creates:
- VPC with public/private ISOLATED subnets (no NAT Gateway)
- VPC endpoints in single AZ (cost optimized)
- Secrets Manager for Tailscale and API keys
- EC2 t4g.nano ARM64 running Tailscale connector (public subnet)
- ECR repository for agent container
- IAM roles for AgentCore Runtime
- Security groups for VPC mode

### Step 3: Approve Tailscale Routes

After the EC2 instance joins your tailnet:

1. Go to Tailscale admin console
2. Find the device tagged `aws-agent`
3. Approve advertised routes to on-prem /32 addresses:
   - 10.10.110.202/32 (Ollama chat)
   - 10.10.110.137/32 (Ollama vision)
   - 10.10.100.70/32 (Pi-hole, optional)

### Step 4: Build and Push Agent Container

```bash
cd agent

# Build the container
docker build -t glitch-agent .

# Login to ECR
aws ecr get-login-password --region us-west-2 | \
    docker login --username AWS --password-stdin \
    999776382415.dkr.ecr.us-west-2.amazonaws.com

# Tag and push
docker tag glitch-agent:latest \
    999776382415.dkr.ecr.us-west-2.amazonaws.com/glitch-agent:latest
    
docker push 999776382415.dkr.ecr.us-west-2.amazonaws.com/glitch-agent:latest
```

### Step 5: Create AgentCore Runtime

Get the VPC configuration from CDK outputs:

```bash
aws cloudformation describe-stacks \
    --stack-name GlitchAgentCoreStack \
    --query 'Stacks[0].Outputs[?OutputKey==`VpcConfigForAgentCore`].OutputValue' \
    --output text
```

Create the AgentCore Runtime via AWS Console or CLI with:
- Container image from ECR
- VPC mode with subnets and security group from outputs
- IAM role from `GlitchAgentRuntimeRoleArn` output

## Local Development

### Test Agent Locally

```bash
cd agent
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows
pip install -r requirements.txt

# Set environment variables
export AWS_REGION=us-west-2
export GLITCH_MODE=interactive
export OTEL_CONSOLE_ENABLED=true

# Run in interactive mode
python -m src.main
```

### Test Connectivity

```python
from glitch.agent import create_glitch_agent
import asyncio

agent = create_glitch_agent()
connectivity = asyncio.run(agent.check_connectivity())
print(connectivity)
```

## Configuration

### Environment Variables

- `AWS_REGION`: AWS region (default: us-west-2)
- `GLITCH_SESSION_ID`: Session identifier
- `GLITCH_MEMORY_ID`: AgentCore Memory identifier
- `GLITCH_MODE`: `interactive` or `server`
- `OTEL_EXPORTER_OTLP_ENDPOINT`: OTLP endpoint URL
- `OTEL_SERVICE_NAME`: Service name for traces
- `OTEL_CONSOLE_ENABLED`: Enable console exporter for debugging

### Model Configuration

Edit `agent/src/glitch/routing/model_router.py` to configure:
- Task routing rules
- Escalation chains
- Confidence thresholds
- Context usage limits

### Memory Settings

Edit `agent/src/glitch/memory/sliding_window.py` to configure:
- Window size (default: 20 turns)
- Compression threshold (default: 70%)
- Structured memory schema

## Security Considerations

1. **Secrets Management**: All sensitive values in AWS Secrets Manager
2. **IAM Least Privilege**: Minimal permissions for each component
3. **Network Isolation**:
   - AgentCore in private subnets with VPC mode
   - EC2 Tailscale in private subnet with NAT
   - /32 route advertisement only (no broad subnet exposure)
4. **Tailscale Security**:
   - Ephemeral auth keys (single-use, time-limited)
   - ACL rules restricting `aws-agent` tag to specific routes
5. **No SSH Access**: Use AWS Systems Manager Session Manager

## Monitoring

### CloudWatch Logs

Agent logs are sent to CloudWatch Logs at:
- `/aws/bedrock/agentcore/runtime/{runtime-id}`

### OTEL Traces

Traces include:
- `model_used`, `input_tokens`, `output_tokens`, `latency_ms`
- `escalation_reason`, `context_usage`, `compression_ratio`
- `tool_calls_count`, `tool_name`, `execution_status`

### Metrics Dashboard

Key metrics to monitor:
- Escalation frequency and reasons
- Context window usage
- Tool execution latency
- Local vs cloud execution ratio
- AgentCore Memory operations

## Troubleshooting

### Tailscale Connectivity Issues

Check EC2 instance logs:
```bash
aws ssm start-session --target <instance-id>
sudo journalctl -u tailscaled
tailscale status
```

### AgentCore Runtime Issues

Check CloudWatch Logs for the runtime:
```bash
aws logs tail /aws/bedrock/agentcore/runtime/{runtime-id} --follow
```

### Ollama Connectivity

From the EC2 instance:
```bash
curl http://10.10.110.202:11434/api/tags
curl http://10.10.110.137:11434/api/tags
```

## Roadmap

### Current Iteration: Core Infrastructure ✅
- [x] VPC and networking
- [x] Tailscale EC2 connector
- [x] AgentCore Runtime resources
- [x] Glitch orchestrator
- [x] Ollama tool integration
- [x] Memory management
- [x] Model routing and escalation

### Next Iterations

1. **Network Integration**
   - Unifi network management
   - Protect camera monitoring
   - Pi-hole DNS configuration

2. **Enhanced Features**
   - AgentCore HTTP protocol server
   - WebSocket streaming
   - A2A protocol for multi-agent
   - Custom MCP servers

3. **Production Hardening**
   - Multi-AZ NAT Gateways
   - Enhanced monitoring dashboards
   - Automated backups
   - Disaster recovery

## Cost Optimization

This infrastructure has been heavily optimized for cost:

- **No NAT Gateway**: Tailscale EC2 in public subnet (saves $32/mo)
- **ARM64 Graviton**: t4g.nano instead of t3.micro (saves $3.79/mo)
- **Single AZ endpoints**: Interface endpoints in one AZ (saves $43.80/mo)
- **No proxy complexity**: Direct Tailscale routing (saves operational overhead)
- **Local-first execution**: Ollama for simple tasks
- **Tiered escalation**: Reserve expensive models for complex tasks
- **Ephemeral sessions**: AgentCore Memory handles persistence

**Monthly Cost: ~$47.60** (was ~$127 before optimization)

## License

MIT

## Support

For issues or questions, please open an issue in the repository.
