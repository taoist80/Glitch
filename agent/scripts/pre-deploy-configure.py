#!/usr/bin/env python3
"""
Pre-deploy hook: Auto-configure VPC settings before AgentCore deployment.

This script runs automatically before `agentcore deploy` to:
1. Fetch VPC subnet IDs and security group ID from CloudFormation
2. Update .bedrock_agentcore.yaml with correct field names
3. Validate configuration before proceeding

Exit codes:
  0 - Success (configuration updated or already correct)
  1 - Error (missing CloudFormation stacks or invalid configuration)
  2 - Configuration update skipped (not in VPC mode)
"""

import os
import sys
from pathlib import Path

try:
    import boto3
    import yaml
    from botocore.exceptions import ClientError
except ImportError:
    print("Warning: boto3 or pyyaml not available. Skipping VPC auto-configuration.")
    print("To enable auto-configuration, install: pip install boto3 pyyaml")
    sys.exit(0)

REGION = os.environ.get('AWS_REGION', 'us-west-2')
VPC_STACK_NAME = 'GlitchVpcStack'
AGENTCORE_STACK_NAME = 'GlitchAgentCoreStack'
TAILSCALE_STACK_NAME = 'GlitchTailscaleStack'

AGENT_DIR = Path(__file__).parent.parent
CONFIG_FILE = AGENT_DIR / '.bedrock_agentcore.yaml'


def log(message: str, level: str = 'INFO'):
    """Log message with prefix."""
    prefix = {
        'INFO': '[pre-deploy]',
        'WARN': '[pre-deploy] WARNING:',
        'ERROR': '[pre-deploy] ERROR:',
        'SUCCESS': '[pre-deploy] ✓',
    }.get(level, '[pre-deploy]')
    print(f"{prefix} {message}")


def get_stack_outputs(cfn_client, stack_name: str) -> dict:
    """Get outputs from a CloudFormation stack."""
    try:
        response = cfn_client.describe_stacks(StackName=stack_name)
        outputs = {
            o['OutputKey']: o['OutputValue']
            for o in response['Stacks'][0].get('Outputs', [])
        }
        return outputs
    except ClientError as e:
        if e.response['Error']['Code'] == 'ValidationError':
            log(f"Stack {stack_name} not found", 'WARN')
            return {}
        raise


def load_config() -> dict:
    """Load AgentCore configuration."""
    if not CONFIG_FILE.exists():
        log(f"Config file not found: {CONFIG_FILE}", 'ERROR')
        sys.exit(1)
    
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def save_config(config: dict):
    """Save AgentCore configuration with explicit flush."""
    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())


def main():
    log("Checking VPC configuration...")
    
    # Load current config
    config = load_config()
    agent_name = config.get('default_agent', 'Glitch')
    
    if agent_name not in config.get('agents', {}):
        log(f"Agent '{agent_name}' not found in config", 'ERROR')
        sys.exit(1)
    
    agent_config = config['agents'][agent_name]
    network_config = agent_config.get('aws', {}).get('network_configuration', {})
    network_mode = network_config.get('network_mode')
    
    # Skip if not in VPC mode
    if network_mode != 'VPC':
        log(f"Network mode is '{network_mode}', not VPC. Skipping auto-configuration.")
        sys.exit(0)
    
    # Check if already configured with CORRECT field names (subnets, security_groups)
    # Always update security group in case it changed (e.g. stack recreated)
    mode_config = network_config.get('network_mode_config', {})
    has_subnets = bool(mode_config.get('subnets'))
    has_security_groups = bool(mode_config.get('security_groups'))
    
    if has_subnets and has_security_groups:
        log("VPC configuration already present. Checking if security group needs update...")
    else:
        log("VPC mode enabled but configuration missing or using wrong field names. Fetching from CloudFormation...")
    
    # Fetch from CloudFormation
    try:
        cfn_client = boto3.client('cloudformation', region_name=REGION)
        
        vpc_outputs = get_stack_outputs(cfn_client, VPC_STACK_NAME)
        
        if not vpc_outputs:
            log("VpcStack not found. Please deploy infrastructure first:", 'ERROR')
            log("  cd infrastructure && cdk deploy GlitchVpcStack", 'ERROR')
            sys.exit(1)
        
        subnet_ids = vpc_outputs.get('PrivateSubnetIds', '').split(',')
        # Security group now comes from VpcStack (moved to avoid circular dependencies)
        # Output key is AgentCoreSecurityGroupId (export name is GlitchAgentCoreSecurityGroupIdFromVpc)
        security_group_id = vpc_outputs.get('AgentCoreSecurityGroupId')
        
        # Execution role comes from AgentCoreStack (optional - might not be deployed yet)
        agentcore_outputs = get_stack_outputs(cfn_client, AGENTCORE_STACK_NAME)
        execution_role_arn = agentcore_outputs.get('AgentRuntimeRoleArn') if agentcore_outputs else None
        
        if not subnet_ids or not subnet_ids[0]:
            log("PrivateSubnetIds not found in VPC stack outputs", 'ERROR')
            sys.exit(1)
        
        if not security_group_id:
            log("AgentCoreSecurityGroupId not found in AgentCore stack outputs", 'ERROR')
            sys.exit(1)
        
        log(f"Found VPC configuration:")
        log(f"  Subnet IDs: {subnet_ids}")
        log(f"  Security Group ID: {security_group_id}")
        if execution_role_arn:
            log(f"  Execution Role ARN: {execution_role_arn}")
        
        # Update config with CORRECT field names (subnets, security_groups)
        # The toolkit expects these exact names, not subnet_ids/security_group_ids
        if 'network_mode_config' not in network_config:
            network_config['network_mode_config'] = {}
        
        # Check if security group changed
        current_sg = mode_config.get('security_groups', [])
        if current_sg and current_sg[0] != security_group_id:
            log(f"Security group changed: {current_sg[0]} → {security_group_id}")
        
        network_config['network_mode_config']['subnets'] = subnet_ids
        network_config['network_mode_config']['security_groups'] = [security_group_id]
        
        # Remove old incorrect field names if present
        network_config['network_mode_config'].pop('subnet_ids', None)
        network_config['network_mode_config'].pop('security_group_ids', None)
        
        if execution_role_arn:
            agent_config['aws']['execution_role'] = execution_role_arn
        
        # Ollama/Mistral proxy: set GLITCH_OLLAMA_PROXY_HOST from Tailscale EC2 private IP
        tailscale_outputs = get_stack_outputs(cfn_client, TAILSCALE_STACK_NAME)
        private_ip = tailscale_outputs.get('PrivateIp')
        if private_ip:
            if 'aws' not in agent_config:
                agent_config['aws'] = {}
            if 'environment_variables' not in agent_config['aws']:
                agent_config['aws']['environment_variables'] = {}
            agent_config['aws']['environment_variables']['GLITCH_OLLAMA_PROXY_HOST'] = private_ip
            log(f"Ollama proxy host set to {private_ip} (from {TAILSCALE_STACK_NAME})", 'SUCCESS')
        else:
            log(f"{TAILSCALE_STACK_NAME} not found or no PrivateIp output; GLITCH_OLLAMA_PROXY_HOST unchanged", 'WARN')
        
        save_config(config)
        log("VPC configuration updated successfully", 'SUCCESS')
        
    except ClientError as e:
        log(f"AWS API error: {e}", 'ERROR')
        sys.exit(1)
    except Exception as e:
        log(f"Unexpected error: {e}", 'ERROR')
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
