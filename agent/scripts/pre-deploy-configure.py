#!/usr/bin/env python3
"""
Pre-deploy hook: Auto-configure VPC settings before AgentCore deployment.

This script runs automatically before `agentcore deploy` to:
1. Fetch VPC subnet IDs, security group ID, and IAM role ARNs from SSM Parameters
2. Fetch Tailscale EC2 private IP from CloudFormation stack outputs
3. Update .bedrock_agentcore.yaml with correct configuration
4. Validate configuration before proceeding

SSM Parameters (set by GlitchFoundationStack):
  /glitch/vpc/id                    - VPC ID
  /glitch/vpc/private-subnet-ids    - Comma-separated private subnet IDs
  /glitch/security-groups/agentcore - AgentCore security group ID
  /glitch/iam/runtime-role-arn      - Runtime role ARN
  /glitch/iam/codebuild-role-arn    - CodeBuild role ARN

CloudFormation Outputs (from GlitchTailscaleStack):
  PrivateIp                         - Tailscale EC2 VPC private IP (for Ollama proxy)

Environment Variables set automatically:
  GLITCH_OLLAMA_PROXY_HOST          - Tailscale EC2 private IP (required for VPC→on-prem routing)
  GLITCH_OLLAMA_TIMEOUT             - Timeout for Ollama requests (default: 180s)
  GLITCH_MISTRAL_TIMEOUT            - Timeout for Mistral requests (default: 180s)

Exit codes:
  0 - Success (configuration updated or already correct)
  1 - Error (missing SSM parameters or invalid configuration)
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

# SSM Parameter names (must match SSM_PARAMS in infrastructure/lib/stack.ts)
SSM_VPC_ID = '/glitch/vpc/id'
SSM_PRIVATE_SUBNET_IDS = '/glitch/vpc/private-subnet-ids'
SSM_AGENTCORE_SG_ID = '/glitch/security-groups/agentcore'
SSM_RUNTIME_ROLE_ARN = '/glitch/iam/runtime-role-arn'
SSM_CODEBUILD_ROLE_ARN = '/glitch/iam/codebuild-role-arn'

# Fallback: CloudFormation stack names (for backward compatibility)
FOUNDATION_STACK_NAME = 'GlitchFoundationStack'
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


def get_ssm_parameter(ssm_client, name: str) -> str | None:
    """Get a parameter value from SSM Parameter Store."""
    try:
        response = ssm_client.get_parameter(Name=name)
        return response['Parameter']['Value']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            return None
        raise


def get_stack_outputs(cfn_client, stack_name: str) -> dict:
    """Get outputs from a CloudFormation stack (fallback)."""
    try:
        response = cfn_client.describe_stacks(StackName=stack_name)
        outputs = {
            o['OutputKey']: o['OutputValue']
            for o in response['Stacks'][0].get('Outputs', [])
        }
        return outputs
    except ClientError as e:
        if e.response['Error']['Code'] == 'ValidationError':
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
    
    log("VPC mode enabled. Fetching configuration from SSM Parameters...")
    
    try:
        ssm_client = boto3.client('ssm', region_name=REGION)
        cfn_client = boto3.client('cloudformation', region_name=REGION)
        
        # Fetch from SSM Parameters (primary source)
        subnet_ids_str = get_ssm_parameter(ssm_client, SSM_PRIVATE_SUBNET_IDS)
        security_group_id = get_ssm_parameter(ssm_client, SSM_AGENTCORE_SG_ID)
        execution_role_arn = get_ssm_parameter(ssm_client, SSM_RUNTIME_ROLE_ARN)
        codebuild_role_arn = get_ssm_parameter(ssm_client, SSM_CODEBUILD_ROLE_ARN)
        
        if not subnet_ids_str or not security_group_id:
            log("SSM Parameters not found. Please deploy GlitchFoundationStack first:", 'ERROR')
            log("  cd infrastructure && cdk deploy GlitchFoundationStack", 'ERROR')
            sys.exit(1)
        
        subnet_ids = subnet_ids_str.split(',')
        
        log(f"Found VPC configuration from SSM:")
        log(f"  Subnet IDs: {subnet_ids}")
        log(f"  Security Group ID: {security_group_id}")
        if execution_role_arn:
            log(f"  Execution Role ARN: {execution_role_arn}")
        if codebuild_role_arn:
            log(f"  CodeBuild Role ARN: {codebuild_role_arn}")
        
        # Update config with correct field names
        if 'network_mode_config' not in network_config:
            network_config['network_mode_config'] = {}
        
        network_config['network_mode_config']['subnets'] = subnet_ids
        network_config['network_mode_config']['security_groups'] = [security_group_id]
        
        # Remove old incorrect field names if present
        network_config['network_mode_config'].pop('subnet_ids', None)
        network_config['network_mode_config'].pop('security_group_ids', None)
        
        if execution_role_arn:
            agent_config['aws']['execution_role'] = execution_role_arn
            log("Execution role set from SSM", 'SUCCESS')

        if codebuild_role_arn:
            if 'codebuild' not in agent_config:
                agent_config['codebuild'] = {}
            agent_config['codebuild']['execution_role'] = codebuild_role_arn
            log("CodeBuild execution_role set from SSM", 'SUCCESS')

        # Ollama/Mistral proxy: set GLITCH_OLLAMA_PROXY_HOST from Tailscale EC2 private IP
        # Also set default timeouts for Ollama requests (can be overridden via env)
        tailscale_outputs = get_stack_outputs(cfn_client, TAILSCALE_STACK_NAME)
        private_ip = tailscale_outputs.get('PrivateIp')
        if 'aws' not in agent_config:
            agent_config['aws'] = {}
        if 'environment_variables' not in agent_config['aws']:
            agent_config['aws']['environment_variables'] = {}
        env_vars = agent_config['aws']['environment_variables']
        
        if private_ip:
            env_vars['GLITCH_OLLAMA_PROXY_HOST'] = private_ip
            log(f"Ollama proxy host set to {private_ip}", 'SUCCESS')
        else:
            log(f"Tailscale stack not found; GLITCH_OLLAMA_PROXY_HOST unchanged", 'WARN')
        
        # Set default timeouts if not already configured
        if 'GLITCH_OLLAMA_TIMEOUT' not in env_vars:
            env_vars['GLITCH_OLLAMA_TIMEOUT'] = '180'
            log("Ollama timeout set to 180s (default)", 'SUCCESS')
        if 'GLITCH_MISTRAL_TIMEOUT' not in env_vars:
            env_vars['GLITCH_MISTRAL_TIMEOUT'] = '180'
            log("Mistral timeout set to 180s (default)", 'SUCCESS')
        
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
