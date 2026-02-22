import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface AgentCoreStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly tailscaleSecurityGroup: ec2.ISecurityGroup;
}

export class AgentCoreStack extends cdk.Stack {
  public readonly agentRuntimeRole: iam.Role;
  public readonly agentCoreSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { vpc, tailscaleSecurityGroup } = props;

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

    // On-prem Ollama hosts via Tailscale routing (10.10.110.0/24 routes through Tailscale ENI)
    // AgentCore needs explicit egress to the destination CIDR, not just to the Tailscale SG
    this.agentCoreSecurityGroup.addEgressRule(
      ec2.Peer.ipv4('10.10.110.0/24'),
      ec2.Port.tcp(11434),
      'Ollama native API to on-prem chat host (10.10.110.202)'
    );
    this.agentCoreSecurityGroup.addEgressRule(
      ec2.Peer.ipv4('10.10.110.0/24'),
      ec2.Port.tcp(8080),
      'OpenAI-compatible API to on-prem vision host (10.10.110.137)'
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
          // Cross-region inference profiles (us.*) can route to any US region
          // Use wildcard for region to handle dynamic routing
          'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0',
          'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0',
          'arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-20250514-v1:0',
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

    // Grant secrets access via explicit policy (avoids circular dependency with SecretsStack)
    // Use wildcard ARNs to match the secret's full ARN (AWS appends 6-char suffix)
    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'SecretsManagerAccess',
        effect: iam.Effect.ALLOW,
        actions: ['secretsmanager:GetSecretValue'],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/api-keys*`,
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/telegram-bot-token*`,
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/pihole-api*`,
        ],
      })
    );

    this.agentRuntimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogs',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
          'logs:GetLogEvents',
          'logs:DescribeLogStreams',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*:*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*:*`,
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
