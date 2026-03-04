#!/usr/bin/env python3
"""
Integration tests for Glitch infrastructure.

These tests verify the deployed infrastructure matches the expected configuration.
Run after CDK deploy to validate the deployment.

Usage:
    pytest infrastructure/test/test_integration.py -v
    # Or with specific AWS profile:
    AWS_PROFILE=your-profile pytest infrastructure/test/test_integration.py -v
"""

import os
import pytest
import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get('AWS_REGION', 'us-west-2')

FOUNDATION_STACK_NAME = 'GlitchFoundationStack'
AGENTCORE_STACK_NAME = 'GlitchAgentCoreStack'

ON_PREM_CIDR = '10.10.110.0/24'
OLLAMA_CHAT_HOST = '10.10.110.202'
OLLAMA_VISION_HOST = '10.10.110.137'


@pytest.fixture(scope='module')
def cfn_client():
    return boto3.client('cloudformation', region_name=REGION)


@pytest.fixture(scope='module')
def ec2_client():
    return boto3.client('ec2', region_name=REGION)


@pytest.fixture(scope='module')
def foundation_outputs(cfn_client):
    """Get outputs from GlitchFoundationStack."""
    try:
        response = cfn_client.describe_stacks(StackName=FOUNDATION_STACK_NAME)
        outputs = {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0].get('Outputs', [])}
        return outputs
    except ClientError as e:
        pytest.skip(f"Foundation stack not deployed: {e}")


@pytest.fixture(scope='module')
def agentcore_outputs(cfn_client):
    """Get outputs from AgentCore stack."""
    try:
        response = cfn_client.describe_stacks(StackName=AGENTCORE_STACK_NAME)
        outputs = {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0].get('Outputs', [])}
        return outputs
    except ClientError as e:
        pytest.skip(f"AgentCore stack not deployed: {e}")


class TestFoundationStack:
    """Tests for GlitchFoundationStack deployment."""

    def test_vpc_exists(self, foundation_outputs, ec2_client):
        """Verify VPC was created."""
        vpc_id = foundation_outputs.get('VpcId')
        assert vpc_id, "VpcId output not found"

        response = ec2_client.describe_vpcs(VpcIds=[vpc_id])
        assert len(response['Vpcs']) == 1
        assert response['Vpcs'][0]['State'] == 'available'

    def test_private_subnets_exist(self, foundation_outputs, ec2_client):
        """Verify private subnets were created."""
        subnet_ids = foundation_outputs.get('PrivateSubnetIds', '').split(',')
        assert len(subnet_ids) >= 1, "Expected at least one private subnet"

        response = ec2_client.describe_subnets(SubnetIds=subnet_ids)
        assert len(response['Subnets']) == len(subnet_ids)
        for subnet in response['Subnets']:
            assert subnet['State'] == 'available'

    def test_nat_gateway_exists(self, foundation_outputs, ec2_client):
        """Verify NAT gateway exists for private subnet egress."""
        vpc_id = foundation_outputs.get('VpcId')

        response = ec2_client.describe_nat_gateways(
            Filters=[
                {'Name': 'vpc-id', 'Values': [vpc_id]},
                {'Name': 'state', 'Values': ['available', 'pending']},
            ]
        )

        assert len(response['NatGateways']) >= 1, "NAT gateway should exist for private subnet egress"

    def test_vpn_gateway_exists(self, foundation_outputs, ec2_client):
        """Verify Virtual Private Gateway is attached to the VPC (for Site-to-Site VPN)."""
        vpc_id = foundation_outputs.get('VpcId')

        response = ec2_client.describe_vpn_gateways(
            Filters=[
                {'Name': 'attachment.vpc-id', 'Values': [vpc_id]},
                {'Name': 'attachment.state', 'Values': ['attached']},
            ]
        )

        assert len(response['VpnGateways']) >= 1, "Virtual Private Gateway should be attached to VPC"


class TestAgentCoreStack:
    """Tests for AgentCore stack deployment."""

    def test_iam_role_exists(self, agentcore_outputs):
        """Verify IAM runtime role exists."""
        role_arn = agentcore_outputs.get('AgentRuntimeRoleArn')
        assert role_arn, "AgentRuntimeRoleArn output not found"

        iam_client = boto3.client('iam', region_name=REGION)
        role_name = role_arn.split('/')[-1]

        response = iam_client.get_role(RoleName=role_name)
        assert response['Role']['RoleName'] == role_name


class TestOllamaConnectivity:
    """Tests for Ollama connectivity (requires on-prem network access)."""

    @pytest.mark.skip(reason="Requires on-prem network connectivity - run manually")
    def test_ollama_health_check(self):
        """Verify chat (Ollama 11434) and vision (OpenAI 8080) hosts are reachable."""
        import requests

        try:
            r = requests.get(f'http://{OLLAMA_CHAT_HOST}:11434/api/tags', timeout=5)
            assert r.status_code == 200, f"Chat host {OLLAMA_CHAT_HOST} returned {r.status_code}"
        except requests.exceptions.RequestException as e:
            pytest.fail(f"Cannot reach chat host {OLLAMA_CHAT_HOST}: {e}")

        try:
            r = requests.get(f'http://{OLLAMA_VISION_HOST}:8080/v1/models', timeout=5)
            assert r.status_code == 200, f"Vision host {OLLAMA_VISION_HOST} returned {r.status_code}"
        except requests.exceptions.RequestException as e:
            pytest.fail(f"Cannot reach vision host {OLLAMA_VISION_HOST}: {e}")


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
