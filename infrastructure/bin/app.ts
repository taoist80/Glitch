#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { VpcStack } from '../lib/vpc-stack';
import { SecretsStack } from '../lib/secrets-stack';
import { TailscaleStack } from '../lib/tailscale-stack';
import { AgentCoreStack } from '../lib/agentcore-stack';

const app = new cdk.App();

const env = {
  account: '999776382415',
  region: 'us-west-2',
};

const vpcStack = new VpcStack(app, 'GlitchVpcStack', {
  env,
  description: 'VPC infrastructure for AgentCore Glitch',
});

const secretsStack = new SecretsStack(app, 'GlitchSecretsStack', {
  env,
  description: 'Secrets Manager configuration for AgentCore Glitch',
});

const tailscaleStack = new TailscaleStack(app, 'GlitchTailscaleStack', {
  env,
  vpc: vpcStack.vpc,
  tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
  description: 'EC2 Tailscale connector for private network access',
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

cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');

app.synth();
