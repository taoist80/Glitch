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
const stack_1 = require("../lib/stack");
describe('GlitchFoundationStack', () => {
    let app;
    let stack;
    let template;
    beforeEach(() => {
        app = new cdk.App();
        stack = new stack_1.GlitchFoundationStack(app, 'TestFoundationStack', {
            env: { account: '123456789012', region: 'us-west-2' },
        });
        template = assertions_1.Template.fromStack(stack);
    });
    describe('VPC Configuration', () => {
        test('creates VPC with correct CIDR', () => {
            template.hasResourceProperties('AWS::EC2::VPC', {
                CidrBlock: '10.0.0.0/16',
                EnableDnsHostnames: true,
                EnableDnsSupport: true,
            });
        });
        test('creates public and private subnets', () => {
            // At least 2 public + 2 private
            const count = template.findResources('AWS::EC2::Subnet');
            expect(Object.keys(count).length).toBeGreaterThanOrEqual(2);
        });
        test('does not create NAT gateway (cost optimization; agents use PUBLIC mode)', () => {
            template.resourceCountIs('AWS::EC2::NatGateway', 0);
        });
        test('creates Virtual Private Gateway for Site-to-Site VPN', () => {
            template.resourceCountIs('AWS::EC2::VPNGateway', 1);
        });
        test('attaches VPN gateway to VPC', () => {
            // CDK also creates one for the Internet Gateway, so expect at least 2
            const attachments = template.findResources('AWS::EC2::VPCGatewayAttachment');
            expect(Object.keys(attachments).length).toBeGreaterThanOrEqual(2);
        });
        test('does not create VPC endpoints (agents use PUBLIC mode)', () => {
            template.resourceCountIs('AWS::EC2::VPCEndpoint', 0);
        });
    });
    describe('IAM Roles', () => {
        test('creates runtime role with bedrock-agentcore trust', () => {
            template.hasResourceProperties('AWS::IAM::Role', {
                AssumeRolePolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Principal: { Service: 'bedrock-agentcore.amazonaws.com' },
                        }),
                    ]),
                },
            });
        });
        test('creates CodeBuild role with codebuild trust', () => {
            template.hasResourceProperties('AWS::IAM::Role', {
                AssumeRolePolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Principal: { Service: 'codebuild.amazonaws.com' },
                        }),
                    ]),
                },
            });
        });
        test('CodeBuild role has ECR permissions', () => {
            template.hasResourceProperties('AWS::IAM::Policy', {
                PolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Action: 'ecr:GetAuthorizationToken',
                        }),
                    ]),
                },
            });
        });
    });
    describe('SSM Parameters', () => {
        test('creates SSM parameter for VPC ID', () => {
            template.hasResourceProperties('AWS::SSM::Parameter', {
                Name: '/glitch/vpc/id',
                Type: 'String',
            });
        });
        test('creates SSM parameter for private subnet IDs', () => {
            template.hasResourceProperties('AWS::SSM::Parameter', {
                Name: '/glitch/vpc/private-subnet-ids',
                Type: 'String',
            });
        });
        test('creates SSM parameter for runtime role ARN', () => {
            template.hasResourceProperties('AWS::SSM::Parameter', {
                Name: '/glitch/iam/runtime-role-arn',
                Type: 'String',
            });
        });
        test('creates SSM parameter for CodeBuild role ARN', () => {
            template.hasResourceProperties('AWS::SSM::Parameter', {
                Name: '/glitch/iam/codebuild-role-arn',
                Type: 'String',
            });
        });
    });
    describe('Stack Outputs', () => {
        test('outputs VPC ID', () => {
            template.hasOutput('VpcId', {});
        });
        test('outputs private subnet IDs', () => {
            template.hasOutput('PrivateSubnetIds', {});
        });
        test('outputs runtime role ARN', () => {
            template.hasOutput('RuntimeRoleArn', {});
        });
        test('outputs CodeBuild role ARN', () => {
            template.hasOutput('CodeBuildRoleArn', {});
        });
    });
    describe('Custom CIDR', () => {
        test('accepts custom VPC CIDR', () => {
            const customApp = new cdk.App();
            const customStack = new stack_1.GlitchFoundationStack(customApp, 'CustomFoundationStack', {
                vpcCidr: '172.16.0.0/16',
                env: { account: '123456789012', region: 'us-west-2' },
            });
            const customTemplate = assertions_1.Template.fromStack(customStack);
            customTemplate.hasResourceProperties('AWS::EC2::VPC', {
                CidrBlock: '172.16.0.0/16',
            });
        });
    });
});
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidnBjLXN0YWNrLnRlc3QuanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJ2cGMtc3RhY2sudGVzdC50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx1REFBeUQ7QUFDekQsd0NBQXFEO0FBRXJELFFBQVEsQ0FBQyx1QkFBdUIsRUFBRSxHQUFHLEVBQUU7SUFDckMsSUFBSSxHQUFZLENBQUM7SUFDakIsSUFBSSxLQUE0QixDQUFDO0lBQ2pDLElBQUksUUFBa0IsQ0FBQztJQUV2QixVQUFVLENBQUMsR0FBRyxFQUFFO1FBQ2QsR0FBRyxHQUFHLElBQUksR0FBRyxDQUFDLEdBQUcsRUFBRSxDQUFDO1FBQ3BCLEtBQUssR0FBRyxJQUFJLDZCQUFxQixDQUFDLEdBQUcsRUFBRSxxQkFBcUIsRUFBRTtZQUM1RCxHQUFHLEVBQUUsRUFBRSxPQUFPLEVBQUUsY0FBYyxFQUFFLE1BQU0sRUFBRSxXQUFXLEVBQUU7U0FDdEQsQ0FBQyxDQUFDO1FBQ0gsUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO0lBQ3ZDLENBQUMsQ0FBQyxDQUFDO0lBRUgsUUFBUSxDQUFDLG1CQUFtQixFQUFFLEdBQUcsRUFBRTtRQUNqQyxJQUFJLENBQUMsK0JBQStCLEVBQUUsR0FBRyxFQUFFO1lBQ3pDLFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyxlQUFlLEVBQUU7Z0JBQzlDLFNBQVMsRUFBRSxhQUFhO2dCQUN4QixrQkFBa0IsRUFBRSxJQUFJO2dCQUN4QixnQkFBZ0IsRUFBRSxJQUFJO2FBQ3ZCLENBQUMsQ0FBQztRQUNMLENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLG9DQUFvQyxFQUFFLEdBQUcsRUFBRTtZQUM5QyxnQ0FBZ0M7WUFDaEMsTUFBTSxLQUFLLEdBQUcsUUFBUSxDQUFDLGFBQWEsQ0FBQyxrQkFBa0IsQ0FBQyxDQUFDO1lBQ3pELE1BQU0s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LENBQUM7SUFFSCxRQUFRLENBQUMsYUFBYSxFQUFFLEdBQUcsRUFBRTtRQUMzQixJQUFJLENBQUMseUJBQXlCLEVBQUUsR0FBRyxFQUFFO1lBQ25DLE1BQU0sU0FBUyxHQUFHLElBQUksR0FBRyxDQUFDLEdBQUcsRUFBRSxDQUFDO1lBQ2hDLE1BQU0sV0FBVyxHQUFHLElBQUksNkJBQXFCLENBQUMsU0FBUyxFQUFFLHVCQUF1QixFQUFFO2dCQUNoRixPQUFPLEVBQUUsZUFBZTtnQkFDeEIsR0FBRyxFQUFFLEVBQUUsT0FBTyxFQUFFLGNBQWMsRUFBRSxNQUFNLEVBQUUsV0FBVyxFQUFFO2FBQ3RELENBQUMsQ0FBQztZQUNILE1BQU0sY0FBYyxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLFdBQVcsQ0FBQyxDQUFDO1lBRXZELGNBQWMsQ0FBQyxxQkFBcUIsQ0FBQyxlQUFlLEVBQUU7Z0JBQ3BELFNBQVMsRUFBRSxlQUFlO2FBQzNCLENBQUMsQ0FBQztRQUNMLENBQUMsQ0FBQyxDQUFDO0lBQ0wsQ0FBQyxDQUFDLENBQUM7QUFDTCxDQUFDLENBQUMsQ0FBQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgeyBUZW1wbGF0ZSwgTWF0Y2ggfSBmcm9tICdhd3MtY2RrLWxpYi9hc3NlcnRpb25zJztcbmltcG9ydCB7IEdsaXRjaEZvdW5kYXRpb25TdGFjayB9IGZyb20gJy4uL2xpYi9zdGFjayc7XG5cbmRlc2NyaWJlKCdHbGl0Y2hGb3VuZGF0aW9uU3RhY2snLCAoKSA9PiB7XG4gIGxldCBhcHA6IGNkay5BcHA7XG4gIGxldCBzdGFjazogR2xpdGNoRm91bmRhdGlvblN0YWNrO1xuICBsZXQgdGVtcGxhdGU6IFRlbXBsYXRlO1xuXG4gIGJlZm9yZUVhY2goKCkgPT4ge1xuICAgIGFwcCA9IG5ldyBjZGsuQXBwKCk7XG4gICAgc3RhY2sgPSBuZXcgR2xpdGNoRm91bmRhdGlvblN0YWNrKGFwcCwgJ1Rlc3RGb3VuZGF0aW9uU3RhY2snLCB7XG4gICAgICBlbnY6IHsgYWNjb3VudDogJzEyMzQ1Njc4OTAxMicsIHJlZ2lvbjogJ3VzLXdlc3QtMicgfSxcbiAgICB9KTtcbiAgICB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdWUEMgQ29uZmlndXJhdGlvbicsICgpID0+IHtcbiAgICB0ZXN0KCdjcmVhdGVzIFZQQyB3aXRoIGNvcnJlY3QgQ0lEUicsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlZQQycsIHtcbiAgICAgICAgQ2lkckJsb2NrOiAnMTAuMC4wLjAvMTYnLFxuICAgICAgICBFbmFibGVEbnNIb3N0bmFtZXM6IHRydWUsXG4gICAgICAgIEVuYWJsZURuc1N1cHBvcnQ6IHRydWUsXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2NyZWF0ZXMgcHVibGljIGFuZCBwcml2YXRlIHN1Ym5ldHMnLCAoKSA9PiB7XG4gICAgICAvLyBBdCBsZWFzdCAyIHB1YmxpYyArIDIgcHJpdmF0ZVxuICAgICAgY29uc3QgY291bnQgPSB0ZW1wbGF0ZS5maW5kUmVzb3VyY2VzKCdBV1M6OkVDMjo6U3VibmV0Jyk7XG4gICAgICBleHBlY3QoT2JqZWN0LmtleXMoY291bnQpLmxlbmd0aCkudG9CZUdyZWF0ZXJUaGFuT3JFcXVhbCgyKTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2RvZXMgbm90IGNyZWF0ZSBOQVQgZ2F0ZXdheSAoY29zdCBvcHRpbWl6YXRpb247IGFnZW50cyB1c2UgUFVCTElDIG1vZGUpJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUucmVzb3VyY2VDb3VudElzKCdBV1M6OkVDMjo6TmF0R2F0ZXdheScsIDApO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBWaXJ0dWFsIFByaXZhdGUgR2F0ZXdheSBmb3IgU2l0ZS10by1TaXRlIFZQTicsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLnJlc291cmNlQ291bnRJcygnQVdTOjpFQzI6OlZQTkdhdGV3YXknLCAxKTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2F0dGFjaGVzIFZQTiBnYXRld2F5IHRvIFZQQycsICgpID0+IHtcbiAgICAgIC8vIENESyBhbHNvIGNyZWF0ZXMgb25lIGZvciB0aGUgSW50ZXJuZXQgR2F0ZXdheSwgc28gZXhwZWN0IGF0IGxlYXN0IDJcbiAgICAgIGNvbnN0IGF0dGFjaG1lbnRzID0gdGVtcGxhdGUuZmluZFJlc291cmNlcygnQVdTOjpFQzI6OlZQQ0dhdGV3YXlBdHRhY2htZW50Jyk7XG4gICAgICBleHBlY3QoT2JqZWN0LmtleXMoYXR0YWNobWVudHMpLmxlbmd0aCkudG9CZUdyZWF0ZXJUaGFuT3JFcXVhbCgyKTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2RvZXMgbm90IGNyZWF0ZSBWUEMgZW5kcG9pbnRzIChhZ2VudHMgdXNlIFBVQkxJQyBtb2RlKScsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLnJlc291cmNlQ291bnRJcygnQVdTOjpFQzI6OlZQQ0VuZHBvaW50JywgMCk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdJQU0gUm9sZXMnLCAoKSA9PiB7XG4gICAgdGVzdCgnY3JlYXRlcyBydW50aW1lIHJvbGUgd2l0aCBiZWRyb2NrLWFnZW50Y29yZSB0cnVzdCcsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpJQU06OlJvbGUnLCB7XG4gICAgICAgIEFzc3VtZVJvbGVQb2xpY3lEb2N1bWVudDoge1xuICAgICAgICAgIFN0YXRlbWVudDogTWF0Y2guYXJyYXlXaXRoKFtcbiAgICAgICAgICAgIE1hdGNoLm9iamVjdExpa2Uoe1xuICAgICAgICAgICAgICBQcmluY2lwYWw6IHsgU2VydmljZTogJ2JlZHJvY2stYWdlbnRjb3JlLmFtYXpvbmF3cy5jb20nIH0sXG4gICAgICAgICAgICB9KSxcbiAgICAgICAgICBdKSxcbiAgICAgICAgfSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBDb2RlQnVpbGQgcm9sZSB3aXRoIGNvZGVidWlsZCB0cnVzdCcsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpJQU06OlJvbGUnLCB7XG4gICAgICAgIEFzc3VtZVJvbGVQb2xpY3lEb2N1bWVudDoge1xuICAgICAgICAgIFN0YXRlbWVudDogTWF0Y2guYXJyYXlXaXRoKFtcbiAgICAgICAgICAgIE1hdGNoLm9iamVjdExpa2Uoe1xuICAgICAgICAgICAgICBQcmluY2lwYWw6IHsgU2VydmljZTogJ2NvZGVidWlsZC5hbWF6b25hd3MuY29tJyB9LFxuICAgICAgICAgICAgfSksXG4gICAgICAgICAgXSksXG4gICAgICAgIH0sXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ0NvZGVCdWlsZCByb2xlIGhhcyBFQ1IgcGVybWlzc2lvbnMnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6SUFNOjpQb2xpY3knLCB7XG4gICAgICAgIFBvbGljeURvY3VtZW50OiB7XG4gICAgICAgICAgU3RhdGVtZW50OiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7XG4gICAgICAgICAgICAgIEFjdGlvbjogJ2VjcjpHZXRBdXRob3JpemF0aW9uVG9rZW4nLFxuICAgICAgICAgICAgfSksXG4gICAgICAgICAgXSksXG4gICAgICAgIH0sXG4gICAgICB9KTtcbiAgICB9KTtcbiAgfSk7XG5cbiAgZGVzY3JpYmUoJ1NTTSBQYXJhbWV0ZXJzJywgKCkgPT4ge1xuICAgIHRlc3QoJ2NyZWF0ZXMgU1NNIHBhcmFtZXRlciBmb3IgVlBDIElEJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OlNTTTo6UGFyYW1ldGVyJywge1xuICAgICAgICBOYW1lOiAnL2dsaXRjaC92cGMvaWQnLFxuICAgICAgICBUeXBlOiAnU3RyaW5nJyxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBTU00gcGFyYW1ldGVyIGZvciBwcml2YXRlIHN1Ym5ldCBJRHMnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6U1NNOjpQYXJhbWV0ZXInLCB7XG4gICAgICAgIE5hbWU6ICcvZ2xpdGNoL3ZwYy9wcml2YXRlLXN1Ym5ldC1pZHMnLFxuICAgICAgICBUeXBlOiAnU3RyaW5nJyxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBTU00gcGFyYW1ldGVyIGZvciBydW50aW1lIHJvbGUgQVJOJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OlNTTTo6UGFyYW1ldGVyJywge1xuICAgICAgICBOYW1lOiAnL2dsaXRjaC9pYW0vcnVudGltZS1yb2xlLWFybicsXG4gICAgICAgIFR5cGU6ICdTdHJpbmcnLFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdjcmVhdGVzIFNTTSBwYXJhbWV0ZXIgZm9yIENvZGVCdWlsZCByb2xlIEFSTicsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpTU006OlBhcmFtZXRlcicsIHtcbiAgICAgICAgTmFtZTogJy9nbGl0Y2gvaWFtL2NvZGVidWlsZC1yb2xlLWFybicsXG4gICAgICAgIFR5cGU6ICdTdHJpbmcnLFxuICAgICAgfSk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdTdGFjayBPdXRwdXRzJywgKCkgPT4ge1xuICAgIHRlc3QoJ291dHB1dHMgVlBDIElEJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdWcGNJZCcsIHt9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ291dHB1dHMgcHJpdmF0ZSBzdWJuZXQgSURzJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdQcml2YXRlU3VibmV0SWRzJywge30pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnb3V0cHV0cyBydW50aW1lIHJvbGUgQVJOJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdSdW50aW1lUm9sZUFybicsIHt9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ291dHB1dHMgQ29kZUJ1aWxkIHJvbGUgQVJOJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdDb2RlQnVpbGRSb2xlQXJuJywge30pO1xuICAgIH0pO1xuICB9KTtcblxuICBkZXNjcmliZSgnQ3VzdG9tIENJRFInLCAoKSA9PiB7XG4gICAgdGVzdCgnYWNjZXB0cyBjdXN0b20gVlBDIENJRFInLCAoKSA9PiB7XG4gICAgICBjb25zdCBjdXN0b21BcHAgPSBuZXcgY2RrLkFwcCgpO1xuICAgICAgY29uc3QgY3VzdG9tU3RhY2sgPSBuZXcgR2xpdGNoRm91bmRhdGlvblN0YWNrKGN1c3RvbUFwcCwgJ0N1c3RvbUZvdW5kYXRpb25TdGFjaycsIHtcbiAgICAgICAgdnBjQ2lkcjogJzE3Mi4xNi4wLjAvMTYnLFxuICAgICAgICBlbnY6IHsgYWNjb3VudDogJzEyMzQ1Njc4OTAxMicsIHJlZ2lvbjogJ3VzLXdlc3QtMicgfSxcbiAgICAgIH0pO1xuICAgICAgY29uc3QgY3VzdG9tVGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soY3VzdG9tU3RhY2spO1xuXG4gICAgICBjdXN0b21UZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUEMnLCB7XG4gICAgICAgIENpZHJCbG9jazogJzE3Mi4xNi4wLjAvMTYnLFxuICAgICAgfSk7XG4gICAgfSk7XG4gIH0pO1xufSk7XG4iXX0=