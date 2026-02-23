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
const stack_1 = require("../lib/stack");
describe('TailscaleStack', () => {
    let app;
    let vpcStack;
    let vpc;
    let authKeySecret;
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
        authKeySecret = new secretsmanager.Secret(vpcStack, 'TailscaleAuthKey', {
            secretName: 'glitch/tailscale-auth-key',
        });
    });
    function createStack(props) {
        return new stack_1.TailscaleStack(app, 'TestTailscaleStack', {
            vpc,
            tailscaleAuthKeySecret: authKeySecret,
            env: { account: '123456789012', region: 'us-west-2' },
            ...props,
        });
    }
    describe('EC2 Instance', () => {
        test('creates t4g.nano ARM instance', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::EC2::Instance', {
                InstanceType: 't4g.nano',
            });
        });
        test('creates exactly one EC2 instance', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.resourceCountIs('AWS::EC2::Instance', 1);
        });
        test('disables source/dest check for routing', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::EC2::Instance', {
                SourceDestCheck: false,
            });
        });
        test('has Name tag', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::EC2::Instance', {
                Tags: assertions_1.Match.arrayWith([
                    assertions_1.Match.objectLike({ Key: 'Name', Value: 'GlitchTailscaleConnector' }),
                ]),
            });
        });
    });
    describe('Security Group', () => {
        test('creates security group', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::EC2::SecurityGroup', {
                GroupDescription: 'Security group for Tailscale EC2 connector',
            });
        });
        test('security group has egress rules in SecurityGroupEgress property', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            const sgs = template.findResources('AWS::EC2::SecurityGroup');
            const tailscaleSg = Object.values(sgs).find((sg) => sg.Properties?.GroupDescription?.includes('Tailscale'));
            expect(tailscaleSg).toBeDefined();
            expect(tailscaleSg.Properties.SecurityGroupEgress).toBeDefined();
        });
        test('security group has ingress rules in SecurityGroupIngress property', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            const sgs = template.findResources('AWS::EC2::SecurityGroup');
            const tailscaleSg = Object.values(sgs).find((sg) => sg.Properties?.GroupDescription?.includes('Tailscale'));
            expect(tailscaleSg).toBeDefined();
            expect(tailscaleSg.Properties.SecurityGroupIngress).toBeDefined();
        });
    });
    describe('IAM Role', () => {
        test('creates role with EC2 service principal', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Role', {
                AssumeRolePolicyDocument: {
                    Statement: assertions_1.Match.arrayWith([
                        assertions_1.Match.objectLike({
                            Action: 'sts:AssumeRole',
                            Effect: 'Allow',
                            Principal: { Service: 'ec2.amazonaws.com' },
                        }),
                    ]),
                },
            });
        });
        test('attaches SSM managed policy', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::IAM::Role', {
                ManagedPolicyArns: assertions_1.Match.arrayWith([
                    assertions_1.Match.objectLike({
                        'Fn::Join': assertions_1.Match.arrayWith([
                            assertions_1.Match.arrayWith([
                                assertions_1.Match.stringLikeRegexp('AmazonSSMManagedInstanceCore'),
                            ]),
                        ]),
                    }),
                ]),
            });
        });
        test('grants read access to Tailscale auth key secret', () => {
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
    describe('User Data', () => {
        test('user data contains Tailscale installation', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            const instances = template.findResources('AWS::EC2::Instance');
            const instance = Object.values(instances)[0];
            const userData = instance.Properties.UserData;
            expect(userData).toBeDefined();
            expect(userData['Fn::Base64']).toBeDefined();
        });
    });
    describe('VPC Routes', () => {
        test('creates custom resource for ENI lookup', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.resourceCountIs('Custom::AWS', 1);
        });
        test('creates route to on-prem CIDR for isolated subnets', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasResourceProperties('AWS::EC2::Route', {
                DestinationCidrBlock: '10.10.110.0/24',
            });
        });
    });
    describe('Stack Outputs', () => {
        test('exports instance ID', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasOutput('InstanceId', {});
        });
        test('exports security group ID', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasOutput('SecurityGroupId', {});
        });
        test('exports private IP', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasOutput('PrivateIp', {});
        });
        test('exports public IP', () => {
            const stack = createStack();
            const template = assertions_1.Template.fromStack(stack);
            template.hasOutput('PublicIp', {});
        });
    });
    describe('UI Proxy (nginx)', () => {
        test('creates UI URL output when gateway URL and bucket provided', () => {
            const stack = createStack({
                gatewayFunctionUrl: 'https://abc123.lambda-url.us-west-2.on.aws/',
                gatewayHostname: 'abc123.lambda-url.us-west-2.on.aws',
                uiBucketName: 'glitch-ui-bucket',
            });
            const template = assertions_1.Template.fromStack(stack);
            template.hasOutput('TailscaleUiUrl', {});
        });
    });
});
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidGFpbHNjYWxlLXN0YWNrLnRlc3QuanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJ0YWlsc2NhbGUtc3RhY2sudGVzdC50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx1REFBa0U7QUFDbEUseURBQTJDO0FBQzNDLCtFQUFpRTtBQUNqRSx3Q0FBOEM7QUFFOUMsUUFBUSxDQUFDLGdCQUFnQixFQUFFLEdBQUcsRUFBRTtJQUM5QixJQUFJLEdBQVksQ0FBQztJQUNqQixJQUFJLFFBQW1CLENBQUM7SUFDeEIsSUFBSSxHQUFZLENBQUM7SUFDakIsSUFBSSxhQUFvQyxDQUFDO0lBRXpDLFVBQVUsQ0FBQyxHQUFHLEVBQUU7UUFDZCxHQUFHLEdBQUcsSUFBSSxHQUFHLENBQUMsR0FBRyxFQUFFLENBQUM7UUFDcEIsUUFBUSxHQUFHLElBQUksR0FBRyxDQUFDLEtBQUssQ0FBQyxHQUFHLEVBQUUsVUFBVSxFQUFFO1lBQ3hDLEdBQUcsRUFBRSxFQUFFLE9BQU8sRUFBRSxjQUFjLEVBQUUsTUFBTSxFQUFFLFdBQVcsRUFBRTtTQUN0RCxDQUFDLENBQUM7UUFDSCxHQUFHLEdBQUcsSUFBSSxHQUFHLENBQUMsR0FBRyxDQUFDLFFBQVEsRUFBRSxTQUFTLEVBQUU7WUFDckMsTUFBTSxFQUFFLENBQUM7WUFDVCxXQUFXLEVBQUUsQ0FBQztZQUNkLG1CQUFtQixFQUFFO2dCQUNuQixFQUFFLElBQUksRUFBRSxRQUFRLEVBQUUsVUFBVSxFQUFFLEdBQUcsQ0FBQyxVQUFVLENBQUMsTUFBTSxFQUFFLFFBQVEsRUFBRSxFQUFFLEVBQUU7Z0JBQ25FLEVBQUUsSUFBSSxFQUFFLFNBQVMsRUFBRSxVQUFVLEVBQUUsR0FBRyxDQUFDLFVBQVUsQ0FBQyxnQkFBZ0IsRUFBRSxRQUFRLEVBQUUsRUFBRSxFQUFFO2FBQy9FO1NBQ0YsQ0FBQyxDQUFDO1FBQ0gsYUFBYSxHQUFHLElBQUks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UUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO1lBRTNDLFFBQVEsQ0FBQyxTQUFTLENBQUMsV0FBVyxFQUFFLEVBQUUsQ0FBQyxDQUFDO1FBQ3RDLENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLG1CQUFtQixFQUFFLEdBQUcsRUFBRTtZQUM3QixNQUFNLEtBQUssR0FBRyxXQUFXLEVBQUUsQ0FBQztZQUM1QixNQUFNLFFBQVEsR0FBRyxxQkFBUSxDQUFDLFNBQVMsQ0FBQyxLQUFLLENBQUMsQ0FBQztZQUUzQyxRQUFRLENBQUMsU0FBUyxDQUFDLFVBQVUsRUFBRSxFQUFFLENBQUMsQ0FBQztRQUNyQyxDQUFDLENBQUMsQ0FBQztJQUNMLENBQUMsQ0FBQyxDQUFDO0lBRUgsUUFBUSxDQUFDLGtCQUFrQixFQUFFLEdBQUcsRUFBRTtRQUNoQyxJQUFJLENBQUMsNERBQTRELEVBQUUsR0FBRyxFQUFFO1lBQ3RFLE1BQU0sS0FBSyxHQUFHLFdBQVcsQ0FBQztnQkFDeEIsa0JBQWtCLEVBQUUsNkNBQTZDO2dCQUNqRSxlQUFlLEVBQUUsb0NBQW9DO2dCQUNyRCxZQUFZLEVBQUUsa0JBQWtCO2FBQ2pDLENBQUMsQ0FBQztZQUNILE1BQU0sUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO1lBRTNDLFFBQVEsQ0FBQyxTQUFTLENBQUMsZ0JBQWdCLEVBQUUsRUFBRSxDQUFDLENBQUM7UUFDM0MsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztBQUNMLENBQUMsQ0FBQyxDQUFDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCB7IFRlbXBsYXRlLCBNYXRjaCwgQ2FwdHVyZSB9IGZyb20gJ2F3cy1jZGstbGliL2Fzc2VydGlvbnMnO1xuaW1wb3J0ICogYXMgZWMyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lYzInO1xuaW1wb3J0ICogYXMgc2VjcmV0c21hbmFnZXIgZnJvbSAnYXdzLWNkay1saWIvYXdzLXNlY3JldHNtYW5hZ2VyJztcbmltcG9ydCB7IFRhaWxzY2FsZVN0YWNrIH0gZnJvbSAnLi4vbGliL3N0YWNrJztcblxuZGVzY3JpYmUoJ1RhaWxzY2FsZVN0YWNrJywgKCkgPT4ge1xuICBsZXQgYXBwOiBjZGsuQXBwO1xuICBsZXQgdnBjU3RhY2s6IGNkay5TdGFjaztcbiAgbGV0IHZwYzogZWMyLlZwYztcbiAgbGV0IGF1dGhLZXlTZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLlNlY3JldDtcblxuICBiZWZvcmVFYWNoKCgpID0+IHtcbiAgICBhcHAgPSBuZXcgY2RrLkFwcCgpO1xuICAgIHZwY1N0YWNrID0gbmV3IGNkay5TdGFjayhhcHAsICdWcGNTdGFjaycsIHtcbiAgICAgIGVudjogeyBhY2NvdW50OiAnMTIzNDU2Nzg5MDEyJywgcmVnaW9uOiAndXMtd2VzdC0yJyB9LFxuICAgIH0pO1xuICAgIHZwYyA9IG5ldyBlYzIuVnBjKHZwY1N0YWNrLCAnVGVzdFZwYycsIHtcbiAgICAgIG1heEF6czogMixcbiAgICAgIG5hdEdhdGV3YXlzOiAwLFxuICAgICAgc3VibmV0Q29uZmlndXJhdGlvbjogW1xuICAgICAgICB7IG5hbWU6ICdQdWJsaWMnLCBzdWJuZXRUeXBlOiBlYzIuU3VibmV0VHlwZS5QVUJMSUMsIGNpZHJNYXNrOiAyNCB9LFxuICAgICAgICB7IG5hbWU6ICdQcml2YXRlJywgc3VibmV0VHlwZTogZWMyLlN1Ym5ldFR5cGUuUFJJVkFURV9JU09MQVRFRCwgY2lkck1hc2s6IDI0IH0sXG4gICAgICBdLFxuICAgIH0pO1xuICAgIGF1dGhLZXlTZWNyZXQgPSBuZXcgc2VjcmV0c21hbmFnZXIuU2VjcmV0KHZwY1N0YWNrLCAnVGFpbHNjYWxlQXV0aEtleScsIHtcbiAgICAgIHNlY3JldE5hbWU6ICdnbGl0Y2gvdGFpbHNjYWxlLWF1dGgta2V5JyxcbiAgICB9KTtcbiAgfSk7XG5cbiAgZnVuY3Rpb24gY3JlYXRlU3RhY2socHJvcHM/OiBQYXJ0aWFsPENvbnN0cnVjdG9yUGFyYW1ldGVyczx0eXBlb2YgVGFpbHNjYWxlU3RhY2s+WzJdPikge1xuICAgIHJldHVybiBuZXcgVGFpbHNjYWxlU3RhY2soYXBwLCAnVGVzdFRhaWxzY2FsZVN0YWNrJywge1xuICAgICAgdnBjLFxuICAgICAgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogYXV0aEtleVNlY3JldCxcbiAgICAgIGVudjogeyBhY2NvdW50OiAnMTIzNDU2Nzg5MDEyJywgcmVnaW9uOiAndXMtd2VzdC0yJyB9LFxuICAgICAgLi4ucHJvcHMsXG4gICAgfSk7XG4gIH1cblxuICBkZXNjcmliZSgnRUMyIEluc3RhbmNlJywgKCkgPT4ge1xuICAgIHRlc3QoJ2NyZWF0ZXMgdDRnLm5hbm8gQVJNIGluc3RhbmNlJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpJbnN0YW5jZScsIHtcbiAgICAgICAgSW5zdGFuY2VUeXBlOiAndDRnLm5hbm8nLFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdjcmVhdGVzIGV4YWN0bHkgb25lIEVDMiBpbnN0YW5jZScsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUucmVzb3VyY2VDb3VudElzKCdBV1M6OkVDMjo6SW5zdGFuY2UnLCAxKTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2Rpc2FibGVzIHNvdXJjZS9kZXN0IGNoZWNrIGZvciByb3V0aW5nJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpJbnN0YW5jZScsIHtcbiAgICAgICAgU291cmNlRGVzdENoZWNrOiBmYWxzZSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnaGFzIE5hbWUgdGFnJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpJbnN0YW5jZScsIHtcbiAgICAgICAgVGFnczogTWF0Y2guYXJyYXlXaXRoKFtcbiAgICAgICAgICBNYXRjaC5vYmplY3RMaWtlKHsgS2V5OiAnTmFtZScsIFZhbHVlOiAnR2xpdGNoVGFpbHNjYWxlQ29ubmVjdG9yJyB9KSxcbiAgICAgICAgXSksXG4gICAgICB9KTtcbiAgICB9KTtcbiAgfSk7XG5cbiAgZGVzY3JpYmUoJ1NlY3VyaXR5IEdyb3VwJywgKCkgPT4ge1xuICAgIHRlc3QoJ2NyZWF0ZXMgc2VjdXJpdHkgZ3JvdXAnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlNlY3VyaXR5R3JvdXAnLCB7XG4gICAgICAgIEdyb3VwRGVzY3JpcHRpb246ICdTZWN1cml0eSBncm91cCBmb3IgVGFpbHNjYWxlIEVDMiBjb25uZWN0b3InLFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdzZWN1cml0eSBncm91cCBoYXMgZWdyZXNzIHJ1bGVzIGluIFNlY3VyaXR5R3JvdXBFZ3Jlc3MgcHJvcGVydHknLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIGNvbnN0IHNncyA9IHRlbXBsYXRlLmZpbmRSZXNvdXJjZXMoJ0FXUzo6RUMyOjpTZWN1cml0eUdyb3VwJyk7XG4gICAgICBjb25zdCB0YWlsc2NhbGVTZyA9IE9iamVjdC52YWx1ZXMoc2dzKS5maW5kKFxuICAgICAgICAoc2c6IGFueSkgPT4gc2cuUHJvcGVydGllcz8uR3JvdXBEZXNjcmlwdGlvbj8uaW5jbHVkZXMoJ1RhaWxzY2FsZScpXG4gICAgICApO1xuICAgICAgZXhwZWN0KHRhaWxzY2FsZVNnKS50b0JlRGVmaW5lZCgpO1xuICAgICAgZXhwZWN0KCh0YWlsc2NhbGVTZyBhcyBhbnkpLlByb3BlcnRpZXMuU2VjdXJpdHlHcm91cEVncmVzcykudG9CZURlZmluZWQoKTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ3NlY3VyaXR5IGdyb3VwIGhhcyBpbmdyZXNzIHJ1bGVzIGluIFNlY3VyaXR5R3JvdXBJbmdyZXNzIHByb3BlcnR5JywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICBjb25zdCBzZ3MgPSB0ZW1wbGF0ZS5maW5kUmVzb3VyY2VzKCdBV1M6OkVDMjo6U2VjdXJpdHlHcm91cCcpO1xuICAgICAgY29uc3QgdGFpbHNjYWxlU2cgPSBPYmplY3QudmFsdWVzKHNncykuZmluZChcbiAgICAgICAgKHNnOiBhbnkpID0+IHNnLlByb3BlcnRpZXM/Lkdyb3VwRGVzY3JpcHRpb24/LmluY2x1ZGVzKCdUYWlsc2NhbGUnKVxuICAgICAgKTtcbiAgICAgIGV4cGVjdCh0YWlsc2NhbGVTZykudG9CZURlZmluZWQoKTtcbiAgICAgIGV4cGVjdCgodGFpbHNjYWxlU2cgYXMgYW55KS5Qcm9wZXJ0aWVzLlNlY3VyaXR5R3JvdXBJbmdyZXNzKS50b0JlRGVmaW5lZCgpO1xuICAgIH0pO1xuICB9KTtcblxuICBkZXNjcmliZSgnSUFNIFJvbGUnLCAoKSA9PiB7XG4gICAgdGVzdCgnY3JlYXRlcyByb2xlIHdpdGggRUMyIHNlcnZpY2UgcHJpbmNpcGFsJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6SUFNOjpSb2xlJywge1xuICAgICAgICBBc3N1bWVSb2xlUG9saWN5RG9jdW1lbnQ6IHtcbiAgICAgICAgICBTdGF0ZW1lbnQ6IE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgICBNYXRjaC5vYmplY3RMaWtlKHtcbiAgICAgICAgICAgICAgQWN0aW9uOiAnc3RzOkFzc3VtZVJvbGUnLFxuICAgICAgICAgICAgICBFZmZlY3Q6ICdBbGxvdycsXG4gICAgICAgICAgICAgIFByaW5jaXBhbDogeyBTZXJ2aWNlOiAnZWMyLmFtYXpvbmF3cy5jb20nIH0sXG4gICAgICAgICAgICB9KSxcbiAgICAgICAgICBdKSxcbiAgICAgICAgfSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnYXR0YWNoZXMgU1NNIG1hbmFnZWQgcG9saWN5JywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6SUFNOjpSb2xlJywge1xuICAgICAgICBNYW5hZ2VkUG9saWN5QXJuczogTWF0Y2guYXJyYXlXaXRoKFtcbiAgICAgICAgICBNYXRjaC5vYmplY3RMaWtlKHtcbiAgICAgICAgICAgICdGbjo6Sm9pbic6IE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgICAgIE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgICAgICAgTWF0Y2guc3RyaW5nTGlrZVJlZ2V4cCgnQW1hem9uU1NNTWFuYWdlZEluc3RhbmNlQ29yZScpLFxuICAgICAgICAgICAgICBdKSxcbiAgICAgICAgICAgIF0pLFxuICAgICAgICAgIH0pLFxuICAgICAgICBdKSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnZ3JhbnRzIHJlYWQgYWNjZXNzIHRvIFRhaWxzY2FsZSBhdXRoIGtleSBzZWNyZXQnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpJQU06OlBvbGljeScsIHtcbiAgICAgICAgUG9saWN5RG9jdW1lbnQ6IHtcbiAgICAgICAgICBTdGF0ZW1lbnQ6IE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgICBNYXRjaC5vYmplY3RMaWtlKHtcbiAgICAgICAgICAgICAgQWN0aW9uOiBNYXRjaC5hcnJheVdpdGgoWydzZWNyZXRzbWFuYWdlcjpHZXRTZWNyZXRWYWx1ZSddKSxcbiAgICAgICAgICAgICAgRWZmZWN0OiAnQWxsb3cnLFxuICAgICAgICAgICAgfSksXG4gICAgICAgICAgXSksXG4gICAgICAgIH0sXG4gICAgICB9KTtcbiAgICB9KTtcbiAgfSk7XG5cbiAgZGVzY3JpYmUoJ1VzZXIgRGF0YScsICgpID0+IHtcbiAgICB0ZXN0KCd1c2VyIGRhdGEgY29udGFpbnMgVGFpbHNjYWxlIGluc3RhbGxhdGlvbicsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgY29uc3QgaW5zdGFuY2VzID0gdGVtcGxhdGUuZmluZFJlc291cmNlcygnQVdTOjpFQzI6Okluc3RhbmNlJyk7XG4gICAgICBjb25zdCBpbnN0YW5jZSA9IE9iamVjdC52YWx1ZXMoaW5zdGFuY2VzKVswXSBhcyBhbnk7XG4gICAgICBjb25zdCB1c2VyRGF0YSA9IGluc3RhbmNlLlByb3BlcnRpZXMuVXNlckRhdGE7XG4gICAgICBcbiAgICAgIGV4cGVjdCh1c2VyRGF0YSkudG9CZURlZmluZWQoKTtcbiAgICAgIGV4cGVjdCh1c2VyRGF0YVsnRm46OkJhc2U2NCddKS50b0JlRGVmaW5lZCgpO1xuICAgIH0pO1xuICB9KTtcblxuICBkZXNjcmliZSgnVlBDIFJvdXRlcycsICgpID0+IHtcbiAgICB0ZXN0KCdjcmVhdGVzIGN1c3RvbSByZXNvdXJjZSBmb3IgRU5JIGxvb2t1cCcsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUucmVzb3VyY2VDb3VudElzKCdDdXN0b206OkFXUycsIDEpO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyByb3V0ZSB0byBvbi1wcmVtIENJRFIgZm9yIGlzb2xhdGVkIHN1Ym5ldHMnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlJvdXRlJywge1xuICAgICAgICBEZXN0aW5hdGlvbkNpZHJCbG9jazogJzEwLjEwLjExMC4wLzI0JyxcbiAgICAgIH0pO1xuICAgIH0pO1xuICB9KTtcblxuICBkZXNjcmliZSgnU3RhY2sgT3V0cHV0cycsICgpID0+IHtcbiAgICB0ZXN0KCdleHBvcnRzIGluc3RhbmNlIElEJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNPdXRwdXQoJ0luc3RhbmNlSWQnLCB7fSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdleHBvcnRzIHNlY3VyaXR5IGdyb3VwIElEJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNPdXRwdXQoJ1NlY3VyaXR5R3JvdXBJZCcsIHt9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2V4cG9ydHMgcHJpdmF0ZSBJUCcsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdQcml2YXRlSXAnLCB7fSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdleHBvcnRzIHB1YmxpYyBJUCcsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdQdWJsaWNJcCcsIHt9KTtcbiAgICB9KTtcbiAgfSk7XG5cbiAgZGVzY3JpYmUoJ1VJIFByb3h5IChuZ2lueCknLCAoKSA9PiB7XG4gICAgdGVzdCgnY3JlYXRlcyBVSSBVUkwgb3V0cHV0IHdoZW4gZ2F0ZXdheSBVUkwgYW5kIGJ1Y2tldCBwcm92aWRlZCcsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soe1xuICAgICAgICBnYXRld2F5RnVuY3Rpb25Vcmw6ICdodHRwczovL2FiYzEyMy5sYW1iZGEtdXJsLnVzLXdlc3QtMi5vbi5hd3MvJyxcbiAgICAgICAgZ2F0ZXdheUhvc3RuYW1lOiAnYWJjMTIzLmxhbWJkYS11cmwudXMtd2VzdC0yLm9uLmF3cycsXG4gICAgICAgIHVpQnVja2V0TmFtZTogJ2dsaXRjaC11aS1idWNrZXQnLFxuICAgICAgfSk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc091dHB1dCgnVGFpbHNjYWxlVWlVcmwnLCB7fSk7XG4gICAgfSk7XG4gIH0pO1xufSk7XG4iXX0=