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
            assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com'),
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYWdlbnRjb3JlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYWdlbnRjb3JlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBVzNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxhQUFhLEVBQUUsc0JBQXNCLEVBQUUsR0FBRyxLQUFLLENBQUM7UUFFckYsSUFBSSxDQUFDLHNCQUFzQixHQUFHLElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDbEYsR0FBRztZQUNILFdBQVcsRUFBRSwyQ0FBMkM7WUFDeEQsZ0JBQWdCLEVBQUUsS0FBSztTQUN4QixDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsc0JBQXNCLENBQUMsYUFBYSxDQUN2QyxHQUFHLENBQUMsSUFBSSxDQUFDLE9BQU8sRUFBRSxFQUNsQixHQUFHLENBQUMsSUFBSSxDQUFDLEdBQUcsQ0FBQyxHQUFHLENBQUMsRUFDakIsNkJBQTZCLENBQzlCLENBQUM7UUFFRixJQUFJLENBQUMsc0JBQXNCLENBQUMsYUFBYSxDQUN2QyxzQkFBc0IsRUFDdEIsR0FBRyxDQUFDLElBQUksQ0FBQyxVQUFVLEVBQUUsRUFDckIsMENBQTBDLENBQzNDLENBQUM7UUFFRixJQUFJLENBQUMsc0JBQXNCLENBQUMsY0FBYyxDQUN4QyxzQkFBc0IsRUFDdEIsR0FBRyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsR0FBRyxDQUFDLEVBQ2pCLGtDQUFrQyxDQUNuQyxDQUFDO1FBRUYsSUFB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QUFFLGlCQUFpQjtTQUM5QixDQUFDLENBQUM7SUFDTCxDQUFDO0NBQ0Y7QUFoSEQsd0NBZ0hDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIGVjMiBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZWMyJztcbmltcG9ydCAqIGFzIGlhbSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtaWFtJztcbmltcG9ydCAqIGFzIHNlY3JldHNtYW5hZ2VyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1zZWNyZXRzbWFuYWdlcic7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcblxuZXhwb3J0IGludGVyZmFjZSBBZ2VudENvcmVTdGFja1Byb3BzIGV4dGVuZHMgY2RrLlN0YWNrUHJvcHMge1xuICByZWFkb25seSB2cGM6IGVjMi5JVnBjO1xuICByZWFkb25seSB0YWlsc2NhbGVTZWN1cml0eUdyb3VwOiBlYzIuSVNlY3VyaXR5R3JvdXA7XG4gIHJlYWRvbmx5IGFwaUtleXNTZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHJlYWRvbmx5IHRlbGVncmFtQm90VG9rZW5TZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG59XG5cbmV4cG9ydCBjbGFzcyBBZ2VudENvcmVTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSBhZ2VudFJ1bnRpbWVSb2xlOiBpYW0uUm9sZTtcbiAgcHVibGljIHJlYWRvbmx5IGFnZW50Q29yZVNlY3VyaXR5R3JvdXA6IGVjMi5TZWN1cml0eUdyb3VwO1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBBZ2VudENvcmVTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICBjb25zdCB7IHZwYywgdGFpbHNjYWxlU2VjdXJpdHlHcm91cCwgYXBpS2V5c1NlY3JldCwgdGVsZWdyYW1Cb3RUb2tlblNlY3JldCB9ID0gcHJvcHM7XG5cbiAgICB0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAgPSBuZXcgZWMyLlNlY3VyaXR5R3JvdXAodGhpcywgJ0FnZW50Q29yZVNlY3VyaXR5R3JvdXAnLCB7XG4gICAgICB2cGMsXG4gICAgICBkZXNjcmlwdGlvbjogJ1NlY3VyaXR5IGdyb3VwIGZvciBBZ2VudENvcmUgUnVudGltZSBFTklzJyxcbiAgICAgIGFsbG93QWxsT3V0Ym91bmQ6IGZhbHNlLFxuICAgIH0pO1xuXG4gICAgdGhpcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC50Y3AoNDQzKSxcbiAgICAgICdIVFRQUyBmb3IgQmVkcm9jayBBUEkgY2FsbHMnXG4gICAgKTtcblxuICAgIHRoaXMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgdGFpbHNjYWxlU2VjdXJpdHlHcm91cCxcbiAgICAgIGVjMi5Qb3J0LmFsbFRyYWZmaWMoKSxcbiAgICAgICdBbGxvdyBhbGwgdHJhZmZpYyB0byBUYWlsc2NhbGUgY29ubmVjdG9yJ1xuICAgICk7XG5cbiAgICB0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICB0YWlsc2NhbGVTZWN1cml0eUdyb3VwLFxuICAgICAgZWMyLlBvcnQudGNwKDQ0MyksXG4gICAgICAnQWxsb3cgSFRUUFMgZnJvbSBUYWlsc2NhbGUgcHJveHknXG4gICAgKTtcblxuICAgIHRoaXMuYWdlbnRSdW50aW1lUm9sZSA9IG5ldyBpYW0uUm9sZSh0aGlzLCAnQWdlbnRSdW50aW1lUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdiZWRyb2NrLmFtYXpvbmF3cy5jb20nKSxcbiAgICAgIGRlc2NyaXB0aW9uOiAnSUFNIHJvbGUgZm9yIEFnZW50Q29yZSBSdW50aW1lJyxcbiAgICAgIHJvbGVOYW1lOiAnR2xpdGNoQWdlbnRDb3JlUnVudGltZVJvbGUnLFxuICAgIH0pO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdCZWRyb2NrTW9kZWxBY2Nlc3MnLFxuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAnYmVkcm9jazpJbnZva2VNb2RlbCcsXG4gICAgICAgICAgJ2JlZHJvY2s6SW52b2tlTW9kZWxXaXRoUmVzcG9uc2VTdHJlYW0nLFxuICAgICAgICBdLFxuICAgICAgICByZXNvdXJjZXM6IFtcbiAgICAgICAgICBgYXJuOmF3czpiZWRyb2NrOiR7dGhpcy5yZWdpb259Ojpmb3VuZGF0aW9uLW1vZGVsL2FudGhyb3BpYy5jbGF1ZGUtc29ubmV0LTQtMjAyNTA1MTQtdjE6MGAsXG4gICAgICAgICAgYGFybjphd3M6YmVkcm9jazoke3RoaXMucmVnaW9ufTo6Zm91bmRhdGlvbi1tb2RlbC9hbnRocm9waWMuY2xhdWRlLXNvbm5ldC00LjYqYCxcbiAgICAgICAgICBgYXJuOmF3czpiZWRyb2NrOiR7dGhpcy5yZWdpb259Ojpmb3VuZGF0aW9uLW1vZGVsL2FudGhyb3BpYy5jbGF1ZGUtb3B1cy00KmAsXG4gICAgICAgIF0sXG4gICAgICB9KVxuICAgICk7XG5cbiAgICB0aGlzLmFnZW50UnVudGltZVJvbGUuYWRkVG9Qb2xpY3koXG4gICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgIHNpZDogJ0FnZW50Q29yZU1lbW9yeUFjY2VzcycsXG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpDcmVhdGVFdmVudCcsXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkdldEV2ZW50JyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6TGlzdEV2ZW50cycsXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkxpc3RTZXNzaW9ucycsXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkNyZWF0ZU1lbW9yeVJlY29yZCcsXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkdldE1lbW9yeVJlY29yZCcsXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkxpc3RNZW1vcnlSZWNvcmRzJyxcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6UmV0cmlldmVNZW1vcnlSZWNvcmRzJyxcbiAgICAgICAgXSxcbiAgICAgICAgcmVzb3VyY2VzOiBbJyonXSxcbiAgICAgIH0pXG4gICAgKTtcblxuICAgIGFwaUtleXNTZWNyZXQuZ3JhbnRSZWFkKHRoaXMuYWdlbnRSdW50aW1lUm9sZSk7XG4gICAgdGVsZWdyYW1Cb3RUb2tlblNlY3JldC5ncmFudFJlYWQodGhpcy5hZ2VudFJ1bnRpbWVSb2xlKTtcblxuICAgIHRoaXMuYWdlbnRSdW50aW1lUm9sZS5hZGRUb1BvbGljeShcbiAgICAgIG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgc2lkOiAnQ2xvdWRXYXRjaExvZ3MnLFxuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAnbG9nczpDcmVhdGVMb2dHcm91cCcsXG4gICAgICAgICAgJ2xvZ3M6Q3JlYXRlTG9nU3RyZWFtJyxcbiAgICAgICAgICAnbG9nczpQdXRMb2dFdmVudHMnLFxuICAgICAgICBdLFxuICAgICAgICByZXNvdXJjZXM6IFtcbiAgICAgICAgICBgYXJuOmF3czpsb2dzOiR7dGhpcy5yZWdpb259OiR7dGhpcy5hY2NvdW50fTpsb2ctZ3JvdXA6L2F3cy9iZWRyb2NrL2FnZW50Y29yZS8qYCxcbiAgICAgICAgXSxcbiAgICAgIH0pXG4gICAgKTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdBZ2VudFJ1bnRpbWVSb2xlQXJuJywge1xuICAgICAgdmFsdWU6IHRoaXMuYWdlbnRSdW50aW1lUm9sZS5yb2xlQXJuLFxuICAgICAgZGVzY3JpcHRpb246ICdJQU0gcm9sZSBBUk4gZm9yIEFnZW50Q29yZSBSdW50aW1lICh1c2Ugd2l0aCBhZ2VudGNvcmUgY29uZmlndXJlIC0tZXhlY3V0aW9uLXJvbGUpJyxcbiAgICAgIGV4cG9ydE5hbWU6ICdHbGl0Y2hBZ2VudFJ1bnRpbWVSb2xlQXJuJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdBZ2VudENvcmVTZWN1cml0eUdyb3VwSWQnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwLnNlY3VyaXR5R3JvdXBJZCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnU2VjdXJpdHkgZ3JvdXAgSUQgZm9yIEFnZW50Q29yZSBFTklzJyxcbiAgICAgIGV4cG9ydE5hbWU6ICdHbGl0Y2hBZ2VudENvcmVTZWN1cml0eUdyb3VwSWQnLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1ZwY0NvbmZpZ0ZvckFnZW50Q29yZScsIHtcbiAgICAgIHZhbHVlOiBKU09OLnN0cmluZ2lmeSh7XG4gICAgICAgIHN1Ym5ldHM6IHZwYy5pc29sYXRlZFN1Ym5ldHMubWFwKHMgPT4gcy5zdWJuZXRJZCksXG4gICAgICAgIHNlY3VyaXR5R3JvdXBzOiBbdGhpcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwLnNlY3VyaXR5R3JvdXBJZF0sXG4gICAgICB9KSxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVlBDIGNvbmZpZ3VyYXRpb24gZm9yIEFnZW50Q29yZSBSdW50aW1lIChKU09OKScsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoVnBjQ29uZmlnJyxcbiAgICB9KTtcbiAgfVxufVxuIl19