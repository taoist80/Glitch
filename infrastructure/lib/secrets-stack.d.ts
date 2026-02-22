import * as cdk from 'aws-cdk-lib';
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
export declare class SecretsStack extends cdk.Stack {
    readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
    readonly apiKeysSecret: secretsmanager.ISecret;
    readonly telegramBotTokenSecret: secretsmanager.ISecret;
    readonly porkbunApiSecret: secretsmanager.ISecret;
    readonly piholeApiSecret: secretsmanager.ISecret;
    constructor(scope: Construct, id: string, props?: SecretsStackProps);
}
