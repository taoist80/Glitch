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
                // Cross-region inference profiles (us.*) can route to any US region
                // Use wildcard for region to handle dynamic routing
                'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0',
                'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0',
                'arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-20250514-v1:0',
                // Inference profiles (cross-region and account-specific)
                `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
                `arn:aws:bedrock:${this.region}::inference-profile/*`,
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
                'logs:GetLogEvents',
                'logs:DescribeLogStreams',
            ],
            resources: [
                `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock/agentcore/*`,
                `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*`,
                `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*:*`,
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYWdlbnRjb3JlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYWdlbnRjb3JlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBVzNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxhQUFhLEVBQUUsc0JBQXNCLEVBQUUsR0FBRyxLQUFLLENBQUM7UUFFckYsSUFBSSxDQUFDLHNCQUFzQixHQUFHLElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDbEYsR0FBRztZQUNILFdBQVcsRUFBRSwyQ0FBMkM7WUFDeEQsZ0JBQWdCLEVBQUUsS0FBSztTQUN4QixDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsc0JBQXNCLENBQUMsYUFBYSxDQUN2QyxHQUFHLENBQUMsSUFBSSxDQUFDLE9BQU8sRUFBRSxFQUNsQixHQUFHLENBQUMsSUFBSSxDQUFDLEdBQUcsQ0FBQyxHQUFHLENBQUMsRUFDakIsNkJBQTZCLENBQzlCLENBQUM7UUFFRixJQUFJLENBQUMsc0JBQXNCLENBQUMsYUFBYSxDQUN2QyxzQkFBc0IsRUFDdEIsR0FBRyxDQUFDLElBQUksQ0FBQyxVQUFVLEVBQUUsRUFDckIsMENBQTBDLENBQzNDLENBQUM7UUFFRixJQUFJLENBQUMsc0JBQXNCLENBQUMsY0FBYyxDQUN4QyxzQkFBc0IsRUFDdEIsR0FBRyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsR0FBRyxDQUFDLEVBQ2pCLGtDQUFrQyxDQUNuQyxDQUFDO1FBRUYsSUFB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QUFJLENBQUMsT0FBTyxzQkFBc0I7Z0JBQ2pFLGdCQUFnQixJQUFJLENBQUMsTUFBTSxJQUFJLElBQUksQ0FBQyxPQUFPLHdCQUF3QjthQUNwRTtTQUNGLENBQUMsQ0FDSCxDQUFDO1FBRUYsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxxQkFBcUIsRUFBRTtZQUM3QyxLQUFLLEVBQUUsSUFBSSxDQUFDLGdCQUFnQixDQUFDLE9BQU87WUFDcEMsV0FBVyxFQUFFLG9GQUFvRjtZQUNqRyxVQUFVLEVBQUUsMkJBQTJCO1NBQ3hDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsMEJBQTBCLEVBQUU7WUFDbEQsS0FBSyxFQUFFLElBQUksQ0FBQyxzQkFBc0IsQ0FBQyxlQUFlO1lBQ2xELFdBQVcsRUFBRSxzQ0FBc0M7WUFDbkQsVUFBVSxFQUFFLGdDQUFnQztTQUM3QyxDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLHVCQUF1QixFQUFFO1lBQy9DLEtBQUssRUFBRSxJQUFJLENBQUMsU0FBUyxDQUFDO2dCQUNwQixPQUFPLEVBQUUsR0FBRyxDQUFDLGVBQWUsQ0FBQyxHQUFHLENBQUMsQ0FBQyxDQUFDLEVBQUUsQ0FBQyxDQUFDLENBQUMsUUFBUSxDQUFDO2dCQUNqRCxjQUFjLEVBQUUsQ0FBQyxJQUFJLENBQUMsc0JBQXNCLENBQUMsZUFBZSxDQUFDO2FBQzlELENBQUM7WUFDRixXQUFXLEVBQUUsZ0RBQWdEO1lBQzdELFVBQVUsRUFBRSxpQkFBaUI7U0FDOUIsQ0FBQyxDQUFDO0lBQ0wsQ0FBQztDQUNGO0FBbEpELHdDQWtKQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgKiBhcyBlYzIgZnJvbSAnYXdzLWNkay1saWIvYXdzLWVjMic7XG5pbXBvcnQgKiBhcyBpYW0gZnJvbSAnYXdzLWNkay1saWIvYXdzLWlhbSc7XG5pbXBvcnQgKiBhcyBzZWNyZXRzbWFuYWdlciBmcm9tICdhd3MtY2RrLWxpYi9hd3Mtc2VjcmV0c21hbmFnZXInO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5cbmV4cG9ydCBpbnRlcmZhY2UgQWdlbnRDb3JlU3RhY2tQcm9wcyBleHRlbmRzIGNkay5TdGFja1Byb3BzIHtcbiAgcmVhZG9ubHkgdnBjOiBlYzIuSVZwYztcbiAgcmVhZG9ubHkgdGFpbHNjYWxlU2VjdXJpdHlHcm91cDogZWMyLklTZWN1cml0eUdyb3VwO1xuICByZWFkb25seSBhcGlLZXlzU2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuICByZWFkb25seSB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xufVxuXG5leHBvcnQgY2xhc3MgQWdlbnRDb3JlU3RhY2sgZXh0ZW5kcyBjZGsuU3RhY2sge1xuICBwdWJsaWMgcmVhZG9ubHkgYWdlbnRSdW50aW1lUm9sZTogaWFtLlJvbGU7XG4gIHB1YmxpYyByZWFkb25seSBhZ2VudENvcmVTZWN1cml0eUdyb3VwOiBlYzIuU2VjdXJpdHlHcm91cDtcblxuICBjb25zdHJ1Y3RvcihzY29wZTogQ29uc3RydWN0LCBpZDogc3RyaW5nLCBwcm9wczogQWdlbnRDb3JlU3RhY2tQcm9wcykge1xuICAgIHN1cGVyKHNjb3BlLCBpZCwgcHJvcHMpO1xuXG4gICAgY29uc3QgeyB2cGMsIHRhaWxzY2FsZVNlY3VyaXR5R3JvdXAsIGFwaUtleXNTZWNyZXQsIHRlbGVncmFtQm90VG9rZW5TZWNyZXQgfSA9IHByb3BzO1xuXG4gICAgdGhpcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwID0gbmV3IGVjMi5TZWN1cml0eUdyb3VwKHRoaXMsICdBZ2VudENvcmVTZWN1cml0eUdyb3VwJywge1xuICAgICAgdnBjLFxuICAgICAgZGVzY3JpcHRpb246ICdTZWN1cml0eSBncm91cCBmb3IgQWdlbnRDb3JlIFJ1bnRpbWUgRU5JcycsXG4gICAgICBhbGxvd0FsbE91dGJvdW5kOiBmYWxzZSxcbiAgICB9KTtcblxuICAgIHRoaXMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudGNwKDQ0MyksXG4gICAgICAnSFRUUFMgZm9yIEJlZHJvY2sgQVBJIGNhbGxzJ1xuICAgICk7XG5cbiAgICB0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIHRhaWxzY2FsZVNlY3VyaXR5R3JvdXAsXG4gICAgICBlYzIuUG9ydC5hbGxUcmFmZmljKCksXG4gICAgICAnQWxsb3cgYWxsIHRyYWZmaWMgdG8gVGFpbHNjYWxlIGNvbm5lY3RvcidcbiAgICApO1xuXG4gICAgdGhpcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwLmFkZEluZ3Jlc3NSdWxlKFxuICAgICAgdGFpbHNjYWxlU2VjdXJpdHlHcm91cCxcbiAgICAgIGVjMi5Qb3J0LnRjcCg0NDMpLFxuICAgICAgJ0FsbG93IEhUVFBTIGZyb20gVGFpbHNjYWxlIHByb3h5J1xuICAgICk7XG5cbiAgICB0aGlzLmFnZW50UnVudGltZVJvbGUgPSBuZXcgaWFtLlJvbGUodGhpcywgJ0FnZW50UnVudGltZVJvbGUnLCB7XG4gICAgICBhc3N1bWVkQnk6IG5ldyBpYW0uU2VydmljZVByaW5jaXBhbCgnYmVkcm9jay1hZ2VudGNvcmUuYW1hem9uYXdzLmNvbScpLFxuICAgICAgZGVzY3JpcHRpb246ICdJQU0gcm9sZSBmb3IgQWdlbnRDb3JlIFJ1bnRpbWUnLFxuICAgICAgcm9sZU5hbWU6ICdHbGl0Y2hBZ2VudENvcmVSdW50aW1lUm9sZScsXG4gICAgfSk7XG5cbiAgICB0aGlzLmFnZW50UnVudGltZVJvbGUuYWRkVG9Qb2xpY3koXG4gICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgIHNpZDogJ0JlZHJvY2tNb2RlbEFjY2VzcycsXG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdiZWRyb2NrOkludm9rZU1vZGVsJyxcbiAgICAgICAgICAnYmVkcm9jazpJbnZva2VNb2RlbFdpdGhSZXNwb25zZVN0cmVhbScsXG4gICAgICAgIF0sXG4gICAgICAgIHJlc291cmNlczogW1xuICAgICAgICAgIC8vIENyb3NzLXJlZ2lvbiBpbmZlcmVuY2UgcHJvZmlsZXMgKHVzLiopIGNhbiByb3V0ZSB0byBhbnkgVVMgcmVnaW9uXG4gICAgICAgICAgLy8gVXNlIHdpbGRjYXJkIGZvciByZWdpb24gdG8gaGFuZGxlIGR5bmFtaWMgcm91dGluZ1xuICAgICAgICAgICdhcm46YXdzOmJlZHJvY2s6Kjo6Zm91bmRhdGlvbi1tb2RlbC9hbnRocm9waWMuY2xhdWRlLXNvbm5ldC00LTIwMjUwNTE0LXYxOjAnLFxuICAgICAgICAgICdhcm46YXdzOmJlZHJvY2s6Kjo6Zm91bmRhdGlvbi1tb2RlbC9hbnRocm9waWMuY2xhdWRlLXNvbm5ldC00LTUtMjAyNTA5MjktdjE6MCcsXG4gICAgICAgICAgJ2Fybjphd3M6YmVkcm9jazoqOjpmb3VuZGF0aW9uLW1vZGVsL2FudGhyb3BpYy5jbGF1ZGUtb3B1cy00LTIwMjUwNTE0LXYxOjAnLFxuICAgICAgICAgIC8vIEluZmVyZW5jZSBwcm9maWxlcyAoY3Jvc3MtcmVnaW9uIGFuZCBhY2NvdW50LXNwZWNpZmljKVxuICAgICAgICAgIGBhcm46YXdzOmJlZHJvY2s6JHt0aGlzLnJlZ2lvbn06JHt0aGlzLmFjY291bnR9OmluZmVyZW5jZS1wcm9maWxlLypgLFxuICAgICAgICAgIGBhcm46YXdzOmJlZHJvY2s6JHt0aGlzLnJlZ2lvbn06OmluZmVyZW5jZS1wcm9maWxlLypgLFxuICAgICAgICBdLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdFQ1JJbWFnZUFjY2VzcycsXG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdlY3I6QmF0Y2hHZXRJbWFnZScsXG4gICAgICAgICAgJ2VjcjpHZXREb3dubG9hZFVybEZvckxheWVyJyxcbiAgICAgICAgXSxcbiAgICAgICAgcmVzb3VyY2VzOiBbXG4gICAgICAgICAgYGFybjphd3M6ZWNyOiR7dGhpcy5yZWdpb259OiR7dGhpcy5hY2NvdW50fTpyZXBvc2l0b3J5L2JlZHJvY2stYWdlbnRjb3JlLSpgLFxuICAgICAgICBdLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdFQ1JUb2tlbkFjY2VzcycsXG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdlY3I6R2V0QXV0aG9yaXphdGlvblRva2VuJyxcbiAgICAgICAgXSxcbiAgICAgICAgcmVzb3VyY2VzOiBbJyonXSxcbiAgICAgIH0pXG4gICAgKTtcblxuICAgIHRoaXMuYWdlbnRSdW50aW1lUm9sZS5hZGRUb1BvbGljeShcbiAgICAgIG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgc2lkOiAnQWdlbnRDb3JlTWVtb3J5QWNjZXNzJyxcbiAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkNyZWF0ZUV2ZW50JyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6R2V0RXZlbnQnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpMaXN0RXZlbnRzJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6TGlzdFNlc3Npb25zJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6Q3JlYXRlTWVtb3J5UmVjb3JkJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6R2V0TWVtb3J5UmVjb3JkJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6TGlzdE1lbW9yeVJlY29yZHMnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpSZXRyaWV2ZU1lbW9yeVJlY29yZHMnLFxuICAgICAgICBdLFxuICAgICAgICByZXNvdXJjZXM6IFsnKiddLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgYXBpS2V5c1NlY3JldC5ncmFudFJlYWQodGhpcy5hZ2VudFJ1bnRpbWVSb2xlKTtcbiAgICB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0LmdyYW50UmVhZCh0aGlzLmFnZW50UnVudGltZVJvbGUpO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdDbG91ZFdhdGNoTG9ncycsXG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdsb2dzOkNyZWF0ZUxvZ0dyb3VwJyxcbiAgICAgICAgICAnbG9nczpDcmVhdGVMb2dTdHJlYW0nLFxuICAgICAgICAgICdsb2dzOlB1dExvZ0V2ZW50cycsXG4gICAgICAgICAgJ2xvZ3M6R2V0TG9nRXZlbnRzJyxcbiAgICAgICAgICAnbG9nczpEZXNjcmliZUxvZ1N0cmVhbXMnLFxuICAgICAgICBdLFxuICAgICAgICByZXNvdXJjZXM6IFtcbiAgICAgICAgICBgYXJuOmF3czpsb2dzOiR7dGhpcy5yZWdpb259OiR7dGhpcy5hY2NvdW50fTpsb2ctZ3JvdXA6L2F3cy9iZWRyb2NrL2FnZW50Y29yZS8qYCxcbiAgICAgICAgICBgYXJuOmF3czpsb2dzOiR7dGhpcy5yZWdpb259OiR7dGhpcy5hY2NvdW50fTpsb2ctZ3JvdXA6L2dsaXRjaC8qYCxcbiAgICAgICAgICBgYXJuOmF3czpsb2dzOiR7dGhpcy5yZWdpb259OiR7dGhpcy5hY2NvdW50fTpsb2ctZ3JvdXA6L2dsaXRjaC8qOipgLFxuICAgICAgICBdLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0FnZW50UnVudGltZVJvbGVBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLnJvbGVBcm4sXG4gICAgICBkZXNjcmlwdGlvbjogJ0lBTSByb2xlIEFSTiBmb3IgQWdlbnRDb3JlIFJ1bnRpbWUgKHVzZSB3aXRoIGFnZW50Y29yZSBjb25maWd1cmUgLS1leGVjdXRpb24tcm9sZSknLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaEFnZW50UnVudGltZVJvbGVBcm4nLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0FnZW50Q29yZVNlY3VyaXR5R3JvdXBJZCcsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAuc2VjdXJpdHlHcm91cElkLFxuICAgICAgZGVzY3JpcHRpb246ICdTZWN1cml0eSBncm91cCBJRCBmb3IgQWdlbnRDb3JlIEVOSXMnLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaEFnZW50Q29yZVNlY3VyaXR5R3JvdXBJZCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnVnBjQ29uZmlnRm9yQWdlbnRDb3JlJywge1xuICAgICAgdmFsdWU6IEpTT04uc3RyaW5naWZ5KHtcbiAgICAgICAgc3VibmV0czogdnBjLmlzb2xhdGVkU3VibmV0cy5tYXAocyA9PiBzLnN1Ym5ldElkKSxcbiAgICAgICAgc2VjdXJpdHlHcm91cHM6IFt0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAuc2VjdXJpdHlHcm91cElkXSxcbiAgICAgIH0pLFxuICAgICAgZGVzY3JpcHRpb246ICdWUEMgY29uZmlndXJhdGlvbiBmb3IgQWdlbnRDb3JlIFJ1bnRpbWUgKEpTT04pJyxcbiAgICAgIGV4cG9ydE5hbWU6ICdHbGl0Y2hWcGNDb25maWcnLFxuICAgIH0pO1xuICB9XG59XG4iXX0=