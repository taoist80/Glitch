# VPC Tailscale Deployment and Verification

Follow this order after implementing the [VPC Tailscale MCP Routing](.cursor/plans/vpc_tailscale_mcp_routing_1b7b125b.plan.md) plan.

## Deployment order

1. **Deploy VPC stack** (adds VPC endpoints: bedrock-runtime, bedrock-agentcore)
   ```bash
   cdk deploy GlitchVpcStack
   ```

2. **Deploy Tailscale stack** (route tables, ENI routes for 10.10.110.0/24)
   ```bash
   cdk deploy GlitchTailscaleStack
   ```

3. **Approve routes in Tailscale**
   - Open [admin.tailscale.com](https://admin.tailscale.com)
   - Approve the **10.10.110.0/24** subnet route advertised by the AWS Tailscale node (if not auto-approved)

4. **Configure AgentCore for VPC**
   - Get private subnet IDs from `GlitchVpcStack` output **PrivateSubnetIds** (comma-separated).
   - Get security group ID from `GlitchAgentCoreStack` output **AgentCoreSecurityGroupId**.
   - Run:
     ```bash
     cd agent && agentcore configure
     ```
   - Set network mode to VPC and provide the subnet IDs and security group ID when prompted (or edit `.bedrock_agentcore.yaml` `network_mode_config` with `subnet_ids` and `security_group_ids`).

5. **Redeploy AgentCore runtime**
   ```bash
   cd agent && agentcore deploy
   ```

6. **MCP servers (optional)**  
   Install UniFi and Pi-hole MCP servers on 10.10.110.230 per [docs/mcp-servers-local-install.md](mcp-servers-local-install.md).

## Verification

- **Tailscale admin:** Route **10.10.110.0/24** is approved for the AWS node.
- **VPC route tables:** Each private subnet route table has a route **10.10.110.0/24 → ENI** of the Tailscale instance.
- **Ollama:** From the Glitch UI or Telegram, confirm Ollama hosts (e.g. 10.10.110.202, 10.10.110.137) are reachable and health checks pass.
- **Bedrock:** Send a message; Claude (Bedrock) should respond.
- **Memory:** AgentCore Memory events are created (check observability/logs).
- **UniFi / Pi-hole MCP:** If installed on 10.10.110.230, confirm `unifi-mcp-server` and `mcp-pihole-server` run and respond.
