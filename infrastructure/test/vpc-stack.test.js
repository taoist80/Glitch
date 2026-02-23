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
describe('VpcStack', () => {
    let app;
    let stack;
    let template;
    beforeEach(() => {
        app = new cdk.App();
        stack = new stack_1.VpcStack(app, 'TestVpcStack', {
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
            const customStack = new stack_1.VpcStack(customApp, 'CustomVpcStack', {
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidnBjLXN0YWNrLnRlc3QuanMiLCJzb3VyY2VSb290IjoiIiwic291cmNlcyI6WyJ2cGMtc3RhY2sudGVzdC50cyJdLCJuYW1lcyI6W10sIm1hcHBpbmdzIjoiOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx1REFBeUQ7QUFDekQsd0NBQXdDO0FBRXhDLFFBQVEsQ0FBQyxVQUFVLEVBQUUsR0FBRyxFQUFFO0lBQ3hCLElBQUksR0FBWSxDQUFDO0lBQ2pCLElBQUksS0FBZSxDQUFDO0lBQ3BCLElBQUksUUFBa0IsQ0FBQztJQUV2QixVQUFVLENBQUMsR0FBRyxFQUFFO1FBQ2QsR0FBRyxHQUFHLElBQUksR0FBRyxDQUFDLEdBQUcsRUFBRSxDQUFDO1FBQ3BCLEtBQUssR0FBRyxJQUFJLGdCQUFRLENBQUMsR0FBRyxFQUFFLGNBQWMsRUFBRTtZQUN4QyxHQUFHLEVBQUUsRUFBRSxPQUFPLEVBQUUsY0FBYyxFQUFFLE1BQU0sRUFBRSxXQUFXLEVBQUU7U0FDdEQsQ0FBQyxDQUFDO1FBQ0gsUUFBUSxHQUFHLHFCQUFRLENBQUMsU0FBUyxDQUFDLEtBQUssQ0FBQyxDQUFDO0lBQ3ZDLENBQUMsQ0FBQyxDQUFDO0lBRUgsUUFBUSxDQUFDLG1CQUFtQixFQUFFLEdBQUcsRUFBRTtRQUNqQyxJQUFJLENBQUMsK0JBQStCLEVBQUUsR0FBRyxFQUFFO1lBQ3pDLFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyxlQUFlLEVBQUU7Z0JBQzlDLFNBQVMsRUFBRSxhQUFhO2dCQUN4QixrQkFBa0IsRUFBRSxJQUFJO2dCQUN4QixnQkFBZ0IsRUFBRSxJQUFJO2FBQ3ZCLENBQUMsQ0FBQztRQUNMLENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLDZDQUE2QyxFQUFFLEdBQUcsRUFBRTtZQUN2RCxRQUFRLENBQUMsZUFBZSxDQUFDLGtCQUFrQixFQUFFLENBQUMsQ0FBQyxDQUFDO1FBQ2xELENBQUMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLGtEQUFrRCxFQUFFLEdBQUcsRUFBRTtZQUM1RCxRQUFRLENBQUMsZUFBZSxDQUFDLHNCQUFzQixFQUFFLENBQUMsQ0FBQyxDQUFDO1FBQ3RELENBQUMsQ0FBQyxDQUFDO0lBQ0wsQ0FBQyxDQUFDLENBQUM7SUFFSCxRQUFRLENBQUMsZUFBZSxFQUFFLEdBQUcsRUFBRTtRQUM3QixJQUFJLENBQUMsMENBQTBDLEVBQUUsR0FBRyxFQUFFO1lBQ3BELFFBQVEsQ0FBQyxlQUFlLENBQUMsdUJBQXVCLEVBQUUsQ0FBQyxDQUFDLENBQUM7UUFDdkQsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsOENBQThDLEVBQUUsR0FBRyxFQUFFO1lBQ3hELFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyx1QkFBdUIsRUFBRTtnQkFDdEQsZUFBZSxFQUFFLFdBQVc7Z0JBQzVCLGlCQUFpQixFQUFFLElBQUk7YUFDeEIsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsdUNBQXVDLEVBQUUsR0FBRyxFQUFFO1lBQ2pELFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyx1QkFBdUIsRUFBRTtnQkFDdEQsV0FBVyxFQUFFLGlDQUFpQztnQkFDOUMsZUFBZSxFQUFFLFdBQVc7Z0JBQzVCLGlCQUFpQixFQUFFLElBQUk7YUFDeEIsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsb0NBQW9DLEVBQUUsR0FBRyxFQUFFO1lBQzlDLFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyx1QkFBdUIsRUFBRTtnQkFDdEQsV0FBVyxFQUFFLGlDQUFpQztnQkFDOUMsZUFBZSxFQUFFLFdBQVc7Z0JBQzVCLGlCQUFpQixFQUFFLElBQUk7YUFDeEIsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsNENBQTRDLEVBQUUsR0FBRyxFQUFFO1lBQ3RELFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyx1QkFBdUIsRUFBRTtnQkFDdEQsV0FBVyxFQUFFLDhCQUE4QjtnQkFDM0MsZUFBZSxFQUFFLFdBQVc7Z0JBQzVCLGlCQUFpQixFQUFFLElBQUk7YUFDeEIsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsNENBQTRDLEVBQUUsR0FBRyxFQUFFO1lBQ3RELFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyx1QkFBdUIsRUFBRTtnQkFDdEQsV0FBVyxFQUFFLHdDQUF3QztnQkFDckQsZUFBZSxFQUFFLFdBQVc7Z0JBQzVCLGlCQUFpQixFQUFFLElBQUk7YUFDeEIsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsNENBQTRDLEVBQUUsR0FBRyxFQUFFO1lBQ3RELFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyx1QkFBdUIsRUFBRTtnQkFDdEQsV0FBVyxFQUFFLHlDQUF5QztnQkFDdEQsZUFBZSxFQUFFLFdBQVc7Z0JBQzVCLGlCQUFpQixFQUFFLElBQUk7YUFDeEIsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsOENBQThDLEVBQUUsR0FBRyxFQUFFO1lBQ3hELFFBQVEsQ0FBQyxxQkFBcUIsQ0FBQyx1QkFBdUIsRUFBRTtnQkFDdEQsV0FBVyxFQUFFLDJDQUEyQztnQkFDeEQsZUFBZSxFQUFFLFdBQVc7Z0JBQzVCLGlCQUFpQixFQUFFLElBQUk7YUFDeEIsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztJQUVILFFBQVEsQ0FBQyxlQUFlLEVBQUUsR0FBRyxFQUFFO1FBQzdCLElBQUksQ0FBQyxnQkFBZ0IsRUFBRSxHQUFHLEVBQUU7WUFDMUIsUUFBUSxDQUFDLFNBQVMsQ0FBQyxPQUFPLEVBQUU7Z0JBQzFCLE1BQU0sRUFBRSxFQUFFLElBQUksRUFBRSxhQUFhLEVBQUU7YUFDaEMsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsNEJBQTRCLEVBQUUsR0FBRyxFQUFFO1lBQ3RDLFFBQVEsQ0FBQyxTQUFTLENBQUMsa0JBQWtCLEVBQUU7Z0JBQ3JDLE1BQU0sRUFBRSxFQUFFLElBQUksRUFBRSx3QkFBd0IsRUFBRTthQUMzQyxDQUFDLENBQUM7UUFDTCxDQUFDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyw0QkFBNEIsRUFBRSxHQUFHLEVBQUU7WUFDdEMsUUFBUSxDQUFDLFNBQVMsQ0FBQyxtQkFBbUIsRUFBRTtnQkFDdEMsTUFBTSxFQUFFLEVBQUUsSUFBSSxFQUFFLHlCQUF5QixFQUFFO2FBQzVDLENBQUMsQ0FBQztRQUNMLENBQUMsQ0FBQyxDQUFDO0lBQ0wsQ0FBQyxDQUFDLENBQUM7SUFFSCxRQUFRLENBQUMsYUFBYSxFQUFFLEdBQUcsRUFBRTtRQUMzQixJQUFJLENBQUMseUJBQXlCLEVBQUUsR0FBRyxFQUFFO1lBQ25DLE1BQU0sU0FBUyxHQUFHLElBQUksR0FBRyxDQUFDLEdBQUcsRUFBRSxDQUFDO1lBQ2hDLE1BQU0sV0FBVyxHQUFHLElBQUksZ0JBQVEsQ0FBQyxTQUFTLEVBQUUsZ0JBQWdCLEVBQUU7Z0JBQzVELE9BQU8sRUFBRSxlQUFlO2dCQUN4QixHQUFHLEVBQUUsRUFBRSxPQUFPLEVBQUUsY0FBYyxFQUFFLE1BQU0sRUFBRSxXQUFXLEVBQUU7YUFDdEQsQ0FBQyxDQUFDO1lBQ0gsTUFBTSxjQUFjLEdBQUcscUJBQVEsQ0FBQyxTQUFTLENBQUMsV0FBVyxDQUFDLENBQUM7WUFFdkQsY0FBYyxDQUFDLHFCQUFxQixDQUFDLGVBQWUsRUFBRTtnQkFDcEQsU0FBUyxFQUFFLGVBQWU7YUFDM0IsQ0FBQyxDQUFDO1FBQ0wsQ0FBQyxDQUFDLENBQUM7SUFDTCxDQUFDLENBQUMsQ0FBQztBQUNMLENBQUMsQ0FBQyxDQUFDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCB7IFRlbXBsYXRlLCBNYXRjaCB9IGZyb20gJ2F3cy1jZGstbGliL2Fzc2VydGlvbnMnO1xuaW1wb3J0IHsgVnBjU3RhY2sgfSBmcm9tICcuLi9saWIvc3RhY2snO1xuXG5kZXNjcmliZSgnVnBjU3RhY2snLCAoKSA9PiB7XG4gIGxldCBhcHA6IGNkay5BcHA7XG4gIGxldCBzdGFjazogVnBjU3RhY2s7XG4gIGxldCB0ZW1wbGF0ZTogVGVtcGxhdGU7XG5cbiAgYmVmb3JlRWFjaCgoKSA9PiB7XG4gICAgYXBwID0gbmV3IGNkay5BcHAoKTtcbiAgICBzdGFjayA9IG5ldyBWcGNTdGFjayhhcHAsICdUZXN0VnBjU3RhY2snLCB7XG4gICAgICBlbnY6IHsgYWNjb3VudDogJzEyMzQ1Njc4OTAxMicsIHJlZ2lvbjogJ3VzLXdlc3QtMicgfSxcbiAgICB9KTtcbiAgICB0ZW1wbGF0ZSA9IFRlbXBsYXRlLmZyb21TdGFjayhzdGFjayk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdWUEMgQ29uZmlndXJhdGlvbicsICgpID0+IHtcbiAgICB0ZXN0KCdjcmVhdGVzIFZQQyB3aXRoIGNvcnJlY3QgQ0lEUicsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlZQQycsIHtcbiAgICAgICAgQ2lkckJsb2NrOiAnMTAuMC4wLjAvMTYnLFxuICAgICAgICBFbmFibGVEbnNIb3N0bmFtZXM6IHRydWUsXG4gICAgICAgIEVuYWJsZURuc1N1cHBvcnQ6IHRydWUsXG4gICAgICB9KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2NyZWF0ZXMgcHVibGljIGFuZCBwcml2YXRlIHN1Ym5ldHMgaW4gMiBBWnMnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5yZXNvdXJjZUNvdW50SXMoJ0FXUzo6RUMyOjpTdWJuZXQnLCA0KTtcbiAgICB9KTtcblxuICAgIHRlc3QoJ2RvZXMgbm90IGNyZWF0ZSBOQVQgZ2F0ZXdheXMgKGNvc3Qgb3B0aW1pemF0aW9uKScsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLnJlc291cmNlQ291bnRJcygnQVdTOjpFQzI6Ok5hdEdhdGV3YXknLCAwKTtcbiAgICB9KTtcbiAgfSk7XG5cbiAgZGVzY3JpYmUoJ1ZQQyBFbmRwb2ludHMnLCAoKSA9PiB7XG4gICAgdGVzdCgnY3JlYXRlcyBleHBlY3RlZCBudW1iZXIgb2YgVlBDIGVuZHBvaW50cycsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLnJlc291cmNlQ291bnRJcygnQVdTOjpFQzI6OlZQQ0VuZHBvaW50JywgOCk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdjcmVhdGVzIGludGVyZmFjZSBlbmRwb2ludHMgd2l0aCBwcml2YXRlIEROUycsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlZQQ0VuZHBvaW50Jywge1xuICAgICAgICBWcGNFbmRwb2ludFR5cGU6ICdJbnRlcmZhY2UnLFxuICAgICAgICBQcml2YXRlRG5zRW5hYmxlZDogdHJ1ZSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBFQ1IgRG9ja2VyIGludGVyZmFjZSBlbmRwb2ludCcsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlZQQ0VuZHBvaW50Jywge1xuICAgICAgICBTZXJ2aWNlTmFtZTogJ2NvbS5hbWF6b25hd3MudXMtd2VzdC0yLmVjci5ka3InLFxuICAgICAgICBWcGNFbmRwb2ludFR5cGU6ICdJbnRlcmZhY2UnLFxuICAgICAgICBQcml2YXRlRG5zRW5hYmxlZDogdHJ1ZSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBFQ1IgQVBJIGludGVyZmFjZSBlbmRwb2ludCcsICgpID0+IHtcbiAgICAgIHRlbXBsYXRlLmhhc1Jlc291cmNlUHJvcGVydGllcygnQVdTOjpFQzI6OlZQQ0VuZHBvaW50Jywge1xuICAgICAgICBTZXJ2aWNlTmFtZTogJ2NvbS5hbWF6b25hd3MudXMtd2VzdC0yLmVjci5hcGknLFxuICAgICAgICBWcGNFbmRwb2ludFR5cGU6ICdJbnRlcmZhY2UnLFxuICAgICAgICBQcml2YXRlRG5zRW5hYmxlZDogdHJ1ZSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBDbG91ZFdhdGNoIExvZ3MgaW50ZXJmYWNlIGVuZHBvaW50JywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzUmVzb3VyY2VQcm9wZXJ0aWVzKCdBV1M6OkVDMjo6VlBDRW5kcG9pbnQnLCB7XG4gICAgICAgIFNlcnZpY2VOYW1lOiAnY29tLmFtYXpvbmF3cy51cy13ZXN0LTIubG9ncycsXG4gICAgICAgIFZwY0VuZHBvaW50VHlwZTogJ0ludGVyZmFjZScsXG4gICAgICAgIFByaXZhdGVEbnNFbmFibGVkOiB0cnVlLFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdjcmVhdGVzIFNlY3JldHMgTWFuYWdlciBpbnRlcmZhY2UgZW5kcG9pbnQnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUENFbmRwb2ludCcsIHtcbiAgICAgICAgU2VydmljZU5hbWU6ICdjb20uYW1hem9uYXdzLnVzLXdlc3QtMi5zZWNyZXRzbWFuYWdlcicsXG4gICAgICAgIFZwY0VuZHBvaW50VHlwZTogJ0ludGVyZmFjZScsXG4gICAgICAgIFByaXZhdGVEbnNFbmFibGVkOiB0cnVlLFxuICAgICAgfSk7XG4gICAgfSk7XG5cbiAgICB0ZXN0KCdjcmVhdGVzIEJlZHJvY2sgUnVudGltZSBpbnRlcmZhY2UgZW5kcG9pbnQnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUENFbmRwb2ludCcsIHtcbiAgICAgICAgU2VydmljZU5hbWU6ICdjb20uYW1hem9uYXdzLnVzLXdlc3QtMi5iZWRyb2NrLXJ1bnRpbWUnLFxuICAgICAgICBWcGNFbmRwb2ludFR5cGU6ICdJbnRlcmZhY2UnLFxuICAgICAgICBQcml2YXRlRG5zRW5hYmxlZDogdHJ1ZSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnY3JlYXRlcyBCZWRyb2NrIEFnZW50Q29yZSBpbnRlcmZhY2UgZW5kcG9pbnQnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUENFbmRwb2ludCcsIHtcbiAgICAgICAgU2VydmljZU5hbWU6ICdjb20uYW1hem9uYXdzLnVzLXdlc3QtMi5iZWRyb2NrLWFnZW50Y29yZScsXG4gICAgICAgIFZwY0VuZHBvaW50VHlwZTogJ0ludGVyZmFjZScsXG4gICAgICAgIFByaXZhdGVEbnNFbmFibGVkOiB0cnVlLFxuICAgICAgfSk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdTdGFjayBPdXRwdXRzJywgKCkgPT4ge1xuICAgIHRlc3QoJ2V4cG9ydHMgVlBDIElEJywgKCkgPT4ge1xuICAgICAgdGVtcGxhdGUuaGFzT3V0cHV0KCdWcGNJZCcsIHtcbiAgICAgICAgRXhwb3J0OiB7IE5hbWU6ICdHbGl0Y2hWcGNJZCcgfSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnZXhwb3J0cyBwcml2YXRlIHN1Ym5ldCBJRHMnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNPdXRwdXQoJ1ByaXZhdGVTdWJuZXRJZHMnLCB7XG4gICAgICAgIEV4cG9ydDogeyBOYW1lOiAnR2xpdGNoUHJpdmF0ZVN1Ym5ldElkcycgfSxcbiAgICAgIH0pO1xuICAgIH0pO1xuXG4gICAgdGVzdCgnZXhwb3J0cyBhdmFpbGFiaWxpdHkgem9uZXMnLCAoKSA9PiB7XG4gICAgICB0ZW1wbGF0ZS5oYXNPdXRwdXQoJ0F2YWlsYWJpbGl0eVpvbmVzJywge1xuICAgICAgICBFeHBvcnQ6IHsgTmFtZTogJ0dsaXRjaEF2YWlsYWJpbGl0eVpvbmVzJyB9LFxuICAgICAgfSk7XG4gICAgfSk7XG4gIH0pO1xuXG4gIGRlc2NyaWJlKCdDdXN0b20gQ0lEUicsICgpID0+IHtcbiAgICB0ZXN0KCdhY2NlcHRzIGN1c3RvbSBWUEMgQ0lEUicsICgpID0+IHtcbiAgICAgIGNvbnN0IGN1c3RvbUFwcCA9IG5ldyBjZGsuQXBwKCk7XG4gICAgICBjb25zdCBjdXN0b21TdGFjayA9IG5ldyBWcGNTdGFjayhjdXN0b21BcHAsICdDdXN0b21WcGNTdGFjaycsIHtcbiAgICAgICAgdnBjQ2lkcjogJzE3Mi4xNi4wLjAvMTYnLFxuICAgICAgICBlbnY6IHsgYWNjb3VudDogJzEyMzQ1Njc4OTAxMicsIHJlZ2lvbjogJ3VzLXdlc3QtMicgfSxcbiAgICAgIH0pO1xuICAgICAgY29uc3QgY3VzdG9tVGVtcGxhdGUgPSBUZW1wbGF0ZS5mcm9tU3RhY2soY3VzdG9tU3RhY2spO1xuXG4gICAgICBjdXN0b21UZW1wbGF0ZS5oYXNSZXNvdXJjZVByb3BlcnRpZXMoJ0FXUzo6RUMyOjpWUEMnLCB7XG4gICAgICAgIENpZHJCbG9jazogJzE3Mi4xNi4wLjAvMTYnLFxuICAgICAgfSk7XG4gICAgfSk7XG4gIH0pO1xufSk7XG4iXX0=