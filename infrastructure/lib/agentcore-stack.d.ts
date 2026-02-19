import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
export interface AgentCoreStackProps extends cdk.StackProps {
    readonly vpc: ec2.IVpc;
    readonly tailscaleSecurityGroup: ec2.ISecurityGroup;
    readonly apiKeysSecret: secretsmanager.ISecret;
    readonly telegramBotTokenSecret: secretsmanager.ISecret;
}
export declare class AgentCoreStack extends cdk.Stack {
    readonly agentRuntimeRole: iam.Role;
    readonly agentCoreSecurityGroup: ec2.SecurityGroup;
    constructor(scope: Construct, id: string, props: AgentCoreStackProps);
}
