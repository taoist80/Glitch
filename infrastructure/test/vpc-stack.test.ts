import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import { GlitchFoundationStack } from '../lib/stack';

describe('GlitchFoundationStack', () => {
  let app: cdk.App;
  let stack: GlitchFoundationStack;
  let template: Template;

  beforeEach(() => {
    app = new cdk.App();
    stack = new GlitchFoundationStack(app, 'TestFoundationStack', {
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

  describe('Security Groups', () => {
    test('creates AgentCore security group', () => {
      template.hasResourceProperties('AWS::EC2::SecurityGroup', {
        GroupDescription: 'Security group for AgentCore runtime ENIs',
      });
    });
  });

  describe('IAM Roles', () => {
    test('creates runtime role with bedrock-agentcore trust', () => {
      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
            }),
          ]),
        },
      });
    });

    test('creates CodeBuild role with codebuild trust', () => {
      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Principal: { Service: 'codebuild.amazonaws.com' },
            }),
          ]),
        },
      });
    });

    test('CodeBuild role has ECR permissions', () => {
      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 'ecr:GetAuthorizationToken',
            }),
          ]),
        },
      });
    });
  });

  describe('SSM Parameters', () => {
    test('creates SSM parameter for VPC ID', () => {
      template.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/glitch/vpc/id',
        Type: 'String',
      });
    });

    test('creates SSM parameter for private subnet IDs', () => {
      template.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/glitch/vpc/private-subnet-ids',
        Type: 'String',
      });
    });

    test('creates SSM parameter for AgentCore security group', () => {
      template.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/glitch/security-groups/agentcore',
        Type: 'String',
      });
    });

    test('creates SSM parameter for runtime role ARN', () => {
      template.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/glitch/iam/runtime-role-arn',
        Type: 'String',
      });
    });

    test('creates SSM parameter for CodeBuild role ARN', () => {
      template.hasResourceProperties('AWS::SSM::Parameter', {
        Name: '/glitch/iam/codebuild-role-arn',
        Type: 'String',
      });
    });
  });

  describe('Stack Outputs', () => {
    test('outputs VPC ID', () => {
      template.hasOutput('VpcId', {});
    });

    test('outputs private subnet IDs', () => {
      template.hasOutput('PrivateSubnetIds', {});
    });

    test('outputs runtime role ARN', () => {
      template.hasOutput('RuntimeRoleArn', {});
    });

    test('outputs CodeBuild role ARN', () => {
      template.hasOutput('CodeBuildRoleArn', {});
    });
  });

  describe('Custom CIDR', () => {
    test('accepts custom VPC CIDR', () => {
      const customApp = new cdk.App();
      const customStack = new GlitchFoundationStack(customApp, 'CustomFoundationStack', {
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
