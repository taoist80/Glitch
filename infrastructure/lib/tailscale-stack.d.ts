import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';
export interface TailscaleStackProps extends cdk.StackProps {
    readonly vpc: ec2.IVpc;
    readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
    readonly agentCoreSecurityGroup?: ec2.ISecurityGroup;
    readonly agentCoreRuntimeArn?: string;
    /** Bump this to force EC2 instance replacement (new instance runs user data from scratch). */
    readonly instanceBootstrapVersion?: string;
    /** Gateway Lambda Function URL for nginx proxy (UI API and invocations). */
    readonly gatewayFunctionUrl?: string;
    /** Gateway Lambda hostname (e.g. xxx.lambda-url.region.on.aws) for Host header. Use Fn.select(2, Fn.split('/', url)) in app. */
    readonly gatewayHostname?: string;
    /** S3 UI bucket name for nginx to proxy static files. */
    readonly uiBucketName?: string;
    /** Custom domain for the UI (e.g. glitch.awoo.agency). Used in nginx server_name and TLS cert. */
    readonly customDomain?: string;
    /** Porkbun API secret for Let's Encrypt DNS-01 challenge. Required if customDomain is set. */
    readonly porkbunApiSecret?: secretsmanager.ISecret;
    /** Email for Let's Encrypt certificate notifications. */
    readonly certbotEmail?: string;
}
export declare class TailscaleStack extends cdk.Stack {
    readonly instance: ec2.Instance;
    readonly securityGroup: ec2.SecurityGroup;
    constructor(scope: Construct, id: string, props: TailscaleStackProps);
}
