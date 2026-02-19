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
exports.SecretsStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const secretsmanager = __importStar(require("aws-cdk-lib/aws-secretsmanager"));
class SecretsStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        this.tailscaleAuthKeySecret = new secretsmanager.Secret(this, 'TailscaleAuthKey', {
            secretName: 'glitch/tailscale-auth-key',
            description: 'Ephemeral Tailscale authentication key for EC2 connector',
            removalPolicy: cdk.RemovalPolicy.RETAIN,
        });
        this.apiKeysSecret = new secretsmanager.Secret(this, 'ApiKeys', {
            secretName: 'glitch/api-keys',
            description: 'API keys for MCP integrations and external services',
            removalPolicy: cdk.RemovalPolicy.RETAIN,
            secretObjectValue: {
                placeholder: cdk.SecretValue.unsafePlainText('{}'),
            },
        });
        new cdk.CfnOutput(this, 'TailscaleAuthKeySecretArn', {
            value: this.tailscaleAuthKeySecret.secretArn,
            description: 'ARN of Tailscale auth key secret',
            exportName: 'GlitchTailscaleAuthKeyArn',
        });
        new cdk.CfnOutput(this, 'ApiKeysSecretArn', {
            value: this.apiKeysSecret.secretArn,
            description: 'ARN of API keys secret',
            exportName: 'GlitchApiKeysArn',
        });
    }
}
exports.SecretsStack = SecretsStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoic2VjcmV0cy1zdGFjay5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbInNlY3JldHMtc3RhY2sudHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O0FBQUEsaURBQW1DO0FBQ25DLCtFQUFpRTtBQUdqRSxNQUFhLFlBQWEsU0FBUSxHQUFHLENBQUMsS0FBSztJQUl6QyxZQUFZLEtBQWdCLEVBQUUsRUFBVSxFQUFFLEtBQXNCO1FBQzlELEtBQUssQ0FBQyxLQUFLLEVBQUUsRUFBRSxFQUFFLEtBQUssQ0FBQyxDQUFDO1FBRXhCLElBQUksQ0FBQyxzQkFBc0IsR0FBRyxJQUFJLGNBQWMsQ0FBQyxNQUFNLENBQUMsSUFBSSxFQUFFLGtCQUFrQixFQUFFO1lBQ2hGLFVBQVUsRUFBRSwyQkFBMkI7WUFDdkMsV0FBVyxFQUFFLDBEQUEwRDtZQUN2RSxhQUFhLEVBQUUsR0FBRyxDQUFDLGFBQWEsQ0FBQyxNQUFNO1NBQ3hDLENBQUMsQ0FBQztRQUVILElBQUksQ0FBQyxhQUFhLEdBQUcsSUFBSSxjQUFjLENBQUMsTUFBTSxDQUFDLElBQUksRUFBRSxTQUFTLEVBQUU7WUFDOUQsVUFBVSxFQUFFLGlCQUFpQjtZQUM3QixXQUFXLEVBQUUscURBQXFEO1lBQ2xFLGFBQWEsRUFBRSxHQUFHLENBQUMsYUFBYSxDQUFDLE1BQU07WUFDdkMsaUJBQWlCLEVBQUU7Z0JBQ2pCLFdBQVcsRUFBRSxHQUFHLENBQUMsV0FBVyxDQUFDLGVBQWUsQ0FBQyxJQUFJLENBQUM7YUFDbkQ7U0FDRixDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLDJCQUEyQixFQUFFO1lBQ25ELEtBQUssRUFBRSxJQUFJLENBQUMsc0JBQXNCLENBQUMsU0FBUztZQUM1QyxXQUFXLEVBQUUsa0NBQWtDO1lBQy9DLFVBQVUsRUFBRSwyQkFBMkI7U0FDeEMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxrQkFBa0IsRUFBRTtZQUMxQyxLQUFLLEVBQUUsSUFBSSxDQUFDLGFBQWEsQ0FBQyxTQUFTO1lBQ25DLFdBQVcsRUFBRSx3QkFBd0I7WUFDckMsVUFBVSxFQUFFLGtCQUFrQjtTQUMvQixDQUFDLENBQUM7SUFDTCxDQUFDO0NBQ0Y7QUFsQ0Qsb0NBa0NDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIHNlY3JldHNtYW5hZ2VyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1zZWNyZXRzbWFuYWdlcic7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcblxuZXhwb3J0IGNsYXNzIFNlY3JldHNTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuICBwdWJsaWMgcmVhZG9ubHkgYXBpS2V5c1NlY3JldDogc2VjcmV0c21hbmFnZXIuSVNlY3JldDtcblxuICBjb25zdHJ1Y3RvcihzY29wZTogQ29uc3RydWN0LCBpZDogc3RyaW5nLCBwcm9wcz86IGNkay5TdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICB0aGlzLnRhaWxzY2FsZUF1dGhLZXlTZWNyZXQgPSBuZXcgc2VjcmV0c21hbmFnZXIuU2VjcmV0KHRoaXMsICdUYWlsc2NhbGVBdXRoS2V5Jywge1xuICAgICAgc2VjcmV0TmFtZTogJ2dsaXRjaC90YWlsc2NhbGUtYXV0aC1rZXknLFxuICAgICAgZGVzY3JpcHRpb246ICdFcGhlbWVyYWwgVGFpbHNjYWxlIGF1dGhlbnRpY2F0aW9uIGtleSBmb3IgRUMyIGNvbm5lY3RvcicsXG4gICAgICByZW1vdmFsUG9saWN5OiBjZGsuUmVtb3ZhbFBvbGljeS5SRVRBSU4sXG4gICAgfSk7XG5cbiAgICB0aGlzLmFwaUtleXNTZWNyZXQgPSBuZXcgc2VjcmV0c21hbmFnZXIuU2VjcmV0KHRoaXMsICdBcGlLZXlzJywge1xuICAgICAgc2VjcmV0TmFtZTogJ2dsaXRjaC9hcGkta2V5cycsXG4gICAgICBkZXNjcmlwdGlvbjogJ0FQSSBrZXlzIGZvciBNQ1AgaW50ZWdyYXRpb25zIGFuZCBleHRlcm5hbCBzZXJ2aWNlcycsXG4gICAgICByZW1vdmFsUG9saWN5OiBjZGsuUmVtb3ZhbFBvbGljeS5SRVRBSU4sXG4gICAgICBzZWNyZXRPYmplY3RWYWx1ZToge1xuICAgICAgICBwbGFjZWhvbGRlcjogY2RrLlNlY3JldFZhbHVlLnVuc2FmZVBsYWluVGV4dCgne30nKSxcbiAgICAgIH0sXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnVGFpbHNjYWxlQXV0aEtleVNlY3JldEFybicsIHtcbiAgICAgIHZhbHVlOiB0aGlzLnRhaWxzY2FsZUF1dGhLZXlTZWNyZXQuc2VjcmV0QXJuLFxuICAgICAgZGVzY3JpcHRpb246ICdBUk4gb2YgVGFpbHNjYWxlIGF1dGgga2V5IHNlY3JldCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoVGFpbHNjYWxlQXV0aEtleUFybicsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnQXBpS2V5c1NlY3JldEFybicsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmFwaUtleXNTZWNyZXQuc2VjcmV0QXJuLFxuICAgICAgZGVzY3JpcHRpb246ICdBUk4gb2YgQVBJIGtleXMgc2VjcmV0JyxcbiAgICAgIGV4cG9ydE5hbWU6ICdHbGl0Y2hBcGlLZXlzQXJuJyxcbiAgICB9KTtcbiAgfVxufVxuIl19