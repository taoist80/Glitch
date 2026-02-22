#!/usr/bin/env python3
"""
Integration tests for VPC/Tailscale/AgentCore infrastructure.

These tests verify the deployed infrastructure matches the expected configuration.
Run after CDK deploy to validate the deployment.

Usage:
    pytest infrastructure/test/test_integration.py -v
    # Or with specific AWS profile:
    AWS_PROFILE=your-profile pytest infrastructure/test/test_integration.py -v
"""

import json
import os
import subprocess
import pytest
import boto3
from botocore.exceptions import ClientError

REGION = os.environ.get('AWS_REGION', 'us-west-2')
ACCOUNT_ID = os.environ.get('AWS_ACCOUNT_ID', '999776382415')

VPC_STACK_NAME = 'GlitchVpcStack'
TAILSCALE_STACK_NAME = 'GlitchTailscaleStack'
AGENTCORE_STACK_NAME = 'GlitchAgentCoreStack'

ON_PREM_CIDR = '10.10.110.0/24'
# Chat: Ollama native 11434. Vision: OpenAI-compatible 8080.
OLLAMA_CHAT_HOST = '10.10.110.202'
OLLAMA_VISION_HOST = '10.10.110.137'


@pytest.fixture(scope='module')
def cfn_client():
    return boto3.client('cloudformation', region_name=REGION)


@pytest.fixture(scope='module')
def ec2_client():
    return boto3.client('ec2', region_name=REGION)


@pytest.fixture(scope='module')
def ssm_client():
    return boto3.client('ssm', region_name=REGION)


@pytest.fixture(scope='module')
def vpc_outputs(cfn_client):
    """Get outputs from VPC stack."""
    try:
        response = cfn_client.describe_stacks(StackName=VPC_STACK_NAME)
        outputs = {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0].get('Outputs', [])}
        return outputs
    except ClientError as e:
        pytest.skip(f"VPC stack not deployed: {e}")


@pytest.fixture(scope='module')
def tailscale_outputs(cfn_client):
    """Get outputs from Tailscale stack."""
    try:
        response = cfn_client.describe_stacks(StackName=TAILSCALE_STACK_NAME)
        outputs = {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0].get('Outputs', [])}
        return outputs
    except ClientError as e:
        pytest.skip(f"Tailscale stack not deployed: {e}")


@pytest.fixture(scope='module')
def agentcore_outputs(cfn_client):
    """Get outputs from AgentCore stack."""
    try:
        response = cfn_client.describe_stacks(StackName=AGENTCORE_STACK_NAME)
        outputs = {o['OutputKey']: o['OutputValue'] for o in response['Stacks'][0].get('Outputs', [])}
        return outputs
    except ClientError as e:
        pytest.skip(f"AgentCore stack not deployed: {e}")


class TestVpcStack:
    """Tests for VPC stack deployment."""

    def test_vpc_exists(self, vpc_outputs, ec2_client):
        """Verify VPC was created."""
        vpc_id = vpc_outputs.get('VpcId')
        assert vpc_id, "VpcId output not found"
        
        response = ec2_client.describe_vpcs(VpcIds=[vpc_id])
        assert len(response['Vpcs']) == 1
        assert response['Vpcs'][0]['State'] == 'available'

    def test_private_subnets_exist(self, vpc_outputs, ec2_client):
        """Verify private subnets were created."""
        subnet_ids = vpc_outputs.get('PrivateSubnetIds', '').split(',')
        assert len(subnet_ids) >= 2, "Expected at least 2 private subnets"
        
        response = ec2_client.describe_subnets(SubnetIds=subnet_ids)
        assert len(response['Subnets']) == len(subnet_ids)
        for subnet in response['Subnets']:
            assert subnet['State'] == 'available'

    def test_vpc_endpoints_exist(self, vpc_outputs, ec2_client):
        """Verify VPC endpoints were created."""
        vpc_id = vpc_outputs.get('VpcId')
        
        response = ec2_client.describe_vpc_endpoints(
            Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
        )
        
        endpoint_services = [ep['ServiceName'] for ep in response['VpcEndpoints']]
        
        required_endpoints = [
            's3',
            'ecr.dkr',
            'ecr.api',
            'logs',
            'secretsmanager',
            'bedrock-runtime',
            'bedrock-agentcore',
        ]
        
        for required in required_endpoints:
            assert any(required in svc for svc in endpoint_services), \
                f"Missing VPC endpoint for {required}"

    def test_no_nat_gateways(self, vpc_outputs, ec2_client):
        """Verify no NAT gateways (cost optimization)."""
        vpc_id = vpc_outputs.get('VpcId')
        
        response = ec2_client.describe_nat_gateways(
            Filters=[
                {'Name': 'vpc-id', 'Values': [vpc_id]},
                {'Name': 'state', 'Values': ['available', 'pending']},
            ]
        )
        
        assert len(response['NatGateways']) == 0, "NAT gateways should not exist"


