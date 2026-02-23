#!/usr/bin/env node
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import * as fs from 'fs';
import * as path from 'path';
import * as yaml from 'yaml';
import {
  VpcStack,
  AgentCoreIamStack,
  SecretsStack,
  TailscaleStack,
  AgentCoreStack,
  GlitchStorageStack,
  GlitchGatewayStack,
  GlitchUiHostingStack,
  GlitchCertificateStack,
  TelegramWebhookStack,
  StorageStackMigrationStack,
} from '../lib/stack';

/**
 * Read AgentCore config from .bedrock_agentcore.yaml to get runtime ARN and execution role.
 * Falls back to context or hardcoded defaults if file is missing.
 */
function getAgentCoreConfig(agentName: string = 'Glitch'): { runtimeArn: string | null; executionRoleArn: string | null } {
  const configPath = path.resolve(__dirname, '../../agent/.bedrock_agentcore.yaml');
  try {
    if (fs.existsSync(configPath)) {
      const content = fs.readFileSync(configPath, 'utf8');
      const config = yaml.parse(content);
      const agent = config?.agents?.[agentName];
      return {
        runtimeArn: agent?.bedrock_agentcore?.agent_arn ?? null,
        executionRoleArn: agent?.aws?.execution_role ?? null,
      };
    }
  } catch (e) {
    console.warn(`Warning: Could not read AgentCore config from ${configPath}:`, e);
  }
  return { runtimeArn: null, executionRoleArn: null };
}

const app = new cdk.App();

const env = {
  account: '999776382415',
  region: 'us-west-2',
};

// Custom domain configuration
const customDomain = 'glitch.awoo.agency';

// Read AgentCore config from .bedrock_agentcore.yaml
const agentCoreConfig = getAgentCoreConfig('Glitch');

const vpcStack = new VpcStack(app, 'GlitchVpcStack', {
  env,
  description: 'VPC infrastructure for AgentCore Glitch',
});

// Create AgentCore runtime role first so SecretsStack/StorageStack can attach policies (avoids IAM 404).
// Required: deploy GlitchAgentCoreIamStack before other stacks that reference the role. Use:
//   pnpm run deploy:iam-first   OR   cdk deploy GlitchAgentCoreIamStack && cdk deploy --all
const agentCoreIamStack = new AgentCoreIamStack(app, 'GlitchAgentCoreIamStack', {
  env,
  description: 'IAM role for AgentCore Runtime (created before SecretsStack)',
});
agentCoreIamStack.addDependency(vpcStack);

// AgentCore runtime ARN (from .bedrock_agentcore.yaml or context)
const agentCoreRuntimeArn =
  app.node.tryGetContext('glitchAgentCoreRuntimeArn') ??
  agentCoreConfig.runtimeArn;

if (!agentCoreRuntimeArn) {
  throw new Error(
    'AgentCore runtime ARN not found. Either:\n' +
    '  1. Deploy the agent first: cd agent && agentcore deploy\n' +
    '  2. Or pass via context: -c glitchAgentCoreRuntimeArn=arn:aws:bedrock-agentcore:...'
  );
}

const secretsStack = new SecretsStack(app, 'GlitchSecretsStack', {
  env,
  description: 'Secrets Manager configuration for AgentCore Glitch',
});

const storageStack = new GlitchStorageStack(app, 'GlitchStorageStack', {
  env,
  description: 'DynamoDB, S3, SSM, and telemetry log group for Glitch',
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
  description: 'Telegram webhook Lambda (receives updates, invokes AgentCore runtime)',
});
telegramWebhookStack.addDependency(storageStack);
telegramWebhookStack.addDependency(secretsStack);
// NOTE: Removed agentCoreIamStack dependency - TelegramWebhookStack now uses Fn.importValue instead of cross-stack ref

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
  agentCoreSecurityGroup: vpcStack.agentCoreSecurityGroup,
  agentCoreRuntimeArn,
  instanceBootstrapVersion: '8',
  gatewayFunctionUrl: gatewayStack.functionUrl,
  gatewayHostname: gatewayUrlHostname,
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

const agentCoreRuntimeRoleArn = app.node.tryGetContext('glitchAgentCoreRoleArn') as string | undefined;
const agentCoreStack = new AgentCoreStack(app, 'GlitchAgentCoreStack', {
  env,
  vpc: vpcStack.vpc,
  agentCoreSecurityGroup: vpcStack.agentCoreSecurityGroup,
  agentRuntimeRoleArn: agentCoreRuntimeRoleArn,
  description: 'AgentCore Runtime resources',
});
agentCoreStack.addDependency(vpcStack);
// NOTE: Removed agentCoreIamStack dependency - AgentCoreStack now uses Fn.importValue instead of cross-stack ref
agentCoreStack.addDependency(tailscaleStack);

// Telegram webhook custom resource attaches a policy to the runtime role; that role is owned by AgentCoreStack,
// so deploy AgentCoreStack first so the role exists when the custom resource runs.
telegramWebhookStack.addDependency(agentCoreStack);

// One-time migration: deploy this stack so GlitchStorageStack's old custom resource Deletes can succeed, then remove.
const storageMigrationStack = new StorageStackMigrationStack(app, 'GlitchStorageStackMigration', {
  env,
  description: 'One-time: creates legacy role so GlitchStorageStack custom resource deletes succeed. Delete this stack after StorageStack update.',
});

cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');

app.synth();
