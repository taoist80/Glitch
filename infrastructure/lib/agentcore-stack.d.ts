import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as ecr from 'aws-cdk-lib/aws-ecr';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
export interface AgentCoreStackProps extends cdk.StackProps {
    readonly vpc: ec2.IVpc;
    readonly tailscaleSecurityGroup: ec2.ISecurityGroup;
    readonly apiKeysSecret: secretsmanager.ISecret;
}
export declare class AgentCoreStack extends cdk.Stack {
    readonly ecrRepository: ecr.Repository;
    readonly agentRuntimeRole: iam.Role;
    readonly agentCoreSecurityGroup: ec2.SecurityGroup;
    constructor(scope: Construct, id: string, props: AgentCoreStackProps);
}
