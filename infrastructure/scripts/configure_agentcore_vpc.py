#!/usr/bin/env python3
"""
Programmatically configure AgentCore VPC settings from CloudFormation outputs.

This script eliminates the need for manual `agentcore configure` input by:
1. Reading VPC subnet IDs and security group ID from CloudFormation stack outputs
2. Updating the .bedrock_agentcore.yaml file directly

Usage:
    python scripts/configure_agentcore_vpc.py
    # Or with specific AWS profile:
    AWS_PROFILE=your-profile python scripts/configure_agentcore_vpc.py
    # Dry run (show what would be changed):
    python scripts/configure_agentcore_vpc.py --dry-run
"""

import argparse
import json
import os
import sys
from pathlib import Path

import boto3
import yaml
from botocore.exceptions import ClientError

REGION = os.environ.get('AWS_REGION', 'us-west-2')

VPC_STACK_NAME = 'GlitchVpcStack'
AGENTCORE_STACK_NAME = 'GlitchAgentCoreStack'

AGENT_DIR = Path(__file__).parent.parent.parent / 'agent'
CONFIG_FILE = AGENT_DIR / '.bedrock_agentcore.yaml'


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
        print(f"Error: Could not get outputs from {stack_name}: {e}")
        sys.exit(1)


def load_agentcore_config() -> dict:
    """Load the AgentCore configuration file."""
    if not CONFIG_FILE.exists():
        print(f"Error: Config file not found: {CONFIG_FILE}")
        sys.exit(1)
    
    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


def save_agentcore_config(config: dict) -> None:
    """Save the AgentCore configuration file."""
    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(
        description='Configure AgentCore VPC settings from CloudFormation outputs'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be changed without modifying files'
    )
    parser.add_argument(
        '--agent',
        default='Glitch',
        help='Agent name in config (default: Glitch)'
    )
    parser.add_argument(
        '--region',
        default=REGION,
        help=f'AWS region (default: {REGION})'
    )
    args = parser.parse_args()

    print(f"Fetching CloudFormation outputs from {args.region}...")
    cfn_client = boto3.client('cloudformation', region_name=args.region)

    vpc_outputs = get_stack_outputs(cfn_client, VPC_STACK_NAME)
    agentcore_outputs = get_stack_outputs(cfn_client, AGENTCORE_STACK_NAME)

    subnet_ids = vpc_outputs.get('PrivateSubnetIds', '').split(',')
    security_group_id = agentcore_outputs.get('AgentCoreSecurityGroupId')
    execution_role_arn = agentcore_outputs.get('AgentRuntimeRoleArn')

    if not subnet_ids or not subnet_ids[0]:
        print("Error: PrivateSubnetIds not found in VPC stack outputs")
        sys.exit(1)
    
    if not security_group_id:
        print("Error: AgentCoreSecurityGroupId not found in AgentCore stack outputs")
        sys.exit(1)

    print(f"\nFound configuration:")
    print(f"  Subnet IDs: {subnet_ids}")
    print(f"  Security Group ID: {security_group_id}")
    if execution_role_arn:
        print(f"  Execution Role ARN: {execution_role_arn}")

    config = load_agentcore_config()
    
    if args.agent not in config.get('agents', {}):
        print(f"Error: Agent '{args.agent}' not found in config")
        sys.exit(1)

    agent_config = config['agents'][args.agent]
    
    current_network_config = agent_config.get('aws', {}).get('network_configuration', {})
    current_mode_config = current_network_config.get('network_mode_config')
    
    # Toolkit and AWS API expect subnets and security_groups (not subnet_ids/security_group_ids)
    new_mode_config = {
        'subnets': subnet_ids,
        'security_groups': [security_group_id],
    }

    print(f"\nCurrent network_mode_config: {current_mode_config}")
    print(f"New network_mode_config: {new_mode_config}")

    if args.dry_run:
        print("\n[DRY RUN] Would update config file but not making changes")
        return

    if 'aws' not in agent_config:
        agent_config['aws'] = {}
    if 'network_configuration' not in agent_config['aws']:
        agent_config['aws']['network_configuration'] = {}
    
    agent_config['aws']['network_configuration']['network_mode'] = 'VPC'
    agent_config['aws']['network_configuration']['network_mode_config'] = new_mode_config
    
    if execution_role_arn:
        agent_config['aws']['execution_role'] = execution_role_arn

    save_agentcore_config(config)
    print(f"\nUpdated {CONFIG_FILE}")
    print("\nNext steps:")
    print("  1. Run: cd agent && agentcore deploy")
    print("  2. Verify deployment with: agentcore status")


if __name__ == '__main__':
    main()
