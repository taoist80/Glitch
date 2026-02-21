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
                `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYWdlbnRjb3JlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsiYWdlbnRjb3JlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBVzNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxhQUFhLEVBQUUsc0JBQXNCLEVBQUUsR0FBRyxLQUFLLENBQUM7UUFFckYsSUFBSSxDQUFDLHNCQUFzQixHQUFHLElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDbEYsR0FBRztZQUNILFdBQVcsRUFBRSwyQ0FBMkM7WUFDeEQsZ0JBQWdCLEVBQUUsS0FBSztTQUN4QixDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsc0JBQXNCLENBQUMsYUFBYSxDQUN2QyxHQUFHLENBQUMsSUFBSSxDQUFDLE9BQU8sRUFBRSxFQUNsQixHQUFHLENBQUMsSUFBSSxDQUFDLEdBQUcsQ0FBQyxHQUFHLENBQUMsRUFDakIsNkJBQTZCLENBQzlCLENBQUM7UUFFRixJQUFJLENBQUMsc0JBQXNCLENBQUMsYUFBYSxDQUN2QyxzQkFBc0IsRUFDdEIsR0FBRyxDQUFDLElBQUksQ0FBQyxVQUFVLEVBQUUsRUFDckIsMENBQTBDLENBQzNDLENBQUM7UUFFRixJQUFJLENBQUMsc0JBQXNCLENBQUMsY0FBYyxDQUN4QyxzQkFBc0IsRUFDdEIsR0FBRyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsR0FBRyxDQUFDLEVBQ2pCLGtDQUFrQyxDQUNuQyxDQUFDO1FBRUYsSUFB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QUU7WUFDN0MsS0FBSyxFQUFFLElBQUksQ0FBQyxnQkFBZ0IsQ0FBQyxPQUFPO1lBQ3BDLFdBQVcsRUFBRSxvRkFBb0Y7WUFDakcsVUFBVSxFQUFFLDJCQUEyQjtTQUN4QyxDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLDBCQUEwQixFQUFFO1lBQ2xELEtBQUssRUFBRSxJQUFJLENBQUMsc0JBQXNCLENBQUMsZUFBZTtZQUNsRCxXQUFXLEVBQUUsc0NBQXNDO1lBQ25ELFVBQVUsRUFBRSxnQ0FBZ0M7U0FDN0MsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSx1QkFBdUIsRUFBRTtZQUMvQyxLQUFLLEVBQUUsSUFBSSxDQUFDLFNBQVMsQ0FBQztnQkFDcEIsT0FBTyxFQUFFLEdBQUcsQ0FBQyxlQUFlLENBQUMsR0FBRyxDQUFDLENBQUMsQ0FBQyxFQUFFLENBQUMsQ0FBQyxDQUFDLFFBQVEsQ0FBQztnQkFDakQsY0FBYyxFQUFFLENBQUMsSUFBSSxDQUFDLHNCQUFzQixDQUFDLGVBQWUsQ0FBQzthQUM5RCxDQUFDO1lBQ0YsV0FBVyxFQUFFLGdEQUFnRDtZQUM3RCxVQUFVLEVBQUUsaUJBQWlCO1NBQzlCLENBQUMsQ0FBQztJQUNMLENBQUM7Q0FDRjtBQTFJRCx3Q0EwSUMiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0ICogYXMgZWMyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lYzInO1xuaW1wb3J0ICogYXMgaWFtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1pYW0nO1xuaW1wb3J0ICogYXMgc2VjcmV0c21hbmFnZXIgZnJvbSAnYXdzLWNkay1saWIvYXdzLXNlY3JldHNtYW5hZ2VyJztcbmltcG9ydCB7IENvbnN0cnVjdCB9IGZyb20gJ2NvbnN0cnVjdHMnO1xuXG5leHBvcnQgaW50ZXJmYWNlIEFnZW50Q29yZVN0YWNrUHJvcHMgZXh0ZW5kcyBjZGsuU3RhY2tQcm9wcyB7XG4gIHJlYWRvbmx5IHZwYzogZWMyLklWcGM7XG4gIHJlYWRvbmx5IHRhaWxzY2FsZVNlY3VyaXR5R3JvdXA6IGVjMi5JU2VjdXJpdHlHcm91cDtcbiAgcmVhZG9ubHkgYXBpS2V5c1NlY3JldDogc2VjcmV0c21hbmFnZXIuSVNlY3JldDtcbiAgcmVhZG9ubHkgdGVsZWdyYW1Cb3RUb2tlblNlY3JldDogc2VjcmV0c21hbmFnZXIuSVNlY3JldDtcbn1cblxuZXhwb3J0IGNsYXNzIEFnZW50Q29yZVN0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgcHVibGljIHJlYWRvbmx5IGFnZW50UnVudGltZVJvbGU6IGlhbS5Sb2xlO1xuICBwdWJsaWMgcmVhZG9ubHkgYWdlbnRDb3JlU2VjdXJpdHlHcm91cDogZWMyLlNlY3VyaXR5R3JvdXA7XG5cbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM6IEFnZW50Q29yZVN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIGNvbnN0IHsgdnBjLCB0YWlsc2NhbGVTZWN1cml0eUdyb3VwLCBhcGlLZXlzU2VjcmV0LCB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0IH0gPSBwcm9wcztcblxuICAgIHRoaXMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cCA9IG5ldyBlYzIuU2VjdXJpdHlHcm91cCh0aGlzLCAnQWdlbnRDb3JlU2VjdXJpdHlHcm91cCcsIHtcbiAgICAgIHZwYyxcbiAgICAgIGRlc2NyaXB0aW9uOiAnU2VjdXJpdHkgZ3JvdXAgZm9yIEFnZW50Q29yZSBSdW50aW1lIEVOSXMnLFxuICAgICAgYWxsb3dBbGxPdXRib3VuZDogZmFsc2UsXG4gICAgfSk7XG5cbiAgICB0aGlzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnRjcCg0NDMpLFxuICAgICAgJ0hUVFBTIGZvciBCZWRyb2NrIEFQSSBjYWxscydcbiAgICApO1xuXG4gICAgdGhpcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICB0YWlsc2NhbGVTZWN1cml0eUdyb3VwLFxuICAgICAgZWMyLlBvcnQuYWxsVHJhZmZpYygpLFxuICAgICAgJ0FsbG93IGFsbCB0cmFmZmljIHRvIFRhaWxzY2FsZSBjb25uZWN0b3InXG4gICAgKTtcblxuICAgIHRoaXMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cC5hZGRJbmdyZXNzUnVsZShcbiAgICAgIHRhaWxzY2FsZVNlY3VyaXR5R3JvdXAsXG4gICAgICBlYzIuUG9ydC50Y3AoNDQzKSxcbiAgICAgICdBbGxvdyBIVFRQUyBmcm9tIFRhaWxzY2FsZSBwcm94eSdcbiAgICApO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlID0gbmV3IGlhbS5Sb2xlKHRoaXMsICdBZ2VudFJ1bnRpbWVSb2xlJywge1xuICAgICAgYXNzdW1lZEJ5OiBuZXcgaWFtLlNlcnZpY2VQcmluY2lwYWwoJ2JlZHJvY2stYWdlbnRjb3JlLmFtYXpvbmF3cy5jb20nKSxcbiAgICAgIGRlc2NyaXB0aW9uOiAnSUFNIHJvbGUgZm9yIEFnZW50Q29yZSBSdW50aW1lJyxcbiAgICAgIHJvbGVOYW1lOiAnR2xpdGNoQWdlbnRDb3JlUnVudGltZVJvbGUnLFxuICAgIH0pO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdCZWRyb2NrTW9kZWxBY2Nlc3MnLFxuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAnYmVkcm9jazpJbnZva2VNb2RlbCcsXG4gICAgICAgICAgJ2JlZHJvY2s6SW52b2tlTW9kZWxXaXRoUmVzcG9uc2VTdHJlYW0nLFxuICAgICAgICBdLFxuICAgICAgICByZXNvdXJjZXM6IFtcbiAgICAgICAgICBgYXJuOmF3czpiZWRyb2NrOiR7dGhpcy5yZWdpb259Ojpmb3VuZGF0aW9uLW1vZGVsL2FudGhyb3BpYy5jbGF1ZGUtc29ubmV0LTQtMjAyNTA1MTQtdjE6MGAsXG4gICAgICAgICAgYGFybjphd3M6YmVkcm9jazoke3RoaXMucmVnaW9ufTo6Zm91bmRhdGlvbi1tb2RlbC9hbnRocm9waWMuY2xhdWRlLXNvbm5ldC00LjYqYCxcbiAgICAgICAgICBgYXJuOmF3czpiZWRyb2NrOiR7dGhpcy5yZWdpb259Ojpmb3VuZGF0aW9uLW1vZGVsL2FudGhyb3BpYy5jbGF1ZGUtb3B1cy00KmAsXG4gICAgICAgICAgYGFybjphd3M6YmVkcm9jazoke3RoaXMucmVnaW9ufToke3RoaXMuYWNjb3VudH06aW5mZXJlbmNlLXByb2ZpbGUvKmAsXG4gICAgICAgIF0sXG4gICAgICB9KVxuICAgICk7XG5cbiAgICB0aGlzLmFnZW50UnVudGltZVJvbGUuYWRkVG9Qb2xpY3koXG4gICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgIHNpZDogJ0VDUkltYWdlQWNjZXNzJyxcbiAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgJ2VjcjpCYXRjaEdldEltYWdlJyxcbiAgICAgICAgICAnZWNyOkdldERvd25sb2FkVXJsRm9yTGF5ZXInLFxuICAgICAgICBdLFxuICAgICAgICByZXNvdXJjZXM6IFtcbiAgICAgICAgICBgYXJuOmF3czplY3I6JHt0aGlzLnJlZ2lvbn06JHt0aGlzLmFjY291bnR9OnJlcG9zaXRvcnkvYmVkcm9jay1hZ2VudGNvcmUtKmAsXG4gICAgICAgIF0sXG4gICAgICB9KVxuICAgICk7XG5cbiAgICB0aGlzLmFnZW50UnVudGltZVJvbGUuYWRkVG9Qb2xpY3koXG4gICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgIHNpZDogJ0VDUlRva2VuQWNjZXNzJyxcbiAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgJ2VjcjpHZXRBdXRob3JpemF0aW9uVG9rZW4nLFxuICAgICAgICBdLFxuICAgICAgICByZXNvdXJjZXM6IFsnKiddLFxuICAgICAgfSlcbiAgICApO1xuXG4gICAgdGhpcy5hZ2VudFJ1bnRpbWVSb2xlLmFkZFRvUG9saWN5KFxuICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBzaWQ6ICdBZ2VudENvcmVNZW1vcnlBY2Nlc3MnLFxuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6Q3JlYXRlRXZlbnQnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpHZXRFdmVudCcsXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkxpc3RFdmVudHMnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpMaXN0U2Vzc2lvbnMnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpDcmVhdGVNZW1vcnlSZWNvcmQnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpHZXRNZW1vcnlSZWNvcmQnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpMaXN0TWVtb3J5UmVjb3JkcycsXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOlJldHJpZXZlTWVtb3J5UmVjb3JkcycsXG4gICAgICAgIF0sXG4gICAgICAgIHJlc291cmNlczogWycqJ10sXG4gICAgICB9KVxuICAgICk7XG5cbiAgICBhcGlLZXlzU2VjcmV0LmdyYW50UmVhZCh0aGlzLmFnZW50UnVudGltZVJvbGUpO1xuICAgIHRlbGVncmFtQm90VG9rZW5TZWNyZXQuZ3JhbnRSZWFkKHRoaXMuYWdlbnRSdW50aW1lUm9sZSk7XG5cbiAgICB0aGlzLmFnZW50UnVudGltZVJvbGUuYWRkVG9Qb2xpY3koXG4gICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgIHNpZDogJ0Nsb3VkV2F0Y2hMb2dzJyxcbiAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgJ2xvZ3M6Q3JlYXRlTG9nR3JvdXAnLFxuICAgICAgICAgICdsb2dzOkNyZWF0ZUxvZ1N0cmVhbScsXG4gICAgICAgICAgJ2xvZ3M6UHV0TG9nRXZlbnRzJyxcbiAgICAgICAgXSxcbiAgICAgICAgcmVzb3VyY2VzOiBbXG4gICAgICAgICAgYGFybjphd3M6bG9nczoke3RoaXMucmVnaW9ufToke3RoaXMuYWNjb3VudH06bG9nLWdyb3VwOi9hd3MvYmVkcm9jay9hZ2VudGNvcmUvKmAsXG4gICAgICAgIF0sXG4gICAgICB9KVxuICAgICk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnQWdlbnRSdW50aW1lUm9sZUFybicsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmFnZW50UnVudGltZVJvbGUucm9sZUFybixcbiAgICAgIGRlc2NyaXB0aW9uOiAnSUFNIHJvbGUgQVJOIGZvciBBZ2VudENvcmUgUnVudGltZSAodXNlIHdpdGggYWdlbnRjb3JlIGNvbmZpZ3VyZSAtLWV4ZWN1dGlvbi1yb2xlKScsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoQWdlbnRSdW50aW1lUm9sZUFybicsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnQWdlbnRDb3JlU2VjdXJpdHlHcm91cElkJywge1xuICAgICAgdmFsdWU6IHRoaXMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cC5zZWN1cml0eUdyb3VwSWQsXG4gICAgICBkZXNjcmlwdGlvbjogJ1NlY3VyaXR5IGdyb3VwIElEIGZvciBBZ2VudENvcmUgRU5JcycsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoQWdlbnRDb3JlU2VjdXJpdHlHcm91cElkJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdWcGNDb25maWdGb3JBZ2VudENvcmUnLCB7XG4gICAgICB2YWx1ZTogSlNPTi5zdHJpbmdpZnkoe1xuICAgICAgICBzdWJuZXRzOiB2cGMuaXNvbGF0ZWRTdWJuZXRzLm1hcChzID0+IHMuc3VibmV0SWQpLFxuICAgICAgICBzZWN1cml0eUdyb3VwczogW3RoaXMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cC5zZWN1cml0eUdyb3VwSWRdLFxuICAgICAgfSksXG4gICAgICBkZXNjcmlwdGlvbjogJ1ZQQyBjb25maWd1cmF0aW9uIGZvciBBZ2VudENvcmUgUnVudGltZSAoSlNPTiknLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaFZwY0NvbmZpZycsXG4gICAgfSk7XG4gIH1cbn1cbiJdfQ==