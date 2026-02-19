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
    telegramBotTokenSecret: secretsStack.telegramBotTokenSecret,
    description: 'AgentCore Runtime resources',
});
agentCoreStack.addDependency(vpcStack);
agentCoreStack.addDependency(secretsStack);
agentCoreStack.addDependency(tailscaleStack);
cdk.Tags.of(app).add('Project', 'AgentCore-Glitch');
cdk.Tags.of(app).add('ManagedBy', 'CDK');
app.synth();
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYXBwLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYXBwLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUNBLHVDQUFxQztBQUNyQyxpREFBbUM7QUFDbkMsZ0RBQTRDO0FBQzVDLHdEQUFvRDtBQUNwRCw0REFBd0Q7QUFDeEQsNERBQXdEO0FBRXhELE1BQU0sR0FBRyxHQUFHLElBQUksR0FBRyxDQUFDLEdBQUcsRUFBRSxDQUFDO0FBRTFCLE1BQU0sR0FBRyxHQUFHO0lBQ1YsT0FBTyxFQUFFLGNBQWM7SUFDdkIsTUFBTSxFQUFFLFdBQVc7Q0FDcEIsQ0FBQztBQUVGLE1BQU0sUUFBUSxHQUFHLElBQUksb0JBQVEsQ0FBQyxHQUFHLEVBQUUsZ0JBQWdCLEVBQUU7SUFDbkQsR0FBRztJQUNILFdBQVcsRUFBRSx5Q0FBeUM7Q0FDdkQsQ0FBQyxDQUFDO0FBRUgsTUFBTSxZQUFZLEdBQUcsSUFBSSw0QkFBWSxDQUFDLEdBQUcsRUFBRSxvQkFBb0IsRUFBRTtJQUMvRCxHQUFHO0lBQ0gsV0FBVyxFQUFFLG9EQUFvRDtDQUNsRSxDQUFDLENBQUM7QUFFSCxNQUFNLGNBQWMsR0FBRyxJQUFJLGdDQUFjLENBQUMsR0FBRyxFQUFFLHNCQUFzQixFQUFFO0lBQ3JFLEdBQUc7SUFDSCxHQUFHLEVBQUUsUUFBUSxDQUFDLEdBQUc7SUFDakIsc0JBQXNCLEVBQUUsWUFBWSxDQUFDLHNCQUFzQjtJQUMzRCxXQUFXLEVBQUUsb0RBQW9EO0NBQ2xFLENBQUMsQ0FBQztBQUNILGNBQWMsQ0FBQyxhQUFhLENBQUMsUUFBUSxDQUFDLENBQUM7QUFDdkMsY0FBYyxDQUFDLGFBQWEsQ0FBQyxZQUFZLENBQUMsQ0FBQztBQUUzQyxNQUFNLGNBQWMsR0FBRyxJQUFJLGdDQUFjLENBQUMsR0FBRyxFQUFFLHNCQUFzQixFQUFFO0lBQ3JFLEdBQUc7SUFDSCxHQUFHLEVBQUUsUUFBUSxDQUFDLEdBQUc7SUFDakIsc0JBQXNCLEVBQUUsY0FBYyxDQUFDLGFBQWE7SUFDcEQsYUFBYSxFQUFFLFlBQVksQ0FBQyxhQUFhO0lBQ3pDLHNCQUFzQixFQUFFLFlBQVksQ0FBQyxzQkFBc0I7SUFDM0QsV0FBVyxFQUFFLDZCQUE2QjtDQUMzQyxDQUFDLENBQUM7QUFDSCxjQUFjLENBQUMsYUFBYSxDQUFDLFFBQVEsQ0FBQyxDQUFDO0FBQ3ZDLGNBQWMsQ0FBQyxhQUFhLENBQUMsWUFBWSxDQUFDLENBQUM7QUFDM0MsY0FBYyxDQUFDLGFBQWEsQ0FBQyxjQUFjLENBQUMsQ0FBQztBQUU3QyxHQUFHLENBQUMsSUFBSSxDQUFDLEVBQUUsQ0FBQyxHQUFHLENBQUMsQ0FBQyxHQUFHLENBQUMsU0FBUyxFQUFFLGtCQUFrQixDQUFDLENBQUM7QUFDcEQsR0FBRyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsR0FBRyxDQUFDLENBQUMsR0FBRyxDQUFDLFdBQVcsRUFBRSxLQUFLLENBQUMsQ0FBQztBQUV6QyxHQUFHLENBQUMsS0FBSyxFQUFFLENBQUMiLCJzb3VyY2VzQ29udGVudCI6WyIjIS91c3IvYmluL2VudiBub2RlXG5pbXBvcnQgJ3NvdXJjZS1tYXAtc3VwcG9ydC9yZWdpc3Rlcic7XG5pbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0IHsgVnBjU3RhY2sgfSBmcm9tICcuLi9saWIvdnBjLXN0YWNrJztcbmltcG9ydCB7IFNlY3JldHNTdGFjayB9IGZyb20gJy4uL2xpYi9zZWNyZXRzLXN0YWNrJztcbmltcG9ydCB7IFRhaWxzY2FsZVN0YWNrIH0gZnJvbSAnLi4vbGliL3RhaWxzY2FsZS1zdGFjayc7XG5pbXBvcnQgeyBBZ2VudENvcmVTdGFjayB9IGZyb20gJy4uL2xpYi9hZ2VudGNvcmUtc3RhY2snO1xuXG5jb25zdCBhcHAgPSBuZXcgY2RrLkFwcCgpO1xuXG5jb25zdCBlbnYgPSB7XG4gIGFjY291bnQ6ICc5OTk3NzYzODI0MTUnLFxuICByZWdpb246ICd1cy13ZXN0LTInLFxufTtcblxuY29uc3QgdnBjU3RhY2sgPSBuZXcgVnBjU3RhY2soYXBwLCAnR2xpdGNoVnBjU3RhY2snLCB7XG4gIGVudixcbiAgZGVzY3JpcHRpb246ICdWUEMgaW5mcmFzdHJ1Y3R1cmUgZm9yIEFnZW50Q29yZSBHbGl0Y2gnLFxufSk7XG5cbmNvbnN0IHNlY3JldHNTdGFjayA9IG5ldyBTZWNyZXRzU3RhY2soYXBwLCAnR2xpdGNoU2VjcmV0c1N0YWNrJywge1xuICBlbnYsXG4gIGRlc2NyaXB0aW9uOiAnU2VjcmV0cyBNYW5hZ2VyIGNvbmZpZ3VyYXRpb24gZm9yIEFnZW50Q29yZSBHbGl0Y2gnLFxufSk7XG5cbmNvbnN0IHRhaWxzY2FsZVN0YWNrID0gbmV3IFRhaWxzY2FsZVN0YWNrKGFwcCwgJ0dsaXRjaFRhaWxzY2FsZVN0YWNrJywge1xuICBlbnYsXG4gIHZwYzogdnBjU3RhY2sudnBjLFxuICB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0OiBzZWNyZXRzU3RhY2sudGFpbHNjYWxlQXV0aEtleVNlY3JldCxcbiAgZGVzY3JpcHRpb246ICdFQzIgVGFpbHNjYWxlIGNvbm5lY3RvciBmb3IgcHJpdmF0ZSBuZXR3b3JrIGFjY2VzcycsXG59KTtcbnRhaWxzY2FsZVN0YWNrLmFkZERlcGVuZGVuY3kodnBjU3RhY2spO1xudGFpbHNjYWxlU3RhY2suYWRkRGVwZW5kZW5jeShzZWNyZXRzU3RhY2spO1xuXG5jb25zdCBhZ2VudENvcmVTdGFjayA9IG5ldyBBZ2VudENvcmVTdGFjayhhcHAsICdHbGl0Y2hBZ2VudENvcmVTdGFjaycsIHtcbiAgZW52LFxuICB2cGM6IHZwY1N0YWNrLnZwYyxcbiAgdGFpbHNjYWxlU2VjdXJpdHlHcm91cDogdGFpbHNjYWxlU3RhY2suc2VjdXJpdHlHcm91cCxcbiAgYXBpS2V5c1NlY3JldDogc2VjcmV0c1N0YWNrLmFwaUtleXNTZWNyZXQsXG4gIHRlbGVncmFtQm90VG9rZW5TZWNyZXQ6IHNlY3JldHNTdGFjay50ZWxlZ3JhbUJvdFRva2VuU2VjcmV0LFxuICBkZXNjcmlwdGlvbjogJ0FnZW50Q29yZSBSdW50aW1lIHJlc291cmNlcycsXG59KTtcbmFnZW50Q29yZVN0YWNrLmFkZERlcGVuZGVuY3kodnBjU3RhY2spO1xuYWdlbnRDb3JlU3RhY2suYWRkRGVwZW5kZW5jeShzZWNyZXRzU3RhY2spO1xuYWdlbnRDb3JlU3RhY2suYWRkRGVwZW5kZW5jeSh0YWlsc2NhbGVTdGFjayk7XG5cbmNkay5UYWdzLm9mKGFwcCkuYWRkKCdQcm9qZWN0JywgJ0FnZW50Q29yZS1HbGl0Y2gnKTtcbmNkay5UYWdzLm9mKGFwcCkuYWRkKCdNYW5hZ2VkQnknLCAnQ0RLJyk7XG5cbmFwcC5zeW50aCgpO1xuIl19