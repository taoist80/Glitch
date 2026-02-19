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
const app = new cdk.App();
const env = {
    account: '999776382415',
    region: 'us-west-2',
};
const vpcStack = new vpc_stack_1.VpcStack(app, 'GlitchVpcStack', {
    env,
    description: 'VPC infrastructure for AgentCore Glitch',
});
const secretsStack = new secrets_stack_1.SecretsStack(app, 'GlitchSecretsStack', {
    env,
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
    description: 'AgentCore Runtime resources',
});
agentCoreStack.addDependency(vpcStack);
agentCoreStack.addDependency(secretsStack);
agentCoreStack.addDependency(tailscaleStack);
cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');
app.synth();
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLHVDQUFxQztBQUNyQyxpREFBbUM7QUFDbkMsZ0RBQTRDO0FBQzVDLHdEQUFvRDtBQUNwRCw0REFBd0Q7QUFDeEQsNERBQXdEO0FBRXhELE1BQU0sR0FBRyxHQUFHLElBQUksR0FBRyxDQUFDLEdBQUcsRUFBRSxDQUFDO0FBRTFCLE1BQU0sR0FBRyxHQUFHO0lBQ1YsT0FBTyxFQUFFLGNBQWM7SUFDdkIsTUFBTSxFQUFFLFdBQVc7Q0FDcEIsQ0FBQztBQUVGLE1BQU0sUUFBUSxHQUFHLElBQUksb0JBQVEsQ0FBQyxHQUFHLEVBQUUsZ0JBQWdCLEVBQUU7SUFDbkQsR0FBRztJQUNILFdBQVcsRUFBRSx5Q0FBeUM7Q0FDdkQsQ0FBQyxDQUFDO0FBRUgsTUFBTSxZQUFZLEdBQUcsSUFBSSw0QkFBWSxDQUFDLEdBQUcsRUFBRSxvQkFBb0IsRUFBRTtJQUMvRCxHQUFHO0lBQ0gsV0FBVyxFQUFFLG9EQUFvRDtDQUNsRSxDQUFDLENBQUM7QUFFSCxNQUFNLGNBQWMsR0FBRyxJQUFJLGdDQUFjLENBQUMsR0FBRyxFQUFFLHNCQUFzQixFQUFFO0lBQ3JFLEdBQUc7SUFDSCxHQUFHLEVBQUUsUUFBUSxDQUFDLEdBQUc7SUFDakIsc0JBQXNCLEVBQUUsWUFBWSxDQUFDLHNCQUFzQjtJQUMzRCxXQUFXLEVBQUUsb0RBQW9EO0NBQ2xFLENBQUMsQ0FBQztBQUNILGNBQWMsQ0FBQyxhQUFhLENBQUMsUUFBUSxDQUFDLENBQUM7QUFDdkMsY0FBYyxDQUFDLGFBQWEsQ0FBQyxZQUFZLENBQUMsQ0FBQztBQUUzQyxNQUFNLGNBQWMsR0FBRyxJQUFJLGdDQUFjLENBQUMsR0FBRyxFQUFFLHNCQUFzQixFQUFFO0lBQ3JFLEdBQUc7SUFDSCxHQUFHLEVBQUUsUUFBUSxDQUFDLEdBQUc7SUFDakIsc0JBQXNCLEVBQUUsY0FBYyxDQUFDLGFBQWE7SUFDcEQsYUFBYSxFQUFFLFlBQVksQ0FBQyxhQUFhO0lBQ3pDLFdBQVcsRUFBRSw2QkFBNkI7Q0FDM0MsQ0FBQyxDQUFDO0FBQ0gsY0FBYyxDQUFDLGFBQWEsQ0FBQyxRQUFRLENBQUMsQ0FBQztBQUN2QyxjQUFjLENBQUMsYUFBYSxDQUFDLFlBQVksQ0FBQyxDQUFDO0FBQzNDLGNBQWMsQ0FBQyxhQUFhLENBQUMsY0FBYyxDQUFDLENBQUM7QUFFN0MsR0FBRyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsR0FBRyxDQUFDLENBQUMsR0FBRyxDQUFDLFNBQVMsRUFBRSxrQkFBa0IsQ0FBQyxDQUFDO0FBQ3BELEdBQUcsQ0FBQyxJQUFJLENBQUMsRUFBRSxDQUFDLEdBQUcsQ0FBQyxDQUFDLEdBQUcsQ0FBQyxXQUFXLEVBQUUsS0FBSyxDQUFDLENBQUM7QUFFekMsR0FBRyxDQUFDLEtBQUssRUFBRSxDQUFDIiwic291cmNlc0NvbnRlbnQiOlsiIyEvdXNyL2Jpbi9lbnYgbm9kZVxuaW1wb3J0ICdzb3VyY2UtbWFwLXN1cHBvcnQvcmVnaXN0ZXInO1xuaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCB7IFZwY1N0YWNrIH0gZnJvbSAnLi4vbGliL3ZwYy1zdGFjayc7XG5pbXBvcnQgeyBTZWNyZXRzU3RhY2sgfSBmcm9tICcuLi9saWIvc2VjcmV0cy1zdGFjayc7XG5pbXBvcnQgeyBUYWlsc2NhbGVTdGFjayB9IGZyb20gJy4uL2xpYi90YWlsc2NhbGUtc3RhY2snO1xuaW1wb3J0IHsgQWdlbnRDb3JlU3RhY2sgfSBmcm9tICcuLi9saWIvYWdlbnRjb3JlLXN0YWNrJztcblxuY29uc3QgYXBwID0gbmV3IGNkay5BcHAoKTtcblxuY29uc3QgZW52ID0ge1xuICBhY2NvdW50OiAnOTk5Nzc2MzgyNDE1JyxcbiAgcmVnaW9uOiAndXMtd2VzdC0yJyxcbn07XG5cbmNvbnN0IHZwY1N0YWNrID0gbmV3IFZwY1N0YWNrKGFwcCwgJ0dsaXRjaFZwY1N0YWNrJywge1xuICBlbnYsXG4gIGRlc2NyaXB0aW9uOiAnVlBDIGluZnJhc3RydWN0dXJlIGZvciBBZ2VudENvcmUgR2xpdGNoJyxcbn0pO1xuXG5jb25zdCBzZWNyZXRzU3RhY2sgPSBuZXcgU2VjcmV0c1N0YWNrKGFwcCwgJ0dsaXRjaFNlY3JldHNTdGFjaycsIHtcbiAgZW52LFxuICBkZXNjcmlwdGlvbjogJ1NlY3JldHMgTWFuYWdlciBjb25maWd1cmF0aW9uIGZvciBBZ2VudENvcmUgR2xpdGNoJyxcbn0pO1xuXG5jb25zdCB0YWlsc2NhbGVTdGFjayA9IG5ldyBUYWlsc2NhbGVTdGFjayhhcHAsICdHbGl0Y2hUYWlsc2NhbGVTdGFjaycsIHtcbiAgZW52LFxuICB2cGM6IHZwY1N0YWNrLnZwYyxcbiAgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogc2VjcmV0c1N0YWNrLnRhaWxzY2FsZUF1dGhLZXlTZWNyZXQsXG4gIGRlc2NyaXB0aW9uOiAnRUMyIFRhaWxzY2FsZSBjb25uZWN0b3IgZm9yIHByaXZhdGUgbmV0d29yayBhY2Nlc3MnLFxufSk7XG50YWlsc2NhbGVTdGFjay5hZGREZXBlbmRlbmN5KHZwY1N0YWNrKTtcbnRhaWxzY2FsZVN0YWNrLmFkZERlcGVuZGVuY3koc2VjcmV0c1N0YWNrKTtcblxuY29uc3QgYWdlbnRDb3JlU3RhY2sgPSBuZXcgQWdlbnRDb3JlU3RhY2soYXBwLCAnR2xpdGNoQWdlbnRDb3JlU3RhY2snLCB7XG4gIGVudixcbiAgdnBjOiB2cGNTdGFjay52cGMsXG4gIHRhaWxzY2FsZVNlY3VyaXR5R3JvdXA6IHRhaWxzY2FsZVN0YWNrLnNlY3VyaXR5R3JvdXAsXG4gIGFwaUtleXNTZWNyZXQ6IHNlY3JldHNTdGFjay5hcGlLZXlzU2VjcmV0LFxuICBkZXNjcmlwdGlvbjogJ0FnZW50Q29yZSBSdW50aW1lIHJlc291cmNlcycsXG59KTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3kodnBjU3RhY2spO1xuYWdlbnRDb3JlU3RhY2suYWRkRGVwZW5kZW5jeShzZWNyZXRzU3RhY2spO1xuYWdlbnRDb3JlU3RhY2suYWRkRGVwZW5kZW5jeSh0YWlsc2NhbGVTdGFjayk7XG5cbmNkay5UYWdzLm9mKGFwcCkuYWRkKCdQcm9qZWN0JywgJ0FnZW50Q29yZS1HbGl0Y2gnKTtcbmNkay5UYWdzLm9mKGFwcCkuYWRkKCdNYW5hZ2VkQnknLCAnQ0RLJyk7XG5cbmFwcC5zeW50aCgpO1xuIl19