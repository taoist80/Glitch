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
const tailscale_stack_1 = require("../lib/tailscale-stack");
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
        return new tailscale_stack_1.TailscaleStack(app, 'TestTailscaleStack', {
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidGFpbHNjYWxlLXN0YWNrLnRlc3QuanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJ0YWlsc2NhbGUtc3RhY2sudGVzdC50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx1REFBa0U7QUFDbEUseURBQTJDO0FBQzNDLCtFQUFpRTtBQUNqRSw0REFBd0Q7QUFFeEQsUUFBUSxDQUFDLGdCQUFnQixFQUFFLEdBQUcsRUFBRTtJQUM5QixJQUFJLEdBQVksQ0FBQztJQUNqQixJQUFJLFFBQW1CLENBQUM7SUFDeEIsSUFBSSxHQUFZLENBQUM7SUFDakIsSUFBSSxhQUFvQyxDQUFDO0lBRXpDLFVBQVUsQ0FBQyxHQUFHLEVBQUU7UUFDZCxHQUFHLEdBQUcsSUFBSSxHQUFHLENBQUMsR0FBRyxFQUFFLENBQUM7UUFDcEIsUUFBUSxHQUFHLElBQUksR0FBRyxDQUFDLEtBQUssQ0FBQyxHQUFHLEVBQUUsVUFBVSxFQUFFO1lBQ3hDLEdBQUcsRUFBRSxFQUFFLE9BQU8sRUFBRSxjQUFjLEVBQUUsTUFBTSxFQUFFLFdBQVcsRUFBRTtTQUN0RCxDQUFDLENBQUM7UUFDSCxHQUFHLEdBQUcsSUFBSSxHQUFHLENBQUMsR0FBRyxDQUFDLFFBQVEsRUFBRSxTQUFTLEVBQUU7WUFDckMsTUFBTSxFQUFFLENBQUM7WUFDVCxXQUFXLEVBQUUsQ0FBQztZQUNkLG1CQUFtQixFQUFFO2dCQUNuQixFQUFFLElBQUksRUFBRSxRQUFRLEVBQUUsVUFBVSxFQUFFLEdBQUcsQ0FBQyxVQUFVLENBQUMsTUFBTSxFQUFFLFFBQVEsRUFBRSxFQUFFLEVBQUU7Z0JBQ25FLEVBQUUsSUFBSSxFQUFFLFNBQVMsRUFBRSxVQUFVLEVBQUUsR0FBRyxDQUFDLFVBQVUsQ0FBQyxnQkFBZ0IsRUFBRSxRQUFRLEVBQUUsRUFBRSxFQUFFO2FBQy9FO1NBQ0YsQ0FBQyxDQUFDO1FBQ0gsYUFBYSxHQUFHLElBQUksY0FBYyxDQUFDLE1BQU0sQ0FBQyxRQUFRLEVBQUUsa0JBQWtCLEVBQUU7WUFDdEUsVUFBVSxFQUFFLDJCQUEyQjtTQUN4QyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztJQUVILFNBQVMsV0FBVyxDQUFDLEtBQWdFO1FBQ25GLE9BQU8sSUFBSSxnQ0FBYyxDQUFDLEdBQUcsRUFBRSxvQkFBb0IsRUFBRTtZQUNuRCxHQUFHO1lBQ0gsc0JBQXNCLEVBQUUsYUFBYTtZQUNyQyxHQUFHLEVBQUUsRUFBRSxPQUFPLEVBQUUsY0FBYyxFQUFFLE1BQU0sRUFBRSxXQUFXLEVBQUU7WUFDckQsR0FBRyxLQUFLO1NBQ1QsQ0FBQyxDQUFDO0lBQ0wsQ0FBQztJQUVELFFBQVEsQ0FBQyxjQUFjLEVBQUUsR0FBRyxFQUFFO1FBQzVCLElBQUksQ0FBQywrQkFBK0IsRUFBRSxHQUFHLEVBQUU7WUFDekMsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsUUFBUSxDQUFDLHFCQUFxQixDQUFDLG9CQUFvQixFQUFFO2dCQUNuRCxZQUFZLEVBQUUsVUFBVTthQUN6QixDQUFDLENBQUM7UUFDTCxDQUFDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxrQ0FBa0MsRUFBRSxHQUFHLEVBQUU7WUFDNUMsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsUUFBUSxDQUFDLGVBQWUsQ0FBQyxvQkFBb0IsRUFBRSxDQUFDLENBQUMsQ0FBQztRQUNwRCxDQUFDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyx3Q0FBd0MsRUFBRSxHQUFHLEVBQUU7WUFDbEQsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsUUFBUSxDQUFDLHFCQUFxQixDQUFDLG9CQUFvQixFQUFFO2dCQUNuRCxlQUFlLEVBQUUsS0FBSzthQUN2QixDQUFDLENBQUM7UUFDTCxDQUFDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxjQUFjLEVBQUUsR0FBRyxFQUFFO1lBQ3hCLE1BQU0sS0FBSyxHQUFHLFdBQVcsRUFBRSxDQUFDO1lBQzVCLE1BQU0sUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO1lBRTNDLFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyxvQkFBb0IsRUFBRTtnQkFDbkQsSUFBSSxFQUFFLGtCQUFLLENBQUMsU0FBUyxDQUFDO29CQUNwQixrQkFBSyxDQUFDLFVBQVUsQ0FBQyxFQUFFLEdBQUcsRUFBRSxNQUFNLEVBQUUsS0FBSyxFQUFFLDBCQUEwQixFQUFFLENBQUM7aUJBQ3JFLENBQUM7YUFDSCxDQUFDLENBQUM7UUFDTCxDQUFDLENBQUMsQ0FBQztJQUNMLENBQUMsQ0FBQyxDQUFDO0lBRUgsUUFBUSxDQUFDLGdCQUFnQixFQUFFLEdBQUcsRUFBRTtRQUM5QixJQUFJLENBQUMsd0JBQXdCLEVBQUUsR0FBRyxFQUFFO1lBQ2xDLE1BQU0sS0FBSyxHQUFHLFdBQVcsRUFBRSxDQUFDO1lBQzVCLE1BQU0sUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO1lBRTNDLFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyx5QkFBeUIsRUFBRTtnQkFDeEQsZ0JBQWdCLEVBQUUsNENBQTRDO2FBQy9ELENBQUMsQ0FBQztRQUNMLENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLGlFQUFpRSxFQUFFLEdBQUcsRUFBRTtZQUMzRSxNQUFNLEtBQUssR0FBRyxXQUFXLEVBQUUsQ0FBQztZQUM1QixNQUFNLFFBQVEsR0FBRyxxQkFBUSxDQUFDLFNBQVMsQ0FBQyxLQUFLLENBQUMsQ0FBQztZQUUzQyxNQUFNLEdBQUcsR0FBRyxRQUFRLENBQUMsYUFBYSxDQUFDLHlCQUF5QixDQUFDLENBQUM7WUFDOUQsTUFBTSxXQUFXLEdBQUcsTUFBTSxDQUFDLE1BQU0sQ0FBQyxHQUFHLENBQUMsQ0FBQyxJQUFJLENBQ3pDLENBQUMsRUFBTyxFQUFFLEVBQUUsQ0FBQyxFQUFFLENBQUMsVUFBVSxFQUFFLGdCQUFnQixFQUFFLFFBQVEsQ0FBQyxXQUFXLENBQUMsQ0FDcEUsQ0FBQztZQUNGLE1BQU0sQ0FBQyxXQUFXLENBQUMsQ0FBQyxXQUFXLEVBQUUsQ0FBQztZQUNsQyxNQUFNLENBQUUsV0FBbUIsQ0FBQyxVQUFVLENBQUMsbUJBQW1CLENBQUMsQ0FBQyxXQUFXLEVBQUUsQ0FBQztRQUM1RSxDQUFDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxtRUFBbUUsRUFBRSxHQUFHLEVBQUU7WUFDN0UsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsTUFBTSxHQUFHLEdBQUcsUUFBUSxDQUFDLGFBQWEsQ0FBQyx5QkFBeUIsQ0FBQyxDQUFDO1lBQzlELE1BQU0sV0FBVyxHQUFHLE1BQU0sQ0FBQyxNQUFNLENBQUMsR0FBRyxDQUFDLENBQUMsSUFBSSxDQUN6QyxDQUFDLEVBQU8sRUFBRSxFQUFFLENBQUMsRUFBRSxDQUFDLFVBQVUsRUFBRSxnQkFBZ0IsRUFBRSxRQUFRLENBQUMsV0FBVyxDQUFDLENBQ3BFLENBQUM7WUFDRixNQUFNLENBQUMsV0FBVyxDQUFDLENBQUMsV0FBVyxFQUFFLENBQUM7WUFDbEMsTUFBTSxDQUFFLFdBQW1CLENBQUMsVUFBVSxDQUFDLG9CQUFvQixDQUFDLENBQUMsV0FBVyxFQUFFLENBQUM7UUFDN0UsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztJQUVILFFBQVEsQ0FBQyxVQUFVLEVBQUUsR0FBRyxFQUFFO1FBQ3hCLElBQUksQ0FBQyx5Q0FBeUMsRUFBRSxHQUFHLEVBQUU7WUFDbkQsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsUUFBUSxDQUFDLHFCQUFxQixDQUFDLGdCQUFnQixFQUFFO2dCQUMvQyx3QkFBd0IsRUFBRTtvQkFDeEIsU0FBUyxFQUFFLGtCQUFLLENBQUMsU0FBUyxDQUFDO3dCQUN6QixrQkFBSyxDQUFDLFVBQVUsQ0FBQzs0QkFDZixNQUFNLEVBQUUsZ0JBQWdCOzRCQUN4QixNQUFNLEVBQUUsT0FBTzs0QkFDZixTQUFTLEVBQUUsRUFBRSxPQUFPLEVBQUUsbUJBQW1CLEVBQUU7eUJBQzVDLENBQUM7cUJBQ0gsQ0FBQztpQkFDSDthQUNGLENBQUMsQ0FBQztRQUNMLENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLDZCQUE2QixFQUFFLEdBQUcsRUFBRTtZQUN2QyxNQUFNLEtBQUssR0FBRyxXQUFXLEVBQUUsQ0FBQztZQUM1QixNQUFNLFFBQVEsR0FBRyxxQkFBUSxDQUFDLFNBQVMsQ0FBQyxLQUFLLENBQUMsQ0FBQztZQUUzQyxRQUFRLENBQUMscUJBQXFCLENBQUMsZ0JBQWdCLEVBQUU7Z0JBQy9DLGlCQUFpQixFQUFFLGtCQUFLLENBQUMsU0FBUyxDQUFDO29CQUNqQyxrQkFBSyxDQUFDLFVBQVUsQ0FBQzt3QkFDZixVQUFVLEVBQUUsa0JBQUssQ0FBQyxTQUFTLENBQUM7NEJBQzFCLGtCQUFLLENBQUMsU0FBUyxDQUFDO2dDQUNkLGtCQUFLLENBQUMsZ0JBQWdCLENBQUMsOEJBQThCLENBQUM7NkJBQ3ZELENBQUM7eUJBQ0gsQ0FBQztxQkFDSCxDQUFDO2lCQUNILENBQUM7YUFDSCxDQUFDLENBQUM7UUFDTCxDQUFDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxpREFBaUQsRUFBRSxHQUFHLEVBQUU7WUFDM0QsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsUUFBUSxDQUFDLHFCQUFxQixDQUFDLGtCQUFrQixFQUFFO2dCQUNqRCxjQUFjLEVBQUU7b0JBQ2QsU0FBUyxFQUFFLGtCQUFLLENBQUMsU0FBUyxDQUFDO3dCQUN6QixrQkFBSyxDQUFDLFVBQVUsQ0FBQzs0QkFDZixNQUFNLEVBQUUsa0JBQUssQ0FBQyxTQUFTLENBQUMsQ0FBQywrQkFBK0IsQ0FBQyxDQUFDOzRCQUMxRCxNQUFNLEVBQUUsT0FBTzt5QkFDaEIsQ0FBQztxQkFDSCxDQUFDO2lCQUNIO2FBQ0YsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztJQUVILFFBQVEsQ0FBQyxXQUFXLEVBQUUsR0FBRyxFQUFFO1FBQ3pCLElBQUksQ0FBQywyQ0FBMkMsRUFBRSxHQUFHLEVBQUU7WUFDckQsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsTUFBTSxTQUFTLEdBQUcsUUFBUSxDQUFDLGFBQWEsQ0FBQyxvQkFBb0IsQ0FBQyxDQUFDO1lBQy9ELE1BQU0sUUFBUSxHQUFHLE1BQU0sQ0FBQyxNQUFNLENBQUMsU0FBUyxDQUFDLENBQUMsQ0FBQyxDQUFRLENBQUM7WUFDcEQsTUFBTSxRQUFRLEdBQUcsUUFBUSxDQUFDLFVBQVUsQ0FBQyxRQUFRLENBQUM7WUFFOUMsTUFBTSxDQUFDLFFBQVEsQ0FBQyxDQUFDLFdBQVcsRUFBRSxDQUFDO1lBQy9CLE1BQU0sQ0FBQyxRQUFRLENBQUMsWUFBWSxDQUFDLENBQUMsQ0FBQyxXQUFXLEVBQUUsQ0FBQztRQUMvQyxDQUFDLENBQUMsQ0FBQztJQUNMLENBQUMsQ0FBQyxDQUFDO0lBRUgsUUFBUSxDQUFDLFlBQVksRUFBRSxHQUFHLEVBQUU7UUFDMUIsSUFBSSxDQUFDLHdDQUF3QyxFQUFFLEdBQUcsRUFBRTtZQUNsRCxNQUFNLEtBQUssR0FBRyxXQUFXLEVBQUUsQ0FBQztZQUM1QixNQUFNLFFBQVEsR0FBRyxxQkFBUSxDQUFDLFNBQVMsQ0FBQyxLQUFLLENBQUMsQ0FBQztZQUUzQyxRQUFRLENBQUMsZUFBZSxDQUFDLGFBQWEsRUFBRSxDQUFDLENBQUMsQ0FBQztRQUM3QyxDQUFDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxvREFBb0QsRUFBRSxHQUFHLEVBQUU7WUFDOUQsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsUUFBUSxDQUFDLHFCQUFxQixDQUFDLGlCQUFpQixFQUFFO2dCQUNoRCxvQkFBb0IsRUFBRSxnQkFBZ0I7YUFDdkMsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztJQUVILFFBQVEsQ0FBQyxlQUFlLEVBQUUsR0FBRyxFQUFFO1FBQzdCLElBQUksQ0FBQyxxQkFBcUIsRUFBRSxHQUFHLEVBQUU7WUFDL0IsTUFBTSxLQUFLLEdBQUcsV0FBVyxFQUFFLENBQUM7WUFDNUIsTUFBTSxRQUFRLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsS0FBSyxDQUFDLENBQUM7WUFFM0MsUUFBUSxDQUFDLFNBQVMsQ0FBQyxZQUFZLEVBQUUsRUFBRSxDQUFDLENBQUM7UUFDdkMsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsMkJBQTJCLEVBQUUsR0FBRyxFQUFFO1lBQ3JDLE1BQU0sS0FBSyxHQUFHLFdBQVcsRUFBRSxDQUFDO1lBQzVCLE1BQU0sUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO1lBRTNDLFFBQVEsQ0FBQyxTQUFTLENBQUMsaUJBQWlCLEVBQUUsRUFBRSxDQUFDLENBQUM7UUFDNUMsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsb0JBQW9CLEVBQUUsR0FBRyxFQUFFO1lBQzlCLE1BQU0sS0FBSyxHQUFHLFdBQVcsRUFBRSxDQUFDO1lBQzVCLE1BQU0sUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO1lBRTNDLFFBQVEsQ0FBQyxTQUFTLENBQUMsV0FBVyxFQUFFLEVBQUUsQ0FBQyxDQUFDO1FBQ3RDLENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLG1CQUFtQixFQUFFLEdBQUcsRUFBRTtZQUM3QixNQUFNLEtBQUssR0FBRyxXQUFXLEVBQUUsQ0FBQztZQUM1QixNQUFNLFFBQVEsR0FBRyxxQkFBUSxDQUFDLFNBQVMsQ0FBQyxLQUFLLENBQUMsQ0FBQztZQUUzQyxRQUFRLENBQUMsU0FBUyxDQUFDLFVBQVUsRUFBRSxFQUFFLENBQUMsQ0FBQztRQUNyQyxDQUFDLENBQUMsQ0FBQztJQUNMLENBQUMsQ0FBQyxDQUFDO0lBRUgsUUFBUSxDQUFDLGtCQUFrQixFQUFFLEdBQUcsRUFBRTtRQUNoQyxJQUFJLENBQUMsNERBQTRELEVBQUUsR0FBRyxFQUFFO1lBQ3RFLE1BQU0sS0FBSyxHQUFHLFdBQVcsQ0FBQztnQkFDeEIsa0JBQWtCLEVBQUUsNkNBQTZDO2dCQUNqRSxlQUFlLEVBQUUsb0NBQW9DO2dCQUNyRCxZQUFZLEVBQUUsa0JBQWtCO2FBQ2pDLENBQUMsQ0FBQztZQUNILE1BQU0sUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO1lBRTNDLFFBQVEsQ0FBQyxTQUFTLENBQUMsZ0JBQWdCLEVBQUUsRUFBRSxDQUFDLENBQUM7UUFDM0MsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztBQUNMLENBQUMsQ0FBQyxDQUFDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCB7IFRlbXBsYXRlLCBNYXRjaCwgQ2FwdHVyZSB9IGZyb20gJ2F3cy1jZGstbGliL2Fzc2VydGlvbnMnO1xuaW1wb3J0ICogYXMgZWMyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lYzInO1xuaW1wb3J0ICogYXMgc2VjcmV0c21hbmFnZXIgZnJvbSAnYXdzLWNkay1saWIvYXdzLXNlY3JldHNtYW5hZ2VyJztcbmltcG9ydCB7IFRhaWxzY2FsZVN0YWNrIH0gZnJvbSAnLi4vbGliL3RhaWxzY2FsZS1zdGFjayc7XG5cbmRlc2NyaWJlKCdUYWlsc2NhbGVTdGFjaycsICgpID0+IHtcbiAgbGV0IGFwcDogY2RrLkFwcDtcbiAgbGV0IHZwY1N0YWNrOiBjZGsuU3RhY2s7XG4gIGxldCB2cGM6IGVjMi5WcGM7XG4gIGxldCBhdXRoS2V5U2VjcmV0OiBzZWNyZXRzbWFuYWdlci5TZWNyZXQ7XG5cbiAgYmVmb3JlRWFjaCgoKSA9PiB7XG4gICAgYXBwID0gbmV3IGNkay5BcHAoKTtcbiAgICB2cGNTdGFjayA9IG5ldyBjZGsuU3RhY2soYXBwLCAnVnBjU3RhY2snLCB7XG4gICAgICBlbnY6IHsgYWNjb3VudDogJzEyMzQ1Njc4OTAxMicsIHJlZ2lvbjogJ3VzLXdlc3QtMicgfSxcbiAgICB9KTtcbiAgICB2cGMgPSBuZXcgZWMyLlZwYyh2cGNTdGFjaywgJ1Rlc3RWcGMnLCB7XG4gICAgICBtYXhBenM6IDIsXG4gICAgICBuYXRHYXRld2F5czogMCxcbiAgICAgIHN1Ym5ldENvbmZpZ3VyYXRpb246IFtcbiAgICAgICAgeyBuYW1lOiAnUHVibGljJywgc3VibmV0VHlwZTogZWMyLlN1Ym5ldFR5cGUuUFVCTElDLCBjaWRyTWFzazogMjQgfSxcbiAgICAgICAgeyBuYW1lOiAnUHJpdmF0ZScsIHN1Ym5ldFR5cGU6IGVjMi5TdWJuZXRUeXBlLlBSSVZBVEVfSVNPTEFURUQsIGNpZHJNYXNrOiAyNCB9LFxuICAgICAgXSxcbiAgICB9KTtcbiAgICBhdXRoS2V5U2VjcmV0ID0gbmV3IHNlY3JldHNtYW5hZ2VyLlNlY3JldCh2cGNTdGFjaywgJ1RhaWxzY2FsZUF1dGhLZXknLCB7XG4gICAgICBzZWNyZXROYW1lOiAnZ2xpdGNoL3RhaWxzY2FsZS1hdXRoLWtleScsXG4gICAgfSk7XG4gIH0pO1xuXG4gIGZ1bmN0aW9uIGNyZWF0ZVN0YWNrKHByb3BzPzogUGFydGlhbDxDb25zdHJ1Y3RvclBhcmFtZXRlcnM8dHlwZW9mIFRhaWxzY2FsZVN0YWNrPlsyXT4pIHtcbiAgICByZXR1cm4gbmV3IFRhaWxzY2FsZVN0YWNrKGFwcCwgJ1Rlc3RUYWlsc2NhbGVTdGFjaycsIHtcbiAgICAgIHZwYyxcbiAgICAgIHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQ6IGF1dGhLZXlTZWNyZXQsXG4gICAgICBlbnY6IHsgYWNjb3VudDogJzEyMzQ1Njc4OTAxMicsIHJlZ2lvbjogJ3VzLXdlc3QtMicgfSxcbiAgICAgIC4uLnByb3BzLFxuICAgIH0pO1xuICB9XG5cbiAgZGVzY3JpYmUoJ0VDMiBJbnN0YW5jZScsICgpID0+IHtcbiAgICB0ZXN0KCdjcmVhdGVzIHQ0Zy5uYW5vIEFSTSBpbnN0YW5jZScsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OkVDMjo6SW5zdGFuY2UnLCB7XG4gICAgICAgIEluc3RhbmNlVHlwZTogJ3Q0Zy5uYW5vJyxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBleGFjdGx5IG9uZSBFQzIgaW5zdGFuY2UnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLnJlc291cmNlQ291bnRJcygnQVdTOjpFQzI6Okluc3RhbmNlJywgMSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdkaXNhYmxlcyBzb3VyY2UvZGVzdCBjaGVjayBmb3Igcm91dGluZycsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OkVDMjo6SW5zdGFuY2UnLCB7XG4gICAgICAgIFNvdXJjZURlc3RDaGVjazogZmFsc2UsXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2hhcyBOYW1lIHRhZycsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OkVDMjo6SW5zdGFuY2UnLCB7XG4gICAgICAgIFRhZ3M6IE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7IEtleTogJ05hbWUnLCBWYWx1ZTogJ0dsaXRjaFRhaWxzY2FsZUNvbm5lY3RvcicgfSksXG4gICAgICAgIF0pLFxuICAgICAgfSk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdTZWN1cml0eSBHcm91cCcsICgpID0+IHtcbiAgICB0ZXN0KCdjcmVhdGVzIHNlY3VyaXR5IGdyb3VwJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpTZWN1cml0eUdyb3VwJywge1xuICAgICAgICBHcm91cERlc2NyaXB0aW9uOiAnU2VjdXJpdHkgZ3JvdXAgZm9yIFRhaWxzY2FsZSBFQzIgY29ubmVjdG9yJyxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnc2VjdXJpdHkgZ3JvdXAgaGFzIGVncmVzcyBydWxlcyBpbiBTZWN1cml0eUdyb3VwRWdyZXNzIHByb3BlcnR5JywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICBjb25zdCBzZ3MgPSB0ZW1wbGF0ZS5maW5kUmVzb3VyY2VzKCdBV1M6OkVDMjo6U2VjdXJpdHlHcm91cCcpO1xuICAgICAgY29uc3QgdGFpbHNjYWxlU2cgPSBPYmplY3QudmFsdWVzKHNncykuZmluZChcbiAgICAgICAgKHNnOiBhbnkpID0+IHNnLlByb3BlcnRpZXM/Lkdyb3VwRGVzY3JpcHRpb24/LmluY2x1ZGVzKCdUYWlsc2NhbGUnKVxuICAgICAgKTtcbiAgICAgIGV4cGVjdCh0YWlsc2NhbGVTZykudG9CZURlZmluZWQoKTtcbiAgICAgIGV4cGVjdCgodGFpbHNjYWxlU2cgYXMgYW55KS5Qcm9wZXJ0aWVzLlNlY3VyaXR5R3JvdXBFZ3Jlc3MpLnRvQmVEZWZpbmVkKCk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdzZWN1cml0eSBncm91cCBoYXMgaW5ncmVzcyBydWxlcyBpbiBTZWN1cml0eUdyb3VwSW5ncmVzcyBwcm9wZXJ0eScsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgY29uc3Qgc2dzID0gdGVtcGxhdGUuZmluZFJlc291cmNlcygnQVdTOjpFQzI6OlNlY3VyaXR5R3JvdXAnKTtcbiAgICAgIGNvbnN0IHRhaWxzY2FsZVNnID0gT2JqZWN0LnZhbHVlcyhzZ3MpLmZpbmQoXG4gICAgICAgIChzZzogYW55KSA9PiBzZy5Qcm9wZXJ0aWVzPy5Hcm91cERlc2NyaXB0aW9uPy5pbmNsdWRlcygnVGFpbHNjYWxlJylcbiAgICAgICk7XG4gICAgICBleHBlY3QodGFpbHNjYWxlU2cpLnRvQmVEZWZpbmVkKCk7XG4gICAgICBleHBlY3QoKHRhaWxzY2FsZVNnIGFzIGFueSkuUHJvcGVydGllcy5TZWN1cml0eUdyb3VwSW5ncmVzcykudG9CZURlZmluZWQoKTtcbiAgICB9KTtcbiAgfSk7XG5cbiAgZGVzY3JpYmUoJ0lBTSBSb2xlJywgKCkgPT4ge1xuICAgIHRlc3QoJ2NyZWF0ZXMgcm9sZSB3aXRoIEVDMiBzZXJ2aWNlIHByaW5jaXBhbCcsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OklBTTo6Um9sZScsIHtcbiAgICAgICAgQXNzdW1lUm9sZVBvbGljeURvY3VtZW50OiB7XG4gICAgICAgICAgU3RhdGVtZW50OiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7XG4gICAgICAgICAgICAgIEFjdGlvbjogJ3N0czpBc3N1bWVSb2xlJyxcbiAgICAgICAgICAgICAgRWZmZWN0OiAnQWxsb3cnLFxuICAgICAgICAgICAgICBQcmluY2lwYWw6IHsgU2VydmljZTogJ2VjMi5hbWF6b25hd3MuY29tJyB9LFxuICAgICAgICAgICAgfSksXG4gICAgICAgICAgXSksXG4gICAgICAgIH0sXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2F0dGFjaGVzIFNTTSBtYW5hZ2VkIHBvbGljeScsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OklBTTo6Um9sZScsIHtcbiAgICAgICAgTWFuYWdlZFBvbGljeUFybnM6IE1hdGNoLmFycmF5V2l0aChbXG4gICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7XG4gICAgICAgICAgICAnRm46OkpvaW4nOiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgICBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgICAgIE1hdGNoLnN0cmluZ0xpa2VSZWdleHAoJ0FtYXpvblNTTU1hbmFnZWRJbnN0YW5jZUNvcmUnKSxcbiAgICAgICAgICAgICAgXSksXG4gICAgICAgICAgICBdKSxcbiAgICAgICAgICB9KSxcbiAgICAgICAgXSksXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2dyYW50cyByZWFkIGFjY2VzcyB0byBUYWlsc2NhbGUgYXV0aCBrZXkgc2VjcmV0JywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6SUFNOjpQb2xpY3knLCB7XG4gICAgICAgIFBvbGljeURvY3VtZW50OiB7XG4gICAgICAgICAgU3RhdGVtZW50OiBNYXRjaC5hcnJheVdpdGgoW1xuICAgICAgICAgICAgTWF0Y2gub2JqZWN0TGlrZSh7XG4gICAgICAgICAgICAgIEFjdGlvbjogTWF0Y2guYXJyYXlXaXRoKFsnc2VjcmV0c21hbmFnZXI6R2V0U2VjcmV0VmFsdWUnXSksXG4gICAgICAgICAgICAgIEVmZmVjdDogJ0FsbG93JyxcbiAgICAgICAgICAgIH0pLFxuICAgICAgICAgIF0pLFxuICAgICAgICB9LFxuICAgICAgfSk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdVc2VyIERhdGEnLCAoKSA9PiB7XG4gICAgdGVzdCgndXNlciBkYXRhIGNvbnRhaW5zIFRhaWxzY2FsZSBpbnN0YWxsYXRpb24nLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIGNvbnN0IGluc3RhbmNlcyA9IHRlbXBsYXRlLmZpbmRSZXNvdXJjZXMoJ0FXUzo6RUMyOjpJbnN0YW5jZScpO1xuICAgICAgY29uc3QgaW5zdGFuY2UgPSBPYmplY3QudmFsdWVzKGluc3RhbmNlcylbMF0gYXMgYW55O1xuICAgICAgY29uc3QgdXNlckRhdGEgPSBpbnN0YW5jZS5Qcm9wZXJ0aWVzLlVzZXJEYXRhO1xuICAgICAgXG4gICAgICBleHBlY3QodXNlckRhdGEpLnRvQmVEZWZpbmVkKCk7XG4gICAgICBleHBlY3QodXNlckRhdGFbJ0ZuOjpCYXNlNjQnXSkudG9CZURlZmluZWQoKTtcbiAgICB9KTtcbiAgfSk7XG5cbiAgZGVzY3JpYmUoJ1ZQQyBSb3V0ZXMnLCAoKSA9PiB7XG4gICAgdGVzdCgnY3JlYXRlcyBjdXN0b20gcmVzb3VyY2UgZm9yIEVOSSBsb29rdXAnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLnJlc291cmNlQ291bnRJcygnQ3VzdG9tOjpBV1MnLCAxKTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2NyZWF0ZXMgcm91dGUgdG8gb24tcHJlbSBDSURSIGZvciBpc29sYXRlZCBzdWJuZXRzJywgKCkgPT4ge1xuICAgICAgY29uc3Qgc3RhY2sgPSBjcmVhdGVTdGFjaygpO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpSb3V0ZScsIHtcbiAgICAgICAgRGVzdGluYXRpb25DaWRyQmxvY2s6ICcxMC4xMC4xMTAuMC8yNCcsXG4gICAgICB9KTtcbiAgICB9KTtcbiAgfSk7XG5cbiAgZGVzY3JpYmUoJ1N0YWNrIE91dHB1dHMnLCAoKSA9PiB7XG4gICAgdGVzdCgnZXhwb3J0cyBpbnN0YW5jZSBJRCcsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdJbnN0YW5jZUlkJywge30pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnZXhwb3J0cyBzZWN1cml0eSBncm91cCBJRCcsICgpID0+IHtcbiAgICAgIGNvbnN0IHN0YWNrID0gY3JlYXRlU3RhY2soKTtcbiAgICAgIGNvbnN0IHRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKHN0YWNrKTtcblxuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdTZWN1cml0eUdyb3VwSWQnLCB7fSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdleHBvcnRzIHByaXZhdGUgSVAnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc091dHB1dCgnUHJpdmF0ZUlwJywge30pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnZXhwb3J0cyBwdWJsaWMgSVAnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKCk7XG4gICAgICBjb25zdCB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG5cbiAgICAgIHRlbXBsYXRlLmhhc091dHB1dCgnUHVibGljSXAnLCB7fSk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdVSSBQcm94eSAobmdpbngpJywgKCkgPT4ge1xuICAgIHRlc3QoJ2NyZWF0ZXMgVUkgVVJMIG91dHB1dCB3aGVuIGdhdGV3YXkgVVJMIGFuZCBidWNrZXQgcHJvdmlkZWQnLCAoKSA9PiB7XG4gICAgICBjb25zdCBzdGFjayA9IGNyZWF0ZVN0YWNrKHtcbiAgICAgICAgZ2F0ZXdheUZ1bmN0aW9uVXJsOiAnaHR0cHM6Ly9hYmMxMjMubGFtYmRhLXVybC51cy13ZXN0LTIub24uYXdzLycsXG4gICAgICAgIGdhdGV3YXlIb3N0bmFtZTogJ2FiYzEyMy5sYW1iZGEtdXJsLnVzLXdlc3QtMi5vbi5hd3MnLFxuICAgICAgICB1aUJ1Y2tldE5hbWU6ICdnbGl0Y2gtdWktYnVja2V0JyxcbiAgICAgIH0pO1xuICAgICAgY29uc3QgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuXG4gICAgICB0ZW1wbGF0ZS5oYXNPdXRwdXQoJ1RhaWxzY2FsZVVpVXJsJywge30pO1xuICAgIH0pO1xuICB9KTtcbn0pO1xuIl19