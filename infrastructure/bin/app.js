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
const vpc_stack_1 = require("../lib/vpc-stack");
const secrets_stack_1 = require("../lib/secrets-stack");
const tailscale_stack_1 = require("../lib/tailscale-stack");
const agentcore_stack_1 = require("../lib/agentcore-stack");
const storage_stack_1 = require("../lib/storage-stack");
const gateway_stack_1 = require("../lib/gateway-stack");
const ui_hosting_stack_1 = require("../lib/ui-hosting-stack");
const certificate_stack_1 = require("../lib/certificate-stack");
const app = new cdk.App();
const env = {
    account: '999776382415',
    region: 'us-west-2',
};
// Custom domain configuration
const customDomain = 'glitch.awoo.agency';
const vpcStack = new vpc_stack_1.VpcStack(app, 'GlitchVpcStack', {
    env,
    description: 'VPC infrastructure for AgentCore Glitch',
});
// Default AgentCore SDK runtime role (from .bedrock_agentcore.yaml); grant it Telegram secret read
const defaultExecutionRoleArn = app.node.tryGetContext('glitchDefaultExecutionRoleArn') ??
    `arn:aws:iam::${env.account}:role/AmazonBedrockAgentCoreSDKRuntime-${env.region}-14980158e2`;
// AgentCore runtime ARN (from .bedrock_agentcore.yaml or agentcore runtime list)
const agentCoreRuntimeArn = app.node.tryGetContext('glitchAgentCoreRuntimeArn') ??
    `arn:aws:bedrock-agentcore:${env.region}:${env.account}:runtime/Glitch-78q5TgEa8M`;
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
// Bump instanceBootstrapVersion (e.g. to '6') to force EC2 instance replacement on next deploy.
const tailscaleStack = new tailscale_stack_1.TailscaleStack(app, 'GlitchTailscaleStack', {
    env,
    vpc: vpcStack.vpc,
    tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
    agentCoreRuntimeArn,
    instanceBootstrapVersion: '6',
    gatewayFunctionUrl: gatewayStack.functionUrl,
    uiBucketName: uiHostingStack.uiBucket.bucketName,
    description: 'EC2 Tailscale connector and UI proxy (nginx + Tailscale Serve)',
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLHVDQUFxQztBQUNyQyxpREFBbUM7QUFDbkMsZ0RBQTRDO0FBQzVDLHdEQUFvRDtBQUNwRCw0REFBd0Q7QUFDeEQsNERBQXdEO0FBQ3hELHdEQUEwRDtBQUMxRCx3REFBMEQ7QUFDMUQsOERBQStEO0FBQy9ELGdFQUFrRTtBQUVsRSxNQUFNLEdBQUcsR0FBRyxJQUFJLEdBQUcsQ0FBQyxHQUFHLEVBQUUsQ0FBQztBQUUxQixNQUFNLEdBQUcsR0FBRztJQUNWLE9BQU8sRUFBRSxjQUFjO0lBQ3ZCLE1BQU0sRUFBRSxXQUFXO0NBQ3BCLENBQUM7QUFFRiw4QkFBOEI7QUFDOUIsTUFBTSxZQUFZLEdBQUcsb0JBQW9CLENBQUM7QUFFMUMsTUFBTSxRQUFRLEdBQUcsSUFBSSxvQkFBUSxDQUFDLEdBQUcsRUFBRSxnQkFBZ0IsRUFBRTtJQUNuRCxHQUFHO0lBQ0gsV0FBVyxFQUFFLHlDQUF5QztDQUN2RCxDQUFDLENBQUM7QUFFSCxtR0FBbUc7QUFDbkcsTUFBTSx1QkFBdUIsR0FDM0IsR0FBRyxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsK0JBQStCLENBQUM7SUFDdkQsZ0JBQWdCLEdBQUcsQ0FBQyxPQUFPLDBDQUEwQyxHQUFHLENBQUMsTUFBTSxhQUFhLENBQUM7QUFFL0YsaUZBQWlGO0FBQ2pGLE1BQU0sbUJBQW1CLEdBQ3ZCLEdBQUcsQ0FBQyxJQUFJLENBQUMsYUFBYSxDQUFDLDJCQUEyQixDQUFDO0lBQ25ELDZCQUE2QixHQUFHLENBQUMsTUFBTSxJQUFJLEdBQUcsQ0FBQyxPQUFPLDRCQUE0QixDQUFDO0FBRXJGLE1BQU0sWUFBWSxHQUFHLElBQUksNEJBQVksQ0FBQyxHQUFHLEVBQUUsb0JBQW9CLEVBQUU7SUFDL0QsR0FBRztJQUNILHVCQUF1QjtJQUN2QixXQUFX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QUFDM0MsY0FBYyxDQUFDLGFBQWEsQ0FBQyxjQUFjLENBQUMsQ0FBQztBQUU3QyxHQUFHLENBQUMsSUFBSSxDQUFDLEVBQUUsQ0FBQyxHQUFHLENBQUMsQ0FBQyxHQUFHLENBQUMsU0FBUyxFQUFFLGtCQUFrQixDQUFDLENBQUM7QUFDcEQsR0FBRyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsR0FBRyxDQUFDLENBQUMsR0FBRyxDQUFDLFdBQVcsRUFBRSxLQUFLLENBQUMsQ0FBQztBQUV6QyxHQUFHLENBQUMsS0FBSyxFQUFFLENBQUMiLCJzb3VyY2VzQ29udGVudCI6WyIjIS91c3IvYmluL2VudiBub2RlXG5pbXBvcnQgJ3NvdXJjZS1tYXAtc3VwcG9ydC9yZWdpc3Rlcic7XG5pbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0IHsgVnBjU3RhY2sgfSBmcm9tICcuLi9saWIvdnBjLXN0YWNrJztcbmltcG9ydCB7IFNlY3JldHNTdGFjayB9IGZyb20gJy4uL2xpYi9zZWNyZXRzLXN0YWNrJztcbmltcG9ydCB7IFRhaWxzY2FsZVN0YWNrIH0gZnJvbSAnLi4vbGliL3RhaWxzY2FsZS1zdGFjayc7XG5pbXBvcnQgeyBBZ2VudENvcmVTdGFjayB9IGZyb20gJy4uL2xpYi9hZ2VudGNvcmUtc3RhY2snO1xuaW1wb3J0IHsgR2xpdGNoU3RvcmFnZVN0YWNrIH0gZnJvbSAnLi4vbGliL3N0b3JhZ2Utc3RhY2snO1xuaW1wb3J0IHsgR2xpdGNoR2F0ZXdheVN0YWNrIH0gZnJvbSAnLi4vbGliL2dhdGV3YXktc3RhY2snO1xuaW1wb3J0IHsgR2xpdGNoVWlIb3N0aW5nU3RhY2sgfSBmcm9tICcuLi9saWIvdWktaG9zdGluZy1zdGFjayc7XG5pbXBvcnQgeyBHbGl0Y2hDZXJ0aWZpY2F0ZVN0YWNrIH0gZnJvbSAnLi4vbGliL2NlcnRpZmljYXRlLXN0YWNrJztcblxuY29uc3QgYXBwID0gbmV3IGNkay5BcHAoKTtcblxuY29uc3QgZW52ID0ge1xuICBhY2NvdW50OiAnOTk5Nzc2MzgyNDE1JyxcbiAgcmVnaW9uOiAndXMtd2VzdC0yJyxcbn07XG5cbi8vIEN1c3RvbSBkb21haW4gY29uZmlndXJhdGlvblxuY29uc3QgY3VzdG9tRG9tYWluID0gJ2dsaXRjaC5hd29vLmFnZW5jeSc7XG5cbmNvbnN0IHZwY1N0YWNrID0gbmV3IFZwY1N0YWNrKGFwcCwgJ0dsaXRjaFZwY1N0YWNrJywge1xuICBlbnYsXG4gIGRlc2NyaXB0aW9uOiAnVlBDIGluZnJhc3RydWN0dXJlIGZvciBBZ2VudENvcmUgR2xpdGNoJyxcbn0pO1xuXG4vLyBEZWZhdWx0IEFnZW50Q29yZSBTREsgcnVudGltZSByb2xlIChmcm9tIC5iZWRyb2NrX2FnZW50Y29yZS55YW1sKTsgZ3JhbnQgaXQgVGVsZWdyYW0gc2VjcmV0IHJlYWRcbmNvbnN0IGRlZmF1bHRFeGVjdXRpb25Sb2xlQXJuID1cbiAgYXBwLm5vZGUudHJ5R2V0Q29udGV4dCgnZ2xpdGNoRGVmYXVsdEV4ZWN1dGlvblJvbGVBcm4nKSA/P1xuICBgYXJuOmF3czppYW06OiR7ZW52LmFjY291bnR9OnJvbGUvQW1hem9uQmVkcm9ja0FnZW50Q29yZVNES1J1bnRpbWUtJHtlbnYucmVnaW9ufS0xNDk4MDE1OGUyYDtcblxuLy8gQWdlbnRDb3JlIHJ1bnRpbWUgQVJOIChmcm9tIC5iZWRyb2NrX2FnZW50Y29yZS55YW1sIG9yIGFnZW50Y29yZSBydW50aW1lIGxpc3QpXG5jb25zdCBhZ2VudENvcmVSdW50aW1lQXJuID1cbiAgYXBwLm5vZGUudHJ5R2V0Q29udGV4dCgnZ2xpdGNoQWdlbnRDb3JlUnVudGltZUFybicpID8/XG4gIGBhcm46YXdzOmJlZHJvY2stYWdlbnRjb3JlOiR7ZW52LnJlZ2lvbn06JHtlbnYuYWNjb3VudH06cnVudGltZS9HbGl0Y2gtNzhxNVRnRWE4TWA7XG5cbmNvbnN0IHNlY3JldHNTdGFjayA9IG5ldyBTZWNyZXRzU3RhY2soYXBwLCAnR2xpdGNoU2VjcmV0c1N0YWNrJywge1xuICBlbnYsXG4gIGRlZmF1bHRFeGVjdXRpb25Sb2xlQXJuLFxuICBkZXNjcmlwdGlvbjogJ1NlY3JldHMgTWFuYWdlciBjb25maWd1cmF0aW9uIGZvciBBZ2VudENvcmUgR2xpdGNoJyxcbn0pO1xuXG5jb25zdCBzdG9yYWdlU3RhY2sgPSBuZXcgR2xpdGNoU3RvcmFnZVN0YWNrKGFwcCwgJ0dsaXRjaFN0b3JhZ2VTdGFjaycsIHtcbiAgZW52LFxuICBkZWZhdWx0RXhlY3V0aW9uUm9sZUFybixcbiAgZGVzY3JpcHRpb246ICdEeW5hbW9EQiwgUzMsIFNTTSwgYW5kIHRlbGVtZXRyeSBsb2cgZ3JvdXAgZm9yIEdsaXRjaCcsXG59KTtcblxuY29uc3QgZ2F0ZXdheVN0YWNrID0gbmV3IEdsaXRjaEdhdGV3YXlTdGFjayhhcHAsICdHbGl0Y2hHYXRld2F5U3RhY2snLCB7XG4gIGVudixcbiAgY29uZmlnVGFibGU6IHN0b3JhZ2VTdGFjay5jb25maWdUYWJsZSxcbiAgYWdlbnRDb3JlUnVudGltZUFybixcbiAgZGVzY3JpcHRpb246ICdHYXRld2F5IExhbWJkYSAoaW52b2NhdGlvbnMsIC9hcGkvKiwga2VlcGFsaXZlKScsXG59KTtcbmdhdGV3YXlTdGFjay5hZGREZXBlbmRlbmN5KHN0b3JhZ2VTdGFjayk7XG5cbi8vIEV4dHJhY3QgaG9zdG5hbWUgZnJvbSBMYW1iZGEgRnVuY3Rpb24gVVJMIChodHRwczovL3h4eC5sYW1iZGEtdXJsLnJlZ2lvbi5vbi5hd3MvKVxuY29uc3QgZ2F0ZXdheVVybEhvc3RuYW1lID0gY2RrLkZuLnNlbGVjdChcbiAgMixcbiAgY2RrLkZuLnNwbGl0KCcvJywgZ2F0ZXdheVN0YWNrLmZ1bmN0aW9uVXJsKVxuKTtcblxuLy8gQ2VydGlmaWNhdGUgc3RhY2sgaW4gdXMtZWFzdC0xIChyZXF1aXJlZCBmb3IgQ2xvdWRGcm9udClcbmNvbnN0IGNlcnRpZmljYXRlU3RhY2sgPSBuZXcgR2xpdGNoQ2VydGlmaWNhdGVTdGFjayhhcHAsICdHbGl0Y2hDZXJ0aWZpY2F0ZVN0YWNrJywge1xuICBlbnY6IHsgYWNjb3VudDogZW52LmFjY291bnQsIHJlZ2lvbjogJ3VzLWVhc3QtMScgfSxcbiAgZG9tYWluTmFtZTogY3VzdG9tRG9tYWluLFxuICBjcm9zc1JlZ2lvblJlZmVyZW5jZXM6IHRydWUsXG4gIGRlc2NyaXB0aW9uOiAnQUNNIGNlcnRpZmljYXRlIGZvciBDbG91ZEZyb250IGN1c3RvbSBkb21haW4gKHVzLWVhc3QtMSknLFxufSk7XG5cbmNvbnN0IHVpSG9zdGluZ1N0YWNrID0gbmV3IEdsaXRjaFVpSG9zdGluZ1N0YWNrKGFwcCwgJ0dsaXRjaFVpSG9zdGluZ1N0YWNrJywge1xuICBlbnYsXG4gIGdhdGV3YXlGdW5jdGlvblVybEhvc3RuYW1lOiBnYXRld2F5VXJsSG9zdG5hbWUsXG4gIGRvbWFpbk5hbWU6IGN1c3RvbURvbWFpbixcbiAgY2VydGlmaWNhdGVBcm46IGNlcnRpZmljYXRlU3RhY2suY2VydGlmaWNhdGUuY2VydGlmaWNhdGVBcm4sXG4gIGNyb3NzUmVnaW9uUmVmZXJlbmNlczogdHJ1ZSxcbiAgZGVzY3JpcHRpb246ICdTMyArIENsb3VkRnJvbnQgaG9zdGluZyBmb3IgR2xpdGNoIFVJJyxcbn0pO1xudWlIb3N0aW5nU3RhY2suYWRkRGVwZW5kZW5jeShnYXRld2F5U3RhY2spO1xudWlIb3N0aW5nU3RhY2suYWRkRGVwZW5kZW5jeShjZXJ0aWZpY2F0ZVN0YWNrKTtcblxuLy8gQnVtcCBpbnN0YW5jZUJvb3RzdHJhcFZlcnNpb24gKGUuZy4gdG8gJzYnKSB0byBmb3JjZSBFQzIgaW5zdGFuY2UgcmVwbGFjZW1lbnQgb24gbmV4dCBkZXBsb3kuXG5jb25zdCB0YWlsc2NhbGVTdGFjayA9IG5ldyBUYWlsc2NhbGVTdGFjayhhcHAsICdHbGl0Y2hUYWlsc2NhbGVTdGFjaycsIHtcbiAgZW52LFxuICB2cGM6IHZwY1N0YWNrLnZwYyxcbiAgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogc2VjcmV0c1N0YWNrLnRhaWxzY2FsZUF1dGhLZXlTZWNyZXQsXG4gIGFnZW50Q29yZVJ1bnRpbWVBcm4sXG4gIGluc3RhbmNlQm9vdHN0cmFwVmVyc2lvbjogJzYnLFxuICBnYXRld2F5RnVuY3Rpb25Vcmw6IGdhdGV3YXlTdGFjay5mdW5jdGlvblVybCxcbiAgdWlCdWNrZXROYW1lOiB1aUhvc3RpbmdTdGFjay51aUJ1Y2tldC5idWNrZXROYW1lLFxuICBkZXNjcmlwdGlvbjogJ0VDMiBUYWlsc2NhbGUgY29ubmVjdG9yIGFuZCBVSSBwcm94eSAobmdpbnggKyBUYWlsc2NhbGUgU2VydmUpJyxcbn0pO1xudGFpbHNjYWxlU3RhY2suYWRkRGVwZW5kZW5jeSh2cGNTdGFjayk7XG50YWlsc2NhbGVTdGFjay5hZGREZXBlbmRlbmN5KHNlY3JldHNTdGFjayk7XG50YWlsc2NhbGVTdGFjay5hZGREZXBlbmRlbmN5KGdhdGV3YXlTdGFjayk7XG50YWlsc2NhbGVTdGFjay5hZGREZXBlbmRlbmN5KHVpSG9zdGluZ1N0YWNrKTtcblxuY29uc3QgYWdlbnRDb3JlU3RhY2sgPSBuZXcgQWdlbnRDb3JlU3RhY2soYXBwLCAnR2xpdGNoQWdlbnRDb3JlU3RhY2snLCB7XG4gIGVudixcbiAgdnBjOiB2cGNTdGFjay52cGMsXG4gIHRhaWxzY2FsZVNlY3VyaXR5R3JvdXA6IHRhaWxzY2FsZVN0YWNrLnNlY3VyaXR5R3JvdXAsXG4gIGFwaUtleXNTZWNyZXQ6IHNlY3JldHNTdGFjay5hcGlLZXlzU2VjcmV0LFxuICB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzU3RhY2sudGVsZWdyYW1Cb3RUb2tlblNlY3JldCxcbiAgZGVzY3JpcHRpb246ICdBZ2VudENvcmUgUnVudGltZSByZXNvdXJjZXMnLFxufSk7XG5hZ2VudENvcmVTdGFjay5hZGREZXBlbmRlbmN5KHZwY1N0YWNrKTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3kodGFpbHNjYWxlU3RhY2spO1xuXG5jZGsuVGFncy5vZihhcHApLmFkZCgnUHJvamVjdCcsICdBZ2VudENvcmUtR2xpdGNoJyk7XG5jZGsuVGFncy5vZihhcHApLmFkZCgnTWFuYWdlZEJ5JywgJ0NESycpO1xuXG5hcHAuc3ludGgoKTtcbiJdfQ==