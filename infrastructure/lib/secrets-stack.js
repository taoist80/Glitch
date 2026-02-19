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
    }
}
exports.SecretsStack = SecretsStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoic2VjcmV0cy1zdGFjay5qcyIsInNvdXJjZVJvb3QiOiIiLCJzb3VyY2VzIjpbInNlY3JldHMtc3RhY2sudHMiXSwibmFtZXMiOltdLCJtYXBwaW5ncyI6Ijs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7O0FBQUEsaURBQW1DO0FBQ25DLCtFQUFpRTtBQUdqRSxNQUFhLFlBQWEsU0FBUSxHQUFHLENBQUMsS0FBSztJQUt6QyxZQUFZLEtBQWdCLEVBQUUsRUFBVSxFQUFFLEtBQXNCO1FBQzlELEtBQUssQ0FBQyxLQUFLLEVBQUUsRUFBRSxFQUFFLEtBQUssQ0FBQyxDQUFDO1FBRXhCLElBQUksQ0FBQyxzQkFBc0IsR0FBRyxjQUFjLENBQUMsTUFBTSxDQUFDLGdCQUFnQixDQUNsRSxJQUFJLEVBQ0osa0JBQWtCLEVBQ2xCLDJCQUEyQixDQUM1QixDQUFDO1FBRUYsSUFBSSxDQUFDLGFBQWEsR0FBRyxjQUFjLENBQUMsTUFBTSxDQUFDLGdCQUFnQixDQUN6RCxJQUFJLEVBQ0osU0FBUyxFQUNULGlCQUFpQixDQUNsQixDQUFDO1FBRUYsSUFBSSxDQUFDLHNCQUFzQixHQUFHLGNBQWMsQ0FBQyxNQUFNLENBQUMsZ0JBQWdCLENBQ2xFLElBQUksRUFDSixrQkFBa0IsRUFDbEIsMkJBQTJCLENBQzVCLENBQUM7UUFFRixJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLDJCQUEyQixFQUFFO1lBQ25ELEtBQUssRUFBRSxJQUFJLENBQUMsc0JBQXNCLENBQUMsU0FBUztZQUM1QyxXQUFXLEVBQUUsa0NBQWtDO1lBQy9DLFVBQVUsRUFBRSwyQkFBMkI7U0FDeEMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxrQkFBa0IsRUFBRTtZQUMxQyxLQUFLLEVBQUUsSUFBSSxDQUFDLGFBQWEsQ0FBQyxTQUFTO1lBQ25DLFdBQVcsRUFBRSx3QkFBd0I7WUFDckMsVUFBVSxFQUFFLGtCQUFrQjtTQUMvQixDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLDJCQUEyQixFQUFFO1lBQ25ELEtBQUssRUFBRSxJQUFJLENBQUMsc0JBQXNCLENBQUMsU0FBUztZQUM1QyxXQUFXLEVBQUUsa0NBQWtDO1lBQy9DLFVBQVUsRUFBRSwyQkFBMkI7U0FDeEMsQ0FBQyxDQUFDO0lBQ0wsQ0FBQztDQUNGO0FBNUNELG9DQTRDQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgKiBhcyBzZWNyZXRzbWFuYWdlciBmcm9tICdhd3MtY2RrLWxpYi9hd3Mtc2VjcmV0c21hbmFnZXInO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5cbmV4cG9ydCBjbGFzcyBTZWNyZXRzU3RhY2sgZXh0ZW5kcyBjZGsuU3RhY2sge1xuICBwdWJsaWMgcmVhZG9ubHkgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogc2VjcmV0c21hbmFnZXIuSVNlY3JldDtcbiAgcHVibGljIHJlYWRvbmx5IGFwaUtleXNTZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHB1YmxpYyByZWFkb25seSB0ZWxlZ3JhbUJvdFRva2VuU2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzPzogY2RrLlN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIHRoaXMudGFpbHNjYWxlQXV0aEtleVNlY3JldCA9IHNlY3JldHNtYW5hZ2VyLlNlY3JldC5mcm9tU2VjcmV0TmFtZVYyKFxuICAgICAgdGhpcyxcbiAgICAgICdUYWlsc2NhbGVBdXRoS2V5JyxcbiAgICAgICdnbGl0Y2gvdGFpbHNjYWxlLWF1dGgta2V5J1xuICAgICk7XG5cbiAgICB0aGlzLmFwaUtleXNTZWNyZXQgPSBzZWNyZXRzbWFuYWdlci5TZWNyZXQuZnJvbVNlY3JldE5hbWVWMihcbiAgICAgIHRoaXMsXG4gICAgICAnQXBpS2V5cycsXG4gICAgICAnZ2xpdGNoL2FwaS1rZXlzJ1xuICAgICk7XG5cbiAgICB0aGlzLnRlbGVncmFtQm90VG9rZW5TZWNyZXQgPSBzZWNyZXRzbWFuYWdlci5TZWNyZXQuZnJvbVNlY3JldE5hbWVWMihcbiAgICAgIHRoaXMsXG4gICAgICAnVGVsZWdyYW1Cb3RUb2tlbicsXG4gICAgICAnZ2xpdGNoL3RlbGVncmFtLWJvdC10b2tlbidcbiAgICApO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1RhaWxzY2FsZUF1dGhLZXlTZWNyZXRBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy50YWlsc2NhbGVBdXRoS2V5U2VjcmV0LnNlY3JldEFybixcbiAgICAgIGRlc2NyaXB0aW9uOiAnQVJOIG9mIFRhaWxzY2FsZSBhdXRoIGtleSBzZWNyZXQnLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaFRhaWxzY2FsZUF1dGhLZXlBcm4nLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0FwaUtleXNTZWNyZXRBcm4nLCB7XG4gICAgICB2YWx1ZTogdGhpcy5hcGlLZXlzU2VjcmV0LnNlY3JldEFybixcbiAgICAgIGRlc2NyaXB0aW9uOiAnQVJOIG9mIEFQSSBrZXlzIHNlY3JldCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoQXBpS2V5c0FybicsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnVGVsZWdyYW1Cb3RUb2tlblNlY3JldEFybicsIHtcbiAgICAgIHZhbHVlOiB0aGlzLnRlbGVncmFtQm90VG9rZW5TZWNyZXQuc2VjcmV0QXJuLFxuICAgICAgZGVzY3JpcHRpb246ICdBUk4gb2YgVGVsZWdyYW0gYm90IHRva2VuIHNlY3JldCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoVGVsZWdyYW1Cb3RUb2tlbkFybicsXG4gICAgfSk7XG4gIH1cbn1cbiJdfQ==