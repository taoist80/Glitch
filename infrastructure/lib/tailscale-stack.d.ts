import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
export interface TailscaleStackProps extends cdk.StackProps {
    readonly vpc: ec2.IVpc;
    readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
    readonly agentCoreSecurityGroup?: ec2.ISecurityGroup;
}
export declare class TailscaleStack extends cdk.Stack {
    readonly instance: ec2.Instance;
    readonly securityGroup: ec2.SecurityGroup;
    constructor(scope: Construct, id: string, props: TailscaleStackProps);
}
