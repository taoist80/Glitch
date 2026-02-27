#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'yaml';
import {
  GlitchFoundationStack,
  SSM_PARAMS,
  SecretsStack,
  TailscaleStack,
  AgentCoreStack,
  GlitchStorageStack,
  GlitchGatewayStack,
  GlitchUiHostingStack,
  TelegramWebhookStack,
} from '../lib/stack';

/**
 * Read AgentCore config from .bedrock_agentcore.yaml to get runtime ARN.
 * Falls back to null if file is missing or ARN not set.
 */
function getAgentCoreRuntimeArn(agentName: string = 'Glitch'): string | null {
  const configPath = path.resolve(__dirname, '../../agent/.bedrock_agentcore.yaml');
  try {
    if (fs.existsSync(configPath)) {
      const content = fs.readFileSync(configPath, 'utf8');
      const config = yaml.parse(content);
      return config?.agents?.[agentName]?.bedrock_agentcore?.agent_arn ?? null;
    }
  } catch (e) {
    console.warn(`Warning: Could not read AgentCore config from ${configPath}:`, e);
  }
  return null;
}

const app = new cdk.App();

const env = {
  account: '999776382415',
  region: 'us-west-2',
};

// Custom domain configuration
const customDomain = 'glitch.awoo.agency';

// ============================================================================
// PHASE 1: FOUNDATION (VPC + IAM Roles + SSM Parameters)
// Deploy this first: cdk deploy GlitchFoundationStack
// ============================================================================

const foundationStack = new GlitchFoundationStack(app, 'GlitchFoundationStack', {
  env,
  description: 'Foundation: VPC, IAM roles, security groups, SSM parameters',
});

// ============================================================================
// PHASE 2: AGENT (run after Phase 1)
// Run: cd agent && python3 scripts/pre-deploy-configure.py && agentcore deploy
// This creates the AgentCore runtime and writes the ARN to .bedrock_agentcore.yaml
// ============================================================================

// Read runtime ARN from config (set by agentcore deploy in Phase 2)
// Use placeholder during Phase 1 so synth succeeds
const agentCoreRuntimeArn =
  app.node.tryGetContext('glitchAgentCoreRuntimeArn') ??
  getAgentCoreRuntimeArn() ??
  `arn:aws:bedrock-agentcore:${env.region}:${env.account}:runtime/Glitch-PLACEHOLDER`;

// ============================================================================
// PHASE 3: APPLICATION STACKS (deploy after Phase 2)
// Deploy all: cdk deploy --all
// ============================================================================

const secretsStack = new SecretsStack(app, 'GlitchSecretsStack', {
  env,
  description: 'Secrets Manager references',
});

const storageStack = new GlitchStorageStack(app, 'GlitchStorageStack', {
  env,
  description: 'DynamoDB, S3, and telemetry log group',
});

const gatewayStack = new GlitchGatewayStack(app, 'GlitchGatewayStack', {
  env,
  configTable: storageStack.configTable,
  agentCoreRuntimeArn,
  description: 'Gateway Lambda (invocations, /api/*, keepalive)',
});
gatewayStack.addDependency(storageStack);

const telegramWebhookStack = new TelegramWebhookStack(app, 'GlitchTelegramWebhookStack', {
  env,
  configTable: storageStack.configTable,
  telegramBotTokenSecret: secretsStack.telegramBotTokenSecret,
  agentCoreRuntimeArn,
  description: 'Telegram webhook Lambda',
});
telegramWebhookStack.addDependency(storageStack);
telegramWebhookStack.addDependency(secretsStack);

// Write the webhook URL to SSM in a separate stack to avoid a CFN circular dependency.
// TelegramWebhookStack cannot write its own FunctionUrl as an SSM param because:
//   FunctionUrl → Function → ServiceRole → Policy → (anything) → FunctionUrl creates a cycle.
// Putting the SSM write in a child stack that depends on TelegramWebhookStack breaks the cycle.
const telegramSsmStack = new cdk.Stack(app, 'GlitchTelegramSsmStack', {
  env,
  description: 'SSM parameter: Telegram webhook URL (written separately to avoid CFN circular dep)',
});
new ssm.StringParameter(telegramSsmStack, 'SsmTelegramWebhookUrl', {
  parameterName: SSM_PARAMS.TELEGRAM_WEBHOOK_URL,
  stringValue: telegramWebhookStack.webhookUrl,
  description: 'Telegram webhook Lambda Function URL (for runtime GLITCH_TELEGRAM_WEBHOOK_URL)',
});
telegramSsmStack.addDependency(telegramWebhookStack);

// Extract hostname from Lambda Function URL (for Tailscale nginx proxy config)
const gatewayUrlHostname = cdk.Fn.select(2, cdk.Fn.split('/', gatewayStack.functionUrl));

const uiHostingStack = new GlitchUiHostingStack(app, 'GlitchUiHostingStack', {
  env,
  description: 'S3 bucket for UI static assets (served via Tailscale EC2 nginx)',
});

// Tailscale EC2 connector and nginx proxy
const tailscaleStack = new TailscaleStack(app, 'GlitchTailscaleStack', {
  env,
  vpc: foundationStack.vpc,
  tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
  agentCoreSecurityGroup: foundationStack.agentCoreSecurityGroup,
  agentCoreRuntimeArn,
  instanceBootstrapVersion: '11',
  gatewayFunctionUrl: gatewayStack.functionUrl,
  gatewayHostname: gatewayUrlHostname,
  uiBucketName: uiHostingStack.uiBucket.bucketName,
  customDomain,
  porkbunApiSecret: secretsStack.porkbunApiSecret,
  certbotEmail: 'admin@awoo.agency',
  description: 'Tailscale EC2 connector and nginx proxy',
});
tailscaleStack.addDependency(foundationStack);
tailscaleStack.addDependency(secretsStack);
tailscaleStack.addDependency(gatewayStack);
tailscaleStack.addDependency(uiHostingStack);

// AgentCore policies stack (attaches policies to runtime role)
const agentCoreStack = new AgentCoreStack(app, 'GlitchAgentCoreStack', {
  env,
  vpc: foundationStack.vpc,
  agentCoreSecurityGroup: foundationStack.agentCoreSecurityGroup,
  runtimeRole: foundationStack.runtimeRole,
  tailscaleInstance: tailscaleStack.instance,
  description: 'AgentCore runtime policies',
});
agentCoreStack.addDependency(foundationStack);
agentCoreStack.addDependency(tailscaleStack);

cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');

app.synth();
