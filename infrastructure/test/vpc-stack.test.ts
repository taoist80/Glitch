import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { VpcStack } from '../lib/vpc-stack';

describe('VpcStack', () => {
  let app: cdk.App;
  let stack: VpcStack;
  let template: Template;

  beforeEach(() => {
    app = new cdk.App();
    stack = new VpcStack(app, 'TestVpcStack', {
      env: { account: '123456789012', region: 'us-west-2' },
    });
    template = Template.fromStack(stack);
  });

  describe('VPC Configuration', () => {
    test('creates VPC with correct CIDR', () => {
      template.hasResourceProperties('AWS::EC2::VPC', {
        CidrBlock: '10.0.0.0/16',
        EnableDnsHostnames: true,
        EnableDnsSupport: true,
      });
    });

    test('creates public and private subnets in 2 AZs', () => {
      template.resourceCountIs('AWS::EC2::Subnet', 4);
    });

    test('does not create NAT gateways (cost optimization)', () => {
      template.resourceCountIs('AWS::EC2::NatGateway', 0);
    });
  });

  describe('VPC Endpoints', () => {
    test('creates expected number of VPC endpoints', () => {
      template.resourceCountIs('AWS::EC2::VPCEndpoint', 8);
    });

    test('creates interface endpoints with private DNS', () => {
      template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
        VpcEndpointType: 'Interface',
        PrivateDnsEnabled: true,
      });
    });

    test('creates ECR Docker interface endpoint', () => {
      template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
        ServiceName: 'com.amazonaws.us-west-2.ecr.dkr',
        VpcEndpointType: 'Interface',
        PrivateDnsEnabled: true,
      });
    });

    test('creates ECR API interface endpoint', () => {
      template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
        ServiceName: 'com.amazonaws.us-west-2.ecr.api',
        VpcEndpointType: 'Interface',
        PrivateDnsEnabled: true,
      });
    });

    test('creates CloudWatch Logs interface endpoint', () => {
      template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
        ServiceName: 'com.amazonaws.us-west-2.logs',
        VpcEndpointType: 'Interface',
        PrivateDnsEnabled: true,
      });
    });

    test('creates Secrets Manager interface endpoint', () => {
      template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
        ServiceName: 'com.amazonaws.us-west-2.secretsmanager',
        VpcEndpointType: 'Interface',
        PrivateDnsEnabled: true,
      });
    });

    test('creates Bedrock Runtime interface endpoint', () => {
      template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
        ServiceName: 'com.amazonaws.us-west-2.bedrock-runtime',
        VpcEndpointType: 'Interface',
        PrivateDnsEnabled: true,
      });
    });

    test('creates Bedrock AgentCore interface endpoint', () => {
      template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
        ServiceName: 'com.amazonaws.us-west-2.bedrock-agentcore',
        VpcEndpointType: 'Interface',
        PrivateDnsEnabled: true,
      });
    });
  });

  describe('Stack Outputs', () => {
    test('exports VPC ID', () => {
      template.hasOutput('VpcId', {
        Export: { Name: 'GlitchVpcId' },
      });
    });

    test('exports private subnet IDs', () => {
      template.hasOutput('PrivateSubnetIds', {
        Export: { Name: 'GlitchPrivateSubnetIds' },
      });
    });

    test('exports availability zones', () => {
      template.hasOutput('AvailabilityZones', {
        Export: { Name: 'GlitchAvailabilityZones' },
      });
    });
  });

  describe('Custom CIDR', () => {
    test('accepts custom VPC CIDR', () => {
      const customApp = new cdk.App();
      const customStack = new VpcStack(customApp, 'CustomVpcStack', {
        vpcCidr: '172.16.0.0/16',
        env: { account: '123456789012', region: 'us-west-2' },
      });
      const customTemplate = Template.fromStack(customStack);

      customTemplate.hasResourceProperties('AWS::EC2::VPC', {
        CidrBlock: '172.16.0.0/16',
      });
    });
  });
});
