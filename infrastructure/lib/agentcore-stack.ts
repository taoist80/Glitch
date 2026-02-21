import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly tailscaleSecurityGroup: ec2.ISecurityGroup;
  readonly apiKeysSecret: secretsmanager.ISecret;
  readonly telegramBotTokenSecret: secretsmanager.ISecret;
}

export class AgentCoreStack extends cdk.Stack {
  public readonly agentRuntimeRole: iam.Role;
  public readonly agentCoreSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { vpc, tailscaleSecurityGroup, apiKeysSecret, telegramBotTokenSecret } = props;

    this.agentCoreSecurityGroup = new ec2.SecurityGroup(this, 'AgentCoreSecurityGroup', {
      vpc,
      description: 'Security group for AgentCore Runtime ENIs',
      allowAllOutbound: false,
    });

    this.agentCoreSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'HTTPS for Bedrock API calls'
    );

    this.agentCoreSecurityGroup.addEgressRule(
      tailscaleSecurityGroup,
      ec2.Port.allTraffic(),
      'Allow all traffic to Tailscale connector'
    );

    this.agentCoreSecurityGroup.addIngressRule(
      tailscaleSecurityGroup,
      ec2.Port.tcp(443),
      'Allow HTTPS from Tailscale proxy'
    );

    this.agentRuntimeRole = new iam.Role(this, 'AgentRuntimeRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: 'IAM role for AgentCore Runtime',
      roleName: 'GlitchAgentCoreRuntimeRole',
    });

    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'BedrockModelAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
        ],
        resources: [
          // Foundation models in current region (Sonnet 4, Sonnet 4.5, Opus 4)
          `arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0`,
          `arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0`,
          `arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-opus-4-20250514-v1:0`,
          // Cross-region inference profiles route to us-east-1 foundation models
          'arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0',
          'arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0',
          'arn:aws:bedrock:us-east-1::foundation-model/anthropic.claude-opus-4-20250514-v1:0',
          // Inference profiles (cross-region and account-specific)
          `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
          `arn:aws:bedrock:${this.region}::inference-profile/*`,
        ],
      })
    );

    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'ECRImageAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'ecr:BatchGetImage',
          'ecr:GetDownloadUrlForLayer',
        ],
        resources: [
          `arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`,
        ],
      })
    );

    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'ECRTokenAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'ecr:GetAuthorizationToken',
        ],
        resources: ['*'],
      })
    );

    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'AgentCoreMemoryAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock-agentcore:CreateEvent',
          'bedrock-agentcore:GetEvent',
          'bedrock-agentcore:ListEvents',
          'bedrock-agentcore:ListSessions',
          'bedrock-agentcore:CreateMemoryRecord',
          'bedrock-agentcore:GetMemoryRecord',
          'bedrock-agentcore:ListMemoryRecords',
          'bedrock-agentcore:RetrieveMemoryRecords',
        ],
        resources: ['*'],
      })
    );

    apiKeysSecret.grantRead(this.agentRuntimeRole);
    telegramBotTokenSecret.grantRead(this.agentRuntimeRole);

    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogs',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock/agentcore/*`,
        ],
      })
    );

    new cdk.CfnOutput(this, 'AgentRuntimeRoleArn', {
      value: this.agentRuntimeRole.roleArn,
      description: 'IAM role ARN for AgentCore Runtime (use with agentcore configure --execution-role)',
      exportName: 'GlitchAgentRuntimeRoleArn',
    });

    new cdk.CfnOutput(this, 'AgentCoreSecurityGroupId', {
      value: this.agentCoreSecurityGroup.securityGroupId,
      description: 'Security group ID for AgentCore ENIs',
      exportName: 'GlitchAgentCoreSecurityGroupId',
    });

    new cdk.CfnOutput(this, 'VpcConfigForAgentCore', {
      value: JSON.stringify({
        subnets: vpc.isolatedSubnets.map(s => s.subnetId),
        securityGroups: [this.agentCoreSecurityGroup.securityGroupId],
      }),
      description: 'VPC configuration for AgentCore Runtime (JSON)',
      exportName: 'GlitchVpcConfig',
    });
  }
}
