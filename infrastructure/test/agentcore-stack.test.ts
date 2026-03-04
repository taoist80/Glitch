import * as cdk from 'aws-cdk-lib';
import { Template, Match } from 'aws-cdk-lib/assertions';
import * as iam from 'aws-cdk-lib/aws-iam';
import { AgentCoreStack } from '../lib/stack';

describe('AgentCoreStack', () => {
  let app: cdk.App;
  let runtimeRole: iam.Role;

  beforeEach(() => {
    app = new cdk.App();
    const roleStack = new cdk.Stack(app, 'RoleStack', {
      env: { account: '123456789012', region: 'us-west-2' },
    });
    runtimeRole = new iam.Role(roleStack, 'RuntimeRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
    });
  });

  function createStack() {
    return new AgentCoreStack(app, 'TestAgentCoreStack', {
      runtimeRole,
      env: { account: '123456789012', region: 'us-west-2' },
    });
  }

  describe('IAM Role', () => {
    test('does not create a role (role is passed in from FoundationStack)', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);
      template.resourceCountIs('AWS::IAM::Role', 0);
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
                'bedrock-agentcore:ListMemoryRecords',
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
              Sid: 'SecretsManagerRead',
              Effect: 'Allow',
              Action: 'secretsmanager:GetSecretValue',
            }),
          ]),
        },
      });
    });
  });

  describe('Stack Outputs', () => {
    test('outputs agent runtime role ARN', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);
      template.hasOutput('AgentRuntimeRoleArn', {});
    });
  });
});
