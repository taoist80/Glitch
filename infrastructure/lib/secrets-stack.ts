import * as cdk from 'aws-cdk-lib';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export class SecretsStack extends cdk.Stack {
  public readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
  public readonly apiKeysSecret: secretsmanager.ISecret;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
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
