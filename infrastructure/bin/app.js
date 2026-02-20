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
const tailscaleStack = new tailscale_stack_1.TailscaleStack(app, 'GlitchTailscaleStack', {
    env,
    vpc: vpcStack.vpc,
    tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
    description: 'EC2 Tailscale connector for private network access',
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLHVDQUFxQztBQUNyQyxpREFBbUM7QUFDbkMsZ0RBQTRDO0FBQzVDLHdEQUFvRDtBQUNwRCw0REFBd0Q7QUFDeEQsNERBQXdEO0FBQ3hELDBFQUFxRTtBQUVyRSxNQUFNLEdBQUcsR0FBRyxJQUFJLEdBQUcsQ0FBQyxHQUFHLEVBQUUsQ0FBQztBQUUxQixNQUFNLEdBQUcsR0FBRztJQUNWLE9BQU8sRUFBRSxjQUFjO0lBQ3ZCLE1BQU0sRUFBRSxXQUFXO0NBQ3BCLENBQUM7QUFFRixNQUFNLFFBQVEsR0FBRyxJQUFJLG9CQUFRLENBQUMsR0FBRyxFQUFFLGdCQUFnQixFQUFFO0lBQ25ELEdBQUc7SUFDSCxXQUFXLEVBQUUseUNBQXlDO0NBQ3ZELENBQUMsQ0FBQztBQUVILG1HQUFtRztBQUNuRyxNQUFNLHVCQUF1QixHQUMzQixHQUFHLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQywrQkFBK0IsQ0FBQztJQUN2RCxnQkFBZ0IsR0FBRyxDQUFDLE9BQU8sMENBQTBDLEdBQUcsQ0FBQyxNQUFNLGFBQWEsQ0FBQztBQUUvRixpRkFBaUY7QUFDakYsTUFBTSxtQkFBbUIsR0FDdkIsR0FBRyxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsMkJBQTJCLENBQUM7SUFDbkQsNkJBQTZCLEdBQUcsQ0FBQyxNQUFNLElBQUksR0FBRyxDQUFDLE9BQU8sNEJBQTRCLENBQUM7QUFFckYsTUFBTSxZQUFZLEdBQUcsSUFBSSw0QkFBWSxDQUFDLEdBQUcsRUFBRSxvQkFBb0IsRUFBRTtJQUMvRCxHQUFHO0lBQ0gsdUJBQXVCO0lBQ3ZCLFdBQVcsRUFBRSxvREFBb0Q7Q0FDbEUsQ0FBQyxDQUFDO0FBRUgsTUFBTSxjQUFjLEdBQUcsSUFBSSxnQ0FBYyxDQUFDLEdBQUcsRUFBRSxzQkFBc0IsRUFBRTtJQUNyRSxHQUFHO0lBQ0gsR0FBRyxFQUFFLFFBQVEsQ0FBQyxHQUFHO0lBQ2pCLHNCQUFzQixFQUFFLFlBQVksQ0FBQyxzQkFBc0I7SUFDM0QsV0FBVyxFQUFFLG9EQUFvRDtDQUNsRSxDQUFDLENBQUM7QUFDSCxjQUFjLENBQUMsYUFBYSxDQUFDLFFBQVEsQ0FBQyxDQUFDO0FBQ3ZDLGNBQWMsQ0FBQyxhQUFhLENBQUMsWUFBWSxDQUFDLENBQUM7QUFFM0MsTUFBTSxjQUFjLEdBQUcsSUFBSSxnQ0FBYyxDQUFDLEdBQUcsRUFBRSxzQkFBc0IsRUFBRTtJQUNyRSxHQUFHO0lBQ0gsR0FBRyxFQUFFLFFBQVEsQ0FBQyxHQUFHO0lBQ2pCLHNCQUFzQixFQUFFLGNBQWMsQ0FBQyxhQUFhO0lBQ3BELGFBQWEsRUFBRSxZQUFZLENBQUMsYUFBYTtJQUN6QyxzQkFBc0IsRUFBRSxZQUFZLENBQUMsc0JBQXNCO0lBQzNELFdBQVcsRUFBRSw2QkFBNkI7Q0FDM0MsQ0FBQyxDQUFDO0FBQ0gsY0FBYyxDQUFDLGFBQWEsQ0FBQyxRQUFRLENBQUMsQ0FBQztBQUN2QyxjQUFjLENBQUMsYUFBYSxDQUFDLFlBQVksQ0FBQyxDQUFDO0FBQzNDLGNBQWMsQ0FBQyxhQUFhLENBQUMsY0FBYyxDQUFDLENBQUM7QUFFN0MsTUFBTSxvQkFBb0IsR0FBRyxJQUFJLDZDQUFvQixDQUFDLEdBQUcsRUFBRSw0QkFBNEIsRUFBRTtJQUN2RixHQUFHO0lBQ0gsc0JBQXNCLEVBQUUsWUFBWSxDQUFDLHNCQUFzQjtJQUMzRCxtQkFBbUI7SUFDbkIsdUJBQXVCO0lBQ3ZCLFdBQVcsRUFBRSwrREFBK0Q7Q0FDN0UsQ0FBQyxDQUFDO0FBQ0gsb0JBQW9CLENBQUMsYUFBYSxDQUFDLFlBQVksQ0FBQyxDQUFDO0FBRWpELEdBQUcsQ0FBQyxJQUFJLENBQUMsRUFBRSxDQUFDLEdBQUcsQ0FBQyxDQUFDLEdBQUcsQ0FBQyxTQUFTLEVBQUUsa0JBQWtCLENBQUMsQ0FBQztBQUNwRCxHQUFHLENBQUMsSUFBSSxDQUFDLEVBQUUsQ0FBQyxHQUFHLENBQUMsQ0FBQyxHQUFHLENBQUMsV0FBVyxFQUFFLEtBQUssQ0FBQyxDQUFDO0FBRXpDLEdBQUcsQ0FBQyxLQUFLLEVBQUUsQ0FBQyIsInNvdXJjZXNDb250ZW50IjpbIiMhL3Vzci9iaW4vZW52IG5vZGVcbmltcG9ydCAnc291cmNlLW1hcC1zdXBwb3J0L3JlZ2lzdGVyJztcbmltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgeyBWcGNTdGFjayB9IGZyb20gJy4uL2xpYi92cGMtc3RhY2snO1xuaW1wb3J0IHsgU2VjcmV0c1N0YWNrIH0gZnJvbSAnLi4vbGliL3NlY3JldHMtc3RhY2snO1xuaW1wb3J0IHsgVGFpbHNjYWxlU3RhY2sgfSBmcm9tICcuLi9saWIvdGFpbHNjYWxlLXN0YWNrJztcbmltcG9ydCB7IEFnZW50Q29yZVN0YWNrIH0gZnJvbSAnLi4vbGliL2FnZW50Y29yZS1zdGFjayc7XG5pbXBvcnQgeyBUZWxlZ3JhbVdlYmhvb2tTdGFjayB9IGZyb20gJy4uL2xpYi90ZWxlZ3JhbS13ZWJob29rLXN0YWNrJztcblxuY29uc3QgYXBwID0gbmV3IGNkay5BcHAoKTtcblxuY29uc3QgZW52ID0ge1xuICBhY2NvdW50OiAnOTk5Nzc2MzgyNDE1JyxcbiAgcmVnaW9uOiAndXMtd2VzdC0yJyxcbn07XG5cbmNvbnN0IHZwY1N0YWNrID0gbmV3IFZwY1N0YWNrKGFwcCwgJ0dsaXRjaFZwY1N0YWNrJywge1xuICBlbnYsXG4gIGRlc2NyaXB0aW9uOiAnVlBDIGluZnJhc3RydWN0dXJlIGZvciBBZ2VudENvcmUgR2xpdGNoJyxcbn0pO1xuXG4vLyBEZWZhdWx0IEFnZW50Q29yZSBTREsgcnVudGltZSByb2xlIChmcm9tIC5iZWRyb2NrX2FnZW50Y29yZS55YW1sKTsgZ3JhbnQgaXQgVGVsZWdyYW0gc2VjcmV0IHJlYWRcbmNvbnN0IGRlZmF1bHRFeGVjdXRpb25Sb2xlQXJuID1cbiAgYXBwLm5vZGUudHJ5R2V0Q29udGV4dCgnZ2xpdGNoRGVmYXVsdEV4ZWN1dGlvblJvbGVBcm4nKSA/P1xuICBgYXJuOmF3czppYW06OiR7ZW52LmFjY291bnR9OnJvbGUvQW1hem9uQmVkcm9ja0FnZW50Q29yZVNES1J1bnRpbWUtJHtlbnYucmVnaW9ufS0xNDk4MDE1OGUyYDtcblxuLy8gQWdlbnRDb3JlIHJ1bnRpbWUgQVJOIChmcm9tIC5iZWRyb2NrX2FnZW50Y29yZS55YW1sIG9yIGFnZW50Y29yZSBydW50aW1lIGxpc3QpXG5jb25zdCBhZ2VudENvcmVSdW50aW1lQXJuID1cbiAgYXBwLm5vZGUudHJ5R2V0Q29udGV4dCgnZ2xpdGNoQWdlbnRDb3JlUnVudGltZUFybicpID8/XG4gIGBhcm46YXdzOmJlZHJvY2stYWdlbnRjb3JlOiR7ZW52LnJlZ2lvbn06JHtlbnYuYWNjb3VudH06cnVudGltZS9HbGl0Y2gtNzhxNVRnRWE4TWA7XG5cbmNvbnN0IHNlY3JldHNTdGFjayA9IG5ldyBTZWNyZXRzU3RhY2soYXBwLCAnR2xpdGNoU2VjcmV0c1N0YWNrJywge1xuICBlbnYsXG4gIGRlZmF1bHRFeGVjdXRpb25Sb2xlQXJuLFxuICBkZXNjcmlwdGlvbjogJ1NlY3JldHMgTWFuYWdlciBjb25maWd1cmF0aW9uIGZvciBBZ2VudENvcmUgR2xpdGNoJyxcbn0pO1xuXG5jb25zdCB0YWlsc2NhbGVTdGFjayA9IG5ldyBUYWlsc2NhbGVTdGFjayhhcHAsICdHbGl0Y2hUYWlsc2NhbGVTdGFjaycsIHtcbiAgZW52LFxuICB2cGM6IHZwY1N0YWNrLnZwYyxcbiAgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogc2VjcmV0c1N0YWNrLnRhaWxzY2FsZUF1dGhLZXlTZWNyZXQsXG4gIGRlc2NyaXB0aW9uOiAnRUMyIFRhaWxzY2FsZSBjb25uZWN0b3IgZm9yIHByaXZhdGUgbmV0d29yayBhY2Nlc3MnLFxufSk7XG50YWlsc2NhbGVTdGFjay5hZGREZXBlbmRlbmN5KHZwY1N0YWNrKTtcbnRhaWxzY2FsZVN0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcblxuY29uc3QgYWdlbnRDb3JlU3RhY2sgPSBuZXcgQWdlbnRDb3JlU3RhY2soYXBwLCAnR2xpdGNoQWdlbnRDb3JlU3RhY2snLCB7XG4gIGVudixcbiAgdnBjOiB2cGNTdGFjay52cGMsXG4gIHRhaWxzY2FsZVNlY3VyaXR5R3JvdXA6IHRhaWxzY2FsZVN0YWNrLnNlY3VyaXR5R3JvdXAsXG4gIGFwaUtleXNTZWNyZXQ6IHNlY3JldHNTdGFjay5hcGlLZXlzU2VjcmV0LFxuICB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzU3RhY2sudGVsZWdyYW1Cb3RUb2tlblNlY3JldCxcbiAgZGVzY3JpcHRpb246ICdBZ2VudENvcmUgUnVudGltZSByZXNvdXJjZXMnLFxufSk7XG5hZ2VudENvcmVTdGFjay5hZGREZXBlbmRlbmN5KHZwY1N0YWNrKTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3kodGFpbHNjYWxlU3RhY2spO1xuXG5jb25zdCB0ZWxlZ3JhbVdlYmhvb2tTdGFjayA9IG5ldyBUZWxlZ3JhbVdlYmhvb2tTdGFjayhhcHAsICdHbGl0Y2hUZWxlZ3JhbVdlYmhvb2tTdGFjaycsIHtcbiAgZW52LFxuICB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzU3RhY2sudGVsZWdyYW1Cb3RUb2tlblNlY3JldCxcbiAgYWdlbnRDb3JlUnVudGltZUFybixcbiAgZGVmYXVsdEV4ZWN1dGlvblJvbGVBcm4sXG4gIGRlc2NyaXB0aW9uOiAnVGVsZWdyYW0gd2ViaG9vayBMYW1iZGEgd2l0aCBGdW5jdGlvbiBVUkwgYW5kIER5bmFtb0RCIGNvbmZpZycsXG59KTtcbnRlbGVncmFtV2ViaG9va1N0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcblxuY2RrLlRhZ3Mub2YoYXBwKS5hZGQoJ1Byb2plY3QnLCAnQWdlbnRDb3JlLUdsaXRjaCcpO1xuY2RrLlRhZ3Mub2YoYXBwKS5hZGQoJ01hbmFnZWRCeScsICdDREsnKTtcblxuYXBwLnN5bnRoKCk7XG4iXX0=