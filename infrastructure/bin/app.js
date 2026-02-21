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
const telegram_webhook_stack_1 = require("../lib/telegram-webhook-stack");
const app = new cdk.App();
const env = {
    account: '999776382415',
    region: 'us-west-2',
};
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
// Bump instanceBootstrapVersion (e.g. to '4') to force EC2 instance replacement on next deploy.
const tailscaleStack = new tailscale_stack_1.TailscaleStack(app, 'GlitchTailscaleStack', {
    env,
    vpc: vpcStack.vpc,
    tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
    agentCoreRuntimeArn,
    enableUiServer: true,
    instanceBootstrapVersion: '2',
    description: 'EC2 Tailscale connector with Glitch UI server',
});
tailscaleStack.addDependency(vpcStack);
tailscaleStack.addDependency(secretsStack);
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
const telegramWebhookStack = new telegram_webhook_stack_1.TelegramWebhookStack(app, 'GlitchTelegramWebhookStack', {
    env,
    telegramBotTokenSecret: secretsStack.telegramBotTokenSecret,
    agentCoreRuntimeArn,
    defaultExecutionRoleArn,
    description: 'Telegram webhook Lambda with Function URL and DynamoDB config',
});
telegramWebhookStack.addDependency(secretsStack);
cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');
app.synth();
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLHVDQUFxQztBQUNyQyxpREFBbUM7QUFDbkMsZ0RBQTRDO0FBQzVDLHdEQUFvRDtBQUNwRCw0REFBd0Q7QUFDeEQsNERBQXdEO0FBQ3hELDBFQUFxRTtBQUVyRSxNQUFNLEdBQUcsR0FBRyxJQUFJLEdBQUcsQ0FBQyxHQUFHLEVBQUUsQ0FBQztBQUUxQixNQUFNLEdBQUcsR0FBRztJQUNWLE9BQU8sRUFBRSxjQUFjO0lBQ3ZCLE1BQU0sRUFBRSxXQUFXO0NBQ3BCLENBQUM7QUFFRixNQUFNLFFBQVEsR0FBRyxJQUFJLG9CQUFRLENBQUMsR0FBRyxFQUFFLGdCQUFnQixFQUFFO0lBQ25ELEdBQUc7SUFDSCxXQUFXLEVBQUUseUNBQXlDO0NBQ3ZELENBQUMsQ0FBQztBQUVILG1HQUFtRztBQUNuRyxNQUFNLHVCQUF1QixHQUMzQixHQUFHLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQywrQkFBK0IsQ0FBQztJQUN2RCxnQkFBZ0IsR0FBRyxDQUFDLE9BQU8sMENBQTBDLEdBQUcsQ0FBQyxNQUFNLGFBQWEsQ0FBQztBQUUvRixpRkFBaUY7QUFDakYsTUFBTSxtQkFBbUIsR0FDdkIsR0FBRyxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsMkJBQTJCLENBQUM7SUFDbkQsNkJBQTZCLEdBQUcsQ0FBQyxNQUFNLElBQUksR0FBRyxDQUFDLE9BQU8sNEJBQTRCLENBQUM7QUFFckYsTUFBTSxZQUFZLEdBQUcsSUFBSSw0QkFBWSxDQUFDLEdBQUcsRUFBRSxvQkFBb0IsRUFBRTtJQUMvRCxHQUFHO0lBQ0gsdUJBQXVCO0lBQ3ZCLFdBQVcsRUFBRSxvREFBb0Q7Q0FDbEUsQ0FBQyxDQUFDO0FBRUgsZ0dBQWdHO0FBQ2hHLE1BQU0sY0FBYyxHQUFHLElBQUksZ0NBQWMsQ0FBQyxHQUFHLEVBQUUsc0JBQXNCLEVBQUU7SUFDckUsR0FBRztJQUNILEdBQUcsRUFBRSxRQUFRLENBQUMsR0FBRztJQUNqQixzQkFBc0IsRUFBRSxZQUFZLENBQUMsc0JBQXNCO0lBQzNELG1CQUFtQjtJQUNuQixjQUFjLEVBQUUsSUFBSTtJQUNwQix3QkFBd0IsRUFBRSxHQUFHO0lBQzdCLFdBQVcsRUFBRSwrQ0FBK0M7Q0FDN0QsQ0FBQyxDQUFDO0FBQ0gsY0FBYyxDQUFDLGFBQWEsQ0FBQyxRQUFRLENBQUMsQ0FBQztBQUN2QyxjQUFjLENBQUMsYUFBYSxDQUFDLFlBQVksQ0FBQyxDQUFDO0FBRTNDLE1BQU0sY0FBYyxHQUFHLElBQUksZ0NBQWMsQ0FBQyxHQUFHLEVBQUUsc0JBQXNCLEVBQUU7SUFDckUsR0FBRztJQUNILEdBQUcsRUFBRSxRQUFRLENBQUMsR0FBRztJQUNqQixzQkFBc0IsRUFBRSxjQUFjLENBQUMsYUFBYTtJQUNwRCxhQUFhLEVBQUUsWUFBWSxDQUFDLGFBQWE7SUFDekMsc0JBQXNCLEVBQUUsWUFBWSxDQUFDLHNCQUFzQjtJQUMzRCxXQUFXLEVBQUUsNkJBQTZCO0NBQzNDLENBQUMsQ0FBQztBQUNILGNBQWMsQ0FBQyxhQUFhLENBQUMsUUFBUSxDQUFDLENBQUM7QUFDdkMsY0FBYyxDQUFDLGFBQWEsQ0FBQyxZQUFZLENBQUMsQ0FBQztBQUMzQyxjQUFjLENBQUMsYUFBYSxDQUFDLGNBQWMsQ0FBQyxDQUFDO0FBRTdDLE1BQU0sb0JBQW9CLEdBQUcsSUFBSSw2Q0FBb0IsQ0FBQyxHQUFHLEVBQUUsNEJBQTRCLEVBQUU7SUFDdkYsR0FBRztJQUNILHNCQUFzQixFQUFFLFlBQVksQ0FBQyxzQkFBc0I7SUFDM0QsbUJBQW1CO0lBQ25CLHVCQUF1QjtJQUN2QixXQUFXLEVBQUUsK0RBQStEO0NBQzdFLENBQUMsQ0FBQztBQUNILG9CQUFvQixDQUFDLGFBQWEsQ0FBQyxZQUFZLENBQUMsQ0FBQztBQUVqRCxHQUFHLENBQUMsSUFBSSxDQUFDLEVBQUUsQ0FBQyxHQUFHLENBQUMsQ0FBQyxHQUFHLENBQUMsU0FBUyxFQUFFLGtCQUFrQixDQUFDLENBQUM7QUFDcEQsR0FBRyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsR0FBRyxDQUFDLENBQUMsR0FBRyxDQUFDLFdBQVcsRUFBRSxLQUFLLENBQUMsQ0FBQztBQUV6QyxHQUFHLENBQUMsS0FBSyxFQUFFLENBQUMiLCJzb3VyY2VzQ29udGVudCI6WyIjIS91c3IvYmluL2VudiBub2RlXG5pbXBvcnQgJ3NvdXJjZS1tYXAtc3VwcG9ydC9yZWdpc3Rlcic7XG5pbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0IHsgVnBjU3RhY2sgfSBmcm9tICcuLi9saWIvdnBjLXN0YWNrJztcbmltcG9ydCB7IFNlY3JldHNTdGFjayB9IGZyb20gJy4uL2xpYi9zZWNyZXRzLXN0YWNrJztcbmltcG9ydCB7IFRhaWxzY2FsZVN0YWNrIH0gZnJvbSAnLi4vbGliL3RhaWxzY2FsZS1zdGFjayc7XG5pbXBvcnQgeyBBZ2VudENvcmVTdGFjayB9IGZyb20gJy4uL2xpYi9hZ2VudGNvcmUtc3RhY2snO1xuaW1wb3J0IHsgVGVsZWdyYW1XZWJob29rU3RhY2sgfSBmcm9tICcuLi9saWIvdGVsZWdyYW0td2ViaG9vay1zdGFjayc7XG5cbmNvbnN0IGFwcCA9IG5ldyBjZGsuQXBwKCk7XG5cbmNvbnN0IGVudiA9IHtcbiAgYWNjb3VudDogJzk5OTc3NjM4MjQxNScsXG4gIHJlZ2lvbjogJ3VzLXdlc3QtMicsXG59O1xuXG5jb25zdCB2cGNTdGFjayA9IG5ldyBWcGNTdGFjayhhcHAsICdHbGl0Y2hWcGNTdGFjaycsIHtcbiAgZW52LFxuICBkZXNjcmlwdGlvbjogJ1ZQQyBpbmZyYXN0cnVjdHVyZSBmb3IgQWdlbnRDb3JlIEdsaXRjaCcsXG59KTtcblxuLy8gRGVmYXVsdCBBZ2VudENvcmUgU0RLIHJ1bnRpbWUgcm9sZSAoZnJvbSAuYmVkcm9ja19hZ2VudGNvcmUueWFtbCk7IGdyYW50IGl0IFRlbGVncmFtIHNlY3JldCByZWFkXG5jb25zdCBkZWZhdWx0RXhlY3V0aW9uUm9sZUFybiA9XG4gIGFwcC5ub2RlLnRyeUdldENvbnRleHQoJ2dsaXRjaERlZmF1bHRFeGVjdXRpb25Sb2xlQXJuJykgPz9cbiAgYGFybjphd3M6aWFtOjoke2Vudi5hY2NvdW50fTpyb2xlL0FtYXpvbkJlZHJvY2tBZ2VudENvcmVTREtSdW50aW1lLSR7ZW52LnJlZ2lvbn0tMTQ5ODAxNThlMmA7XG5cbi8vIEFnZW50Q29yZSBydW50aW1lIEFSTiAoZnJvbSAuYmVkcm9ja19hZ2VudGNvcmUueWFtbCBvciBhZ2VudGNvcmUgcnVudGltZSBsaXN0KVxuY29uc3QgYWdlbnRDb3JlUnVudGltZUFybiA9XG4gIGFwcC5ub2RlLnRyeUdldENvbnRleHQoJ2dsaXRjaEFnZW50Q29yZVJ1bnRpbWVBcm4nKSA/P1xuICBgYXJuOmF3czpiZWRyb2NrLWFnZW50Y29yZToke2Vudi5yZWdpb259OiR7ZW52LmFjY291bnR9OnJ1bnRpbWUvR2xpdGNoLTc4cTVUZ0VhOE1gO1xuXG5jb25zdCBzZWNyZXRzU3RhY2sgPSBuZXcgU2VjcmV0c1N0YWNrKGFwcCwgJ0dsaXRjaFNlY3JldHNTdGFjaycsIHtcbiAgZW52LFxuICBkZWZhdWx0RXhlY3V0aW9uUm9sZUFybixcbiAgZGVzY3JpcHRpb246ICdTZWNyZXRzIE1hbmFnZXIgY29uZmlndXJhdGlvbiBmb3IgQWdlbnRDb3JlIEdsaXRjaCcsXG59KTtcblxuLy8gQnVtcCBpbnN0YW5jZUJvb3RzdHJhcFZlcnNpb24gKGUuZy4gdG8gJzQnKSB0byBmb3JjZSBFQzIgaW5zdGFuY2UgcmVwbGFjZW1lbnQgb24gbmV4dCBkZXBsb3kuXG5jb25zdCB0YWlsc2NhbGVTdGFjayA9IG5ldyBUYWlsc2NhbGVTdGFjayhhcHAsICdHbGl0Y2hUYWlsc2NhbGVTdGFjaycsIHtcbiAgZW52LFxuICB2cGM6IHZwY1N0YWNrLnZwYyxcbiAgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogc2VjcmV0c1N0YWNrLnRhaWxzY2FsZUF1dGhLZXlTZWNyZXQsXG4gIGFnZW50Q29yZVJ1bnRpbWVBcm4sXG4gIGVuYWJsZVVpU2VydmVyOiB0cnVlLFxuICBpbnN0YW5jZUJvb3RzdHJhcFZlcnNpb246ICcyJyxcbiAgZGVzY3JpcHRpb246ICdFQzIgVGFpbHNjYWxlIGNvbm5lY3RvciB3aXRoIEdsaXRjaCBVSSBzZXJ2ZXInLFxufSk7XG50YWlsc2NhbGVTdGFjay5hZGREZXBlbmRlbmN5KHZwY1N0YWNrKTtcbnRhaWxzY2FsZVN0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcblxuY29uc3QgYWdlbnRDb3JlU3RhY2sgPSBuZXcgQWdlbnRDb3JlU3RhY2soYXBwLCAnR2xpdGNoQWdlbnRDb3JlU3RhY2snLCB7XG4gIGVudixcbiAgdnBjOiB2cGNTdGFjay52cGMsXG4gIHRhaWxzY2FsZVNlY3VyaXR5R3JvdXA6IHRhaWxzY2FsZVN0YWNrLnNlY3VyaXR5R3JvdXAsXG4gIGFwaUtleXNTZWNyZXQ6IHNlY3JldHNTdGFjay5hcGlLZXlzU2VjcmV0LFxuICB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzU3RhY2sudGVsZWdyYW1Cb3RUb2tlblNlY3JldCxcbiAgZGVzY3JpcHRpb246ICdBZ2VudENvcmUgUnVudGltZSByZXNvdXJjZXMnLFxufSk7XG5hZ2VudENvcmVTdGFjay5hZGREZXBlbmRlbmN5KHZwY1N0YWNrKTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3kodGFpbHNjYWxlU3RhY2spO1xuXG5jb25zdCB0ZWxlZ3JhbVdlYmhvb2tTdGFjayA9IG5ldyBUZWxlZ3JhbVdlYmhvb2tTdGFjayhhcHAsICdHbGl0Y2hUZWxlZ3JhbVdlYmhvb2tTdGFjaycsIHtcbiAgZW52LFxuICB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzU3RhY2sudGVsZWdyYW1Cb3RUb2tlblNlY3JldCxcbiAgYWdlbnRDb3JlUnVudGltZUFybixcbiAgZGVmYXVsdEV4ZWN1dGlvblJvbGVBcm4sXG4gIGRlc2NyaXB0aW9uOiAnVGVsZWdyYW0gd2ViaG9vayBMYW1iZGEgd2l0aCBGdW5jdGlvbiBVUkwgYW5kIER5bmFtb0RCIGNvbmZpZycsXG59KTtcbnRlbGVncmFtV2ViaG9va1N0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcblxuY2RrLlRhZ3Mub2YoYXBwKS5hZGQoJ1Byb2plY3QnLCAnQWdlbnRDb3JlLUdsaXRjaCcpO1xuY2RrLlRhZ3Mub2YoYXBwKS5hZGQoJ01hbmFnZWRCeScsICdDREsnKTtcblxuYXBwLnN5bnRoKCk7XG4iXX0=