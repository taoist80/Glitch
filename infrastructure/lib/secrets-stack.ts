import * as cdk from 'aws-cdk-lib';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export interface SecretsStackProps extends cdk.StackProps {
  /**
   * ARN of the default AgentCore SDK runtime role (used at runtime).
   * When set, this role is granted read access to the Telegram bot token secret
   * so the agent can retrieve the token without env vars.
   */
  readonly defaultExecutionRoleArn?: string;
}

export class SecretsStack extends cdk.Stack {
  public readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
  public readonly apiKeysSecret: secretsmanager.ISecret;
  public readonly telegramBotTokenSecret: secretsmanager.ISecret;
  public readonly porkbunApiSecret: secretsmanager.ISecret;

  constructor(scope: Construct, id: string, props?: SecretsStackProps) {
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

    this.porkbunApiSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'PorkbunApi',
      'glitch/porkbun-api'
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

    // Grant default AgentCore execution role read access to Telegram token (no env vars needed)
    const defaultRoleArn = props?.defaultExecutionRoleArn;
    if (defaultRoleArn) {
      const defaultRole = iam.Role.fromRoleArn(
        this,
        'DefaultAgentCoreRuntimeRole',
        defaultRoleArn
      );
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
