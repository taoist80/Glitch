import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { AgentCoreStack } from '../lib/stack';

describe('AgentCoreStack', () => {
  let app: cdk.App;
  let vpcStack: cdk.Stack;
  let vpc: ec2.Vpc;
  let tailscaleSg: ec2.SecurityGroup;

  beforeEach(() => {
    app = new cdk.App();
    vpcStack = new cdk.Stack(app, 'VpcStack', {
      env: { account: '123456789012', region: 'us-west-2' },
    });
    vpc = new ec2.Vpc(vpcStack, 'TestVpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });
    tailscaleSg = new ec2.SecurityGroup(vpcStack, 'TailscaleSg', {
      vpc,
      description: 'Tailscale SG',
    });
  });

  function createStack() {
    const agentCoreSg = new ec2.SecurityGroup(vpcStack, 'AgentCoreSg', {
      vpc,
      description: 'AgentCore SG',
      allowAllOutbound: false,
    });
    agentCoreSg.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS');
    
    return new AgentCoreStack(app, 'TestAgentCoreStack', {
      vpc,
      agentCoreSecurityGroup: agentCoreSg,
      env: { account: '123456789012', region: 'us-west-2' },
    });
  }

  describe('Security Group', () => {
    test('creates exactly zero security groups (SG is passed in from VpcStack)', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.resourceCountIs('AWS::EC2::SecurityGroup', 0);
    });
  });

  describe('IAM Role', () => {
    test('creates role with bedrock-agentcore service principal', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 'sts:AssumeRole',
              Effect: 'Allow',
              Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
            }),
          ]),
        },
        RoleName: 'GlitchAgentCoreRuntimeRole',
      });
    });

    test('grants Bedrock model invocation permissions', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::ManagedPolicy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: 'BedrockModelAccess',
              Effect: 'Allow',
              Action: Match.arrayWith([
                'bedrock:InvokeModel',
                'bedrock:InvokeModelWithResponseStream',
              ]),
            }),
          ]),
        },
      });
    });

    test('grants ECR image access', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::ManagedPolicy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: 'ECRImageAccess',
              Effect: 'Allow',
              Action: Match.arrayWith([
                'ecr:BatchGetImage',
                'ecr:GetDownloadUrlForLayer',
              ]),
            }),
          ]),
        },
      });
    });

    test('grants ECR authorization token access', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::ManagedPolicy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: 'ECRTokenAccess',
              Effect: 'Allow',
              Action: 'ecr:GetAuthorizationToken',
              Resource: '*',
            }),
          ]),
        },
      });
    });

    test('grants AgentCore Memory access', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::ManagedPolicy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: 'AgentCoreMemoryAccess',
              Effect: 'Allow',
              Action: Match.arrayWith([
                'bedrock-agentcore:CreateEvent',
                'bedrock-agentcore:GetEvent',
                'bedrock-agentcore:ListEvents',
                'bedrock-agentcore:ListSessions',
                'bedrock-agentcore:CreateMemoryRecord',
                'bedrock-agentcore:GetMemoryRecord',
                'bedrock-agentcore:ListMemoryRecords',
                'bedrock-agentcore:RetrieveMemoryRecords',
              ]),
            }),
          ]),
        },
      });
    });

    test('grants CloudWatch Logs access', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::ManagedPolicy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: 'CloudWatchLogs',
              Effect: 'Allow',
              Action: Match.arrayWith([
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents',
              ]),
            }),
          ]),
        },
      });
    });

    test('grants read access to secrets', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::ManagedPolicy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Sid: 'SecretsManagerAccess',
              Effect: 'Allow',
              Action: 'secretsmanager:GetSecretValue',
            }),
          ]),
        },
      });
    });
  });

  describe('Stack Outputs', () => {
    test('exports agent runtime role ARN', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasOutput('AgentRuntimeRoleArn', {
        Export: { Name: 'GlitchAgentRuntimeRoleArn' },
      });
    });

    test('exports security group ID', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasOutput('AgentCoreSecurityGroupId', {
        Export: { Name: 'GlitchAgentCoreSecurityGroupIdFromStack' },
      });
    });

    test('exports VPC config JSON', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasOutput('VpcConfigForAgentCore', {
        Export: { Name: 'GlitchVpcConfig' },
      });
    });
  });
});
