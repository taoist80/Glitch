#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { VpcStack } from '../lib/vpc-stack';
import { SecretsStack } from '../lib/secrets-stack';
import { TailscaleStack } from '../lib/tailscale-stack';
import { AgentCoreStack } from '../lib/agentcore-stack';
import { GlitchStorageStack } from '../lib/storage-stack';
import { GlitchGatewayStack } from '../lib/gateway-stack';

const app = new cdk.App();

const env = {
  account: '999776382415',
  region: 'us-west-2',
};

const vpcStack = new VpcStack(app, 'GlitchVpcStack', {
  env,
  description: 'VPC infrastructure for AgentCore Glitch',
});

// Default AgentCore SDK runtime role (from .bedrock_agentcore.yaml); grant it Telegram secret read
const defaultExecutionRoleArn =
  app.node.tryGetContext('glitchDefaultExecutionRoleArn') ??
  `arn:aws:iam::${env.account}:role/AmazonBedrockAgentCoreSDKRuntime-${env.region}-14980158e2`;

// AgentCore runtime ARN (from .bedrock_agentcore.yaml or agentcore runtime list)
const agentCoreRuntimeArn =
  app.node.tryGetContext('glitchAgentCoreRuntimeArn') ??
  `arn:aws:bedrock-agentcore:${env.region}:${env.account}:runtime/Glitch-78q5TgEa8M`;

const secretsStack = new SecretsStack(app, 'GlitchSecretsStack', {
  env,
  defaultExecutionRoleArn,
  description: 'Secrets Manager configuration for AgentCore Glitch',
});

// Bump instanceBootstrapVersion (e.g. to '5') to force EC2 instance replacement on next deploy.
const tailscaleStack = new TailscaleStack(app, 'GlitchTailscaleStack', {
  env,
  vpc: vpcStack.vpc,
  tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
  agentCoreRuntimeArn,
  instanceBootstrapVersion: '5',
  description: 'EC2 Tailscale connector for on-premises network access',
});
tailscaleStack.addDependency(vpcStack);
tailscaleStack.addDependency(secretsStack);

const agentCoreStack = new AgentCoreStack(app, 'GlitchAgentCoreStack', {
  env,
  vpc: vpcStack.vpc,
  tailscaleSecurityGroup: tailscaleStack.securityGroup,
  apiKeysSecret: secretsStack.apiKeysSecret,
  telegramBotTokenSecret: secretsStack.telegramBotTokenSecret,
  description: 'AgentCore Runtime resources',
});
agentCoreStack.addDependency(vpcStack);
agentCoreStack.addDependency(secretsStack);
agentCoreStack.addDependency(tailscaleStack);

const storageStack = new GlitchStorageStack(app, 'GlitchStorageStack', {
  env,
  defaultExecutionRoleArn,
  description: 'DynamoDB, S3, SSM, and telemetry log group for Glitch',
});

const gatewayStack = new GlitchGatewayStack(app, 'GlitchGatewayStack', {
  env,
  configTable: storageStack.configTable,
  agentCoreRuntimeArn,
  description: 'Gateway Lambda (invocations, /api/*, keepalive)',
});
gatewayStack.addDependency(storageStack);

cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');

app.synth();
