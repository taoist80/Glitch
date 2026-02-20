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
exports.AgentCoreStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const ec2 = __importStar(require("aws-cdk-lib/aws-ec2"));
const iam = __importStar(require("aws-cdk-lib/aws-iam"));
class AgentCoreStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        const { vpc, tailscaleSecurityGroup, apiKeysSecret, telegramBotTokenSecret } = props;
        this.agentCoreSecurityGroup = new ec2.SecurityGroup(this, 'AgentCoreSecurityGroup', {
            vpc,
            description: 'Security group for AgentCore Runtime ENIs',
            allowAllOutbound: false,
        });
        this.agentCoreSecurityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS for Bedrock API calls');
        this.agentCoreSecurityGroup.addEgressRule(tailscaleSecurityGroup, ec2.Port.allTraffic(), 'Allow all traffic to Tailscale connector');
        this.agentCoreSecurityGroup.addIngressRule(tailscaleSecurityGroup, ec2.Port.tcp(443), 'Allow HTTPS from Tailscale proxy');
        this.agentRuntimeRole = new iam.Role(this, 'AgentRuntimeRole', {
            assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
            description: 'IAM role for AgentCore Runtime',
            roleName: 'GlitchAgentCoreRuntimeRole',
        });
        this.agentRuntimeRole.addToPolicy(new iam.PolicyStatement({
            sid: 'BedrockModelAccess',
            effect: iam.Effect.ALLOW,
            actions: [
                'bedrock:InvokeModel',
                'bedrock:InvokeModelWithResponseStream',
            ],
            resources: [
                `arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0`,
                `arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-sonnet-4.6*`,
                `arn:aws:bedrock:${this.region}::foundation-model/anthropic.claude-opus-4*`,
            ],
        }));
        this.agentRuntimeRole.addToPolicy(new iam.PolicyStatement({
            sid: 'ECRImageAccess',
            effect: iam.Effect.ALLOW,
            actions: [
                'ecr:BatchGetImage',
                'ecr:GetDownloadUrlForLayer',
            ],
            resources: [
                `arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`,
            ],
        }));
        this.agentRuntimeRole.addToPolicy(new iam.PolicyStatement({
            sid: 'ECRTokenAccess',
            effect: iam.Effect.ALLOW,
            actions: [
                'ecr:GetAuthorizationToken',
            ],
            resources: ['*'],
        }));
        this.agentRuntimeRole.addToPolicy(new iam.PolicyStatement({
            sid: 'AgentCoreMemoryAccess',
            effect: iam.Effect.ALLOW,
            actions: [
                'bedrock-agentcore:CreateEvent',
                'bedrock-agentcore:GetEvent',
                'bedrock-agentcore:ListEvents',
                'bedrock-agentcore:ListSessions',
                'bedrock-agentcore:CreateMemoryRecord',
                'bedrock-agentcore:GetMemoryRecord',
                'bedrock-agentcore:ListMemoryRecords',
                'bedrock-agentcore:RetrieveMemoryRecords',
            ],
            resources: ['*'],
        }));
        apiKeysSecret.grantRead(this.agentRuntimeRole);
        telegramBotTokenSecret.grantRead(this.agentRuntimeRole);
        this.agentRuntimeRole.addToPolicy(new iam.PolicyStatement({
            sid: 'CloudWatchLogs',
            effect: iam.Effect.ALLOW,
            actions: [
                'logs:CreateLogGroup',
                'logs:CreateLogStream',
                'logs:PutLogEvents',
            ],
            resources: [
                `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock/agentcore/*`,
            ],
        }));
        new cdk.CfnOutput(this, 'AgentRuntimeRoleArn', {
            value: this.agentRuntimeRole.roleArn,
            description: 'IAM role ARN for AgentCore Runtime (use with agentcore configure --execution-role)',
            exportName: 'GlitchAgentRuntimeRoleArn',
        });
        new cdk.CfnOutput(this, 'AgentCoreSecurityGroupId', {
            value: this.agentCoreSecurityGroup.securityGroupId,
            description: 'Security group ID for AgentCore ENIs',
            exportName: 'GlitchAgentCoreSecurityGroupId',
        });
        new cdk.CfnOutput(this, 'VpcConfigForAgentCore', {
            value: JSON.stringify({
                subnets: vpc.isolatedSubnets.map(s => s.subnetId),
                securityGroups: [this.agentCoreSecurityGroup.securityGroupId],
            }),
            description: 'VPC configuration for AgentCore Runtime (JSON)',
            exportName: 'GlitchVpcConfig',
        });
    }
}
exports.AgentCoreStack = AgentCoreStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYWdlbnRjb3JlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYWdlbnRjb3JlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBVzNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxhQUFhLEVBQUUsc0JBQXNCLEVBQUUsR0FBRyxLQUFLLENBQUM7UUFFckYsSUFBSSxDQUFDLHNCQUFzQixHQUFHLElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDbEYsR0FBRztZQUNILFdBQVcsRUFBRSwyQ0FBMkM7WUFDeEQsZ0JBQWdCLEVBQUUsS0FBSztTQUN4QixDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsc0JBQXNCLENBQUMsYUFBYSxDQUN2QyxHQUFHLENBQUMsSUFBSSxDQUFDLE9BQU8sRUFBRSxFQUNsQixHQUFHLENBQUMsSUFBSSxDQUFDLEdBQUcsQ0FBQyxHQUFHLENBQUMsRUFDakIsNkJBQTZCLENBQzlCLENBQUM7UUFFRixJQUFJLENBQUMsc0JBQXNCLENBQUMsYUFBYSxDQUN2QyxzQkFBc0IsRUFDdEIsR0FBRyxDQUFDLElBQUksQ0FBQyxVQUFVLEVBQUUsRUFDckIsMENBQTBDLENBQzNDLENBQUM7UUFFRixJQUFJLENBQUMsc0JBQXNCLENBQUMsY0FBYyxDQUN4QyxzQkFBc0IsRUFDdEIsR0FBRyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsR0FBRyxDQUFDLEVBQ2pCLGtDQUFrQyxDQUNuQyxDQUFDO1FBRUYsSUFB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LEVBQUUsb0ZBQW9GO1lBQ2pHLFVBQVUsRUFBRSwyQkFBMkI7U0FDeEMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSwwQkFBMEIsRUFBRTtZQUNsRCxLQUFLLEVBQUUsSUFBSSxDQUFDLHNCQUFzQixDQUFDLGVBQWU7WUFDbEQsV0FBVyxFQUFFLHNDQUFzQztZQUNuRCxVQUFVLEVBQUUsZ0NBQWdDO1NBQzdDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsdUJBQXVCLEVBQUU7WUFDL0MsS0FBSyxFQUFFLElBQUksQ0FBQyxTQUFTLENBQUM7Z0JBQ3BCLE9BQU8sRUFBRSxHQUFHLENBQUMsZUFBZSxDQUFDLEdBQUcsQ0FBQyxDQUFDLENBQUMsRUFBRSxDQUFDLENBQUMsQ0FBQyxRQUFRLENBQUM7Z0JBQ2pELGNBQWMsRUFBRSxDQUFDLElBQUksQ0FBQyxzQkFBc0IsQ0FBQyxlQUFlLENBQUM7YUFDOUQsQ0FBQztZQUNGLFdBQVcsRUFBRSxnREFBZ0Q7WUFDN0QsVUFBVSxFQUFFLGlCQUFpQjtTQUM5QixDQUFDLENBQUM7SUFDTCxDQUFDO0NBQ0Y7QUF6SUQsd0NBeUlDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIGVjMiBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZWMyJztcbmltcG9ydCAqIGFzIGlhbSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtaWFtJztcbmltcG9ydCAqIGFzIHNlY3JldHNtYW5hZ2VyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1zZWNyZXRzbWFuYWdlcic7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcblxuZXhwb3J0IGludGVyZmFjZSBBZ2VudENvcmVTdGFja1Byb3BzIGV4dGVuZHMgY2RrLlN0YWNrUHJvcHMge1xuICByZWFkb25seSB2cGM6IGVjMi5JVnBjO1xuICByZWFkb25seSB0YWlsc2NhbGVTZWN1cml0eUdyb3VwOiBlYzIuSVNlY3VyaXR5R3JvdXA7XG4gIHJlYWRvbmx5IGFwaUtleXNTZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHJlYWRvbmx5IHRlbGVncmFtQm90VG9rZW5TZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG59XG5cbmV4cG9ydCBjbGFzcyBBZ2VudENvcmVTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSBhZ2VudFJ1bnRpbWVSb2xlOiBpYW0uUm9sZTtcbiAgcHVibGljIHJlYWRvbmx5IGFnZW50Q29yZVNlY3VyaXR5R3JvdXA6IGVjMi5TZWN1cml0eUdyb3VwO1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBBZ2VudENvcmVTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICBjb25zdCB7IHZwYywgdGFpbHNjYWxlU2VjdXJpdHlHcm91cCwgYXBpS2V5c1NlY3JldCwgdGVsZWdyYW1Cb3RUb2tlblNlY3JldCB9ID0gcHJvcHM7XG5cbiAgICB0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAgPSBuZXcgZWMyLlNlY3VyaXR5R3JvdXAodGhpcywgJ0FnZW50Q29yZVNlY3VyaXR5R3JvdXAnLCB7XG4gICAgICB2cGMsXG4gICAgICBkZXNjcmlwdGlvbjogJ1NlY3VyaXR5IGdyb3VwIGZvciBBZ2VudENvcmUgUnVudGltZSBFTklzJyxcbiAgICAgIGFsbG93QWxsT3V0Ym91bmQ6IGZhbHNlLFxuICAgIH0pO1xuXG4gICAgdGhpcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC50Y3AoNDQzKSxcbiAgICAgICdIVFRQUyBmb3IgQmVkcm9jayBBUEkgY2FsbHMnXG4gICAgKTtcblxuICAgIHRoaXMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgdGFpbHNjYWxlU2VjdXJpdHlHcm91cCxcbiAgICAgIGVjMi5Qb3J0LmFsbFRyYWZmaWMoKSxcbiAgICAgICdBbGxvdyBhbGwgdHJhZmZpYyB0byBUYWlsc2NhbGUgY29ubmVjdG9yJ1xuICAgICk7XG5cbiAgICB0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICB0YWlsc2NhbGVTZWN1cml0eUdyb3VwLFxuICAgICAgZWMyLlBvcnQudGNwKDQ0MyksXG4gICAgICAnQWxsb3cgSFRUUFMgZnJvbSBUYWlsc2NhbGUgcHJveHknXG4gICAgKTtcblxuICAgIHRoaXMuYWdlbnRSdW50aW1lUm9sZSA9IG5ldyBpYW0uUm9sZSh0aGlzLCAnQWdlbnRSdW50aW1lUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdiZWRyb2NrLWFnZW50Y29yZS5hbWF6b25hd3MuY29tJyksXG4gICAgICBkZXNjcmlwdGlvbjogJ0lBTSByb2xlIGZvciBBZ2VudENvcmUgUnVudGltZScsXG4gICAgICByb2xlTmFtZTogJ0dsaXRjaEFnZW50Q29yZVJ1bnRpbWVSb2xlJyxcbiAgICB9KTtcblxuICAgIHRoaXMuYWdlbnRSdW50aW1lUm9sZS5hZGRUb1BvbGljeShcbiAgICAgIG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgc2lkOiAnQmVkcm9ja01vZGVsQWNjZXNzJyxcbiAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgJ2JlZHJvY2s6SW52b2tlTW9kZWwnLFxuICAgICAgICAgICdiZWRyb2NrOkludm9rZU1vZGVsV2l0aFJlc3BvbnNlU3RyZWFtJyxcbiAgICAgICAgXSxcbiAgICAgICAgcmVzb3VyY2VzOiBbXG4gICAgICAgICAgYGFybjphd3M6YmVkcm9jazoke3RoaXMucmVnaW9ufTo6Zm91bmRhdGlvbi1tb2RlbC9hbnRocm9waWMuY2xhdWRlLXNvbm5ldC00LTIwMjUwNTE0LXYxOjBgLFxuICAgICAgICAgIGBhcm46YXdzOmJlZHJvY2s6JHt0aGlzLnJlZ2lvbn06OmZvdW5kYXRpb24tbW9kZWwvYW50aHJvcGljLmNsYXVkZS1zb25uZXQtNC42KmAsXG4gICAgICAgICAgYGFybjphd3M6YmVkcm9jazoke3RoaXMucmVnaW9ufTo6Zm91bmRhdGlvbi1tb2RlbC9hbnRocm9waWMuY2xhdWRlLW9wdXMtNCpgLFxuICAgICAgICBdLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdFQ1JJbWFnZUFjY2VzcycsXG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdlY3I6QmF0Y2hHZXRJbWFnZScsXG4gICAgICAgICAgJ2VjcjpHZXREb3dubG9hZFVybEZvckxheWVyJyxcbiAgICAgICAgXSxcbiAgICAgICAgcmVzb3VyY2VzOiBbXG4gICAgICAgICAgYGFybjphd3M6ZWNyOiR7dGhpcy5yZWdpb259OiR7dGhpcy5hY2NvdW50fTpyZXBvc2l0b3J5L2JlZHJvY2stYWdlbnRjb3JlLSpgLFxuICAgICAgICBdLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdFQ1JUb2tlbkFjY2VzcycsXG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdlY3I6R2V0QXV0aG9yaXphdGlvblRva2VuJyxcbiAgICAgICAgXSxcbiAgICAgICAgcmVzb3VyY2VzOiBbJyonXSxcbiAgICAgIH0pXG4gICAgKTtcblxuICAgIHRoaXMuYWdlbnRSdW50aW1lUm9sZS5hZGRUb1BvbGljeShcbiAgICAgIG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgc2lkOiAnQWdlbnRDb3JlTWVtb3J5QWNjZXNzJyxcbiAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkNyZWF0ZUV2ZW50JyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6R2V0RXZlbnQnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpMaXN0RXZlbnRzJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6TGlzdFNlc3Npb25zJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6Q3JlYXRlTWVtb3J5UmVjb3JkJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6R2V0TWVtb3J5UmVjb3JkJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6TGlzdE1lbW9yeVJlY29yZHMnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpSZXRyaWV2ZU1lbW9yeVJlY29yZHMnLFxuICAgICAgICBdLFxuICAgICAgICByZXNvdXJjZXM6IFsnKiddLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgYXBpS2V5c1NlY3JldC5ncmFudFJlYWQodGhpcy5hZ2VudFJ1bnRpbWVSb2xlKTtcbiAgICB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0LmdyYW50UmVhZCh0aGlzLmFnZW50UnVudGltZVJvbGUpO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdDbG91ZFdhdGNoTG9ncycsXG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdsb2dzOkNyZWF0ZUxvZ0dyb3VwJyxcbiAgICAgICAgICAnbG9nczpDcmVhdGVMb2dTdHJlYW0nLFxuICAgICAgICAgICdsb2dzOlB1dExvZ0V2ZW50cycsXG4gICAgICAgIF0sXG4gICAgICAgIHJlc291cmNlczogW1xuICAgICAgICAgIGBhcm46YXdzOmxvZ3M6JHt0aGlzLnJlZ2lvbn06JHt0aGlzLmFjY291bnR9OmxvZy1ncm91cDovYXdzL2JlZHJvY2svYWdlbnRjb3JlLypgLFxuICAgICAgICBdLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0FnZW50UnVudGltZVJvbGVBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLnJvbGVBcm4sXG4gICAgICBkZXNjcmlwdGlvbjogJ0lBTSByb2xlIEFSTiBmb3IgQWdlbnRDb3JlIFJ1bnRpbWUgKHVzZSB3aXRoIGFnZW50Y29yZSBjb25maWd1cmUgLS1leGVjdXRpb24tcm9sZSknLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaEFnZW50UnVudGltZVJvbGVBcm4nLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0FnZW50Q29yZVNlY3VyaXR5R3JvdXBJZCcsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAuc2VjdXJpdHlHcm91cElkLFxuICAgICAgZGVzY3JpcHRpb246ICdTZWN1cml0eSBncm91cCBJRCBmb3IgQWdlbnRDb3JlIEVOSXMnLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaEFnZW50Q29yZVNlY3VyaXR5R3JvdXBJZCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnVnBjQ29uZmlnRm9yQWdlbnRDb3JlJywge1xuICAgICAgdmFsdWU6IEpTT04uc3RyaW5naWZ5KHtcbiAgICAgICAgc3VibmV0czogdnBjLmlzb2xhdGVkU3VibmV0cy5tYXAocyA9PiBzLnN1Ym5ldElkKSxcbiAgICAgICAgc2VjdXJpdHlHcm91cHM6IFt0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAuc2VjdXJpdHlHcm91cElkXSxcbiAgICAgIH0pLFxuICAgICAgZGVzY3JpcHRpb246ICdWUEMgY29uZmlndXJhdGlvbiBmb3IgQWdlbnRDb3JlIFJ1bnRpbWUgKEpTT04pJyxcbiAgICAgIGV4cG9ydE5hbWU6ICdHbGl0Y2hWcGNDb25maWcnLFxuICAgIH0pO1xuICB9XG59XG4iXX0=