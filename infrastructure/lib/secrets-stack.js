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
const iam = __importStar(require("aws-cdk-lib/aws-iam"));
const secretsmanager = __importStar(require("aws-cdk-lib/aws-secretsmanager"));
class SecretsStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        this.tailscaleAuthKeySecret = secretsmanager.Secret.fromSecretNameV2(this, 'TailscaleAuthKey', 'glitch/tailscale-auth-key');
        this.apiKeysSecret = secretsmanager.Secret.fromSecretNameV2(this, 'ApiKeys', 'glitch/api-keys');
        this.telegramBotTokenSecret = secretsmanager.Secret.fromSecretNameV2(this, 'TelegramBotToken', 'glitch/telegram-bot-token');
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
        new cdk.CfnOutput(this, 'TelegramBotTokenSecretArn', {
            value: this.telegramBotTokenSecret.secretArn,
            description: 'ARN of Telegram bot token secret',
            exportName: 'GlitchTelegramBotTokenArn',
        });
        // Grant default AgentCore execution role read access to Telegram token (no env vars needed)
        const defaultRoleArn = props?.defaultExecutionRoleArn;
        if (defaultRoleArn) {
            const defaultRole = iam.Role.fromRoleArn(this, 'DefaultAgentCoreRuntimeRole', defaultRoleArn);
            // Use wildcard ARN so we match the secret's full ARN (AWS appends 6-char suffix to secret names)
            const telegramSecretArn = `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/telegram-bot-token*`;
            new iam.ManagedPolicy(this, 'GlitchDefaultRoleTelegramSecretPolicy', {
                roles: [defaultRole],
                document: new iam.PolicyDocument({
                    statements: [
                        new iam.PolicyStatement({
                            sid: 'TelegramBotTokenSecret',
                            effect: iam.Effect.ALLOW,
                            actions: ['secretsmanager:GetSecretValue'],
                            resources: [telegramSecretArn],
                        }),
                    ],
                }),
            });
        }
    }
}
exports.SecretsStack = SecretsStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoic2VjcmV0cy1zdGFjay5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbInNlY3JldHMtc3RhY2sudHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O0FBQUEsaURBQW1DO0FBQ25DLHlEQUEyQztBQUMzQywrRUFBaUU7QUFZakUsTUFBYSxZQUFhLFNBQVEsR0FBRyxDQUFDLEtBQUs7SUFLekMsWUFBWSxLQUFnQixFQUFFLEVBQVUsRUFBRSxLQUF5QjtRQUNqRSxLQUFLLENBQUMsS0FBSyxFQUFFLEVBQUUsRUFBRSxLQUFLLENBQUMsQ0FBQztRQUV4QixJQUFJLENBQUMsc0JBQXNCLEdBQUcsY0FBYyxDQUFDLE1BQU0sQ0FBQyxnQkFBZ0IsQ0FDbEUsSUFBSSxFQUNKLGtCQUFrQixFQUNsQiwyQkFBMkIsQ0FDNUIsQ0FBQztRQUVGLElBQUksQ0FBQyxhQUFhLEdBQUcsY0FBYyxDQUFDLE1BQU0sQ0FBQyxnQkFBZ0IsQ0FDekQsSUFBSSxFQUNKLFNBQVMsRUFDVCxpQkFBaUIsQ0FDbEIsQ0FBQztRQUVGLElBQUksQ0FBQyxzQkFBc0IsR0FBRyxjQUFjLENBQUMsTUFBTSxDQUFDLGdCQUFnQixDQUNsRSxJQUFJLEVBQ0osa0JBQWtCLEVBQ2xCLDJCQUEyQixDQUM1QixDQUFDO1FBRUYsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSwyQkFBMkIsRUFBRTtZQUNuRCxLQUFLLEVBQUUsSUFBSSxDQUFDLHNCQUFzQixDQUFDLFNBQVM7WUFDNUMsV0FBVyxFQUFFLGtDQUFrQztZQUMvQyxVQUFVLEVBQUUsMkJBQTJCO1NBQ3hDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsa0JBQWtCLEVBQUU7WUFDMUMsS0FBSyxFQUFFLElBQUksQ0FBQyxhQUFhLENBQUMsU0FBUztZQUNuQyxXQUFXLEVBQUUsd0JBQXdCO1lBQ3JDLFVBQVUsRUFBRSxrQkFBa0I7U0FDL0IsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSwyQkFBMkIsRUFBRTtZQUNuRCxLQUFLLEVBQUUsSUFBSSxDQUFDLHNCQUFzQixDQUFDLFNBQVM7WUFDNUMsV0FBVyxFQUFFLGtDQUFrQztZQUMvQyxVQUFVLEVBQUUsMkJBQTJCO1NBQ3hDLENBQUMsQ0FBQztRQUVILDRGQUE0RjtRQUM1RixNQUFNLGNBQWMsR0FBRyxLQUFLLEVBQUUsdUJBQXVCLENBQUM7UUFDdEQsSUFBSSxjQUFjLEVBQUUsQ0FBQztZQUNuQixNQUFNLFdBQVcsR0FBRyxHQUFHLENBQUMsSUFBSSxDQUFDLFdBQVcsQ0FDdEMsSUFBSSxFQUNKLDZCQUE2QixFQUM3QixjQUFjLENBQ2YsQ0FBQztZQUNGLGlHQUFpRztZQUNqRyxNQUFNLGlCQUFpQixHQUFHLDBCQUEwQixJQUFJLENBQUMsTUFBTSxJQUFJLElBQUksQ0FBQyxPQUFPLG9DQUFvQyxDQUFDO1lBQ3BILElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsdUNBQXVDLEVBQUU7Z0JBQ25FLEtBQUssRUFBRSxDQUFDLFdBQVcsQ0FBQztnQkFDcEIsUUFBUSxFQUFFLElBQUksR0FBRyxDQUFDLGNBQWMsQ0FBQztvQkFDL0IsVUFBVSxFQUFFO3dCQUNWLElBQUksR0FBRyxDQUFDLGVBQWUsQ0FBQzs0QkFDdEIsR0FBRyxFQUFFLHdCQUF3Qjs0QkFDN0IsTUFBTSxFQUFFLEdBQUcsQ0FBQyxNQUFNLENBQUMsS0FBSzs0QkFDeEIsT0FBTyxFQUFFLENBQUMsK0JBQStCLENBQUM7NEJBQzFDLFNBQVMsRUFBRSxDQUFDLGlCQUFpQixDQUFDO3lCQUMvQixDQUFDO3FCQUNIO2lCQUNGLENBQUM7YUFDSCxDQUFDLENBQUM7UUFDTCxDQUFDO0lBQ0gsQ0FBQztDQUNGO0FBckVELG9DQXFFQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgKiBhcyBpYW0gZnJvbSAnYXdzLWNkay1saWIvYXdzLWlhbSc7XG5pbXBvcnQgKiBhcyBzZWNyZXRzbWFuYWdlciBmcm9tICdhd3MtY2RrLWxpYi9hd3Mtc2VjcmV0c21hbmFnZXInO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5cbmV4cG9ydCBpbnRlcmZhY2UgU2VjcmV0c1N0YWNrUHJvcHMgZXh0ZW5kcyBjZGsuU3RhY2tQcm9wcyB7XG4gIC8qKlxuICAgKiBBUk4gb2YgdGhlIGRlZmF1bHQgQWdlbnRDb3JlIFNESyBydW50aW1lIHJvbGUgKHVzZWQgYXQgcnVudGltZSkuXG4gICAqIFdoZW4gc2V0LCB0aGlzIHJvbGUgaXMgZ3JhbnRlZCByZWFkIGFjY2VzcyB0byB0aGUgVGVsZWdyYW0gYm90IHRva2VuIHNlY3JldFxuICAgKiBzbyB0aGUgYWdlbnQgY2FuIHJldHJpZXZlIHRoZSB0b2tlbiB3aXRob3V0IGVudiB2YXJzLlxuICAgKi9cbiAgcmVhZG9ubHkgZGVmYXVsdEV4ZWN1dGlvblJvbGVBcm4/OiBzdHJpbmc7XG59XG5cbmV4cG9ydCBjbGFzcyBTZWNyZXRzU3RhY2sgZXh0ZW5kcyBjZGsuU3RhY2sge1xuICBwdWJsaWMgcmVhZG9ubHkgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogc2VjcmV0c21hbmFnZXIuSVNlY3JldDtcbiAgcHVibGljIHJlYWRvbmx5IGFwaUtleXNTZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHB1YmxpYyByZWFkb25seSB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzPzogU2VjcmV0c1N0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIHRoaXMudGFpbHNjYWxlQXV0aEtleVNlY3JldCA9IHNlY3JldHNtYW5hZ2VyLlNlY3JldC5mcm9tU2VjcmV0TmFtZVYyKFxuICAgICAgdGhpcyxcbiAgICAgICdUYWlsc2NhbGVBdXRoS2V5JyxcbiAgICAgICdnbGl0Y2gvdGFpbHNjYWxlLWF1dGgta2V5J1xuICAgICk7XG5cbiAgICB0aGlzLmFwaUtleXNTZWNyZXQgPSBzZWNyZXRzbWFuYWdlci5TZWNyZXQuZnJvbVNlY3JldE5hbWVWMihcbiAgICAgIHRoaXMsXG4gICAgICAnQXBpS2V5cycsXG4gICAgICAnZ2xpdGNoL2FwaS1rZXlzJ1xuICAgICk7XG5cbiAgICB0aGlzLnRlbGVncmFtQm90VG9rZW5TZWNyZXQgPSBzZWNyZXRzbWFuYWdlci5TZWNyZXQuZnJvbVNlY3JldE5hbWVWMihcbiAgICAgIHRoaXMsXG4gICAgICAnVGVsZWdyYW1Cb3RUb2tlbicsXG4gICAgICAnZ2xpdGNoL3RlbGVncmFtLWJvdC10b2tlbidcbiAgICApO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1RhaWxzY2FsZUF1dGhLZXlTZWNyZXRBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy50YWlsc2NhbGVBdXRoS2V5U2VjcmV0LnNlY3JldEFybixcbiAgICAgIGRlc2NyaXB0aW9uOiAnQVJOIG9mIFRhaWxzY2FsZSBhdXRoIGtleSBzZWNyZXQnLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaFRhaWxzY2FsZUF1dGhLZXlBcm4nLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0FwaUtleXNTZWNyZXRBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy5hcGlLZXlzU2VjcmV0LnNlY3JldEFybixcbiAgICAgIGRlc2NyaXB0aW9uOiAnQVJOIG9mIEFQSSBrZXlzIHNlY3JldCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoQXBpS2V5c0FybicsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnVGVsZWdyYW1Cb3RUb2tlblNlY3JldEFybicsIHtcbiAgICAgIHZhbHVlOiB0aGlzLnRlbGVncmFtQm90VG9rZW5TZWNyZXQuc2VjcmV0QXJuLFxuICAgICAgZGVzY3JpcHRpb246ICdBUk4gb2YgVGVsZWdyYW0gYm90IHRva2VuIHNlY3JldCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoVGVsZWdyYW1Cb3RUb2tlbkFybicsXG4gICAgfSk7XG5cbiAgICAvLyBHcmFudCBkZWZhdWx0IEFnZW50Q29yZSBleGVjdXRpb24gcm9sZSByZWFkIGFjY2VzcyB0byBUZWxlZ3JhbSB0b2tlbiAobm8gZW52IHZhcnMgbmVlZGVkKVxuICAgIGNvbnN0IGRlZmF1bHRSb2xlQXJuID0gcHJvcHM/LmRlZmF1bHRFeGVjdXRpb25Sb2xlQXJuO1xuICAgIGlmIChkZWZhdWx0Um9sZUFybikge1xuICAgICAgY29uc3QgZGVmYXVsdFJvbGUgPSBpYW0uUm9sZS5mcm9tUm9sZUFybihcbiAgICAgICAgdGhpcyxcbiAgICAgICAgJ0RlZmF1bHRBZ2VudENvcmVSdW50aW1lUm9sZScsXG4gICAgICAgIGRlZmF1bHRSb2xlQXJuXG4gICAgICApO1xuICAgICAgLy8gVXNlIHdpbGRjYXJkIEFSTiBzbyB3ZSBtYXRjaCB0aGUgc2VjcmV0J3MgZnVsbCBBUk4gKEFXUyBhcHBlbmRzIDYtY2hhciBzdWZmaXggdG8gc2VjcmV0IG5hbWVzKVxuICAgICAgY29uc3QgdGVsZWdyYW1TZWNyZXRBcm4gPSBgYXJuOmF3czpzZWNyZXRzbWFuYWdlcjoke3RoaXMucmVnaW9ufToke3RoaXMuYWNjb3VudH06c2VjcmV0OmdsaXRjaC90ZWxlZ3JhbS1ib3QtdG9rZW4qYDtcbiAgICAgIG5ldyBpYW0uTWFuYWdlZFBvbGljeSh0aGlzLCAnR2xpdGNoRGVmYXVsdFJvbGVUZWxlZ3JhbVNlY3JldFBvbGljeScsIHtcbiAgICAgICAgcm9sZXM6IFtkZWZhdWx0Um9sZV0sXG4gICAgICAgIGRvY3VtZW50OiBuZXcgaWFtLlBvbGljeURvY3VtZW50KHtcbiAgICAgICAgICBzdGF0ZW1lbnRzOiBbXG4gICAgICAgICAgICBuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgICAgICAgIHNpZDogJ1RlbGVncmFtQm90VG9rZW5TZWNyZXQnLFxuICAgICAgICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgICAgICAgIGFjdGlvbnM6IFsnc2VjcmV0c21hbmFnZXI6R2V0U2VjcmV0VmFsdWUnXSxcbiAgICAgICAgICAgICAgcmVzb3VyY2VzOiBbdGVsZWdyYW1TZWNyZXRBcm5dLFxuICAgICAgICAgICAgfSksXG4gICAgICAgICAgXSxcbiAgICAgICAgfSksXG4gICAgICB9KTtcbiAgICB9XG4gIH1cbn1cbiJdfQ==