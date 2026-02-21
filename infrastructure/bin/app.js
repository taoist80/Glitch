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
// Bump instanceBootstrapVersion (e.g. to '5') to force EC2 instance replacement on next deploy.
const tailscaleStack = new tailscale_stack_1.TailscaleStack(app, 'GlitchTailscaleStack', {
    env,
    vpc: vpcStack.vpc,
    tailscaleAuthKeySecret: secretsStack.tailscaleAuthKeySecret,
    agentCoreRuntimeArn,
    instanceBootstrapVersion: '5',
    description: 'EC2 Tailscale connector for on-premises network access',
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
cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');
app.synth();
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLHVDQUFxQztBQUNyQyxpREFBbUM7QUFDbkMsZ0RBQTRDO0FBQzVDLHdEQUFvRDtBQUNwRCw0REFBd0Q7QUFDeEQsNERBQXdEO0FBQ3hELHdEQUEwRDtBQUMxRCx3REFBMEQ7QUFFMUQsTUFBTSxHQUFHLEdBQUcsSUFBSSxHQUFHLENBQUMsR0FBRyxFQUFFLENBQUM7QUFFMUIsTUFBTSxHQUFHLEdBQUc7SUFDVixPQUFPLEVBQUUsY0FBYztJQUN2QixNQUFNLEVBQUUsV0FBVztDQUNwQixDQUFDO0FBRUYsTUFBTSxRQUFRLEdBQUcsSUFBSSxvQkFBUSxDQUFDLEdBQUcsRUFBRSxnQkFBZ0IsRUFBRTtJQUNuRCxHQUFHO0lBQ0gsV0FBVyxFQUFFLHlDQUF5QztDQUN2RCxDQUFDLENBQUM7QUFFSCxtR0FBbUc7QUFDbkcsTUFBTSx1QkFBdUIsR0FDM0IsR0FBRyxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsK0JBQStCLENBQUM7SUFDdkQsZ0JBQWdCLEdBQUcsQ0FBQyxPQUFPLDBDQUEwQyxHQUFHLENBQUMsTUFBTSxhQUFhLENBQUM7QUFFL0YsaUZBQWlGO0FBQ2pGLE1BQU0sbUJBQW1CLEdBQ3ZCLEdBQUcsQ0FBQyxJQUFJLENBQUMsYUFBYSxDQUFDLDJCQUEyQixDQUFDO0lBQ25ELDZCQUE2QixHQUFHLENBQUMsTUFBTSxJQUFJLEdBQUcsQ0FBQyxPQUFPLDRCQUE0QixDQUFDO0FBRXJGLE1BQU0sWUFBWSxHQUFHLElBQUksNEJBQVksQ0FBQyxHQUFHLEVBQUUsb0JBQW9CLEVBQUU7SUFDL0QsR0FBRztJQUNILHVCQUF1QjtJQUN2QixXQUFXLEVBQUUsb0RBQW9EO0NBQ2xFLENBQUMsQ0FBQztBQUVILGdHQUFnRztBQUNoRyxNQUFNLGNBQWMsR0FBRyxJQUFJLGdDQUFjLENBQUMsR0FBRyxFQUFFLHNCQUFzQixFQUFFO0lBQ3JFLEdBQUc7SUFDSCxHQUFHLEVBQUUsUUFBUSxDQUFDLEdBQUc7SUFDakIsc0JBQXNCLEVBQUUsWUFBWSxDQUFDLHNCQUFzQjtJQUMzRCxtQkFBbUI7SUFDbkIsd0JBQXdCLEVBQUUsR0FBRztJQUM3QixXQUFXLEVBQUUsd0RBQXdEO0NBQ3RFLENBQUMsQ0FBQztBQUNILGNBQWMsQ0FBQyxhQUFhLENBQUMsUUFBUSxDQUFDLENBQUM7QUFDdkMsY0FBYyxDQUFDLGFBQWEsQ0FBQyxZQUFZLENBQUMsQ0FBQztBQUUzQyxNQUFNLGNBQWMsR0FBRyxJQUFJLGdDQUFjLENBQUMsR0FBRyxFQUFFLHNCQUFzQixFQUFFO0lBQ3JFLEdBQUc7SUFDSCxHQUFHLEVBQUUsUUFBUSxDQUFDLEdBQUc7SUFDakIsc0JBQXNCLEVBQUUsY0FBYyxDQUFDLGFBQWE7SUFDcEQsYUFBYSxFQUFFLFlBQVksQ0FBQyxhQUFhO0lBQ3pDLHNCQUFzQixFQUFFLFlBQVksQ0FBQyxzQkFBc0I7SUFDM0QsV0FBVyxFQUFFLDZCQUE2QjtDQUMzQyxDQUFDLENBQUM7QUFDSCxjQUFjLENBQUMsYUFBYSxDQUFDLFFBQVEsQ0FBQyxDQUFDO0FBQ3ZDLGNBQWMsQ0FBQyxhQUFhLENBQUMsWUFBWSxDQUFDLENBQUM7QUFDM0MsY0FBYyxDQUFDLGFBQWEsQ0FBQyxjQUFjLENBQUMsQ0FBQztBQUU3QyxNQUFNLFlBQVksR0FBRyxJQUFJLGtDQUFrQixDQUFDLEdBQUcsRUFBRSxvQkFBb0IsRUFBRTtJQUNyRSxHQUFHO0lBQ0gsdUJBQXVCO0lBQ3ZCLFdBQVcsRUFBRSx1REFBdUQ7Q0FDckUsQ0FBQyxDQUFDO0FBRUgsTUFBTSxZQUFZLEdBQUcsSUFBSSxrQ0FBa0IsQ0FBQyxHQUFHLEVBQUUsb0JBQW9CLEVBQUU7SUFDckUsR0FBRztJQUNILFdBQVcsRUFBRSxZQUFZLENBQUMsV0FBVztJQUNyQyxtQkFBbUI7SUFDbkIsV0FBVyxFQUFFLGlEQUFpRDtDQUMvRCxDQUFDLENBQUM7QUFDSCxZQUFZLENBQUMsYUFBYSxDQUFDLFlBQVksQ0FBQyxDQUFDO0FBRXpDLEdBQUcsQ0FBQyxJQUFJLENBQUMsRUFBRSxDQUFDLEdBQUcsQ0FBQyxDQUFDLEdBQUcsQ0FBQyxTQUFTLEVBQUUsa0JBQWtCLENBQUMsQ0FBQztBQUNwRCxHQUFHLENBQUMsSUFBSSxDQUFDLEVBQUUsQ0FBQyxHQUFHLENBQUMsQ0FBQyxHQUFHLENBQUMsV0FBVyxFQUFFLEtBQUssQ0FBQyxDQUFDO0FBRXpDLEdBQUcsQ0FBQyxLQUFLLEVBQUUsQ0FBQyIsInNvdXJjZXNDb250ZW50IjpbIiMhL3Vzci9iaW4vZW52IG5vZGVcbmltcG9ydCAnc291cmNlLW1hcC1zdXBwb3J0L3JlZ2lzdGVyJztcbmltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgeyBWcGNTdGFjayB9IGZyb20gJy4uL2xpYi92cGMtc3RhY2snO1xuaW1wb3J0IHsgU2VjcmV0c1N0YWNrIH0gZnJvbSAnLi4vbGliL3NlY3JldHMtc3RhY2snO1xuaW1wb3J0IHsgVGFpbHNjYWxlU3RhY2sgfSBmcm9tICcuLi9saWIvdGFpbHNjYWxlLXN0YWNrJztcbmltcG9ydCB7IEFnZW50Q29yZVN0YWNrIH0gZnJvbSAnLi4vbGliL2FnZW50Y29yZS1zdGFjayc7XG5pbXBvcnQgeyBHbGl0Y2hTdG9yYWdlU3RhY2sgfSBmcm9tICcuLi9saWIvc3RvcmFnZS1zdGFjayc7XG5pbXBvcnQgeyBHbGl0Y2hHYXRld2F5U3RhY2sgfSBmcm9tICcuLi9saWIvZ2F0ZXdheS1zdGFjayc7XG5cbmNvbnN0IGFwcCA9IG5ldyBjZGsuQXBwKCk7XG5cbmNvbnN0IGVudiA9IHtcbiAgYWNjb3VudDogJzk5OTc3NjM4MjQxNScsXG4gIHJlZ2lvbjogJ3VzLXdlc3QtMicsXG59O1xuXG5jb25zdCB2cGNTdGFjayA9IG5ldyBWcGNTdGFjayhhcHAsICdHbGl0Y2hWcGNTdGFjaycsIHtcbiAgZW52LFxuICBkZXNjcmlwdGlvbjogJ1ZQQyBpbmZyYXN0cnVjdHVyZSBmb3IgQWdlbnRDb3JlIEdsaXRjaCcsXG59KTtcblxuLy8gRGVmYXVsdCBBZ2VudENvcmUgU0RLIHJ1bnRpbWUgcm9sZSAoZnJvbSAuYmVkcm9ja19hZ2VudGNvcmUueWFtbCk7IGdyYW50IGl0IFRlbGVncmFtIHNlY3JldCByZWFkXG5jb25zdCBkZWZhdWx0RXhlY3V0aW9uUm9sZUFybiA9XG4gIGFwcC5ub2RlLnRyeUdldENvbnRleHQoJ2dsaXRjaERlZmF1bHRFeGVjdXRpb25Sb2xlQXJuJykgPz9cbiAgYGFybjphd3M6aWFtOjoke2Vudi5hY2NvdW50fTpyb2xlL0FtYXpvbkJlZHJvY2tBZ2VudENvcmVTREtSdW50aW1lLSR7ZW52LnJlZ2lvbn0tMTQ5ODAxNThlMmA7XG5cbi8vIEFnZW50Q29yZSBydW50aW1lIEFSTiAoZnJvbSAuYmVkcm9ja19hZ2VudGNvcmUueWFtbCBvciBhZ2VudGNvcmUgcnVudGltZSBsaXN0KVxuY29uc3QgYWdlbnRDb3JlUnVudGltZUFybiA9XG4gIGFwcC5ub2RlLnRyeUdldENvbnRleHQoJ2dsaXRjaEFnZW50Q29yZVJ1bnRpbWVBcm4nKSA/P1xuICBgYXJuOmF3czpiZWRyb2NrLWFnZW50Y29yZToke2Vudi5yZWdpb259OiR7ZW52LmFjY291bnR9OnJ1bnRpbWUvR2xpdGNoLTc4cTVUZ0VhOE1gO1xuXG5jb25zdCBzZWNyZXRzU3RhY2sgPSBuZXcgU2VjcmV0c1N0YWNrKGFwcCwgJ0dsaXRjaFNlY3JldHNTdGFjaycsIHtcbiAgZW52LFxuICBkZWZhdWx0RXhlY3V0aW9uUm9sZUFybixcbiAgZGVzY3JpcHRpb246ICdTZWNyZXRzIE1hbmFnZXIgY29uZmlndXJhdGlvbiBmb3IgQWdlbnRDb3JlIEdsaXRjaCcsXG59KTtcblxuLy8gQnVtcCBpbnN0YW5jZUJvb3RzdHJhcFZlcnNpb24gKGUuZy4gdG8gJzUnKSB0byBmb3JjZSBFQzIgaW5zdGFuY2UgcmVwbGFjZW1lbnQgb24gbmV4dCBkZXBsb3kuXG5jb25zdCB0YWlsc2NhbGVTdGFjayA9IG5ldyBUYWlsc2NhbGVTdGFjayhhcHAsICdHbGl0Y2hUYWlsc2NhbGVTdGFjaycsIHtcbiAgZW52LFxuICB2cGM6IHZwY1N0YWNrLnZwYyxcbiAgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogc2VjcmV0c1N0YWNrLnRhaWxzY2FsZUF1dGhLZXlTZWNyZXQsXG4gIGFnZW50Q29yZVJ1bnRpbWVBcm4sXG4gIGluc3RhbmNlQm9vdHN0cmFwVmVyc2lvbjogJzUnLFxuICBkZXNjcmlwdGlvbjogJ0VDMiBUYWlsc2NhbGUgY29ubmVjdG9yIGZvciBvbi1wcmVtaXNlcyBuZXR3b3JrIGFjY2VzcycsXG59KTtcbnRhaWxzY2FsZVN0YWNrLmFkZERlcGVuZGVuY3kodnBjU3RhY2spO1xudGFpbHNjYWxlU3RhY2suYWRkRGVwZW5kZW5jeShzZWNyZXRzU3RhY2spO1xuXG5jb25zdCBhZ2VudENvcmVTdGFjayA9IG5ldyBBZ2VudENvcmVTdGFjayhhcHAsICdHbGl0Y2hBZ2VudENvcmVTdGFjaycsIHtcbiAgZW52LFxuICB2cGM6IHZwY1N0YWNrLnZwYyxcbiAgdGFpbHNjYWxlU2VjdXJpdHlHcm91cDogdGFpbHNjYWxlU3RhY2suc2VjdXJpdHlHcm91cCxcbiAgYXBpS2V5c1NlY3JldDogc2VjcmV0c1N0YWNrLmFwaUtleXNTZWNyZXQsXG4gIHRlbGVncmFtQm90VG9rZW5TZWNyZXQ6IHNlY3JldHNTdGFjay50ZWxlZ3JhbUJvdFRva2VuU2VjcmV0LFxuICBkZXNjcmlwdGlvbjogJ0FnZW50Q29yZSBSdW50aW1lIHJlc291cmNlcycsXG59KTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3kodnBjU3RhY2spO1xuYWdlbnRDb3JlU3RhY2suYWRkRGVwZW5kZW5jeShzZWNyZXRzU3RhY2spO1xuYWdlbnRDb3JlU3RhY2suYWRkRGVwZW5kZW5jeSh0YWlsc2NhbGVTdGFjayk7XG5cbmNvbnN0IHN0b3JhZ2VTdGFjayA9IG5ldyBHbGl0Y2hTdG9yYWdlU3RhY2soYXBwLCAnR2xpdGNoU3RvcmFnZVN0YWNrJywge1xuICBlbnYsXG4gIGRlZmF1bHRFeGVjdXRpb25Sb2xlQXJuLFxuICBkZXNjcmlwdGlvbjogJ0R5bmFtb0RCLCBTMywgU1NNLCBhbmQgdGVsZW1ldHJ5IGxvZyBncm91cCBmb3IgR2xpdGNoJyxcbn0pO1xuXG5jb25zdCBnYXRld2F5U3RhY2sgPSBuZXcgR2xpdGNoR2F0ZXdheVN0YWNrKGFwcCwgJ0dsaXRjaEdhdGV3YXlTdGFjaycsIHtcbiAgZW52LFxuICBjb25maWdUYWJsZTogc3RvcmFnZVN0YWNrLmNvbmZpZ1RhYmxlLFxuICBhZ2VudENvcmVSdW50aW1lQXJuLFxuICBkZXNjcmlwdGlvbjogJ0dhdGV3YXkgTGFtYmRhIChpbnZvY2F0aW9ucywgL2FwaS8qLCBrZWVwYWxpdmUpJyxcbn0pO1xuZ2F0ZXdheVN0YWNrLmFkZERlcGVuZGVuY3koc3RvcmFnZVN0YWNrKTtcblxuY2RrLlRhZ3Mub2YoYXBwKS5hZGQoJ1Byb2plY3QnLCAnQWdlbnRDb3JlLUdsaXRjaCcpO1xuY2RrLlRhZ3Mub2YoYXBwKS5hZGQoJ01hbmFnZWRCeScsICdDREsnKTtcblxuYXBwLnN5bnRoKCk7XG4iXX0=