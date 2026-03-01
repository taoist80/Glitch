#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'yaml';
import {
  GlitchFoundationStack,
  GlitchVpnStack,
  SSM_PARAMS,
  SecretsStack,
  AgentCoreStack,
  GlitchStorageStack,
  GlitchGatewayStack,
  GlitchEdgeStack,
  GlitchUiHostingStack,
  TelegramWebhookStack,
  GlitchSentinelStack,
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

const customDomain = 'glitch.awoo.agency';

// ============================================================================
// PHASE 1: FOUNDATION (VPC + IAM Roles + SSM Parameters + S2S VPN)
// Deploy first: cdk deploy GlitchFoundationStack
// Pass on-prem IP when UDM-Pro is ready: -c onPremPublicIp=YOUR.WAN.IP.HERE
// ============================================================================

const foundationStack = new GlitchFoundationStack(app, 'GlitchFoundationStack', {
  env,
  description: 'Foundation: VPC (no NAT Gateway), IAM roles, S2S VPN (UDM-Pro gateway), SSM parameters',
});

// ============================================================================
// PHASE 1b: VPN (deploy once after Phase 1, then leave alone)
// First deploy — pass UDM-Pro WAN IP to create Customer Gateway + VPN Connection:
//   cdk deploy GlitchVpnStack -c onPremPublicIp=YOUR.WAN.IP.HERE
// All VPN resources have DeletionPolicy: RETAIN — safe to redeploy without context.
// ============================================================================

const vpnStack = new GlitchVpnStack(app, 'GlitchVpnStack', {
  env,
  vpc: foundationStack.vpc,
  description: 'Site-to-Site VPN: VGW, Customer Gateway, VPN Connection (UDM-Pro ↔ AWS)',
});
vpnStack.addDependency(foundationStack);

// ============================================================================
// PHASE 2: AGENT (run after Phase 1)
// Run: cd agent && python3 scripts/pre-deploy-configure.py && agentcore deploy
// This creates the AgentCore runtime and writes the ARN to .bedrock_agentcore.yaml
// ============================================================================

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
  description: 'Gateway Lambda (IAM-auth Function URL, /api/*, keepalive)',
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

// Edge stack (us-east-1): WAF WebACL for CloudFront IP allowlisting.
// IPv4 is auto-discovered from Porkbun DDNS at every deploy — no manual IP passing needed.
// To override (e.g. add a second IP): -c allowedIpAddresses=1.2.3.4/32,5.6.7.8/32
const allowedIpAddresses = ((app.node.tryGetContext('allowedIpAddresses') as string) ?? '')
  .split(',')
  .map(s => s.trim())
  .filter(Boolean);

// crossRegionReferences: true allows CDK to pass GlitchEdgeStack (us-east-1) outputs
// to GlitchUiHostingStack (us-west-2) via SSM custom resources at synth time.
const edgeStack = new GlitchEdgeStack(app, 'GlitchEdgeStack', {
  env: { account: env.account, region: 'us-east-1' },
  crossRegionReferences: true,
  allowedIpAddresses,
  description: 'Edge resources (us-east-1): WAF WebACL with IP allowlist for CloudFront',
});

const uiHostingStack = new GlitchUiHostingStack(app, 'GlitchUiHostingStack', {
  env,
  crossRegionReferences: true,
  gatewayFunction: gatewayStack.gatewayFunction,
  gatewayFunctionUrl: gatewayStack.functionUrl,
  customDomain,
  webAclArn: edgeStack.webAclArn,
  certificateArn: app.node.tryGetContext('cloudfrontCertArn') as string | undefined,
  description: 'UI hosting: S3 (OAC) + CloudFront + WAF + Lambda FURL (IAM+OAC)',
});
uiHostingStack.addDependency(gatewayStack);
uiHostingStack.addDependency(edgeStack);

// AgentCore policies stack (attaches policies to runtime role)
const agentCoreStack = new AgentCoreStack(app, 'GlitchAgentCoreStack', {
  env,
  runtimeRole: foundationStack.runtimeRole,
  description: 'AgentCore runtime policies (Glitch agent, PUBLIC mode)',
});
agentCoreStack.addDependency(foundationStack);

// Sentinel agent policies stack
const sentinelStack = new GlitchSentinelStack(app, 'GlitchSentinelStack', {
  env,
  runtimeRole: foundationStack.runtimeRole,
  glitchRuntimeArn: agentCoreRuntimeArn,
  description: 'Sentinel operations agent runtime policies',
});
sentinelStack.addDependency(foundationStack);
sentinelStack.addDependency(agentCoreStack);

cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');

app.synth();
