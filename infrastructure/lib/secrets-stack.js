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
        this.porkbunApiSecret = secretsmanager.Secret.fromSecretNameV2(this, 'PorkbunApi', 'glitch/porkbun-api');
        this.piholeApiSecret = secretsmanager.Secret.fromSecretNameV2(this, 'PiholeApi', 'glitch/pihole-api');
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
        new cdk.CfnOutput(this, 'PiholeApiSecretArn', {
            value: this.piholeApiSecret.secretArn,
            description: 'ARN of Pi-hole API credentials secret',
            exportName: 'GlitchPiholeApiArn',
        });
        // Grant default AgentCore execution role read access to secrets (no env vars needed)
        const defaultRoleArn = props?.defaultExecutionRoleArn;
        if (defaultRoleArn) {
            const defaultRole = iam.Role.fromRoleArn(this, 'DefaultAgentCoreRuntimeRole', defaultRoleArn);
            // Use wildcard ARNs so we match the secret's full ARN (AWS appends 6-char suffix to secret names)
            const telegramSecretArn = `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/telegram-bot-token*`;
            const piholeSecretArn = `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/pihole-api*`;
            new iam.ManagedPolicy(this, 'GlitchDefaultRoleSecretsPolicy', {
                roles: [defaultRole],
                document: new iam.PolicyDocument({
                    statements: [
                        new iam.PolicyStatement({
                            sid: 'TelegramBotTokenSecret',
                            effect: iam.Effect.ALLOW,
                            actions: ['secretsmanager:GetSecretValue'],
                            resources: [telegramSecretArn],
                        }),
                        new iam.PolicyStatement({
                            sid: 'PiholeApiSecret',
                            effect: iam.Effect.ALLOW,
                            actions: ['secretsmanager:GetSecretValue'],
                            resources: [piholeSecretArn],
                        }),
                    ],
                }),
            });
        }
    }
}
exports.SecretsStack = SecretsStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoic2VjcmV0cy1zdGFjay5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbInNlY3JldHMtc3RhY2sudHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O0FBQUEsaURBQW1DO0FBQ25DLHlEQUEyQztBQUMzQywrRUFBaUU7QUFZakUsTUFBYSxZQUFhLFNBQVEsR0FBRyxDQUFDLEtBQUs7SUFPekMsWUFBWSxLQUFnQixFQUFFLEVBQVUsRUFBRSxLQUF5QjtRQUNqRSxLQUFLLENBQUMsS0FBSyxFQUFFLEVBQUUsRUFBRSxLQUFLLENBQUMsQ0FBQztRQUV4QixJQUFJLENBQUMsc0JBQXNCLEdBQUcsY0FBYyxDQUFDLE1BQU0sQ0FBQyxnQkFBZ0IsQ0FDbEUsSUFBSSxFQUNKLGtCQUFrQixFQUNsQiwyQkFBMkIsQ0FDNUIsQ0FBQztRQUVGLElBQUksQ0FBQyxhQUFhLEdBQUcsY0FBYyxDQUFDLE1BQU0sQ0FBQyxnQkFBZ0IsQ0FDekQsSUFBSSxFQUNKLFNBQVMsRUFDVCxpQkFBaUIsQ0FDbEIsQ0FBQztRQUVGLElBQUksQ0FBQyxzQkFBc0IsR0FBRyxjQUFjLENBQUMsTUFBTSxDQUFDLGdCQUFnQixDQUNsRSxJQUFJLEVBQ0osa0JBQWtCLEVBQ2xCLDJCQUEyQixDQUM1QixDQUFDO1FBRUYsSUFBSSxDQUFDLGdCQUFnQixHQUFHLGNBQWMsQ0FBQyxNQUFNLENBQUMsZ0JBQWdCLENBQzVELElBQUksRUFDSixZQUFZLEVBQ1osb0JBQW9CLENBQ3JCLENBQUM7UUFFRixJQUFJLENBQUMsZUFBZSxHQUFHLGNBQWMsQ0FBQyxNQUFNLENBQUMsZ0JBQWdCLENBQzNELElBQUksRUFDSixXQUFXLEVBQ1gsbUJBQW1CLENBQ3BCLENBQUM7UUFFRixJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLDJCQUEyQixFQUFFO1lBQ25ELEtBQUssRUFBRSxJQUFJLENBQUMsc0JBQXNCLENBQUMsU0FBUztZQUM1QyxXQUFXLEVBQUUsa0NBQWtDO1lBQy9DLFVBQVUsRUFBRSwyQkFBMkI7U0FDeEMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxrQkFBa0IsRUFBRTtZQUMxQyxLQUFLLEVBQUUsSUFBSSxDQUFDLGFBQWEsQ0FBQyxTQUFTO1lBQ25DLFdBQVcsRUFBRSx3QkFBd0I7WUFDckMsVUFBVSxFQUFFLGtCQUFrQjtTQUMvQixDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLDJCQUEyQixFQUFFO1lBQ25ELEtBQUssRUFBRSxJQUFJLENBQUMsc0JBQXNCLENBQUMsU0FBUztZQUM1QyxXQUFXLEVBQUUsa0NBQWtDO1lBQy9DLFVBQVUsRUFBRSwyQkFBMkI7U0FDeEMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxvQkFBb0IsRUFBRTtZQUM1QyxLQUFLLEVBQUUsSUFBSSxDQUFDLGVBQWUsQ0FBQyxTQUFTO1lBQ3JDLFdBQVcsRUFBRSx1Q0FBdUM7WUFDcEQsVUFBVSxFQUFFLG9CQUFvQjtTQUNqQyxDQUFDLENBQUM7UUFFSCxxRkFBcUY7UUFDckYsTUFBTSxjQUFjLEdBQUcsS0FBSyxFQUFFLHVCQUF1QixDQUFDO1FBQ3RELElBQUksY0FBYyxFQUFFLENBQUM7WUFDbkIsTUFBTSxXQUFXLEdBQUcsR0FBRyxDQUFDLElBQUksQ0FBQyxXQUFXLENBQ3RDLElBQUksRUFDSiw2QkFBNkIsRUFDN0IsY0FBYyxDQUNmLENBQUM7WUFDRixrR0FBa0c7WUFDbEcsTUFBTSxpQkFBaUIsR0FBRywwQkFBMEIsSUFBSSxDQUFDLE1BQU0sSUFBSSxJQUFJLENBQUMsT0FBTyxvQ0FBb0MsQ0FBQztZQUNwSCxNQUFNLGVBQWUsR0FBRywwQkFBMEIsSUFBSSxDQUFDLE1BQU0sSUFBSSxJQUFJLENBQUMsT0FBTyw0QkFBNEIsQ0FBQztZQUMxRyxJQUFJLEdBQUcsQ0FBQyxhQUFhLENBQUMsSUFBSSxFQUFFLGdDQUFnQyxFQUFFO2dCQUM1RCxLQUFLLEVBQUUsQ0FBQyxXQUFXLENBQUM7Z0JBQ3BCLFFBQVEsRUFBRSxJQUFJLEdBQUcsQ0FBQyxjQUFjLENBQUM7b0JBQy9CLFVBQVUsRUFBRTt3QkFDVixJQUFJLEdBQUcsQ0FBQyxlQUFlLENBQUM7NEJBQ3RCLEdBQUcsRUFBRSx3QkFBd0I7NEJBQzdCLE1BQU0sRUFBRSxHQUFHLENBQUMsTUFBTSxDQUFDLEtBQUs7NEJBQ3hCLE9BQU8sRUFBRSxDQUFDLCtCQUErQixDQUFDOzRCQUMxQyxTQUFTLEVBQUUsQ0FBQyxpQkFBaUIsQ0FBQzt5QkFDL0IsQ0FBQzt3QkFDRixJQUFJLEdBQUcsQ0FBQyxlQUFlLENBQUM7NEJBQ3RCLEdBQUcsRUFBRSxpQkFBaUI7NEJBQ3RCLE1BQU0sRUFBRSxHQUFHLENBQUMsTUFBTSxDQUFDLEtBQUs7NEJBQ3hCLE9BQU8sRUFBRSxDQUFDLCtCQUErQixDQUFDOzRCQUMxQyxTQUFTLEVBQUUsQ0FBQyxlQUFlLENBQUM7eUJBQzdCLENBQUM7cUJBQ0g7aUJBQ0YsQ0FBQzthQUNILENBQUMsQ0FBQztRQUNMLENBQUM7SUFDSCxDQUFDO0NBQ0Y7QUFoR0Qsb0NBZ0dDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIGlhbSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtaWFtJztcbmltcG9ydCAqIGFzIHNlY3JldHNtYW5hZ2VyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1zZWNyZXRzbWFuYWdlcic7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcblxuZXhwb3J0IGludGVyZmFjZSBTZWNyZXRzU3RhY2tQcm9wcyBleHRlbmRzIGNkay5TdGFja1Byb3BzIHtcbiAgLyoqXG4gICAqIEFSTiBvZiB0aGUgZGVmYXVsdCBBZ2VudENvcmUgU0RLIHJ1bnRpbWUgcm9sZSAodXNlZCBhdCBydW50aW1lKS5cbiAgICogV2hlbiBzZXQsIHRoaXMgcm9sZSBpcyBncmFudGVkIHJlYWQgYWNjZXNzIHRvIHRoZSBUZWxlZ3JhbSBib3QgdG9rZW4gc2VjcmV0XG4gICAqIHNvIHRoZSBhZ2VudCBjYW4gcmV0cmlldmUgdGhlIHRva2VuIHdpdGhvdXQgZW52IHZhcnMuXG4gICAqL1xuICByZWFkb25seSBkZWZhdWx0RXhlY3V0aW9uUm9sZUFybj86IHN0cmluZztcbn1cblxuZXhwb3J0IGNsYXNzIFNlY3JldHNTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuICBwdWJsaWMgcmVhZG9ubHkgYXBpS2V5c1NlY3JldDogc2VjcmV0c21hbmFnZXIuSVNlY3JldDtcbiAgcHVibGljIHJlYWRvbmx5IHRlbGVncmFtQm90VG9rZW5TZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHB1YmxpYyByZWFkb25seSBwb3JrYnVuQXBpU2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuICBwdWJsaWMgcmVhZG9ubHkgcGlob2xlQXBpU2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzPzogU2VjcmV0c1N0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIHRoaXMudGFpbHNjYWxlQXV0aEtleVNlY3JldCA9IHNlY3JldHNtYW5hZ2VyLlNlY3JldC5mcm9tU2VjcmV0TmFtZVYyKFxuICAgICAgdGhpcyxcbiAgICAgICdUYWlsc2NhbGVBdXRoS2V5JyxcbiAgICAgICdnbGl0Y2gvdGFpbHNjYWxlLWF1dGgta2V5J1xuICAgICk7XG5cbiAgICB0aGlzLmFwaUtleXNTZWNyZXQgPSBzZWNyZXRzbWFuYWdlci5TZWNyZXQuZnJvbVNlY3JldE5hbWVWMihcbiAgICAgIHRoaXMsXG4gICAgICAnQXBpS2V5cycsXG4gICAgICAnZ2xpdGNoL2FwaS1rZXlzJ1xuICAgICk7XG5cbiAgICB0aGlzLnRlbGVncmFtQm90VG9rZW5TZWNyZXQgPSBzZWNyZXRzbWFuYWdlci5TZWNyZXQuZnJvbVNlY3JldE5hbWVWMihcbiAgICAgIHRoaXMsXG4gICAgICAnVGVsZWdyYW1Cb3RUb2tlbicsXG4gICAgICAnZ2xpdGNoL3RlbGVncmFtLWJvdC10b2tlbidcbiAgICApO1xuXG4gICAgdGhpcy5wb3JrYnVuQXBpU2VjcmV0ID0gc2VjcmV0c21hbmFnZXIuU2VjcmV0LmZyb21TZWNyZXROYW1lVjIoXG4gICAgICB0aGlzLFxuICAgICAgJ1BvcmtidW5BcGknLFxuICAgICAgJ2dsaXRjaC9wb3JrYnVuLWFwaSdcbiAgICApO1xuXG4gICAgdGhpcy5waWhvbGVBcGlTZWNyZXQgPSBzZWNyZXRzbWFuYWdlci5TZWNyZXQuZnJvbVNlY3JldE5hbWVWMihcbiAgICAgIHRoaXMsXG4gICAgICAnUGlob2xlQXBpJyxcbiAgICAgICdnbGl0Y2gvcGlob2xlLWFwaSdcbiAgICApO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1RhaWxzY2FsZUF1dGhLZXlTZWNyZXRBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy50YWlsc2NhbGVBdXRoS2V5U2VjcmV0LnNlY3JldEFybixcbiAgICAgIGRlc2NyaXB0aW9uOiAnQVJOIG9mIFRhaWxzY2FsZSBhdXRoIGtleSBzZWNyZXQnLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaFRhaWxzY2FsZUF1dGhLZXlBcm4nLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0FwaUtleXNTZWNyZXRBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy5hcGlLZXlzU2VjcmV0LnNlY3JldEFybixcbiAgICAgIGRlc2NyaXB0aW9uOiAnQVJOIG9mIEFQSSBrZXlzIHNlY3JldCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoQXBpS2V5c0FybicsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnVGVsZWdyYW1Cb3RUb2tlblNlY3JldEFybicsIHtcbiAgICAgIHZhbHVlOiB0aGlzLnRlbGVncmFtQm90VG9rZW5TZWNyZXQuc2VjcmV0QXJuLFxuICAgICAgZGVzY3JpcHRpb246ICdBUk4gb2YgVGVsZWdyYW0gYm90IHRva2VuIHNlY3JldCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoVGVsZWdyYW1Cb3RUb2tlbkFybicsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnUGlob2xlQXBpU2VjcmV0QXJuJywge1xuICAgICAgdmFsdWU6IHRoaXMucGlob2xlQXBpU2VjcmV0LnNlY3JldEFybixcbiAgICAgIGRlc2NyaXB0aW9uOiAnQVJOIG9mIFBpLWhvbGUgQVBJIGNyZWRlbnRpYWxzIHNlY3JldCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoUGlob2xlQXBpQXJuJyxcbiAgICB9KTtcblxuICAgIC8vIEdyYW50IGRlZmF1bHQgQWdlbnRDb3JlIGV4ZWN1dGlvbiByb2xlIHJlYWQgYWNjZXNzIHRvIHNlY3JldHMgKG5vIGVudiB2YXJzIG5lZWRlZClcbiAgICBjb25zdCBkZWZhdWx0Um9sZUFybiA9IHByb3BzPy5kZWZhdWx0RXhlY3V0aW9uUm9sZUFybjtcbiAgICBpZiAoZGVmYXVsdFJvbGVBcm4pIHtcbiAgICAgIGNvbnN0IGRlZmF1bHRSb2xlID0gaWFtLlJvbGUuZnJvbVJvbGVBcm4oXG4gICAgICAgIHRoaXMsXG4gICAgICAgICdEZWZhdWx0QWdlbnRDb3JlUnVudGltZVJvbGUnLFxuICAgICAgICBkZWZhdWx0Um9sZUFyblxuICAgICAgKTtcbiAgICAgIC8vIFVzZSB3aWxkY2FyZCBBUk5zIHNvIHdlIG1hdGNoIHRoZSBzZWNyZXQncyBmdWxsIEFSTiAoQVdTIGFwcGVuZHMgNi1jaGFyIHN1ZmZpeCB0byBzZWNyZXQgbmFtZXMpXG4gICAgICBjb25zdCB0ZWxlZ3JhbVNlY3JldEFybiA9IGBhcm46YXdzOnNlY3JldHNtYW5hZ2VyOiR7dGhpcy5yZWdpb259OiR7dGhpcy5hY2NvdW50fTpzZWNyZXQ6Z2xpdGNoL3RlbGVncmFtLWJvdC10b2tlbipgO1xuICAgICAgY29uc3QgcGlob2xlU2VjcmV0QXJuID0gYGFybjphd3M6c2VjcmV0c21hbmFnZXI6JHt0aGlzLnJlZ2lvbn06JHt0aGlzLmFjY291bnR9OnNlY3JldDpnbGl0Y2gvcGlob2xlLWFwaSpgO1xuICAgICAgbmV3IGlhbS5NYW5hZ2VkUG9saWN5KHRoaXMsICdHbGl0Y2hEZWZhdWx0Um9sZVNlY3JldHNQb2xpY3knLCB7XG4gICAgICAgIHJvbGVzOiBbZGVmYXVsdFJvbGVdLFxuICAgICAgICBkb2N1bWVudDogbmV3IGlhbS5Qb2xpY3lEb2N1bWVudCh7XG4gICAgICAgICAgc3RhdGVtZW50czogW1xuICAgICAgICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICAgICAgICBzaWQ6ICdUZWxlZ3JhbUJvdFRva2VuU2VjcmV0JyxcbiAgICAgICAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICAgICAgICBhY3Rpb25zOiBbJ3NlY3JldHNtYW5hZ2VyOkdldFNlY3JldFZhbHVlJ10sXG4gICAgICAgICAgICAgIHJlc291cmNlczogW3RlbGVncmFtU2VjcmV0QXJuXSxcbiAgICAgICAgICAgIH0pLFxuICAgICAgICAgICAgbmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICAgICAgICBzaWQ6ICdQaWhvbGVBcGlTZWNyZXQnLFxuICAgICAgICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgICAgICAgIGFjdGlvbnM6IFsnc2VjcmV0c21hbmFnZXI6R2V0U2VjcmV0VmFsdWUnXSxcbiAgICAgICAgICAgICAgcmVzb3VyY2VzOiBbcGlob2xlU2VjcmV0QXJuXSxcbiAgICAgICAgICAgIH0pLFxuICAgICAgICAgIF0sXG4gICAgICAgIH0pLFxuICAgICAgfSk7XG4gICAgfVxuICB9XG59XG4iXX0=