class TestTailscaleStack:
    """Tests for Tailscale stack deployment."""

    def test_instance_exists(self, tailscale_outputs, ec2_client):
        """Verify Tailscale EC2 instance exists."""
        instance_id = tailscale_outputs.get('InstanceId')
        assert instance_id, "InstanceId output not found"
        
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        instances = response['Reservations'][0]['Instances']
        assert len(instances) == 1
        assert instances[0]['State']['Name'] == 'running'

    def test_instance_type(self, tailscale_outputs, ec2_client):
        """Verify instance is t4g.nano (cost optimization)."""
        instance_id = tailscale_outputs.get('InstanceId')
        
        response = ec2_client.describe_instances(InstanceIds=[instance_id])
        instance = response['Reservations'][0]['Instances'][0]
        
        assert instance['InstanceType'] == 't4g.nano'

    def test_source_dest_check_disabled(self, tailscale_outputs, ec2_client):
        """Verify source/dest check is disabled for routing."""
        instance_id = tailscale_outputs.get('InstanceId')
        
        response = ec2_client.describe_instance_attribute(
            InstanceId=instance_id,
            Attribute='sourceDestCheck'
        )
        
        assert response['SourceDestCheck']['Value'] is False

    def test_security_group_rules(self, tailscale_outputs, ec2_client):
        """Verify security group has required rules."""
        sg_id = tailscale_outputs.get('SecurityGroupId')
        assert sg_id, "SecurityGroupId output not found"
        
        response = ec2_client.describe_security_groups(GroupIds=[sg_id])
        sg = response['SecurityGroups'][0]
        
        egress_ports = set()
        for rule in sg['IpPermissionsEgress']:
            if rule.get('FromPort'):
                egress_ports.add(rule['FromPort'])
        
        assert 443 in egress_ports, "Missing HTTPS egress"
        assert 41641 in egress_ports or any(r.get('IpProtocol') == 'udp' for r in sg['IpPermissionsEgress']), \
            "Missing WireGuard egress"

    def test_vpc_routes_to_on_prem(self, vpc_outputs, tailscale_outputs, ec2_client):
        """Verify VPC route tables have route to on-prem CIDR."""
        subnet_ids = vpc_outputs.get('PrivateSubnetIds', '').split(',')
        
        for subnet_id in subnet_ids:
            response = ec2_client.describe_route_tables(
                Filters=[{'Name': 'association.subnet-id', 'Values': [subnet_id]}]
            )
            
            if not response['RouteTables']:
                continue
                
            routes = response['RouteTables'][0]['Routes']
            on_prem_route = next(
                (r for r in routes if r.get('DestinationCidrBlock') == ON_PREM_CIDR),
                None
            )
            
            assert on_prem_route, f"Missing route to {ON_PREM_CIDR} in subnet {subnet_id}"
            assert on_prem_route.get('NetworkInterfaceId'), \
                f"Route to {ON_PREM_CIDR} should target ENI"


class TestAgentCoreStack:
    """Tests for AgentCore stack deployment."""

    def test_security_group_exists(self, agentcore_outputs, ec2_client):
        """Verify AgentCore security group exists."""
        sg_id = agentcore_outputs.get('AgentCoreSecurityGroupId')
        assert sg_id, "AgentCoreSecurityGroupId output not found"
        
        response = ec2_client.describe_security_groups(GroupIds=[sg_id])
        assert len(response['SecurityGroups']) == 1

    def test_iam_role_exists(self, agentcore_outputs):
        """Verify IAM role exists."""
        role_arn = agentcore_outputs.get('AgentRuntimeRoleArn')
        assert role_arn, "AgentRuntimeRoleArn output not found"
        
        iam_client = boto3.client('iam', region_name=REGION)
        role_name = role_arn.split('/')[-1]
        
        response = iam_client.get_role(RoleName=role_name)
        assert response['Role']['RoleName'] == role_name

    def test_vpc_config_output(self, agentcore_outputs):
        """Verify VPC config JSON output is valid."""
        vpc_config = agentcore_outputs.get('VpcConfigForAgentCore')
        assert vpc_config, "VpcConfigForAgentCore output not found"
        
        config = json.loads(vpc_config)
        assert 'subnets' in config
        assert 'securityGroups' in config
        assert len(config['subnets']) >= 2
        assert len(config['securityGroups']) >= 1


class TestTailscaleConnectivity:
    """Tests for Tailscale connectivity (requires Tailscale to be running)."""

    @pytest.mark.skip(reason="Requires Tailscale route approval - run manually")
    def test_tailscale_status(self, tailscale_outputs, ssm_client):
        """Verify Tailscale is running on the instance."""
        instance_id = tailscale_outputs.get('InstanceId')
        
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={'commands': ['tailscale status --json']},
        )
        
        command_id = response['Command']['CommandId']
        
        import time
        for _ in range(30):
            time.sleep(2)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
            if result['Status'] in ['Success', 'Failed']:
                break
        
        assert result['Status'] == 'Success', f"Tailscale status failed: {result.get('StandardErrorContent')}"
        
        status = json.loads(result['StandardOutputContent'])
        assert status.get('BackendState') == 'Running'

    @pytest.mark.skip(reason="Requires Tailscale route approval - run manually")
    def test_on_prem_route_advertised(self, tailscale_outputs, ssm_client):
        """Verify on-prem route is advertised."""
        instance_id = tailscale_outputs.get('InstanceId')
        
        response = ssm_client.send_command(
            InstanceIds=[instance_id],
            DocumentName='AWS-RunShellScript',
            Parameters={'commands': ['tailscale status --json']},
        )
        
        command_id = response['Command']['CommandId']
        
        import time
        for _ in range(30):
            time.sleep(2)
            result = ssm_client.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
            if result['Status'] in ['Success', 'Failed']:
                break
        
        status = json.loads(result['StandardOutputContent'])
        self_status = status.get('Self', {})
        
        assert ON_PREM_CIDR in str(self_status.get('PrimaryRoutes', [])), \
            f"Route {ON_PREM_CIDR} not advertised"


class TestOllamaConnectivity:
    """Tests for Ollama connectivity (requires deployed agent)."""

    @pytest.mark.skip(reason="Requires deployed agent - run manually")
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
