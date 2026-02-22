#!/usr/bin/env node
"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
require("source-map-support/register");
const cdk = __importStar(require("aws-cdk-lib"));
const fs = __importStar(require("fs"));
const path = __importStar(require("path"));
const yaml = __importStar(require("yaml"));
const vpc_stack_1 = require("../lib/vpc-stack");
const secrets_stack_1 = require("../lib/secrets-stack");
const tailscale_stack_1 = require("../lib/tailscale-stack");
const agentcore_stack_1 = require("../lib/agentcore-stack");
const storage_stack_1 = require("../lib/storage-stack");
const gateway_stack_1 = require("../lib/gateway-stack");
const ui_hosting_stack_1 = require("../lib/ui-hosting-stack");
const certificate_stack_1 = require("../lib/certificate-stack");
const telegram_webhook_stack_1 = require("../lib/telegram-webhook-stack");
/**
 * Read AgentCore config from .bedrock_agentcore.yaml to get runtime ARN and execution role.
 * Falls back to context or hardcoded defaults if file is missing.
 */
function getAgentCoreConfig(agentName = 'Glitch') {
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
    }
    catch (e) {
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
const vpcStack = new vpc_stack_1.VpcStack(app, 'GlitchVpcStack', {
    env,
    description: 'VPC infrastructure for AgentCore Glitch',
});
// Default AgentCore SDK runtime role (from .bedrock_agentcore.yaml); grant it Telegram secret read
const defaultExecutionRoleArn = app.node.tryGetContext('glitchDefaultExecutionRoleArn') ??
    agentCoreConfig.executionRoleArn ??
    `arn:aws:iam::${env.account}:role/AmazonBedrockAgentCoreSDKRuntime-${env.region}-14980158e2`;
// AgentCore runtime ARN (from .bedrock_agentcore.yaml or context)
const agentCoreRuntimeArn = app.node.tryGetContext('glitchAgentCoreRuntimeArn') ??
    agentCoreConfig.runtimeArn;
if (!agentCoreRuntimeArn) {
    throw new Error('AgentCore runtime ARN not found. Either:\n' +
        '  1. Deploy the agent first: cd agent && agentcore deploy\n' +
        '  2. Or pass via context: -c glitchAgentCoreRuntimeArn=arn:aws:bedrock-agentcore:...');
}
const secretsStack = new secrets_stack_1.SecretsStack(app, 'GlitchSecretsStack', {
    env,
    defaultExecutionRoleArn,
    description: 'Secrets Manager configuration for AgentCore Glitch',
});
const storageStack = new storage_stack_1.GlitchStorageStack(app, 'GlitchStorageStack', {
    env,
    defaultExecutionRoleArn,
    description: 'DynamoDB, S3, SSM, and telemetry log group for Glitch',
});
const gatewayStack = new gateway_stack_1.GlitchGatewayStack(app, 'GlitchGatewayStack', {
    env,
    configTable: storageStack.configTable,
    agentCoreRuntimeArn,
    description: 'Gateway Lambda (invocations, /api/*, keepalive)',
});
gatewayStack.addDependency(storageStack);
const telegramWebhookStack = new telegram_webhook_stack_1.TelegramWebhookStack(app, 'GlitchTelegramWebhookStack', {
    env,
    configTable: storageStack.configTable,
    telegramBotTokenSecret: secretsStack.telegramBotTokenSecret,
    agentCoreRuntimeArn,
    defaultExecutionRoleArn,
    description: 'Telegram webhook Lambda (receives updates, invokes AgentCore runtime)',
});
telegramWebhookStack.addDependency(storageStack);
telegramWebhookStack.addDependency(secretsStack);
// Extract hostname from Lambda Function URL (https://xxx.lambda-url.region.on.aws/)
const gatewayUrlHostname = cdk.Fn.select(2, cdk.Fn.split('/', gatewayStack.functionUrl));
// Certificate stack in us-east-1 (required for CloudFront)
const certificateStack = new certificate_stack_1.GlitchCertificateStack(app, 'GlitchCertificateStack', {
    env: { account: env.account, region: 'us-east-1' },
    domainName: customDomain,
    crossRegionReferences: true,
    description: 'ACM certificate for CloudFront custom domain (us-east-1)',
});
const uiHostingStack = new ui_hosting_stack_1.GlitchUiHostingStack(app, 'GlitchUiHostingStack', {
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
const tailscaleStack = new tailscale_stack_1.TailscaleStack(app, 'GlitchTailscaleStack', {
    env,
    vpc: vpcStack.vpc,
    tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
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
const agentCoreStack = new agentcore_stack_1.AgentCoreStack(app, 'GlitchAgentCoreStack', {
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLHVDQUFxQztBQUNyQyxpREFBbUM7QUFDbkMsdUNBQXlCO0FBQ3pCLDJDQUE2QjtBQUM3QiwyQ0FBNkI7QUFDN0IsZ0RBQTRDO0FBQzVDLHdEQUFvRDtBQUNwRCw0REFBd0Q7QUFDeEQsNERBQXdEO0FBQ3hELHdEQUEwRDtBQUMxRCx3REFBMEQ7QUFDMUQsOERBQStEO0FBQy9ELGdFQUFrRTtBQUNsRSwwRUFBcUU7QUFFckU7OztHQUdHO0FBQ0gsU0FBUyxrQkFBa0IsQ0FBQyxZQUFvQixRQUFRO0lBQ3RELE1BQU0sVUFBVSxHQUFHLElBQUksQ0FBQyxPQUFPLENBQUMsU0FBUyxFQUFFLHFDQUFxQyxDQUFDLENBQUM7SUFDbEYsSUFBSSxDQUFDO1FBQ0gsSUFBSSxFQUFFLENBQUMsVUFBVSxDQUFDLFVBQVUsQ0FBQyxFQUFFLENBQUM7WUFDOUIsTUFBTSxPQUFPLEdBQUcsRUFBRSxDQUFDLFlBQVksQ0FBQyxVQUFVLEVBQUUsTUFBTSxDQUFDLENBQUM7WUFDcEQsTUFBTSxNQUFNLEdBQUcsSUFBSSxDQUFDLEtBQUssQ0FBQyxPQUFPLENBQUMsQ0FBQztZQUNuQyxNQUFNLEtBQUssR0FBRyxNQUFNLEVBQUUsTUFBTSxFQUFFLENBQUMsU0FBUyxDQUFDLENBQUM7WUFDMUMsT0FBTztnQkFDTCxVQUFVLEVBQUUsS0FBSyxFQUFFLGlCQUFpQixFQUFFLFNBQVMsSUFBSSxJQUFJO2dCQUN2RCxnQkFBZ0IsRUFBRSxLQUFLLEVBQUUsR0FBRyxFQUFFLGNBQWMsSUFBSSxJQUFJO2FBQ3JELENBQUM7UUFDSixDQUFDO0lBQ0gsQ0FBQztJQUFDLE9BQU8sQ0FBQyxFQUFFLENBQUM7UUFDWCxPQUFPLENBQUMsSUFBSSxDQUFDLGlEQUFpRCxVQUFVLEdBQUcsRUFBRSxDQUFDLENBQUMs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WUFBWSxDQUFDLENBQUM7QUFDM0MsY0FBYyxDQUFDLGFBQWEsQ0FBQyxjQUFjLENBQUMsQ0FBQztBQUU3QyxNQUFNLGNBQWMsR0FBRyxJQUFJLGdDQUFjLENBQUMsR0FBRyxFQUFFLHNCQUFzQixFQUFFO0lBQ3JFLEdBQUc7SUFDSCxHQUFHLEVBQUUsUUFBUSxDQUFDLEdBQUc7SUFDakIsc0JBQXNCLEVBQUUsY0FBYyxDQUFDLGFBQWE7SUFDcEQsYUFBYSxFQUFFLFlBQVksQ0FBQyxhQUFhO0lBQ3pDLHNCQUFzQixFQUFFLFlBQVksQ0FBQyxzQkFBc0I7SUFDM0QsV0FBVyxFQUFFLDZCQUE2QjtDQUMzQyxDQUFDLENBQUM7QUFDSCxjQUFjLENBQUMsYUFBYSxDQUFDLFFBQVEsQ0FBQyxDQUFDO0FBQ3ZDLGNBQWMsQ0FBQyxhQUFhLENBQUMsWUFBWSxDQUFDLENBQUM7QUFDM0MsY0FBYyxDQUFDLGFBQWEsQ0FBQyxjQUFjLENBQUMsQ0FBQztBQUU3QyxHQUFHLENBQUMsSUFBSSxDQUFDLEVBQUUsQ0FBQyxHQUFHLENBQUMsQ0FBQyxHQUFHLENBQUMsU0FBUyxFQUFFLGtCQUFrQixDQUFDLENBQUM7QUFDcEQsR0FBRyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsR0FBRyxDQUFDLENBQUMsR0FBRyxDQUFDLFdBQVcsRUFBRSxLQUFLLENBQUMsQ0FBQztBQUV6QyxHQUFHLENBQUMsS0FBSyxFQUFFLENBQUMiLCJzb3VyY2VzQ29udGVudCI6WyIjIS91c3IvYmluL2VudiBub2RlXG5pbXBvcnQgJ3NvdXJjZS1tYXAtc3VwcG9ydC9yZWdpc3Rlcic7XG5pbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0ICogYXMgZnMgZnJvbSAnZnMnO1xuaW1wb3J0ICogYXMgcGF0aCBmcm9tICdwYXRoJztcbmltcG9ydCAqIGFzIHlhbWwgZnJvbSAneWFtbCc7XG5pbXBvcnQgeyBWcGNTdGFjayB9IGZyb20gJy4uL2xpYi92cGMtc3RhY2snO1xuaW1wb3J0IHsgU2VjcmV0c1N0YWNrIH0gZnJvbSAnLi4vbGliL3NlY3JldHMtc3RhY2snO1xuaW1wb3J0IHsgVGFpbHNjYWxlU3RhY2sgfSBmcm9tICcuLi9saWIvdGFpbHNjYWxlLXN0YWNrJztcbmltcG9ydCB7IEFnZW50Q29yZVN0YWNrIH0gZnJvbSAnLi4vbGliL2FnZW50Y29yZS1zdGFjayc7XG5pbXBvcnQgeyBHbGl0Y2hTdG9yYWdlU3RhY2sgfSBmcm9tICcuLi9saWIvc3RvcmFnZS1zdGFjayc7XG5pbXBvcnQgeyBHbGl0Y2hHYXRld2F5U3RhY2sgfSBmcm9tICcuLi9saWIvZ2F0ZXdheS1zdGFjayc7XG5pbXBvcnQgeyBHbGl0Y2hVaUhvc3RpbmdTdGFjayB9IGZyb20gJy4uL2xpYi91aS1ob3N0aW5nLXN0YWNrJztcbmltcG9ydCB7IEdsaXRjaENlcnRpZmljYXRlU3RhY2sgfSBmcm9tICcuLi9saWIvY2VydGlmaWNhdGUtc3RhY2snO1xuaW1wb3J0IHsgVGVsZWdyYW1XZWJob29rU3RhY2sgfSBmcm9tICcuLi9saWIvdGVsZWdyYW0td2ViaG9vay1zdGFjayc7XG5cbi8qKlxuICogUmVhZCBBZ2VudENvcmUgY29uZmlnIGZyb20gLmJlZHJvY2tfYWdlbnRjb3JlLnlhbWwgdG8gZ2V0IHJ1bnRpbWUgQVJOIGFuZCBleGVjdXRpb24gcm9sZS5cbiAqIEZhbGxzIGJhY2sgdG8gY29udGV4dCBvciBoYXJkY29kZWQgZGVmYXVsdHMgaWYgZmlsZSBpcyBtaXNzaW5nLlxuICovXG5mdW5jdGlvbiBnZXRBZ2VudENvcmVDb25maWcoYWdlbnROYW1lOiBzdHJpbmcgPSAnR2xpdGNoJyk6IHsgcnVudGltZUFybjogc3RyaW5nIHwgbnVsbDsgZXhlY3V0aW9uUm9sZUFybjogc3RyaW5nIHwgbnVsbCB9IHtcbiAgY29uc3QgY29uZmlnUGF0aCA9IHBhdGgucmVzb2x2ZShfX2Rpcm5hbWUsICcuLi8uLi9hZ2VudC8uYmVkcm9ja19hZ2VudGNvcmUueWFtbCcpO1xuICB0cnkge1xuICAgIGlmIChmcy5leGlzdHNTeW5jKGNvbmZpZ1BhdGgpKSB7XG4gICAgICBjb25zdCBjb250ZW50ID0gZnMucmVhZEZpbGVTeW5jKGNvbmZpZ1BhdGgsICd1dGY4Jyk7XG4gICAgICBjb25zdCBjb25maWcgPSB5YW1sLnBhcnNlKGNvbnRlbnQpO1xuICAgICAgY29uc3QgYWdlbnQgPSBjb25maWc/LmFnZW50cz8uW2FnZW50TmFtZV07XG4gICAgICByZXR1cm4ge1xuICAgICAgICBydW50aW1lQXJuOiBhZ2VudD8uYmVkcm9ja19hZ2VudGNvcmU/LmFnZW50X2FybiA/PyBudWxsLFxuICAgICAgICBleGVjdXRpb25Sb2xlQXJuOiBhZ2VudD8uYXdzPy5leGVjdXRpb25fcm9sZSA/PyBudWxsLFxuICAgICAgfTtcbiAgICB9XG4gIH0gY2F0Y2ggKGUpIHtcbiAgICBjb25zb2xlLndhcm4oYFdhcm5pbmc6IENvdWxkIG5vdCByZWFkIEFnZW50Q29yZSBjb25maWcgZnJvbSAke2NvbmZpZ1BhdGh9OmAsIGUpO1xuICB9XG4gIHJldHVybiB7IHJ1bnRpbWVBcm46IG51bGwsIGV4ZWN1dGlvblJvbGVBcm46IG51bGwgfTtcbn1cblxuY29uc3QgYXBwID0gbmV3IGNkay5BcHAoKTtcblxuY29uc3QgZW52ID0ge1xuICBhY2NvdW50OiAnOTk5Nzc2MzgyNDE1JyxcbiAgcmVnaW9uOiAndXMtd2VzdC0yJyxcbn07XG5cbi8vIEN1c3RvbSBkb21haW4gY29uZmlndXJhdGlvblxuY29uc3QgY3VzdG9tRG9tYWluID0gJ2dsaXRjaC5hd29vLmFnZW5jeSc7XG5cbi8vIFJlYWQgQWdlbnRDb3JlIGNvbmZpZyBmcm9tIC5iZWRyb2NrX2FnZW50Y29yZS55YW1sXG5jb25zdCBhZ2VudENvcmVDb25maWcgPSBnZXRBZ2VudENvcmVDb25maWcoJ0dsaXRjaCcpO1xuXG5jb25zdCB2cGNTdGFjayA9IG5ldyBWcGNTdGFjayhhcHAsICdHbGl0Y2hWcGNTdGFjaycsIHtcbiAgZW52LFxuICBkZXNjcmlwdGlvbjogJ1ZQQyBpbmZyYXN0cnVjdHVyZSBmb3IgQWdlbnRDb3JlIEdsaXRjaCcsXG59KTtcblxuLy8gRGVmYXVsdCBBZ2VudENvcmUgU0RLIHJ1bnRpbWUgcm9sZSAoZnJvbSAuYmVkcm9ja19hZ2VudGNvcmUueWFtbCk7IGdyYW50IGl0IFRlbGVncmFtIHNlY3JldCByZWFkXG5jb25zdCBkZWZhdWx0RXhlY3V0aW9uUm9sZUFybiA9XG4gIGFwcC5ub2RlLnRyeUdldENvbnRleHQoJ2dsaXRjaERlZmF1bHRFeGVjdXRpb25Sb2xlQXJuJykgPz9cbiAgYWdlbnRDb3JlQ29uZmlnLmV4ZWN1dGlvblJvbGVBcm4gPz9cbiAgYGFybjphd3M6aWFtOjoke2Vudi5hY2NvdW50fTpyb2xlL0FtYXpvbkJlZHJvY2tBZ2VudENvcmVTREtSdW50aW1lLSR7ZW52LnJlZ2lvbn0tMTQ5ODAxNThlMmA7XG5cbi8vIEFnZW50Q29yZSBydW50aW1lIEFSTiAoZnJvbSAuYmVkcm9ja19hZ2VudGNvcmUueWFtbCBvciBjb250ZXh0KVxuY29uc3QgYWdlbnRDb3JlUnVudGltZUFybiA9XG4gIGFwcC5ub2RlLnRyeUdldENvbnRleHQoJ2dsaXRjaEFnZW50Q29yZVJ1bnRpbWVBcm4nKSA/P1xuICBhZ2VudENvcmVDb25maWcucnVudGltZUFybjtcblxuaWYgKCFhZ2VudENvcmVSdW50aW1lQXJuKSB7XG4gIHRocm93IG5ldyBFcnJvcihcbiAgICAnQWdlbnRDb3JlIHJ1bnRpbWUgQVJOIG5vdCBmb3VuZC4gRWl0aGVyOlxcbicgK1xuICAgICcgIDEuIERlcGxveSB0aGUgYWdlbnQgZmlyc3Q6IGNkIGFnZW50ICYmIGFnZW50Y29yZSBkZXBsb3lcXG4nICtcbiAgICAnICAyLiBPciBwYXNzIHZpYSBjb250ZXh0OiAtYyBnbGl0Y2hBZ2VudENvcmVSdW50aW1lQXJuPWFybjphd3M6YmVkcm9jay1hZ2VudGNvcmU6Li4uJ1xuICApO1xufVxuXG5jb25zdCBzZWNyZXRzU3RhY2sgPSBuZXcgU2VjcmV0c1N0YWNrKGFwcCwgJ0dsaXRjaFNlY3JldHNTdGFjaycsIHtcbiAgZW52LFxuICBkZWZhdWx0RXhlY3V0aW9uUm9sZUFybixcbiAgZGVzY3JpcHRpb246ICdTZWNyZXRzIE1hbmFnZXIgY29uZmlndXJhdGlvbiBmb3IgQWdlbnRDb3JlIEdsaXRjaCcsXG59KTtcblxuY29uc3Qgc3RvcmFnZVN0YWNrID0gbmV3IEdsaXRjaFN0b3JhZ2VTdGFjayhhcHAsICdHbGl0Y2hTdG9yYWdlU3RhY2snLCB7XG4gIGVudixcbiAgZGVmYXVsdEV4ZWN1dGlvblJvbGVBcm4sXG4gIGRlc2NyaXB0aW9uOiAnRHluYW1vREIsIFMzLCBTU00sIGFuZCB0ZWxlbWV0cnkgbG9nIGdyb3VwIGZvciBHbGl0Y2gnLFxufSk7XG5cbmNvbnN0IGdhdGV3YXlTdGFjayA9IG5ldyBHbGl0Y2hHYXRld2F5U3RhY2soYXBwLCAnR2xpdGNoR2F0ZXdheVN0YWNrJywge1xuICBlbnYsXG4gIGNvbmZpZ1RhYmxlOiBzdG9yYWdlU3RhY2suY29uZmlnVGFibGUsXG4gIGFnZW50Q29yZVJ1bnRpbWVBcm4sXG4gIGRlc2NyaXB0aW9uOiAnR2F0ZXdheSBMYW1iZGEgKGludm9jYXRpb25zLCAvYXBpLyosIGtlZXBhbGl2ZSknLFxufSk7XG5nYXRld2F5U3RhY2suYWRkRGVwZW5kZW5jeShzdG9yYWdlU3RhY2spO1xuXG5jb25zdCB0ZWxlZ3JhbVdlYmhvb2tTdGFjayA9IG5ldyBUZWxlZ3JhbVdlYmhvb2tTdGFjayhhcHAsICdHbGl0Y2hUZWxlZ3JhbVdlYmhvb2tTdGFjaycsIHtcbiAgZW52LFxuICBjb25maWdUYWJsZTogc3RvcmFnZVN0YWNrLmNvbmZpZ1RhYmxlLFxuICB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzU3RhY2sudGVsZWdyYW1Cb3RUb2tlblNlY3JldCxcbiAgYWdlbnRDb3JlUnVudGltZUFybixcbiAgZGVmYXVsdEV4ZWN1dGlvblJvbGVBcm4sXG4gIGRlc2NyaXB0aW9uOiAnVGVsZWdyYW0gd2ViaG9vayBMYW1iZGEgKHJlY2VpdmVzIHVwZGF0ZXMsIGludm9rZXMgQWdlbnRDb3JlIHJ1bnRpbWUpJyxcbn0pO1xudGVsZWdyYW1XZWJob29rU3RhY2suYWRkRGVwZW5kZW5jeShzdG9yYWdlU3RhY2spO1xudGVsZWdyYW1XZWJob29rU3RhY2suYWRkRGVwZW5kZW5jeShzZWNyZXRzU3RhY2spO1xuXG4vLyBFeHRyYWN0IGhvc3RuYW1lIGZyb20gTGFtYmRhIEZ1bmN0aW9uIFVSTCAoaHR0cHM6Ly94eHgubGFtYmRhLXVybC5yZWdpb24ub24uYXdzLylcbmNvbnN0IGdhdGV3YXlVcmxIb3N0bmFtZSA9IGNkay5Gbi5zZWxlY3QoXG4gIDIsXG4gIGNkay5Gbi5zcGxpdCgnLycsIGdhdGV3YXlTdGFjay5mdW5jdGlvblVybClcbik7XG5cbi8vIENlcnRpZmljYXRlIHN0YWNrIGluIHVzLWVhc3QtMSAocmVxdWlyZWQgZm9yIENsb3VkRnJvbnQpXG5jb25zdCBjZXJ0aWZpY2F0ZVN0YWNrID0gbmV3IEdsaXRjaENlcnRpZmljYXRlU3RhY2soYXBwLCAnR2xpdGNoQ2VydGlmaWNhdGVTdGFjaycsIHtcbiAgZW52OiB7IGFjY291bnQ6IGVudi5hY2NvdW50LCByZWdpb246ICd1cy1lYXN0LTEnIH0sXG4gIGRvbWFpbk5hbWU6IGN1c3RvbURvbWFpbixcbiAgY3Jvc3NSZWdpb25SZWZlcmVuY2VzOiB0cnVlLFxuICBkZXNjcmlwdGlvbjogJ0FDTSBjZXJ0aWZpY2F0ZSBmb3IgQ2xvdWRGcm9udCBjdXN0b20gZG9tYWluICh1cy1lYXN0LTEpJyxcbn0pO1xuXG5jb25zdCB1aUhvc3RpbmdTdGFjayA9IG5ldyBHbGl0Y2hVaUhvc3RpbmdTdGFjayhhcHAsICdHbGl0Y2hVaUhvc3RpbmdTdGFjaycsIHtcbiAgZW52LFxuICBnYXRld2F5RnVuY3Rpb25VcmxIb3N0bmFtZTogZ2F0ZXdheVVybEhvc3RuYW1lLFxuICBkb21haW5OYW1lOiBjdXN0b21Eb21haW4sXG4gIGNlcnRpZmljYXRlQXJuOiBjZXJ0aWZpY2F0ZVN0YWNrLmNlcnRpZmljYXRlLmNlcnRpZmljYXRlQXJuLFxuICBjcm9zc1JlZ2lvblJlZmVyZW5jZXM6IHRydWUsXG4gIGRlc2NyaXB0aW9uOiAnUzMgKyBDbG91ZEZyb250IGhvc3RpbmcgZm9yIEdsaXRjaCBVSScsXG59KTtcbnVpSG9zdGluZ1N0YWNrLmFkZERlcGVuZGVuY3koZ2F0ZXdheVN0YWNrKTtcbnVpSG9zdGluZ1N0YWNrLmFkZERlcGVuZGVuY3koY2VydGlmaWNhdGVTdGFjayk7XG5cbi8vIEJ1bXAgaW5zdGFuY2VCb290c3RyYXBWZXJzaW9uIChlLmcuIHRvICc4JykgdG8gZm9yY2UgRUMyIGluc3RhbmNlIHJlcGxhY2VtZW50IG9uIG5leHQgZGVwbG95LlxuY29uc3QgdGFpbHNjYWxlU3RhY2sgPSBuZXcgVGFpbHNjYWxlU3RhY2soYXBwLCAnR2xpdGNoVGFpbHNjYWxlU3RhY2snLCB7XG4gIGVudixcbiAgdnBjOiB2cGNTdGFjay52cGMsXG4gIHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQ6IHNlY3JldHNTdGFjay50YWlsc2NhbGVBdXRoS2V5U2VjcmV0LFxuICBhZ2VudENvcmVSdW50aW1lQXJuLFxuICBpbnN0YW5jZUJvb3RzdHJhcFZlcnNpb246ICc4JyxcbiAgZ2F0ZXdheUZ1bmN0aW9uVXJsOiBnYXRld2F5U3RhY2suZnVuY3Rpb25VcmwsXG4gIGdhdGV3YXlIb3N0bmFtZTogZ2F0ZXdheVVybEhvc3RuYW1lLFxuICB1aUJ1Y2tldE5hbWU6IHVpSG9zdGluZ1N0YWNrLnVpQnVja2V0LmJ1Y2tldE5hbWUsXG4gIGN1c3RvbURvbWFpbixcbiAgcG9ya2J1bkFwaVNlY3JldDogc2VjcmV0c1N0YWNrLnBvcmtidW5BcGlTZWNyZXQsXG4gIGNlcnRib3RFbWFpbDogJ2FkbWluQGF3b28uYWdlbmN5JyxcbiAgZGVzY3JpcHRpb246ICdFQzIgVGFpbHNjYWxlIGNvbm5lY3RvciBhbmQgVUkgcHJveHkgKG5naW54ICsgTGV0XFwncyBFbmNyeXB0IFRMUyknLFxufSk7XG50YWlsc2NhbGVTdGFjay5hZGREZXBlbmRlbmN5KHZwY1N0YWNrKTtcbnRhaWxzY2FsZVN0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcbnRhaWxzY2FsZVN0YWNrLmFkZERlcGVuZGVuY3koZ2F0ZXdheVN0YWNrKTtcbnRhaWxzY2FsZVN0YWNrLmFkZERlcGVuZGVuY3kodWlIb3N0aW5nU3RhY2spO1xuXG5jb25zdCBhZ2VudENvcmVTdGFjayA9IG5ldyBBZ2VudENvcmVTdGFjayhhcHAsICdHbGl0Y2hBZ2VudENvcmVTdGFjaycsIHtcbiAgZW52LFxuICB2cGM6IHZwY1N0YWNrLnZwYyxcbiAgdGFpbHNjYWxlU2VjdXJpdHlHcm91cDogdGFpbHNjYWxlU3RhY2suc2VjdXJpdHlHcm91cCxcbiAgYXBpS2V5c1NlY3JldDogc2VjcmV0c1N0YWNrLmFwaUtleXNTZWNyZXQsXG4gIHRlbGVncmFtQm90VG9rZW5TZWNyZXQ6IHNlY3JldHNTdGFjay50ZWxlZ3JhbUJvdFRva2VuU2VjcmV0LFxuICBkZXNjcmlwdGlvbjogJ0FnZW50Q29yZSBSdW50aW1lIHJlc291cmNlcycsXG59KTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3kodnBjU3RhY2spO1xuYWdlbnRDb3JlU3RhY2suYWRkRGVwZW5kZW5jeShzZWNyZXRzU3RhY2spO1xuYWdlbnRDb3JlU3RhY2suYWRkRGVwZW5kZW5jeSh0YWlsc2NhbGVTdGFjayk7XG5cbmNkay5UYWdzLm9mKGFwcCkuYWRkKCdQcm9qZWN0JywgJ0FnZW50Q29yZS1HbGl0Y2gnKTtcbmNkay5UYWdzLm9mKGFwcCkuYWRkKCdNYW5hZ2VkQnknLCAnQ0RLJyk7XG5cbmFwcC5zeW50aCgpO1xuIl19