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
const cdk = __importStar(require("aws-cdk-lib"));
const assertions_1 = require("aws-cdk-lib/assertions");
const ec2 = __importStar(require("aws-cdk-lib/aws-ec2"));
const secretsmanager = __importStar(require("aws-cdk-lib/aws-secretsmanager"));
const agentcore_stack_1 = require("../lib/agentcore-stack");
describe('AgentCoreStack', () => {
    let app;
    let vpcStack;
    let vpc;
    let tailscaleSg;
    let apiKeysSecret;
    let telegramSecret;
    beforeEach(() => {
        app = new cdk.App();
        vpcStack = new cdk.Stack(app, 'VpcStack', {
            env: { account: '123456789012', region: 'us-west-2' },
        });
        vpc = new ec2.Vpc(vpcStack, 'TestVpc', {
            maxAzs: 2,
            natGateways: 0,
            subnetConfiguration: [
                { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
                { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
            ],
        });
        tailscaleSg = new ec2.SecurityGroup(vpcStack, 'TailscaleSg', {
            vpc,
            description: 'Tailscale SG',
        });
        apiKeysSecret = new secretsmanager.Secret(vpcStack, 'ApiKeys', {
            secretName: 'glitch/api-keys',
        });
        telegramSecret = new secretsmanager.Secret(vpcStack, 'TelegramToken', {
            secretName: 'glitch/telegram-bot-token',
        });
    });
    function createStack() {
        return new agentcore_stack_1.AgentCoreStack(app, 'TestAgentCoreStack', {
            vpc,
            tailscaleSecurityGroup: tailscaleSg,
            apiKeysSecret,
            telegramBotTokenSecret: telegramSecret,
            env: { account: '123456789012', region: 'us-west-2' },
        });
    }
    describe('Security Group', () => {
        test('creates security group with restricted outbound', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::EC2::SecurityGroup', {
                GroupDescription: 'Security group for AgentCore Runtime ENIs',
            });
        });
        test('creates exactly one security group', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.resourceCountIs('AWS::EC2::SecurityGroup', 1);
        });
        test('allows all traffic egress to Tailscale SG', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::EC2::SecurityGroupEgress', {
                IpProtocol: '-1',
                DestinationSecurityGroupId: assertions_1.Match.anyValue(),
            });
        });
        test('allows HTTPS ingress from Tailscale SG', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::EC2::SecurityGroupIngress', {
                IpProtocol: 'tcp',
                FromPort: 443,
                ToPort: 443,
                SourceSecurityGroupId: assertions_1.Match.anyValue(),
            });
        });
    });
    describe('IAM Role', () => {
        test('creates role with bedrock-agentcore service principal', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Role', {
                AssumeRolePolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Action: 'sts:AssumeRole',
                            Effect: 'Allow',
                            Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
                        }),
                    ]),
                },
                RoleName: 'GlitchAgentCoreRuntimeRole',
            });
        });
        test('grants Bedrock model invocation permissions', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Policy', {
                PolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Sid: 'BedrockModelAccess',
                            Effect: 'Allow',
                            Action: assertions_1.Match.arrayWith([
                                'bedrock:InvokeModel',
                                'bedrock:InvokeModelWithResponseStream',
                            ]),
                        }),
                    ]),
                },
            });
        });
        test('grants ECR image access', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Policy', {
                PolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Sid: 'ECRImageAccess',
                            Effect: 'Allow',
                            Action: assertions_1.Match.arrayWith([
                                'ecr:BatchGetImage',
                                'ecr:GetDownloadUrlForLayer',
                            ]),
                        }),
                    ]),
                },
            });
        });
        test('grants ECR authorization token access', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Policy', {
                PolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Sid: 'ECRTokenAccess',
                            Effect: 'Allow',
                            Action: 'ecr:GetAuthorizationToken',
                            Resource: '*',
                        }),
                    ]),
                },
            });
        });
        test('grants AgentCore Memory access', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Policy', {
                PolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Sid: 'AgentCoreMemoryAccess',
                            Effect: 'Allow',
                            Action: assertions_1.Match.arrayWith([
                                'bedrock-agentcore:CreateEvent',
                                'bedrock-agentcore:GetEvent',
                                'bedrock-agentcore:ListEvents',
                                'bedrock-agentcore:ListSessions',
                                'bedrock-agentcore:CreateMemoryRecord',
                                'bedrock-agentcore:GetMemoryRecord',
                                'bedrock-agentcore:ListMemoryRecords',
                                'bedrock-agentcore:RetrieveMemoryRecords',
                            ]),
                        }),
                    ]),
                },
            });
        });
        test('grants CloudWatch Logs access', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Policy', {
                PolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Sid: 'CloudWatchLogs',
                            Effect: 'Allow',
                            Action: assertions_1.Match.arrayWith([
                                'logs:CreateLogGroup',
                                'logs:CreateLogStream',
                                'logs:PutLogEvents',
                            ]),
                        }),
                    ]),
                },
            });
        });
        test('grants read access to secrets', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Policy', {
                PolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Action: assertions_1.Match.arrayWith(['secretsmanager:GetSecretValue']),
                            Effect: 'Allow',
                        }),
                    ]),
                },
            });
        });
    });
    describe('Stack Outputs', () => {
        test('exports agent runtime role ARN', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasOutput('AgentRuntimeRoleArn', {
                Export: { Name: 'GlitchAgentRuntimeRoleArn' },
            });
        });
        test('exports security group ID', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasOutput('AgentCoreSecurityGroupId', {
                Export: { Name: 'GlitchAgentCoreSecurityGroupId' },
            });
        });
        test('exports VPC config JSON', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasOutput('VpcConfigForAgentCore', {
                Export: { Name: 'GlitchVpcConfig' },
            });
        });
    });
});
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoiYWdlbnRjb3JlLXN0YWNrLnRlc3QuanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJhZ2VudGNvcmUtc3RhY2sudGVzdC50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx1REFBeUQ7QUFDekQseURBQTJDO0FBQzNDLCtFQUFpRTtBQUNqRSw0REFBd0Q7QUFFeEQsUUFBUSxDQUFDLGdCQUFnQixFQUFFLEdBQUcsRUFBRTtJQUM5QixJQUFJLEdBQVksQ0FBQztJQUNqQixJQUFJLFFBQW1CLENBQUM7SUFDeEIsSUFBSSxHQUFZLENBQUM7SUFDakIsSUFBSSxXQUE4QixDQUFDO0lBQ25DLElBQUksYUFBb0MsQ0FBQztJQUN6QyxJQUFJLGNBQXFDLENBQUM7SUFFMUMsVUFBVSxDQUFDLEdBQUcsRUFBRTtRQUNkLEdBQUcsR0FBRyxJQUFJLEdBQUcsQ0FBQyxHQUFHLEVBQUUsQ0FBQztRQUNwQixRQUFRLEdBQUcsSUFBSSxHQUFHLENBQUMsS0FBSyxDQUFDLEdBQUcsRUFBRSxVQUFVLEVBQUU7WUFDeEMsR0FBRyxFQUFFLEVBQUUsT0FBTyxFQUFFLGNBQWMsRUFBRSxNQUFNLEVBQUUsV0FBVyxFQUFFO1NBQ3RELENBQUMsQ0FBQztRQUNILEdBQUcsR0FBRyxJQUFJLEdBQUcsQ0FBQyxHQUFHLENBQUMsUUFBUSxFQUFFLFNBQVMsRUFBRTtZQUNyQyxNQUFNLEVBQUUsQ0FBQztZQUNULFdBQVcsRUFBRSxDQUFDO1lBQ2QsbUJBQW1CLEVBQUU7Z0JBQ25CLEVBQUUsSUFBSSxFQUFFLFFBQVEsRUFBRSxVQUFVLEVBQUUsR0FBRyxDQUFDLFVBQVUsQ0FBQyxNQUFNLEVBQUUsUUFBUSxFQUFFLEVBQUUsRUFBRTtnQkFDbkUsRUFBRSxJQUFJLEVBQUUsU0FBUyxFQUFFLFVBQVUsRUFBRSxHQUFHLENBQUMsVUFBVSxDQUFDLGdCQUFnQixFQUFFLFFBQVEsRUFBRSxFQUFFLEVB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QkFBUSxDQUFDLFNBQVMsQ0FBQyxLQUFLLENBQUMsQ0FBQztZQUUzQyxRQUFRLENBQUMsU0FBUyxDQUFDLHVCQUF1QixFQUFFO2dCQUMxQyxNQUFNLEVBQUUsRUFBRSxJQUFJLEVBQUUsaUJBQWlCLEVBQUU7YUFDcEMsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztBQUNMLENBQUMsQ0FBQyxDQUFDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCB7IFRlbXBsYXRlLCBNYXRjaCB9IGZyb20gJ2F3cy1jZGstbGliL2Fzc2VydGlvbnMnO1xuaW1wb3J0ICogYXMgZWMyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lYzInO1xuaW1wb3J0ICogYXMgc2VjcmV0c21hbmFnZXIgZnJvbSAnYXdzLWNkay1saWIvYXdzLXNlY3JldHNtYW5hZ2VyJztcbmltcG9ydCB7IEFnZW50Q29yZVN0YWNrIH0gZnJvbSAnLi4vbGliL2FnZW50Y29yZS1zdGFjayc7XG5cbmRlc2NyaWJlKCdBZ2VudENvcmVTdGFjaycsICgpID0+IHtcbiAgbGV0IGFwcDogY2RrLkFwcDtcbiAgbGV0IHZwY1N0YWNrOiBjZGsuU3RhY2s7XG4gIGxldCB2cGM6IGVjMi5WcGM7XG4gIGxldCB0YWlsc2NhbGVTZzogZWMyLlNlY3VyaXR5R3JvdXA7XG4gIGxldCBhcGlLZXlzU2VjcmV0OiBzZWNyZXRzbWFuYWdlci5TZWNyZXQ7XG4gIGxldCB0ZWxlZ3JhbVNlY3JldDogc2VjcmV0c21hbmFnZXIuU2VjcmV0O1xuXG4gIGJlZm9yZUVhY2goKCkgPT4ge1xuICAgIGFwcCA9IG5ldyBjZGsuQXBwKCk7XG4gICAgdnBjU3RhY2sgPSBuZXcgY2RrLlN0YWNrKGFwcCwgJ1ZwY1N0YWNrJywge1xuICAgICAgZW52OiB7IGFjY291bnQ6ICcxMjM0NTY3ODkwMTInLCByZWdpb246ICd1cy13ZXN0LTInIH0sXG4gICAgfSk7XG4gICAgdnBjID0gbmV3IGVjMi5WcGModnBjU3RhY2ssICdUZXN0VnBjJywge1xuICAgICAgbWF4QXpzOiAyLFxuICAgICAgbmF0R2F0ZXdheXM6IDAsXG4gICAgICBzdWJuZXRDb25maWd1cmF0aW9uOiBbXG4gICAgICAgIHsgbmFtZTogJ1B1YmxpYycsIHN1Ym5ldFR5cGU6IGVjMi5TdWJuZXRUeXBlLlBVQkxJQywgY2lkck1hc2s6IDI0IH0sXG4gICAgICAgIHsgbmFtZTogJ1ByaXZhdGUnLCBzdWJuZXRUeXBlOiBlYzIuU3VibmV0VHlwZS5QUklWQVRFX0lTT0xBVEVELCBjaWRyTWFzazogMjQgfSxcbiAgICAgIF0sXG4gICAgfSk7XG4gICAgdGFpbHNjYWxlU2cgPSBuZXcgZWMyLlNlY3VyaXR5R3JvdXAodnBjU3RhY2ssICdUYWlsc2NhbGVTZycsIHtcbiAgICAgIHZwYyxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIFNHJyxcbiAgICB9KTtcbiAgICBhcGlLZXlzU2VjcmV0ID0gbmV3IHNlY3JldHNtYW5hZ2VyLlNlY3JldCh2cGNTdGFjaywgJ0FwaUtleXMnLCB7XG4gICAgICBzZWNyZXROYW1lOiAnZ2xpdGNoL2FwaS1rZXlzJyxcbiAgICB9KTtcbiAgICB0ZWxlZ3JhbVNlY3JldCA9IG5ldyBzZWNyZXRzbWFuYWdlci5TZWNyZXQodnBjU3RhY2ssICdUZWxlZ3JhbVRva2VuJywge1xuICAgICAgc2VjcmV0TmFtZTogJ2dsaXRjaC90ZWxlZ3JhbS1ib3QtdG9rZW4nLFxuICAgIH0pO1xuICB9KTtcblxuICBmdW5jdGlvbiBjcmVhdGVTdGFjaygpIHtcbiAgICByZXR1cm4gbmV3IEFnZW50Q29yZVN0YWNrKGFwcCwgJ1Rlc3RBZ2VudENvcmVTdGFjaycsIHtcbiAgICAgIHZwYyxcbiAgICAgIHRhaWxzY2FsZVNlY3VyaXR5R3JvdXA6IHRhaWxzY2FsZVNnLFxuICAgICAgYXBpS2V5c1NlY3JldCxcbiAgICAgIHRlbGVncmFtQm90VG9rZW5TZWNyZXQ6IHRlbGVncmFtU2VjcmV0LFxuICAgICAgZW52OiB7IGFjY291bnQ6ICcxMjM0NTY3ODkwMTInLCByZWdpb246ICd1cy13ZXN0LTInIH0sXG4gICAgfSk7XG4gIH1cblxuICBkZXNjcmliZSgnU2VjdXJpdHkgR3JvdXAnLCAoKSA9PiB7XG4gICAgdGVzdCgnY3JlYXRlcyBzZWN1cml0eSBncm91cCB3aXRoIHJlc3RyaWN0ZWQgb3V0Ym91bmQnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlNlY3VyaXR5R3JvdXAnLCB7XG4gICAgICAgIEdyb3VwRGVzY3JpcHRpb246ICdTZWN1cml0eSBncm91cCBmb3IgQWdlbnRDb3JlIFJ1bnRpbWUgRU5JcycsXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2NyZWF0ZXMgZXhhY3RseSBvbmUgc2VjdXJpdHkgZ3JvdXAnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLnJlc291cmNlQ291bnRJcygnQVdTOjpFQzI6OlNlY3VyaXR5R3JvdXAnLCAxKTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2FsbG93cyBhbGwgdHJhZmZpYyBlZ3Jlc3MgdG8gVGFpbHNjYWxlIFNHJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpTZWN1cml0eUdyb3VwRWdyZXNzJywge1xuICAgICAgICBJcFByb3RvY29sOiAnLTEnLFxuICAgICAgICBEZXN0aW5hdGlvblNlY3VyaXR5R3JvdXBJZDogTWF0Y2guYW55VmFsdWUoKSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnYWxsb3dzIEhUVFBTIGluZ3Jlc3MgZnJvbSBUYWlsc2NhbGUgU0cnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlNlY3VyaXR5R3JvdXBJbmdyZXNzJywge1xuICAgICAgICBJcFByb3RvY29sOiAndGNwJyxcbiAgICAgICAgRnJvbVBvcnQ6IDQ0MyxcbiAgICAgICAgVG9Qb3J0OiA0NDMsXG4gICAgICAgIFNvdXJjZVNlY3VyaXR5R3JvdXBJZDogTWF0Y2guYW55VmFsdWUoKSxcbiAgICAgIH0pO1xuICAgIH0pO1xuICB9KTtcblxuICBkZXNjcmliZSgnSUFNIFJvbGUnLCAoKSA9PiB7XG4gICAgdGVzdCgnY3JlYXRlcyByb2xlIHdpdGggYmVkcm9jay1hZ2VudGNvcmUgc2VydmljZSBwcmluY2lwYWwnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpJQU06OlJvbGUnLCB7XG4gICAgICAgIEFzc3VtZVJvbGVQb2xpY3lEb2N1bWVudDoge1xuICAgICAgICAgIFN0YXRlbWVudDogTWF0Y2guYXJyYXlXaXRoKFtcbiAgICAgICAgICAgIE1hdGNoLm9iamVjdExpa2Uoe1xuICAgICAgICAgICAgICBBY3Rpb246ICdzdHM6QXNzdW1lUm9sZScsXG4gICAgICAgICAgICAgIEVmZmVjdDogJ0FsbG93JyxcbiAgICAgICAgICAgICAgUHJpbmNpcGFsOiB7IFNlcnZpY2U6ICdiZWRyb2NrLWFnZW50Y29yZS5hbWF6b25hd3MuY29tJyB9LFxuICAgICAgICAgICAgfSksXG4gICAgICAgICAgXSksXG4gICAgICAgIH0sXG4gICAgICAgIFJvbGVOYW1lOiAnR2xpdGNoQWdlbnRDb3JlUnVudGltZVJvbGUnLFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdncmFudHMgQmVkcm9jayBtb2RlbCBpbnZvY2F0aW9uIHBlcm1pc3Npb25zJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6SUFNOjpQb2xpY3knLCB7XG4gICAgICAgIFBvbGljeURvY3VtZW50OiB7XG4gICAgICAgICAgU3RhdGVtZW50OiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7XG4gICAgICAgICAgICAgIFNpZDogJ0JlZHJvY2tNb2RlbEFjY2VzcycsXG4gICAgICAgICAgICAgIEVmZmVjdDogJ0FsbG93JyxcbiAgICAgICAgICAgICAgQWN0aW9uOiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgICAgICdiZWRyb2NrOkludm9rZU1vZGVsJyxcbiAgICAgICAgICAgICAgICAnYmVkcm9jazpJbnZva2VNb2RlbFdpdGhSZXNwb25zZVN0cmVhbScsXG4gICAgICAgICAgICAgIF0pLFxuICAgICAgICAgICAgfSksXG4gICAgICAgICAgXSksXG4gICAgICAgIH0sXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2dyYW50cyBFQ1IgaW1hZ2UgYWNjZXNzJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6SUFNOjpQb2xpY3knLCB7XG4gICAgICAgIFBvbGljeURvY3VtZW50OiB7XG4gICAgICAgICAgU3RhdGVtZW50OiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7XG4gICAgICAgICAgICAgIFNpZDogJ0VDUkltYWdlQWNjZXNzJyxcbiAgICAgICAgICAgICAgRWZmZWN0OiAnQWxsb3cnLFxuICAgICAgICAgICAgICBBY3Rpb246IE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgICAgICAgJ2VjcjpCYXRjaEdldEltYWdlJyxcbiAgICAgICAgICAgICAgICAnZWNyOkdldERvd25sb2FkVXJsRm9yTGF5ZXInLFxuICAgICAgICAgICAgICBdKSxcbiAgICAgICAgICAgIH0pLFxuICAgICAgICAgIF0pLFxuICAgICAgICB9LFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdncmFudHMgRUNSIGF1dGhvcml6YXRpb24gdG9rZW4gYWNjZXNzJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6SUFNOjpQb2xpY3knLCB7XG4gICAgICAgIFBvbGljeURvY3VtZW50OiB7XG4gICAgICAgICAgU3RhdGVtZW50OiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7XG4gICAgICAgICAgICAgIFNpZDogJ0VDUlRva2VuQWNjZXNzJyxcbiAgICAgICAgICAgICAgRWZmZWN0OiAnQWxsb3cnLFxuICAgICAgICAgICAgICBBY3Rpb246ICdlY3I6R2V0QXV0aG9yaXphdGlvblRva2VuJyxcbiAgICAgICAgICAgICAgUmVzb3VyY2U6ICcqJyxcbiAgICAgICAgICAgIH0pLFxuICAgICAgICAgIF0pLFxuICAgICAgICB9LFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdncmFudHMgQWdlbnRDb3JlIE1lbW9yeSBhY2Nlc3MnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpJQU06OlBvbGljeScsIHtcbiAgICAgICAgUG9saWN5RG9jdW1lbnQ6IHtcbiAgICAgICAgICBTdGF0ZW1lbnQ6IE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgICBNYXRjaC5vYmplY3RMaWtlKHtcbiAgICAgICAgICAgICAgU2lkOiAnQWdlbnRDb3JlTWVtb3J5QWNjZXNzJyxcbiAgICAgICAgICAgICAgRWZmZWN0OiAnQWxsb3cnLFxuICAgICAgICAgICAgICBBY3Rpb246IE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkNyZWF0ZUV2ZW50JyxcbiAgICAgICAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6R2V0RXZlbnQnLFxuICAgICAgICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpMaXN0RXZlbnRzJyxcbiAgICAgICAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6TGlzdFNlc3Npb25zJyxcbiAgICAgICAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6Q3JlYXRlTWVtb3J5UmVjb3JkJyxcbiAgICAgICAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6R2V0TWVtb3J5UmVjb3JkJyxcbiAgICAgICAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmU6TGlzdE1lbW9yeVJlY29yZHMnLFxuICAgICAgICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpSZXRyaWV2ZU1lbW9yeVJlY29yZHMnLFxuICAgICAgICAgICAgICBdKSxcbiAgICAgICAgICAgIH0pLFxuICAgICAgICAgIF0pLFxuICAgICAgICB9LFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdncmFudHMgQ2xvdWRXYXRjaCBMb2dzIGFjY2VzcycsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OklBTTo6UG9saWN5Jywge1xuICAgICAgICBQb2xpY3lEb2N1bWVudDoge1xuICAgICAgICAgIFN0YXRlbWVudDogTWF0Y2guYXJyYXlXaXRoKFtcbiAgICAgICAgICAgIE1hdGNoLm9iamVjdExpa2Uoe1xuICAgICAgICAgICAgICBTaWQ6ICdDbG91ZFdhdGNoTG9ncycsXG4gICAgICAgICAgICAgIEVmZmVjdDogJ0FsbG93JyxcbiAgICAgICAgICAgICAgQWN0aW9uOiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgICAgICdsb2dzOkNyZWF0ZUxvZ0dyb3VwJyxcbiAgICAgICAgICAgICAgICAnbG9nczpDcmVhdGVMb2dTdHJlYW0nLFxuICAgICAgICAgICAgICAgICdsb2dzOlB1dExvZ0V2ZW50cycsXG4gICAgICAgICAgICAgIF0pLFxuICAgICAgICAgICAgfSksXG4gICAgICAgICAgXSksXG4gICAgICAgIH0sXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2dyYW50cyByZWFkIGFjY2VzcyB0byBzZWNyZXRzJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6SUFNOjpQb2xpY3knLCB7XG4gICAgICAgIFBvbGljeURvY3VtZW50OiB7XG4gICAgICAgICAgU3RhdGVtZW50OiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7XG4gICAgICAgICAgICAgIEFjdGlvbjogTWF0Y2guYXJyYXlXaXRoKFsnc2VjcmV0c21hbmFnZXI6R2V0U2VjcmV0VmFsdWUnXSksXG4gICAgICAgICAgICAgIEVmZmVjdDogJ0FsbG93JyxcbiAgICAgICAgICAgIH0pLFxuICAgICAgICAgIF0pLFxuICAgICAgICB9LFxuICAgICAgfSk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdTdGFjayBPdXRwdXRzJywgKCkgPT4ge1xuICAgIHRlc3QoJ2V4cG9ydHMgYWdlbnQgcnVudGltZSByb2xlIEFSTicsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdBZ2VudFJ1bnRpbWVSb2xlQXJuJywge1xuICAgICAgICBFeHBvcnQ6IHsgTmFtZTogJ0dsaXRjaEFnZW50UnVudGltZVJvbGVBcm4nIH0sXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2V4cG9ydHMgc2VjdXJpdHkgZ3JvdXAgSUQnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc091dHB1dCgnQWdlbnRDb3JlU2VjdXJpdHlHcm91cElkJywge1xuICAgICAgICBFeHBvcnQ6IHsgTmFtZTogJ0dsaXRjaEFnZW50Q29yZVNlY3VyaXR5R3JvdXBJZCcgfSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnZXhwb3J0cyBWUEMgY29uZmlnIEpTT04nLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc091dHB1dCgnVnBjQ29uZmlnRm9yQWdlbnRDb3JlJywge1xuICAgICAgICBFeHBvcnQ6IHsgTmFtZTogJ0dsaXRjaFZwY0NvbmZpZycgfSxcbiAgICAgIH0pO1xuICAgIH0pO1xuICB9KTtcbn0pO1xuIl19