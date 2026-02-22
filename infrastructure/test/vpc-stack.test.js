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
const vpc_stack_1 = require("../lib/vpc-stack");
describe('VpcStack', () => {
    let app;
    let stack;
    let template;
    beforeEach(() => {
        app = new cdk.App();
        stack = new vpc_stack_1.VpcStack(app, 'TestVpcStack', {
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
        test('creates public and private subnets in 2 AZs', () => {
            template.resourceCountIs('AWS::EC2::Subnet', 4);
        });
        test('does not create NAT gateways (cost optimization)', () => {
            template.resourceCountIs('AWS::EC2::NatGateway', 0);
        });
    });
    describe('VPC Endpoints', () => {
        test('creates expected number of VPC endpoints', () => {
            template.resourceCountIs('AWS::EC2::VPCEndpoint', 8);
        });
        test('creates interface endpoints with private DNS', () => {
            template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
                VpcEndpointType: 'Interface',
                PrivateDnsEnabled: true,
            });
        });
        test('creates ECR Docker interface endpoint', () => {
            template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
                ServiceName: 'com.amazonaws.us-west-2.ecr.dkr',
                VpcEndpointType: 'Interface',
                PrivateDnsEnabled: true,
            });
        });
        test('creates ECR API interface endpoint', () => {
            template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
                ServiceName: 'com.amazonaws.us-west-2.ecr.api',
                VpcEndpointType: 'Interface',
                PrivateDnsEnabled: true,
            });
        });
        test('creates CloudWatch Logs interface endpoint', () => {
            template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
                ServiceName: 'com.amazonaws.us-west-2.logs',
                VpcEndpointType: 'Interface',
                PrivateDnsEnabled: true,
            });
        });
        test('creates Secrets Manager interface endpoint', () => {
            template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
                ServiceName: 'com.amazonaws.us-west-2.secretsmanager',
                VpcEndpointType: 'Interface',
                PrivateDnsEnabled: true,
            });
        });
        test('creates Bedrock Runtime interface endpoint', () => {
            template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
                ServiceName: 'com.amazonaws.us-west-2.bedrock-runtime',
                VpcEndpointType: 'Interface',
                PrivateDnsEnabled: true,
            });
        });
        test('creates Bedrock AgentCore interface endpoint', () => {
            template.hasResourceProperties('AWS::EC2::VPCEndpoint', {
                ServiceName: 'com.amazonaws.us-west-2.bedrock-agentcore',
                VpcEndpointType: 'Interface',
                PrivateDnsEnabled: true,
            });
        });
    });
    describe('Stack Outputs', () => {
        test('exports VPC ID', () => {
            template.hasOutput('VpcId', {
                Export: { Name: 'GlitchVpcId' },
            });
        });
        test('exports private subnet IDs', () => {
            template.hasOutput('PrivateSubnetIds', {
                Export: { Name: 'GlitchPrivateSubnetIds' },
            });
        });
        test('exports availability zones', () => {
            template.hasOutput('AvailabilityZones', {
                Export: { Name: 'GlitchAvailabilityZones' },
            });
        });
    });
    describe('Custom CIDR', () => {
        test('accepts custom VPC CIDR', () => {
            const customApp = new cdk.App();
            const customStack = new vpc_stack_1.VpcStack(customApp, 'CustomVpcStack', {
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidnBjLXN0YWNrLnRlc3QuanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJ2cGMtc3RhY2sudGVzdC50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx1REFBeUQ7QUFDekQsZ0RBQTRDO0FBRTVDLFFBQVEsQ0FBQyxVQUFVLEVBQUUsR0FBRyxFQUFFO0lBQ3hCLElBQUksR0FBWSxDQUFDO0lBQ2pCLElBQUksS0FBZSxDQUFDO0lBQ3BCLElBQUksUUFBa0IsQ0FBQztJQUV2QixVQUFVLENBQUMsR0FBRyxFQUFFO1FBQ2QsR0FBRyxHQUFHLElBQUksR0FBRyxDQUFDLEdBQUcsRUFBRSxDQUFDO1FBQ3BCLEtBQUssR0FBRyxJQUFJLG9CQUFRLENBQUMsR0FBRyxFQUFFLGNBQWMsRUFBRTtZQUN4QyxHQUFHLEVBQUUsRUFBRSxPQUFPLEVBQUUsY0FBYyxFQUFFLE1BQU0sRUFBRSxXQUFXLEVBQUU7U0FDdEQsQ0FBQyxDQUFDO1FBQ0gsUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO0lBQ3ZDLENBQUMsQ0FBQyxDQUFDO0lBRUgsUUFBUSxDQUFDLG1CQUFtQixFQUFFLEdBQUcsRUFBRTtRQUNqQyxJQUFJLENBQUMsK0JBQStCLEVBQUUsR0FBRyxFQUFFO1lBQ3pDLFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyxlQUFlLEVBQUU7Z0JBQzlDLFNBQVMsRUFBRSxhQUFhO2dCQUN4QixrQkFBa0IsRUFBRSxJQUFJO2dCQUN4QixnQkFBZ0IsRUFBRSxJQUFJO2FBQ3ZCLENBQUMsQ0FBQztRQUNMLENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLDZDQUE2QyxFQUFFLEdBQUcsRUFBRTtZQUN2RCxRQUFRLENBQUMsZUFBZSxDQUFDLGtCQUFrQixFQUFFLENBQUMsQ0FBQyxDQUFDO1FBQ2xELENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFD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QUU7Z0JBQ3JDLE1BQU0sRUFBRSxFQUFFLElBQUksRUFBRSx3QkFBd0IsRUFBRTthQUMzQyxDQUFDLENBQUM7UUFDTCxDQUFDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyw0QkFBNEIsRUFBRSxHQUFHLEVBQUU7WUFDdEMsUUFBUSxDQUFDLFNBQVMsQ0FBQyxtQkFBbUIsRUFBRTtnQkFDdEMsTUFBTSxFQUFFLEVBQUUsSUFBSSxFQUFFLHlCQUF5QixFQUFFO2FBQzVDLENBQUMsQ0FBQztRQUNMLENBQUMsQ0FBQyxDQUFDO0lBQ0wsQ0FBQyxDQUFDLENBQUM7SUFFSCxRQUFRLENBQUMsYUFBYSxFQUFFLEdBQUcsRUFBRTtRQUMzQixJQUFJLENBQUMseUJBQXlCLEVBQUUsR0FBRyxFQUFFO1lBQ25DLE1BQU0sU0FBUyxHQUFHLElBQUksR0FBRyxDQUFDLEdBQUcsRUFBRSxDQUFDO1lBQ2hDLE1BQU0sV0FBVyxHQUFHLElBQUksb0JBQVEsQ0FBQyxTQUFTLEVBQUUsZ0JBQWdCLEVBQUU7Z0JBQzVELE9BQU8sRUFBRSxlQUFlO2dCQUN4QixHQUFHLEVBQUUsRUFBRSxPQUFPLEVBQUUsY0FBYyxFQUFFLE1BQU0sRUFBRSxXQUFXLEVBQUU7YUFDdEQsQ0FBQyxDQUFDO1lBQ0gsTUFBTSxjQUFjLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsV0FBVyxDQUFDLENBQUM7WUFFdkQsY0FBYyxDQUFDLHFCQUFxQixDQUFDLGVBQWUsRUFBRTtnQkFDcEQsU0FBUyxFQUFFLGVBQWU7YUFDM0IsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztBQUNMLENBQUMsQ0FBQyxDQUFDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCB7IFRlbXBsYXRlLCBNYXRjaCB9IGZyb20gJ2F3cy1jZGstbGliL2Fzc2VydGlvbnMnO1xuaW1wb3J0IHsgVnBjU3RhY2sgfSBmcm9tICcuLi9saWIvdnBjLXN0YWNrJztcblxuZGVzY3JpYmUoJ1ZwY1N0YWNrJywgKCkgPT4ge1xuICBsZXQgYXBwOiBjZGsuQXBwO1xuICBsZXQgc3RhY2s6IFZwY1N0YWNrO1xuICBsZXQgdGVtcGxhdGU6IFRlbXBsYXRlO1xuXG4gIGJlZm9yZUVhY2goKCkgPT4ge1xuICAgIGFwcCA9IG5ldyBjZGsuQXBwKCk7XG4gICAgc3RhY2sgPSBuZXcgVnBjU3RhY2soYXBwLCAnVGVzdFZwY1N0YWNrJywge1xuICAgICAgZW52OiB7IGFjY291bnQ6ICcxMjM0NTY3ODkwMTInLCByZWdpb246ICd1cy13ZXN0LTInIH0sXG4gICAgfSk7XG4gICAgdGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soc3RhY2spO1xuICB9KTtcblxuICBkZXNjcmliZSgnVlBDIENvbmZpZ3VyYXRpb24nLCAoKSA9PiB7XG4gICAgdGVzdCgnY3JlYXRlcyBWUEMgd2l0aCBjb3JyZWN0IENJRFInLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUEMnLCB7XG4gICAgICAgIENpZHJCbG9jazogJzEwLjAuMC4wLzE2JyxcbiAgICAgICAgRW5hYmxlRG5zSG9zdG5hbWVzOiB0cnVlLFxuICAgICAgICBFbmFibGVEbnNTdXBwb3J0OiB0cnVlLFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdjcmVhdGVzIHB1YmxpYyBhbmQgcHJpdmF0ZSBzdWJuZXRzIGluIDIgQVpzJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUucmVzb3VyY2VDb3VudElzKCdBV1M6OkVDMjo6U3VibmV0JywgNCk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdkb2VzIG5vdCBjcmVhdGUgTkFUIGdhdGV3YXlzIChjb3N0IG9wdGltaXphdGlvbiknLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5yZXNvdXJjZUNvdW50SXMoJ0FXUzo6RUMyOjpOYXRHYXRld2F5JywgMCk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdWUEMgRW5kcG9pbnRzJywgKCkgPT4ge1xuICAgIHRlc3QoJ2NyZWF0ZXMgZXhwZWN0ZWQgbnVtYmVyIG9mIFZQQyBlbmRwb2ludHMnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5yZXNvdXJjZUNvdW50SXMoJ0FXUzo6RUMyOjpWUENFbmRwb2ludCcsIDgpO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBpbnRlcmZhY2UgZW5kcG9pbnRzIHdpdGggcHJpdmF0ZSBETlMnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUENFbmRwb2ludCcsIHtcbiAgICAgICAgVnBjRW5kcG9pbnRUeXBlOiAnSW50ZXJmYWNlJyxcbiAgICAgICAgUHJpdmF0ZURuc0VuYWJsZWQ6IHRydWUsXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2NyZWF0ZXMgRUNSIERvY2tlciBpbnRlcmZhY2UgZW5kcG9pbnQnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUENFbmRwb2ludCcsIHtcbiAgICAgICAgU2VydmljZU5hbWU6ICdjb20uYW1hem9uYXdzLnVzLXdlc3QtMi5lY3IuZGtyJyxcbiAgICAgICAgVnBjRW5kcG9pbnRUeXBlOiAnSW50ZXJmYWNlJyxcbiAgICAgICAgUHJpdmF0ZURuc0VuYWJsZWQ6IHRydWUsXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2NyZWF0ZXMgRUNSIEFQSSBpbnRlcmZhY2UgZW5kcG9pbnQnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUENFbmRwb2ludCcsIHtcbiAgICAgICAgU2VydmljZU5hbWU6ICdjb20uYW1hem9uYXdzLnVzLXdlc3QtMi5lY3IuYXBpJyxcbiAgICAgICAgVnBjRW5kcG9pbnRUeXBlOiAnSW50ZXJmYWNlJyxcbiAgICAgICAgUHJpdmF0ZURuc0VuYWJsZWQ6IHRydWUsXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2NyZWF0ZXMgQ2xvdWRXYXRjaCBMb2dzIGludGVyZmFjZSBlbmRwb2ludCcsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlZQQ0VuZHBvaW50Jywge1xuICAgICAgICBTZXJ2aWNlTmFtZTogJ2NvbS5hbWF6b25hd3MudXMtd2VzdC0yLmxvZ3MnLFxuICAgICAgICBWcGNFbmRwb2ludFR5cGU6ICdJbnRlcmZhY2UnLFxuICAgICAgICBQcml2YXRlRG5zRW5hYmxlZDogdHJ1ZSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBTZWNyZXRzIE1hbmFnZXIgaW50ZXJmYWNlIGVuZHBvaW50JywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OkVDMjo6VlBDRW5kcG9pbnQnLCB7XG4gICAgICAgIFNlcnZpY2VOYW1lOiAnY29tLmFtYXpvbmF3cy51cy13ZXN0LTIuc2VjcmV0c21hbmFnZXInLFxuICAgICAgICBWcGNFbmRwb2ludFR5cGU6ICdJbnRlcmZhY2UnLFxuICAgICAgICBQcml2YXRlRG5zRW5hYmxlZDogdHJ1ZSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBCZWRyb2NrIFJ1bnRpbWUgaW50ZXJmYWNlIGVuZHBvaW50JywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OkVDMjo6VlBDRW5kcG9pbnQnLCB7XG4gICAgICAgIFNlcnZpY2VOYW1lOiAnY29tLmFtYXpvbmF3cy51cy13ZXN0LTIuYmVkcm9jay1ydW50aW1lJyxcbiAgICAgICAgVnBjRW5kcG9pbnRUeXBlOiAnSW50ZXJmYWNlJyxcbiAgICAgICAgUHJpdmF0ZURuc0VuYWJsZWQ6IHRydWUsXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2NyZWF0ZXMgQmVkcm9jayBBZ2VudENvcmUgaW50ZXJmYWNlIGVuZHBvaW50JywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OkVDMjo6VlBDRW5kcG9pbnQnLCB7XG4gICAgICAgIFNlcnZpY2VOYW1lOiAnY29tLmFtYXpvbmF3cy51cy13ZXN0LTIuYmVkcm9jay1hZ2VudGNvcmUnLFxuICAgICAgICBWcGNFbmRwb2ludFR5cGU6ICdJbnRlcmZhY2UnLFxuICAgICAgICBQcml2YXRlRG5zRW5hYmxlZDogdHJ1ZSxcbiAgICAgIH0pO1xuICAgIH0pO1xuICB9KTtcblxuICBkZXNjcmliZSgnU3RhY2sgT3V0cHV0cycsICgpID0+IHtcbiAgICB0ZXN0KCdleHBvcnRzIFZQQyBJRCcsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc091dHB1dCgnVnBjSWQnLCB7XG4gICAgICAgIEV4cG9ydDogeyBOYW1lOiAnR2xpdGNoVnBjSWQnIH0sXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2V4cG9ydHMgcHJpdmF0ZSBzdWJuZXQgSURzJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdQcml2YXRlU3VibmV0SWRzJywge1xuICAgICAgICBFeHBvcnQ6IHsgTmFtZTogJ0dsaXRjaFByaXZhdGVTdWJuZXRJZHMnIH0sXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2V4cG9ydHMgYXZhaWxhYmlsaXR5IHpvbmVzJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdBdmFpbGFiaWxpdHlab25lcycsIHtcbiAgICAgICAgRXhwb3J0OiB7IE5hbWU6ICdHbGl0Y2hBdmFpbGFiaWxpdHlab25lcycgfSxcbiAgICAgIH0pO1xuICAgIH0pO1xuICB9KTtcblxuICBkZXNjcmliZSgnQ3VzdG9tIENJRFInLCAoKSA9PiB7XG4gICAgdGVzdCgnYWNjZXB0cyBjdXN0b20gVlBDIENJRFInLCAoKSA9PiB7XG4gICAgICBjb25zdCBjdXN0b21BcHAgPSBuZXcgY2RrLkFwcCgpO1xuICAgICAgY29uc3QgY3VzdG9tU3RhY2sgPSBuZXcgVnBjU3RhY2soY3VzdG9tQXBwLCAnQ3VzdG9tVnBjU3RhY2snLCB7XG4gICAgICAgIHZwY0NpZHI6ICcxNzIuMTYuMC4wLzE2JyxcbiAgICAgICAgZW52OiB7IGFjY291bnQ6ICcxMjM0NTY3ODkwMTInLCByZWdpb246ICd1cy13ZXN0LTInIH0sXG4gICAgICB9KTtcbiAgICAgIGNvbnN0IGN1c3RvbVRlbXBsYXRlID0gVGVtcGxhdGUuZnJvbVN0YWNrKGN1c3RvbVN0YWNrKTtcblxuICAgICAgY3VzdG9tVGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OkVDMjo6VlBDJywge1xuICAgICAgICBDaWRyQmxvY2s6ICcxNzIuMTYuMC4wLzE2JyxcbiAgICAgIH0pO1xuICAgIH0pO1xuICB9KTtcbn0pO1xuIl19