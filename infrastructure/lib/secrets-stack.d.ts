import * as cdk from 'aws-cdk-lib';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
export declare class SecretsStack extends cdk.Stack {
    readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
    readonly apiKeysSecret: secretsmanager.ISecret;
    readonly telegramBotTokenSecret: secretsmanager.ISecret;
    constructor(scope: Construct, id: string, props?: cdk.StackProps);
}
