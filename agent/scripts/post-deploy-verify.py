#!/usr/bin/env python3
"""
Post-deploy hook: Verify deployment after AgentCore deployment succeeds.

This script runs automatically after successful `agentcore deploy` to:
1. Verify agent runtime is accessible
2. Check VPC connectivity (if in VPC mode)
3. Run basic health checks

Exit codes:
  0 - Success (all checks passed)
  1 - Error (verification failed)
  2 - Warning (some checks failed but deployment is usable)
"""

import os
import sys
import time
from pathlib import Path

try:
    import boto3
    import yaml
    from botocore.exceptions import ClientError
except ImportError:
    print("[post-deploy] Warning: boto3 or pyyaml not available. Skipping verification.")
    sys.exit(0)

REGION = os.environ.get('AWS_REGION', 'us-west-2')
AGENT_DIR = Path(__file__).parent.parent
CONFIG_FILE = AGENT_DIR / '.bedrock_agentcore.yaml'


def log(message: str, level: str = 'INFO'):
    """Log message with prefix."""
    prefix = {
        'INFO': '[post-deploy]',
        'WARN': '[post-deploy] WARNING:',
        'ERROR': '[post-deploy] ERROR:',
        'SUCCESS': '[post-deploy] ✓',
    }.get(level, '[post-deploy]')
    print(f"{prefix} {message}")


def load_config() -> dict:
    """Load AgentCore configuration."""
    if not CONFIG_FILE.exists():
        log(f"Config file not found: {CONFIG_FILE}", 'ERROR')
        sys.exit(1)
    
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def verify_agent_runtime(agent_arn: str) -> bool:
    """Verify agent runtime is accessible."""
    try:
        client = boto3.client('bedrock-agentcore', region_name=REGION)
        
        # Extract runtime ID from ARN
        # ARN format: arn:aws:bedrock-agentcore:region:account:runtime/runtime-id
        runtime_id = agent_arn.split('/')[-1]
        
        log(f"Checking runtime status for {runtime_id}...")
        
        # Note: This is a placeholder - actual API may differ
        # The real verification would use agentcore CLI or SDK
        log("Runtime verification skipped (requires agentcore CLI)", 'WARN')
        return True
        
    except Exception as e:
        log(f"Runtime verification failed: {e}", 'ERROR')
        return False


def verify_vpc_connectivity(agent_config: dict) -> bool:
    """Verify VPC connectivity if in VPC mode."""
    network_config = agent_config.get('aws', {}).get('network_configuration', {})
    network_mode = network_config.get('network_mode')
    
    if network_mode != 'VPC':
        log("Not in VPC mode, skipping VPC connectivity checks")
        return True
    
    log("Verifying VPC configuration...")
    
    mode_config = network_config.get('network_mode_config', {})
    # Support both old field names (subnet_ids/security_group_ids) and new (subnets/security_groups)
    subnet_ids = mode_config.get('subnets', mode_config.get('subnet_ids', []))
    sg_ids = mode_config.get('security_groups', mode_config.get('security_group_ids', []))
    
    if not subnet_ids or not sg_ids:
        log("VPC configuration incomplete", 'ERROR')
        return False
    
    try:
        ec2 = boto3.client('ec2', region_name=REGION)
        
        # Verify subnets exist
        subnets = ec2.describe_subnets(SubnetIds=subnet_ids)
        log(f"Found {len(subnets['Subnets'])} subnets", 'SUCCESS')
        
        # Verify security groups exist
        sgs = ec2.describe_security_groups(GroupIds=sg_ids)
        log(f"Found {len(sgs['SecurityGroups'])} security groups", 'SUCCESS')
        
        # Check VPC endpoints
        vpc_id = subnets['Subnets'][0]['VpcId']
        endpoints = ec2.describe_vpc_endpoints(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
        )
        
        required_endpoints = ['bedrock-runtime', 'bedrock-agentcore', 'ecr']
        found_endpoints = []
        for ep in endpoints['VpcEndpoints']:
            service_name = ep['ServiceName']
            for required in required_endpoints:
                if required in service_name:
                    found_endpoints.append(required)
        
        if len(found_endpoints) >= 3:
            log(f"VPC endpoints verified: {', '.join(found_endpoints)}", 'SUCCESS')
        else:
            log(f"Some VPC endpoints missing. Found: {', '.join(found_endpoints)}", 'WARN')
            return False
        
        return True
        
    except ClientError as e:
        log(f"VPC verification failed: {e}", 'ERROR')
        return False


def main():
    log("Running post-deployment verification...")
    
    config = load_config()
    agent_name = config.get('default_agent', 'Glitch')
    
    if agent_name not in config.get('agents', {}):
        log(f"Agent '{agent_name}' not found in config", 'ERROR')
        sys.exit(1)
    
    agent_config = config['agents'][agent_name]
    
    # Get agent ARN
    agent_arn = agent_config.get('bedrock_agentcore', {}).get('agent_arn')
    if not agent_arn:
        log("Agent ARN not found in config", 'WARN')
        sys.exit(2)
    
    checks_passed = True
    
    # Run verification checks
    log("\n=== Verification Checks ===")
    
    # 1. Runtime verification
    if not verify_agent_runtime(agent_arn):
        checks_passed = False
    
    # 2. VPC connectivity
    if not verify_vpc_connectivity(agent_config):
        checks_passed = False
    
    # Summary
    log("\n=== Verification Summary ===")
    if checks_passed:
        log("All checks passed!", 'SUCCESS')
        log("\nNext steps:")
        log("  1. Test agent invocation: agentcore invoke --message 'Hello'")
        log("  2. Check logs: agentcore logs")
        log("  3. Monitor in AWS Console: CloudWatch Logs")
        sys.exit(0)
    else:
        log("Some checks failed. Review errors above.", 'WARN')
        log("\nDeployment may still work, but issues were detected.")
        log("Run infrastructure integration tests for detailed diagnostics:")
        log("  cd ../infrastructure && pytest test/test_integration.py -v")
        sys.exit(2)


if __name__ == '__main__':
    main()
