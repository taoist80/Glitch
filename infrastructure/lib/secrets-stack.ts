import * as cdk from 'aws-cdk-lib';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export class SecretsStack extends cdk.Stack {
  public readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
  public readonly apiKeysSecret: secretsmanager.ISecret;
  public readonly telegramBotTokenSecret: secretsmanager.ISecret;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    this.tailscaleAuthKeySecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'TailscaleAuthKey',
      'glitch/tailscale-auth-key'
    );

    this.apiKeysSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'ApiKeys',
      'glitch/api-keys'
    );

    this.telegramBotTokenSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'TelegramBotToken',
      'glitch/telegram-bot-token'
    );

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
