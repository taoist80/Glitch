#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { VpcStack } from '../lib/vpc-stack';
import { SecretsStack } from '../lib/secrets-stack';
import { TailscaleStack } from '../lib/tailscale-stack';
import { AgentCoreStack } from '../lib/agentcore-stack';
import { GlitchStorageStack } from '../lib/storage-stack';
import { GlitchGatewayStack } from '../lib/gateway-stack';
import { GlitchUiHostingStack } from '../lib/ui-hosting-stack';
import { GlitchCertificateStack } from '../lib/certificate-stack';

const app = new cdk.App();

const env = {
  account: '999776382415',
  region: 'us-west-2',
};

// Custom domain configuration
const customDomain = 'glitch.awoo.agency';

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

// Extract hostname from Lambda Function URL (https://xxx.lambda-url.region.on.aws/)
const gatewayUrlHostname = cdk.Fn.select(
  2,
  cdk.Fn.split('/', gatewayStack.functionUrl)
);

// Certificate stack in us-east-1 (required for CloudFront)
const certificateStack = new GlitchCertificateStack(app, 'GlitchCertificateStack', {
  env: { account: env.account, region: 'us-east-1' },
  domainName: customDomain,
  crossRegionReferences: true,
  description: 'ACM certificate for CloudFront custom domain (us-east-1)',
});

const uiHostingStack = new GlitchUiHostingStack(app, 'GlitchUiHostingStack', {
  env,
  gatewayFunctionUrlHostname: gatewayUrlHostname,
  domainName: customDomain,
  certificateArn: certificateStack.certificate.certificateArn,
  crossRegionReferences: true,
  description: 'S3 + CloudFront hosting for Glitch UI',
});
uiHostingStack.addDependency(gatewayStack);
uiHostingStack.addDependency(certificateStack);

// Bump instanceBootstrapVersion (e.g. to '8') to force EC2 instance replacement on next deploy.
const tailscaleStack = new TailscaleStack(app, 'GlitchTailscaleStack', {
  env,
  vpc: vpcStack.vpc,
  tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
  agentCoreRuntimeArn,
  instanceBootstrapVersion: '8',
  gatewayFunctionUrl: gatewayStack.functionUrl,
  uiBucketName: uiHostingStack.uiBucket.bucketName,
  customDomain,
  porkbunApiSecret: secretsStack.porkbunApiSecret,
  certbotEmail: 'admin@awoo.agency',
  description: 'EC2 Tailscale connector and UI proxy (nginx + Let\'s Encrypt TLS)',
});
tailscaleStack.addDependency(vpcStack);
tailscaleStack.addDependency(secretsStack);
tailscaleStack.addDependency(gatewayStack);
tailscaleStack.addDependency(uiHostingStack);

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
