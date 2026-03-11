#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'yaml';
import { execSync } from 'child_process';
import {
  GlitchFoundationStack,
  GlitchProtectDbStack,
  AgentCoreStack,
  GlitchGatewayStack,
  GlitchEdgeStack,
  GlitchUiHostingStack,
  TelegramWebhookStack,
} from '../lib/stack';

/**
 * Detect the deploy machine's current public IPv4 address by calling an IP echo
 * service. Since CDK always runs on the home network, this gives the home IP
 * without any manual input or post-deploy webhook call.
 *
 * Tries three services in order; returns null if all fail (e.g. in CI without
 * outbound internet access, where allowedIpAddresses context override is used instead).
 */
function detectPublicIp(): string | null {
  const services = ['https://ifconfig.me', 'https://api.ipify.org', 'https://icanhazip.com'];
  for (const url of services) {
    try {
      const ip = execSync(`curl -sf --max-time 5 ${url}`, { encoding: 'utf8' }).trim();
      if (/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) {
        console.log(`[CDK] Detected public IP: ${ip} (via ${url})`);
        return ip;
      }
    } catch { /* try next service */ }
  }
  console.warn('[CDK] Could not detect public IP; falling back to SSM/context value');
  return null;
}

/**
 * Read AgentCore config from a .bedrock_agentcore.yaml to get runtime ARN.
 * Falls back to null if file is missing or ARN not set.
 */
function getAgentCoreRuntimeArn(agentName: string = 'Glitch', yamlDir: string = '../../agent'): string | null {
  const configPath = path.resolve(__dirname, yamlDir, '.bedrock_agentcore.yaml');
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
// PHASE 1: FOUNDATION (VPC + IAM Roles + SSM Parameters)
// Deploy first: cdk deploy GlitchFoundationStack
// ============================================================================

const foundationStack = new GlitchFoundationStack(app, 'GlitchFoundationStack', {
  env,
  description: 'Foundation: VPC, IAM roles, SSM parameters',
});

// ============================================================================
// PHASE 2: AGENT (run after Phase 1)
// Run: cd agent && python3 scripts/pre-deploy-configure.py && agentcore deploy
// This creates the AgentCore runtime and writes the ARN to .bedrock_agentcore.yaml
// ============================================================================

const agentCoreRuntimeArn =
  app.node.tryGetContext('glitchAgentCoreRuntimeArn') ??
  getAgentCoreRuntimeArn('Glitch', '../../agent') ??
  `arn:aws:bedrock-agentcore:${env.region}:${env.account}:runtime/Glitch-PLACEHOLDER`;

// ============================================================================
// PHASE 3: APPLICATION STACKS (deploy after Phase 2)
// Deploy all: cdk deploy --all
// ============================================================================

const protectDbStack = new GlitchProtectDbStack(app, 'GlitchProtectDbStack', {
  env,
  vpc: foundationStack.vpc,
  description: 'RDS Postgres (t4g.micro) for Protect tab — IAM auth, single-AZ',
});
protectDbStack.addDependency(foundationStack);

const gatewayStack = new GlitchGatewayStack(app, 'GlitchGatewayStack', {
  env,
  configTable: foundationStack.configTable,
  agentCoreRuntimeArn,
  vpc: foundationStack.vpc,
  agentcoreUtilsLayer: foundationStack.agentcoreUtilsLayer,
  description: 'Gateway Lambda (IAM-auth Function URL, /api/*, keepalive)',
});
gatewayStack.addDependency(foundationStack);

const telegramWebhookStack = new TelegramWebhookStack(app, 'GlitchTelegramWebhookStack', {
  env,
  configTable: foundationStack.configTable,
  telegramBotTokenSecret: foundationStack.telegramBotTokenSecret,
  agentCoreRuntimeArn,
  agentcoreUtilsLayer: foundationStack.agentcoreUtilsLayer,
  description: 'Telegram webhook Lambda + SSM webhook URL',
});
telegramWebhookStack.addDependency(foundationStack);

// Edge stack (us-east-1): WAF WebACL for CloudFront IP allowlisting.
//
// IP resolution order (first non-empty wins):
//   1. -c allowedIpAddresses=1.2.3.4/32   explicit override (useful in CI or for multiple IPs)
//   2. detectPublicIp()                    auto-detected from the deploy machine at synth time
//   3. GlitchEdgeStack SSM/fallback logic  reads /glitch/waf/allowed-ipv4 from SSM
//
// No manual steps needed: deploying from the home network auto-detects the correct IP.
const contextIps = ((app.node.tryGetContext('allowedIpAddresses') as string) ?? '')
  .split(',')
  .map((s: string) => s.trim())
  .filter(Boolean);

const detectedIp = detectPublicIp();
const allowedIpAddresses: string[] = contextIps.length > 0
  ? contextIps
  : detectedIp ? [`${detectedIp}/32`] : [];

const cloudfrontCertArn = app.node.tryGetContext('cloudfrontCertArn') as string | undefined;

const edgeStack = new GlitchEdgeStack(app, 'GlitchEdgeStack', {
  env: { account: env.account, region: 'us-east-1' },
  crossRegionReferences: true,
  allowedIpAddresses,
  description: 'Edge resources (us-east-1): WAF WebACL + DDNS updater webhook (us-east-1)',
});

const uiHostingStack = new GlitchUiHostingStack(app, 'GlitchUiHostingStack', {
  env,
  crossRegionReferences: true,
  gatewayFunction: gatewayStack.gatewayFunction,
  gatewayFunctionUrl: gatewayStack.functionUrl,
  customDomain,
  webAclArn: edgeStack.webAclArn,
  certificateArn: cloudfrontCertArn,
  description: 'UI hosting: S3 (OAC) + CloudFront + WAF + Lambda FURL (IAM+OAC)',
});
uiHostingStack.addDependency(gatewayStack);
uiHostingStack.addDependency(edgeStack);

// AgentCore policies stack (attaches policies to runtime role — includes ops capabilities)
const agentCoreStack = new AgentCoreStack(app, 'GlitchAgentCoreStack', {
  env,
  runtimeRole: foundationStack.runtimeRole,
  description: 'AgentCore runtime policies (Glitch merged agent, PUBLIC mode)',
});
agentCoreStack.addDependency(foundationStack);


cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');

app.synth();
