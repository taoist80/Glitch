/**
 * All Glitch CDK stacks in a single file.
 * Order: dependency-friendly (interfaces and stacks used by others come first).
 */
import * as cdk from 'aws-cdk-lib';
import * as cr from 'aws-cdk-lib/custom-resources';
import * as acm from 'aws-cdk-lib/aws-certificatemanager';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as ssm from 'aws-cdk-lib/aws-ssm';
import { Construct } from 'constructs';
import * as path from 'path';

// --- SSM Parameter Names (single source of truth) ---
export const SSM_PARAMS = {
  VPC_ID: '/glitch/vpc/id',
  PRIVATE_SUBNET_IDS: '/glitch/vpc/private-subnet-ids',
  PUBLIC_SUBNET_IDS: '/glitch/vpc/public-subnet-ids',
  AGENTCORE_SG_ID: '/glitch/security-groups/agentcore',
  RUNTIME_ROLE_ARN: '/glitch/iam/runtime-role-arn',
  CODEBUILD_ROLE_ARN: '/glitch/iam/codebuild-role-arn',
} as const;

// --- GlitchFoundationStack ---
// Consolidated stack: VPC + Security Groups + IAM Roles + SSM Parameters
// No hardcoded role names - CloudFormation generates unique names

export interface GlitchFoundationStackProps extends cdk.StackProps {
  readonly vpcCidr?: string;
}

export class GlitchFoundationStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly privateSubnets: ec2.ISubnet[];
  public readonly publicSubnets: ec2.ISubnet[];
  public readonly agentCoreSecurityGroup: ec2.SecurityGroup;
  public readonly runtimeRole: iam.Role;
  public readonly codeBuildRole: iam.Role;

  constructor(scope: Construct, id: string, props?: GlitchFoundationStackProps) {
    super(scope, id, props);

    // ========== VPC ==========
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 0,
      ipAddresses: ec2.IpAddresses.cidr(props?.vpcCidr || '10.0.0.0/16'),
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
      enableDnsHostnames: true,
      enableDnsSupport: true,
    });

    this.privateSubnets = this.vpc.isolatedSubnets;
    this.publicSubnets = this.vpc.publicSubnets;

    const singleAzSubnetSelection = {
      subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
      onePerAz: true,
      availabilityZones: [this.vpc.availabilityZones[0]],
    };

    // ========== Security Groups (before endpoints so endpoint SG can allow AgentCore) ==========
    this.agentCoreSecurityGroup = new ec2.SecurityGroup(this, 'AgentCoreSG', {
      vpc: this.vpc,
      description: 'Security group for AgentCore runtime ENIs',
      allowAllOutbound: false,
    });

    this.agentCoreSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'HTTPS to AWS services'
    );

    // SG for interface endpoints: only the runtime (AgentCore SG) can use them (least privilege).
    // Without this, endpoints may use the VPC default SG which often does not allow the runtime SG.
    const vpcEndpointsSecurityGroup = new ec2.SecurityGroup(this, 'VpcEndpointsSG', {
      vpc: this.vpc,
      description: 'Security group for VPC interface endpoints; allow AgentCore runtime only',
      allowAllOutbound: false,
    });
    vpcEndpointsSecurityGroup.addIngressRule(
      this.agentCoreSecurityGroup,
      ec2.Port.tcp(443),
      'HTTPS from AgentCore runtime'
    );

    const endpointProps = {
      privateDnsEnabled: true,
      subnets: singleAzSubnetSelection,
      securityGroups: [vpcEndpointsSecurityGroup],
    };

    // VPC Endpoints
    this.vpc.addGatewayEndpoint('S3Endpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
      subnets: [{ subnetType: ec2.SubnetType.PRIVATE_ISOLATED }],
    });

    this.vpc.addInterfaceEndpoint('EcrDockerEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
      ...endpointProps,
    });

    this.vpc.addInterfaceEndpoint('EcrApiEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.ECR,
      ...endpointProps,
    });

    this.vpc.addInterfaceEndpoint('CloudWatchLogsEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      ...endpointProps,
    });

    this.vpc.addInterfaceEndpoint('SecretsManagerEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      ...endpointProps,
    });

    this.vpc.addInterfaceEndpoint('BedrockAgentCoreEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENT_RUNTIME,
      ...endpointProps,
    });

    this.vpc.addInterfaceEndpoint('BedrockRuntimeEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
      ...endpointProps,
    });

    this.vpc.addInterfaceEndpoint('BedrockAgentCoreDataPlaneEndpoint', {
      service: new ec2.InterfaceVpcEndpointService(
        `com.amazonaws.${this.region}.bedrock-agentcore`
      ),
      ...endpointProps,
    });

    // STS: required for SDK credential refresh in isolated subnets (no NAT/internet).
    // Without this, any AWS SDK call that needs to exchange credentials via STS will time out.
    this.vpc.addInterfaceEndpoint('StsEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.STS,
      ...endpointProps,
    });

    // CloudWatch (metrics): required for OTEL ADOT to export metrics to CloudWatch.
    this.vpc.addInterfaceEndpoint('CloudWatchEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH,
      ...endpointProps,
    });

    // X-Ray: required for OTEL ADOT to export traces.
    this.vpc.addInterfaceEndpoint('XRayEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.XRAY,
      ...endpointProps,
    });

    // ========== IAM Roles (NO hardcoded names) ==========
    
    // Runtime role for AgentCore
    this.runtimeRole = new iam.Role(this, 'RuntimeRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: 'IAM role for AgentCore Runtime',
      // NO roleName - let CloudFormation generate it
    });

    // CloudWatch Logs: /glitch/* (telemetry) and /aws/bedrock-agentcore/* (runtime application logs).
    // Application logs (stdout/stderr) are delivered by AgentCore to /aws/bedrock-agentcore/runtimes/<id>/...
    // Both are required so logs work even if GlitchAgentCoreStack is not yet deployed.
    this.runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchLogs',
        effect: iam.Effect.ALLOW,
        actions: [
          'logs:CreateLogGroup',
          'logs:CreateLogStream',
          'logs:PutLogEvents',
          'logs:DescribeLogStreams',
        ],
        resources: [
          `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*:*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
          `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*:*`,
        ],
      })
    );

    // X-Ray: OTEL ADOT traces exporter.
    this.runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'XRayTracing',
        effect: iam.Effect.ALLOW,
        actions: [
          'xray:PutTraceSegments',
          'xray:PutTelemetryRecords',
          'xray:GetSamplingRules',
          'xray:GetSamplingTargets',
        ],
        resources: ['*'],
      })
    );

    // CloudWatch metrics: OTEL ADOT metrics exporter.
    this.runtimeRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'CloudWatchMetrics',
        effect: iam.Effect.ALLOW,
        actions: ['cloudwatch:PutMetricData'],
        resources: ['*'],
      })
    );

    // CodeBuild role for container builds
    this.codeBuildRole = new iam.Role(this, 'CodeBuildRole', {
      assumedBy: new iam.ServicePrincipal('codebuild.amazonaws.com'),
      description: 'IAM role for AgentCore CodeBuild container builds',
      // NO roleName - let CloudFormation generate it
    });

    // CodeBuild policies
    this.codeBuildRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/*`],
    }));

    this.codeBuildRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['s3:GetObject', 's3:GetObjectVersion', 's3:PutObject'],
      resources: [
        `arn:aws:s3:::bedrock-agentcore-codebuild-sources-${this.account}-${this.region}`,
        `arn:aws:s3:::bedrock-agentcore-codebuild-sources-${this.account}-${this.region}/*`,
      ],
    }));

    this.codeBuildRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['s3:GetBucketAcl', 's3:GetBucketLocation'],
      resources: [`arn:aws:s3:::bedrock-agentcore-codebuild-sources-${this.account}-${this.region}`],
    }));

    this.codeBuildRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['ecr:GetAuthorizationToken'],
      resources: ['*'],
    }));

    this.codeBuildRole.addToPolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: [
        'ecr:BatchCheckLayerAvailability',
        'ecr:GetDownloadUrlForLayer',
        'ecr:BatchGetImage',
        'ecr:PutImage',
        'ecr:InitiateLayerUpload',
        'ecr:UploadLayerPart',
        'ecr:CompleteLayerUpload',
      ],
      resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-glitch`],
    }));

    // ========== SSM Parameters (for cross-stack references) ==========
    new ssm.StringParameter(this, 'SsmVpcId', {
      parameterName: SSM_PARAMS.VPC_ID,
      stringValue: this.vpc.vpcId,
      description: 'Glitch VPC ID',
    });

    new ssm.StringParameter(this, 'SsmPrivateSubnets', {
      parameterName: SSM_PARAMS.PRIVATE_SUBNET_IDS,
      stringValue: this.privateSubnets.map(s => s.subnetId).join(','),
      description: 'Glitch private subnet IDs (comma-separated)',
    });

    new ssm.StringParameter(this, 'SsmPublicSubnets', {
      parameterName: SSM_PARAMS.PUBLIC_SUBNET_IDS,
      stringValue: this.publicSubnets.map(s => s.subnetId).join(','),
      description: 'Glitch public subnet IDs (comma-separated)',
    });

    new ssm.StringParameter(this, 'SsmAgentCoreSgId', {
      parameterName: SSM_PARAMS.AGENTCORE_SG_ID,
      stringValue: this.agentCoreSecurityGroup.securityGroupId,
      description: 'AgentCore security group ID',
    });

    new ssm.StringParameter(this, 'SsmRuntimeRoleArn', {
      parameterName: SSM_PARAMS.RUNTIME_ROLE_ARN,
      stringValue: this.runtimeRole.roleArn,
      description: 'AgentCore runtime role ARN',
    });

    new ssm.StringParameter(this, 'SsmCodeBuildRoleArn', {
      parameterName: SSM_PARAMS.CODEBUILD_ROLE_ARN,
      stringValue: this.codeBuildRole.roleArn,
      description: 'CodeBuild role ARN for agentcore deploy',
    });

    // ========== Outputs ==========
    new cdk.CfnOutput(this, 'VpcId', { value: this.vpc.vpcId, description: 'VPC ID' });
    new cdk.CfnOutput(this, 'PrivateSubnetIds', {
      value: this.privateSubnets.map(s => s.subnetId).join(','),
      description: 'Private subnet IDs',
    });
    new cdk.CfnOutput(this, 'AgentCoreSecurityGroupId', {
      value: this.agentCoreSecurityGroup.securityGroupId,
      description: 'AgentCore security group ID',
    });
    new cdk.CfnOutput(this, 'RuntimeRoleArn', {
      value: this.runtimeRole.roleArn,
      description: 'Runtime role ARN (use with agentcore configure --execution-role)',
    });
    new cdk.CfnOutput(this, 'CodeBuildRoleArn', {
      value: this.codeBuildRole.roleArn,
      description: 'CodeBuild role ARN (set in agent/.bedrock_agentcore.yaml codebuild.execution_role)',
    });
  }
}

// --- DEPRECATED: AgentCoreIamStack and GlitchCodeBuildRoleStack ---
// These stacks are replaced by GlitchFoundationStack which consolidates
// VPC + IAM roles + SSM parameters into a single stack.
// Keeping empty exports for backward compatibility during migration.

/** @deprecated Use GlitchFoundationStack instead */
export class AgentCoreIamStack extends cdk.Stack {
  public readonly agentRuntimeRole: iam.IRole;
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    // Read role ARN from SSM (set by GlitchFoundationStack)
    const roleArn = ssm.StringParameter.valueForStringParameter(this, SSM_PARAMS.RUNTIME_ROLE_ARN);
    this.agentRuntimeRole = iam.Role.fromRoleArn(this, 'RuntimeRole', roleArn);
  }
}

/** @deprecated Use GlitchFoundationStack instead */
export class GlitchCodeBuildRoleStack extends cdk.Stack {
  public readonly codeBuildRole: iam.IRole;
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    // Read role ARN from SSM (set by GlitchFoundationStack)
    const roleArn = ssm.StringParameter.valueForStringParameter(this, SSM_PARAMS.CODEBUILD_ROLE_ARN);
    this.codeBuildRole = iam.Role.fromRoleArn(this, 'CodeBuildRole', roleArn);
  }
}

/** @deprecated Use GlitchFoundationStack instead */
export class VpcStack extends cdk.Stack {
  public readonly vpc: ec2.IVpc;
  public readonly privateSubnets: ec2.ISubnet[];
  public readonly publicSubnets: ec2.ISubnet[];
  public readonly agentCoreSecurityGroup: ec2.ISecurityGroup;
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);
    const vpcId = ssm.StringParameter.valueForStringParameter(this, SSM_PARAMS.VPC_ID);
    this.vpc = ec2.Vpc.fromLookup(this, 'Vpc', { vpcId });
    this.privateSubnets = this.vpc.isolatedSubnets;
    this.publicSubnets = this.vpc.publicSubnets;
    const sgId = ssm.StringParameter.valueForStringParameter(this, SSM_PARAMS.AGENTCORE_SG_ID);
    this.agentCoreSecurityGroup = ec2.SecurityGroup.fromSecurityGroupId(this, 'AgentCoreSG', sgId);
  }
}

// --- SecretsStack ---

export interface SecretsStackProps extends cdk.StackProps {
  // No IAM role props: secret read access for the AgentCore runtime role is granted
  // in AgentCoreStack (SecretsManagerAccess policy) to avoid deploy-order and 404 issues.
}

export class SecretsStack extends cdk.Stack {
  public readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
  public readonly apiKeysSecret: secretsmanager.ISecret;
  public readonly telegramBotTokenSecret: secretsmanager.ISecret;
  public readonly porkbunApiSecret: secretsmanager.ISecret;
  public readonly piholeApiSecret: secretsmanager.ISecret;

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

    this.piholeApiSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'PiholeApi',
      'glitch/pihole-api'
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

    new cdk.CfnOutput(this, 'PiholeApiSecretArn', {
      value: this.piholeApiSecret.secretArn,
      description: 'ARN of Pi-hole API credentials secret',
      exportName: 'GlitchPiholeApiArn',
    });

    // AgentCore runtime role secret access is granted in AgentCoreStack (SecretsManagerAccess
    // policy) so this stack has no IAM dependency and deploys reliably.
  }
}

// --- GlitchStorageStack ---

export interface StorageStackProps extends cdk.StackProps {
  // No IAM role: storage/telemetry permissions for the AgentCore runtime role
  // are granted in AgentCoreStack to avoid custom resources and deploy-order issues.
}

/**
 * Storage stack that imports existing resources created outside CDK.
 * Resources were created manually or by a previous stack and are now adopted.
 */
export class GlitchStorageStack extends cdk.Stack {
  public readonly configTable: dynamodb.ITable;
  public readonly soulBucket: s3.IBucket;
  public readonly telemetryLogGroup: logs.ILogGroup;

  constructor(scope: Construct, id: string, props: StorageStackProps) {
    super(scope, id, props);

    const tableName = 'glitch-telegram-config';
    const bucketName = `glitch-agent-state-${this.account}-${this.region}`;
    const logGroupName = '/glitch/telemetry';

    this.configTable = dynamodb.Table.fromTableName(this, 'ConfigTable', tableName);

    this.soulBucket = s3.Bucket.fromBucketName(this, 'GlitchSoulBucket', bucketName);

    this.telemetryLogGroup = logs.LogGroup.fromLogGroupName(
      this,
      'GlitchTelemetryLogGroup',
      logGroupName
    );

    new cdk.CfnOutput(this, 'GlitchSoulBucketName', {
      value: this.soulBucket.bucketName,
      description: 'S3 bucket for Glitch SOUL.md',
      exportName: 'GlitchSoulBucketName',
    });
    new cdk.CfnOutput(this, 'GlitchTelemetryLogGroupName', {
      value: this.telemetryLogGroup.logGroupName,
      description: 'CloudWatch Logs group for telemetry',
      exportName: 'GlitchTelemetryLogGroupName',
    });
  }
}

// --- GlitchGatewayStack ---

export interface GlitchGatewayStackProps extends cdk.StackProps {
  readonly agentCoreRuntimeArn: string;
  readonly configTable: dynamodb.ITable;
}

/**
 * Glitch Gateway stack: Lambda Function URL for UI invocations, /api/* proxy, and keepalive.
 */
export class GlitchGatewayStack extends cdk.Stack {
  public readonly gatewayFunction: lambda.Function;
  public readonly functionUrl: string;

  constructor(scope: Construct, id: string, props: GlitchGatewayStackProps) {
    super(scope, id, props);

    const { agentCoreRuntimeArn, configTable } = props;

    this.gatewayFunction = new lambda.Function(this, 'GatewayFunction', {
      functionName: 'glitch-gateway',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromInline(this.getLambdaCode()),
      timeout: cdk.Duration.seconds(300),
      memorySize: 512,
      environment: {
        CONFIG_TABLE_NAME: configTable.tableName,
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
      },
    });

    configTable.grantReadWriteData(this.gatewayFunction);

    // Use wildcard action to bypass CloudFormation PropertyValidation for newer bedrock-agentcore APIs
    this.gatewayFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'BedrockAgentCoreAccess',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:*'],
        resources: [
          agentCoreRuntimeArn,
          `${agentCoreRuntimeArn}/*`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:code-interpreter/*`,
        ],
      })
    );

    const fnUrl = this.gatewayFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [
          lambda.HttpMethod.GET,
          lambda.HttpMethod.POST,
        ],
        allowedHeaders: ['Content-Type', 'X-Client-Id', 'X-Session-Id'],
        maxAge: cdk.Duration.hours(1),
      },
    });

    this.functionUrl = fnUrl.url;

    const keepaliveRule = new events.Rule(this, 'GatewayKeepaliveRule', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(5)),
      description: 'Keep gateway Lambda warm to reduce cold starts',
    });
    keepaliveRule.addTarget(new targets.LambdaFunction(this.gatewayFunction, {
      event: events.RuleTargetInput.fromObject({ path: '/health', method: 'GET' }),
    }));

    new cdk.CfnOutput(this, 'GatewayFunctionUrl', {
      value: this.functionUrl,
      description: 'Gateway Lambda Function URL',
      exportName: 'GlitchGatewayUrl',
    });
  }

  private getLambdaCode(): string {
    return `
import json
import os
import logging
import boto3
import uuid
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from urllib.parse import quote
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
session = boto3.Session()

CONFIG_TABLE_NAME = os.environ['CONFIG_TABLE_NAME']
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')

table = dynamodb.Table(CONFIG_TABLE_NAME)


def get_data_plane_endpoint(region: str) -> str:
    return f"https://bedrock-agentcore.{region}.amazonaws.com"


def parse_runtime_arn(runtime_arn: str) -> dict:
    parts = runtime_arn.split(':')
    if len(parts) != 6:
        raise ValueError(f"Invalid runtime ARN: {runtime_arn}")
    resource = parts[5]
    if not resource.startswith('runtime/'):
        raise ValueError(f"Invalid runtime ARN resource: {resource}")
    return {
        'region': parts[3],
        'account_id': parts[4],
        'runtime_id': resource.split('/', 1)[1],
    }


def get_or_create_session(client_id: str) -> str:
    """Get existing session_id for client or create new one. AgentCore requires length >= 33."""
    try:
        response = table.get_item(Key={'pk': f'UI_SESSION#{client_id}', 'sk': 'session'})
        if 'Item' in response:
            session_id = response['Item']['session_id']
            if len(session_id) >= 33:
                return session_id
            # Existing short session_id; replace with valid one and update DB
    except Exception as e:
        logger.warning(f"Failed to get session: {e}")
    
    session_id = f"ui-{client_id}-{uuid.uuid4().hex}"
    try:
        table.put_item(Item={
            'pk': f'UI_SESSION#{client_id}',
            'sk': 'session',
            'session_id': session_id,
            'created_at': str(int(__import__('time').time())),
        })
    except Exception as e:
        logger.warning(f"Failed to save session: {e}")
    
    return session_id


def get_session_agent_mode(session_id: str) -> tuple:
    """Load agent_id and mode_id for session from DynamoDB. Returns (agent_id, mode_id)."""
    if not table:
        return (None, None)
    try:
        r = table.get_item(Key={"pk": "SESSION_AGENT", "sk": session_id})
        if "Item" not in r:
            return (None, None)
        item = r["Item"]
        return (item.get("agent_id"), item.get("mode_id"))
    except Exception as e:
        logger.debug("get_session_agent_mode: %s", e)
        return (None, None)


def invoke_agent(prompt: str, session_id: str, stream: bool = False, agent_id: str = None, mode_id: str = None) -> dict:
    """Invoke AgentCore Runtime via signed HTTP request. Forwards agent_id and mode_id when set."""
    if not AGENTCORE_RUNTIME_ARN:
        return {"error": "Agent runtime not configured"}

    if agent_id is None and mode_id is None:
        agent_id, mode_id = get_session_agent_mode(session_id)

    import urllib.request

    try:
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        payload = {"prompt": prompt, "session_id": session_id}
        if stream:
            payload["stream"] = True
        if agent_id:
            payload["agent_id"] = agent_id
        if mode_id:
            payload["mode_id"] = mode_id
        body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
        }
        aws_request = AWSRequest(method='POST', url=url, data=body, headers=headers)
        credentials = session.get_credentials()
        if credentials:
            SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
        req = urllib.request.Request(
            url, data=body, headers=dict(aws_request.headers), method='POST'
        )
        with urllib.request.urlopen(req, timeout=180) as response:
            result = json.loads(response.read().decode())
            logger.info(f"Agent response keys: {list(result.keys()) if isinstance(result, dict) else 'not-dict'}")
            if isinstance(result, dict) and result.get('error'):
                logger.warning(f"Agent returned error: {result.get('error')}")
            return result if isinstance(result, dict) else {"message": str(result)}
    except Exception as e:
        logger.error(f"Failed to invoke agent: {e}", exc_info=True)
        return {"error": f"gateway_invoke_agent: {e}"}


def invoke_api(path: str, method: str, body: dict, session_id: str) -> dict:
    """Invoke AgentCore Runtime with _ui_api_request payload."""
    if not AGENTCORE_RUNTIME_ARN:
        return {"error": "Agent runtime not configured"}
    
    import urllib.request
    import urllib.error
    
    try:
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        payload = {
            "_ui_api_request": {
                "path": path,
                "method": method,
                "body": body,
            }
        }
        req_body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
        }
        aws_request = AWSRequest(method='POST', url=url, data=req_body, headers=headers)
        credentials = session.get_credentials()
        if credentials:
            SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
        req = urllib.request.Request(
            url, data=req_body, headers=dict(aws_request.headers), method='POST'
        )
        with urllib.request.urlopen(req, timeout=180) as response:
            result = json.loads(response.read().decode())
            return result if isinstance(result, dict) else {"data": result}
    except urllib.error.HTTPError as e:
        err_body = e.fp.read().decode() if e.fp else ''
        try:
            e.fp.close()
        except Exception:
            pass
        logger.error(f"AgentCore HTTP {e.code}: {e.reason} body=%s", err_body[:500])
        return {"error": f"gateway_invoke_api: AgentCore HTTP {e.code}: {e.reason}. {err_body[:500]}"}
    except Exception as e:
        logger.error(f"Failed to invoke API: {e}", exc_info=True)
        return {"error": f"gateway_invoke_api: {e}"}


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj) if obj % 1 else int(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def handler(event, context):
    """Lambda handler for gateway. Routes requests to AgentCore Runtime."""
    logger.info(f"Received event: {json.dumps(event)[:500]}")
    
    # Handle CloudWatch Events keepalive
    if event.get('source') == 'aws.events':
        return {'statusCode': 200, 'body': json.dumps({'status': 'healthy'})}
    
    # Parse request
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')
    path = event.get('rawPath', '/')
    headers = event.get('headers', {})
    
    # Get or create client session
    client_id = headers.get('x-client-id') or headers.get('X-Client-Id') or 'anonymous'
    session_id = get_or_create_session(client_id)
    
    # Parse body
    body = {}
    if event.get('body'):
        try:
            raw_body = event['body']
            if event.get('isBase64Encoded'):
                import base64
                raw_body = base64.b64decode(raw_body).decode('utf-8')
            body = json.loads(raw_body)
        except Exception as e:
            logger.warning(f"Failed to parse body: {e}")
    
    # Route requests
    response_body = {}
    status_code = 200
    
    try:
        # Health check
        if path == '/health' or path == '/':
            response_body = {'status': 'healthy', 'session_id': session_id}
        
        # Chat invocation
        elif path == '/invocations' and http_method == 'POST':
            prompt = body.get('prompt', '')
            stream = body.get('stream', False)
            agent_id = body.get('agent_id') or None
            mode_id = body.get('mode_id') or None
            if not prompt:
                response_body = {'error': 'No prompt provided'}
                status_code = 400
            else:
                response_body = invoke_agent(prompt, session_id, stream=stream, agent_id=agent_id, mode_id=mode_id)
        
        # API proxy routes: /api/* (from nginx) or direct paths (from UI with Lambda base URL)
        elif path.startswith('/api/'):
            api_path = '/' + path[5:]
            response_body = invoke_api(api_path, http_method, body, session_id)
        elif (path in ('/status', '/telegram/config', '/ollama/health', '/memory/summary', '/telemetry', '/streaming-info', '/mcp/servers', '/agents', '/modes') or
              path.startswith('/skills') or path.startswith('/sessions/')):
            response_body = invoke_api(path, http_method, body, session_id)
        else:
            response_body = {'error': f'Unknown path: {path}'}
            status_code = 404
    
    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        response_body = {'error': f'gateway_handler: {e}'}
        status_code = 500
    
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, X-Client-Id, X-Session-Id',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        },
        'body': json.dumps(response_body, default=decimal_default),
    }
`;
  }
}

// --- TelegramWebhookStack ---

export interface TelegramWebhookStackProps extends cdk.StackProps {
  readonly configTable: dynamodb.ITable;
  readonly telegramBotTokenSecret: secretsmanager.ISecret;
  readonly agentCoreRuntimeArn: string;
}

/**
 * Telegram webhook stack: Lambda that receives Telegram updates and invokes AgentCore runtime.
 */
export class TelegramWebhookStack extends cdk.Stack {
  public readonly webhookFunction: lambda.Function;
  public readonly webhookUrl: string;

  constructor(scope: Construct, id: string, props: TelegramWebhookStackProps) {
    super(scope, id, props);

    const { configTable, telegramBotTokenSecret, agentCoreRuntimeArn } = props;

    this.webhookFunction = new lambda.Function(this, 'TelegramWebhookFunction', {
      functionName: 'glitch-telegram-webhook',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromInline(this.getLambdaCode()),
      timeout: cdk.Duration.seconds(300),
      memorySize: 256,
      environment: {
        CONFIG_TABLE_NAME: configTable.tableName,
        TELEGRAM_SECRET_NAME: 'glitch/telegram-bot-token',
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
      },
    });

    configTable.grantReadWriteData(this.webhookFunction);
    telegramBotTokenSecret.grantRead(this.webhookFunction);

    this.webhookFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'InvokeAgentCoreRuntime',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:*'],
        resources: [
          agentCoreRuntimeArn,
          `${agentCoreRuntimeArn}/*`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:code-interpreter/*`,
        ],
      })
    );

    const functionUrl = this.webhookFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [lambda.HttpMethod.POST],
      },
    });

    this.webhookUrl = functionUrl.url;

    const keepaliveFunction = new lambda.Function(this, 'AgentCoreKeepaliveFunction', {
      functionName: 'glitch-agentcore-keepalive',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromInline(this.getKeepaliveLambdaCode()),
      timeout: cdk.Duration.seconds(30),
      memorySize: 128,
      environment: { AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn },
    });
    keepaliveFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [agentCoreRuntimeArn, `${agentCoreRuntimeArn}/*`],
      })
    );
    new events.Rule(this, 'AgentCoreKeepaliveSchedule', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(10)),
      targets: [new targets.LambdaFunction(keepaliveFunction)],
      description: 'Invoke AgentCore runtime keepalive every 10 min to avoid session termination',
    });

    new cdk.CfnOutput(this, 'TelegramWebhookUrl', {
      value: this.webhookUrl,
      description: 'Telegram webhook Lambda Function URL',
    });
  }

  private getLambdaCode(): string {
    return `
import json
import os
import logging
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from datetime import datetime, timedelta
from urllib.parse import quote

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')
session = boto3.Session()

CONFIG_TABLE_NAME = os.environ['CONFIG_TABLE_NAME']
TELEGRAM_SECRET_NAME = os.environ['TELEGRAM_SECRET_NAME']
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')

table = dynamodb.Table(CONFIG_TABLE_NAME)


def get_data_plane_endpoint(region: str) -> str:
    return f"https://bedrock-agentcore.{region}.amazonaws.com"


def parse_runtime_arn(runtime_arn: str) -> dict:
    parts = runtime_arn.split(':')
    if len(parts) != 6:
        raise ValueError(f"Invalid runtime ARN: {runtime_arn}")
    resource = parts[5]
    if not resource.startswith('runtime/'):
        raise ValueError(f"Invalid runtime ARN resource: {resource}")
    return {
        'region': parts[3],
        'account_id': parts[4],
        'runtime_id': resource.split('/', 1)[1],
    }


def get_bot_token():
    response = secrets_client.get_secret_value(SecretId=TELEGRAM_SECRET_NAME)
    return response['SecretString']


def get_webhook_secret():
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': 'webhook_secret'})
        if 'Item' in response:
            return response['Item']['value']
    except Exception as e:
        logger.warning(f"Failed to get webhook secret: {e}")
    import secrets
    new_secret = secrets.token_hex(32)
    table.put_item(Item={'pk': 'CONFIG', 'sk': 'webhook_secret', 'value': new_secret})
    return new_secret


def _int_or(v, default=None):
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_config():
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': 'main'})
        if 'Item' in response:
            item = response['Item']
            if 'owner_id' in item:
                item = {**item, 'owner_id': _int_or(item['owner_id'], item['owner_id'])}
            return item
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
    return None


_bot_info_cache = {}


def get_bot_info(bot_token: str) -> dict:
    if bot_token in _bot_info_cache:
        return _bot_info_cache[bot_token]
    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get('ok') and data.get('result'):
                r = data['result']
                _bot_info_cache[bot_token] = {'username': (r.get('username') or '').lower(), 'id': r.get('id')}
                return _bot_info_cache[bot_token]
    except Exception as e:
        logger.warning(f"getMe failed: {e}")
    _bot_info_cache[bot_token] = {'username': '', 'id': None}
    return _bot_info_cache[bot_token]


def is_group_chat(chat: dict) -> bool:
    return (chat or {}).get('type') in ('group', 'supergroup')


def is_private_chat(chat: dict) -> bool:
    return (chat or {}).get('type') == 'private'


def is_bot_mentioned(message: dict, bot_username: str, bot_id) -> bool:
    if not bot_username and bot_id is None:
        return False
    text = (message or {}).get('text') or ''
    entities = (message or {}).get('entities') or []
    for e in entities:
        if e.get('type') == 'mention':
            mention = text[e['offset']:e['offset'] + e['length']].lstrip('@').lower()
            if mention == bot_username:
                return True
        if e.get('type') == 'text_mention':
            if e.get('user', {}).get('id') == bot_id:
                return True
    return False


def strip_bot_mention_from_text(message: dict, bot_username: str, bot_id) -> str:
    text = (message or {}).get('text') or ''
    entities = (message or {}).get('entities') or []
    for e in sorted(entities, key=lambda x: -x.get('offset', 0)):
        if e.get('type') == 'mention':
            mention = text[e['offset']:e['offset'] + e['length']].lstrip('@').lower()
            if mention == bot_username:
                before = text[:e['offset']].strip()
                after = text[e['offset'] + e['length']:].strip()
                return ' '.join([before, after]).strip() or ''
        if e.get('type') == 'text_mention' and e.get('user', {}).get('id') == bot_id:
            before = text[:e['offset']].strip()
            after = text[e['offset'] + e['length']:].strip()
            return ' '.join([before, after]).strip() or ''
    return text.strip()


def is_user_allowed_dm(user_id, config: dict) -> bool:
    if not config:
        return False
    owner_id = _int_or(config.get('owner_id'))
    if owner_id is not None and owner_id == _int_or(user_id):
        return True
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': f"allowed_dm#{user_id}"})
        return 'Item' in response
    except Exception:
        return False


def allow_dm(user_id: int) -> None:
    table.put_item(Item={'pk': 'CONFIG', 'sk': f"allowed_dm#{user_id}", 'user_id': user_id})
    logger.info(f"Allowed DM for user {user_id}")


def revoke_dm(user_id: int) -> None:
    table.delete_item(Key={'pk': 'CONFIG', 'sk': f"allowed_dm#{user_id}"})
    logger.info(f"Revoked DM for user {user_id}")


def list_allowed_dm_user_ids() -> list:
    try:
        response = table.query(
            KeyConditionExpression='pk = :pk AND begins_with(sk, :sk)',
            ExpressionAttributeValues={':pk': 'CONFIG', ':sk': 'allowed_dm#'}
        )
        return [int(item['user_id']) for item in response.get('Items', []) if item.get('user_id')]
    except Exception as e:
        logger.warning(f"list_allowed_dm failed: {e}")
        return []


def set_owner(user_id: int):
    table.put_item(Item={
        'pk': 'CONFIG',
        'sk': 'main',
        'owner_id': user_id,
        'claimed_at': datetime.utcnow().isoformat() + 'Z',
        'status': 'claimed',
    })
    logger.info(f"Owner set to {user_id}")


def get_pairing_code():
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': 'pairing'})
        if 'Item' in response:
            item = response['Item']
            expires_at = datetime.fromisoformat(item['expires_at'].rstrip('Z'))
            if datetime.utcnow() < expires_at:
                return item['code']
    except Exception as e:
        logger.warning(f"Failed to get pairing code: {e}")
    import secrets
    import string
    alphabet = string.ascii_uppercase + string.digits
    code = ''.join(secrets.choice(alphabet) for _ in range(8))
    expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z'
    ttl = int((datetime.utcnow() + timedelta(hours=2)).timestamp())
    table.put_item(Item={
        'pk': 'CONFIG',
        'sk': 'pairing',
        'code': code,
        'expires_at': expires_at,
        'ttl': ttl,
    })
    logger.info("Generated new pairing code (expires in 1 hour)")
    return code


def validate_pairing_code(code: str, user_id: int) -> bool:
    config = get_config()
    if config and config.get('status') in ('claimed', 'locked'):
        logger.warning(f"Pairing rejected: already {config.get('status')}")
        return False
    stored_code = get_pairing_code()
    if code.upper() == stored_code:
        set_owner(user_id)
        table.delete_item(Key={'pk': 'CONFIG', 'sk': 'pairing'})
        return True
    logger.warning(f"Invalid pairing code from user {user_id}")
    return False


def send_telegram_message(chat_id: int, text: str, bot_token: str):
    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = json.dumps({'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


def invoke_agent(prompt: str, session_id: str):
    if not AGENTCORE_RUNTIME_ARN:
        logger.warning("AGENTCORE_RUNTIME_ARN not set")
        return "Agent runtime not configured."
    logger.info("Invoking agent: prompt_len=%d session_id=%s", len(prompt or ""), session_id)
    import urllib.request
    try:
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        payload = {"prompt": prompt, "session_id": session_id}
        body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
        }
        aws_request = AWSRequest(method='POST', url=url, data=body, headers=headers)
        credentials = session.get_credentials()
        if credentials:
            SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
        req = urllib.request.Request(url, data=body, headers=dict(aws_request.headers), method='POST')
        with urllib.request.urlopen(req, timeout=180) as response:
            result = json.loads(response.read().decode())
            logger.info("Invoke agent success: has_message=%s", bool(isinstance(result, dict) and result.get('message')))
            return result if isinstance(result, dict) else str(result)
    except Exception as e:
        logger.error(f"Failed to invoke agent: {e}", exc_info=True)
        return f"Error: {e}"


def handler(event, context):
    logger.info("Received event: %s", json.dumps(event)[:500])
    try:
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})
    except Exception as e:
        logger.error(f"Failed to parse body: {e}")
        return {'statusCode': 400, 'body': 'Invalid JSON'}
    headers = event.get('headers', {})
    secret_token = headers.get('x-telegram-bot-api-secret-token')
    expected_secret = get_webhook_secret()
    if secret_token and secret_token != expected_secret:
        logger.warning("Invalid webhook secret")
        return {'statusCode': 403, 'body': 'Forbidden'}
    try:
        bot_token = get_bot_token()
    except Exception as e:
        logger.error(f"Failed to get bot token: {e}", exc_info=True)
        return {'statusCode': 200, 'body': 'OK'}
    message = body.get('message', {})
    if not message:
        return {'statusCode': 200, 'body': 'OK'}
    chat_id = message.get('chat', {}).get('id')
    user_id = _int_or(message.get('from', {}).get('id'))
    text = (message.get('text') or '').strip()
    if not chat_id or not text:
        return {'statusCode': 200, 'body': 'OK'}
    logger.info("Message from user %s in chat %s: %s", user_id, chat_id, text[:100])
    try:
        config = get_config()
    except Exception as e:
        logger.error(f"Failed to get config: {e}", exc_info=True)
        return {'statusCode': 200, 'body': 'OK'}
    is_claimed = config and config.get('status') in ('claimed', 'locked')
    if not is_claimed:
        if validate_pairing_code(text, user_id):
            send_telegram_message(chat_id, "✅ You are now the owner. Use /help for commands.", bot_token)
        else:
            send_telegram_message(chat_id, "❌ Bot not configured. Send the pairing code from startup logs.", bot_token)
        return {'statusCode': 200, 'body': 'OK'}
    if text.startswith('/'):
        cmd = text.split()[0].lower()
        owner_id = _int_or(config.get('owner_id'))
        is_owner = (user_id is not None and owner_id is not None and user_id == owner_id)
        if cmd == '/help' or cmd == '/start':
            help_text = "🤖 *Glitch Bot*\\n\\n/new - New conversation\\n/status - Status\\n/help - This message"
            if is_owner:
                help_text += "\\n/allow <user_id> - Allow DM\\n/revoke <user_id> - Revoke DM\\n/allowed - List allowed"
            send_telegram_message(chat_id, help_text, bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/status':
            send_telegram_message(chat_id, "📊 Owner: \`" + str(owner_id) + "\` Status: " + config.get('status', 'unknown'), bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/allow' and is_owner:
            parts = text.split()
            target_id = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            if message.get('reply_to_message', {}).get('from'):
                target_id = message['reply_to_message']['from'].get('id')
            if target_id is not None:
                allow_dm(target_id)
                send_telegram_message(chat_id, "✅ User \`" + str(target_id) + "\` can DM.", bot_token)
            else:
                send_telegram_message(chat_id, "Usage: /allow <user_id> or reply + /allow", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/revoke' and is_owner:
            parts = text.split()
            target_id = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            if message.get('reply_to_message', {}).get('from'):
                target_id = message['reply_to_message']['from'].get('id')
            if target_id is not None:
                revoke_dm(target_id)
                send_telegram_message(chat_id, "Revoked DM for \`" + str(target_id) + "\`.", bot_token)
            else:
                send_telegram_message(chat_id, "Usage: /revoke <user_id> or reply + /revoke", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/allowed' and is_owner:
            allowed = list_allowed_dm_user_ids()
            send_telegram_message(chat_id, "Allowed to DM: " + (", ".join(str(u) for u in allowed) if allowed else "Only owner"), bot_token)
            return {'statusCode': 200, 'body': 'OK'}
    chat = message.get('chat', {})
    if is_group_chat(chat):
        bot_info = get_bot_info(bot_token)
        if not is_bot_mentioned(message, bot_info.get('username'), bot_info.get('id')):
            return {'statusCode': 200, 'body': 'OK'}
        text = strip_bot_mention_from_text(message, bot_info.get('username'), bot_info.get('id'))
        if not text:
            return {'statusCode': 200, 'body': 'OK'}
    elif is_private_chat(chat):
        if not is_user_allowed_dm(user_id, config):
            send_telegram_message(chat_id, "You are not authorized to DM this bot.", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
    try:
        base_session = f"telegram:dm:{chat_id}" if is_private_chat(chat) else f"telegram:group:{chat_id}"
        session_id = base_session.ljust(33, '0')
        result = invoke_agent(text, session_id)
        if isinstance(result, dict):
            message_text = result.get('message') or result.get('response') or str(result)
            send_telegram_message(chat_id, message_text, bot_token)
        else:
            send_telegram_message(chat_id, str(result), bot_token)
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        try:
            send_telegram_message(chat_id, "Sorry, something went wrong. Please try again.", bot_token)
        except Exception:
            pass
    return {'statusCode': 200, 'body': 'OK'}
`;
  }

  private getKeepaliveLambdaCode(): string {
    return `
import json
import os
import urllib.request
from urllib.parse import quote
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

def get_data_plane_endpoint(region):
    return "https://bedrock-agentcore." + region + ".amazonaws.com"

def parse_runtime_arn(arn):
    parts = arn.split(':')
    if len(parts) != 6 or not (parts[5] or '').startswith('runtime/'):
        raise ValueError("Invalid runtime ARN: " + str(arn))
    return {'region': parts[3], 'account_id': parts[4], 'runtime_id': parts[5].split('/', 1)[1]}

def handler(event, context):
    arn = os.environ.get('AGENTCORE_RUNTIME_ARN', '')
    if not arn:
        return
    try:
        parts = parse_runtime_arn(arn)
        region = parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(arn, safe='')
        url = endpoint + "/runtimes/" + encoded_arn + "/invocations"
        payload = {"prompt": "ping", "session_id": "system:keepalive"}
        body = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': 'system:keepalive'}
        session = boto3.Session()
        creds = session.get_credentials()
        if creds:
            req = AWSRequest(method='POST', url=url, data=body, headers=headers)
            SigV4Auth(creds, 'bedrock-agentcore', region).add_auth(req)
            headers = dict(req.headers)
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except Exception as e:
        import logging
        logging.getLogger().warning("Keepalive invoke failed: %s", e)
`;
  }
}

// --- GlitchCertificateStack ---

export interface GlitchCertificateStackProps extends cdk.StackProps {
  readonly domainName: string;
}

/**
 * Certificate stack for CloudFront custom domain. Must be deployed in us-east-1.
 */
export class GlitchCertificateStack extends cdk.Stack {
  public readonly certificate: acm.Certificate;

  constructor(scope: Construct, id: string, props: GlitchCertificateStackProps) {
    super(scope, id, props);

    const { domainName } = props;

    this.certificate = new acm.Certificate(this, 'Certificate', {
      domainName,
      validation: acm.CertificateValidation.fromDns(),
    });

    new cdk.CfnOutput(this, 'CertificateArn', {
      value: this.certificate.certificateArn,
      description: 'ACM Certificate ARN for CloudFront',
      exportName: 'GlitchCertificateArn',
    });

    new cdk.CfnOutput(this, 'DomainName', {
      value: domainName,
      description: 'Domain name for the certificate',
    });

    new cdk.CfnOutput(this, 'ValidationInstructions', {
      value: `Add the CNAME record shown in ACM console to your DNS provider (Porkbun) to validate the certificate.`,
      description: 'Instructions for certificate validation',
    });
  }
}

// --- GlitchUiHostingStack ---

export interface GlitchUiHostingStackProps extends cdk.StackProps {
  readonly gatewayFunctionUrlHostname: string;
  readonly domainName?: string;
  readonly certificateArn?: string;
}

/**
 * Glitch UI Hosting stack: S3 bucket + CloudFront distribution for serving the React UI.
 */
export class GlitchUiHostingStack extends cdk.Stack {
  public readonly distribution: cloudfront.Distribution;
  public readonly uiBucket: s3.Bucket;
  public readonly distributionUrl: string;

  constructor(scope: Construct, id: string, props: GlitchUiHostingStackProps) {
    super(scope, id, props);

    const { gatewayFunctionUrlHostname, domainName, certificateArn } = props;

    this.uiBucket = new s3.Bucket(this, 'UiBucket', {
      bucketName: `glitch-ui-${this.account}-${this.region}`,
      blockPublicAccess: new s3.BlockPublicAccess({
        blockPublicAcls: true,
        blockPublicPolicy: false,
        ignorePublicAcls: true,
        restrictPublicBuckets: false,
      }),
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      websiteIndexDocument: 'index.html',
      websiteErrorDocument: 'index.html',
    });
    this.uiBucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: 'PublicReadGetObject',
        effect: iam.Effect.ALLOW,
        principals: [new iam.AnyPrincipal()],
        actions: ['s3:GetObject'],
        resources: [this.uiBucket.arnForObjects('*')],
      })
    );

    const oac = new cloudfront.S3OriginAccessControl(this, 'UiOac', {
      originAccessControlName: 'glitch-ui-oac',
      signing: cloudfront.Signing.SIGV4_ALWAYS,
    });

    const s3Origin = origins.S3BucketOrigin.withOriginAccessControl(this.uiBucket, {
      originAccessControl: oac,
    });

    const lambdaOrigin = new origins.HttpOrigin(gatewayFunctionUrlHostname, {
      protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
    });

    const apiOriginRequestPolicy = new cloudfront.OriginRequestPolicy(
      this,
      'ApiOriginRequestPolicy',
      {
        originRequestPolicyName: 'glitch-api-forward-headers',
        headerBehavior: cloudfront.OriginRequestHeaderBehavior.allowList(
          'X-Client-Id',
          'X-Session-Id',
          'Content-Type'
        ),
        queryStringBehavior: cloudfront.OriginRequestQueryStringBehavior.all(),
        cookieBehavior: cloudfront.OriginRequestCookieBehavior.none(),
      }
    );

    const certificate = certificateArn
      ? acm.Certificate.fromCertificateArn(this, 'Certificate', certificateArn)
      : undefined;

    this.distribution = new cloudfront.Distribution(this, 'UiDistribution', {
      comment: domainName ? `Glitch UI - ${domainName}` : 'Glitch UI - S3 static + Lambda API',
      defaultRootObject: 'index.html',
      domainNames: domainName ? [domainName] : undefined,
      certificate,
      defaultBehavior: {
        origin: s3Origin,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
      },
      additionalBehaviors: {
        '/api/*': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: apiOriginRequestPolicy,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        },
        '/invocations': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: apiOriginRequestPolicy,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        },
        '/health': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: apiOriginRequestPolicy,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        },
      },
      errorResponses: [],
    });

    this.distributionUrl = domainName
      ? `https://${domainName}`
      : `https://${this.distribution.distributionDomainName}`;

    new s3deploy.BucketDeployment(this, 'DeployUi', {
      sources: [s3deploy.Source.asset(path.join(__dirname, '../../ui/dist'))],
      destinationBucket: this.uiBucket,
      distribution: this.distribution,
      distributionPaths: ['/*'],
    });

    new cdk.CfnOutput(this, 'UiUrl', {
      value: this.distributionUrl,
      description: 'Glitch UI URL',
      exportName: 'GlitchUiUrl',
    });

    new cdk.CfnOutput(this, 'CloudFrontDomainName', {
      value: this.distribution.distributionDomainName,
      description: 'CloudFront distribution domain name (for DNS CNAME)',
      exportName: 'GlitchCloudFrontDomain',
    });

    new cdk.CfnOutput(this, 'UiBucketName', {
      value: this.uiBucket.bucketName,
      description: 'S3 bucket for UI static assets',
      exportName: 'GlitchUiBucketName',
    });

    new cdk.CfnOutput(this, 'DistributionId', {
      value: this.distribution.distributionId,
      description: 'CloudFront distribution ID',
      exportName: 'GlitchUiDistributionId',
    });

    if (domainName) {
      new cdk.CfnOutput(this, 'DnsInstructions', {
        value: `Add CNAME record: ${domainName} -> ${this.distribution.distributionDomainName}`,
        description: 'DNS record to add in Porkbun',
      });
    }
  }
}

// --- TailscaleStack ---

export interface TailscaleStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly tailscaleAuthKeySecret: secretsmanager.ISecret;
  readonly agentCoreSecurityGroup?: ec2.ISecurityGroup;
  readonly agentCoreRuntimeArn?: string;
  readonly instanceBootstrapVersion?: string;
  readonly gatewayFunctionUrl?: string;
  readonly gatewayHostname?: string;
  readonly uiBucketName?: string;
  readonly customDomain?: string;
  readonly porkbunApiSecret?: secretsmanager.ISecret;
  readonly certbotEmail?: string;
}

export class TailscaleStack extends cdk.Stack {
  public readonly instance: ec2.Instance;
  public readonly securityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: TailscaleStackProps) {
    super(scope, id, props);

    const { vpc, tailscaleAuthKeySecret, gatewayFunctionUrl, gatewayHostname, uiBucketName, customDomain, porkbunApiSecret, certbotEmail } = props;
    const bootstrapVersion = props.instanceBootstrapVersion ??
      this.node.tryGetContext('glitchTailscaleBootstrapVersion') ?? '5';
    const enableUiProxy = Boolean(gatewayFunctionUrl && uiBucketName);
    const enableTls = Boolean(customDomain && porkbunApiSecret);

    this.securityGroup = new ec2.SecurityGroup(this, 'TailscaleSecurityGroup', {
      vpc,
      description: 'Security group for Tailscale EC2 connector',
      allowAllOutbound: false,
    });

    this.securityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'HTTPS to Tailscale coordination server and DERP relays'
    );
    this.securityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.udp(41641),
      'WireGuard direct peer-to-peer tunnels'
    );
    this.securityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.udp(3478),
      'STUN protocol for NAT traversal'
    );
    this.securityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(80),
      'HTTP fallback and captive portal detection'
    );
    this.securityGroup.addEgressRule(
      ec2.Peer.ipv4('10.10.110.0/24'),
      ec2.Port.tcp(11434),
      'Ollama native API to on-prem (e.g. 10.10.110.202)'
    );
    this.securityGroup.addEgressRule(
      ec2.Peer.ipv4('10.10.110.0/24'),
      ec2.Port.tcp(8080),
      'OpenAI-compatible API to on-prem (e.g. 10.10.110.137 LLaVA)'
    );
    this.securityGroup.addIngressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.udp(41641),
      'Allow inbound WireGuard for direct connections'
    );

    if (props.agentCoreSecurityGroup) {
      this.securityGroup.addIngressRule(
        props.agentCoreSecurityGroup,
        ec2.Port.allTraffic(),
        'Allow all traffic from AgentCore ENIs'
      );
    }

    const role = new iam.Role(this, 'TailscaleInstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'IAM role for Tailscale EC2 connector',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });

    tailscaleAuthKeySecret.grantRead(role);
    if (porkbunApiSecret) {
      porkbunApiSecret.grantRead(role);
    }

    const userData = ec2.UserData.forLinux();

    const userDataCommands = [
      '#!/bin/bash',
      'set -e',
      '',
      'echo "Installing AWS CLI and retrieving Tailscale auth key..."',
      'yum install -y aws-cli',
      '',
      `TAILSCALE_AUTH_KEY=$(aws secretsmanager get-secret-value --secret-id ${tailscaleAuthKeySecret.secretName} --query SecretString --output text --region ${this.region})`,
      '',
      'echo "Setting hostname for predictable Tailscale URL..."',
      'hostnamectl set-hostname glitch-tailscale',
      '',
      'echo "Installing Tailscale..."',
      'curl -fsSL https://tailscale.com/install.sh | sh',
      '',
      'echo "Enabling IP forwarding..."',
      'echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf',
      'echo "net.ipv6.conf.all.forwarding = 1" >> /etc/sysctl.conf',
      'sysctl -p /etc/sysctl.conf',
      '',
      'echo "Starting Tailscale with auth key..."',
      'tailscale up --authkey="$TAILSCALE_AUTH_KEY" --advertise-tags=tag:aws-agent --accept-routes --advertise-routes=10.10.110.0/24',
      '',
      'echo "Clearing auth key from memory..."',
      'unset TAILSCALE_AUTH_KEY',
      '',
      'echo "Tailscale setup complete!"',
      'tailscale status',
    ];

    if (enableUiProxy) {
      const gatewayUrl = gatewayFunctionUrl!.replace(/\/$/, '');
      const lambdaHost = gatewayHostname ?? gatewayUrl.replace(/^https?:\/\//, '');
      const serverNames = customDomain ? `${customDomain} _` : '_';

      userDataCommands.push(
        '',
        'echo "Setting up nginx UI proxy..."',
        'yum install -y nginx',
        '',
        'echo "Setting up Ollama reverse proxy..."',
        'cat > /etc/nginx/conf.d/ollama-proxy.conf << \'OLLAMAEOF\'',
        '# Ollama proxy for AgentCore ENIs',
        'server {',
        '    listen 11434;',
        '    location / {',
        '        proxy_pass http://10.10.110.202:11434;',
        '        proxy_http_version 1.1;',
        '        proxy_set_header Host $host;',
        '        proxy_set_header Connection "";',
        '        proxy_buffering off;',
        '        proxy_read_timeout 300s;',
        '    }',
        '}',
        'server {',
        '    listen 8080;',
        '    location / {',
        '        proxy_pass http://10.10.110.137:8080;',
        '        proxy_http_version 1.1;',
        '        proxy_set_header Host $host;',
        '        proxy_set_header Connection "";',
        '        proxy_buffering off;',
        '        proxy_read_timeout 300s;',
        '    }',
        '}',
        'OLLAMAEOF',
        ''
      );

      if (enableTls && porkbunApiSecret) {
        const email = certbotEmail || 'admin@' + customDomain;
        userDataCommands.push(
          'echo "Setting up Let\'s Encrypt with Porkbun DNS..."',
          'yum install -y python3 python3-pip augeas-libs',
          'pip3 install certbot certbot-dns-porkbun',
          '',
          '# Retrieve Porkbun API credentials',
          `PORKBUN_CREDS=$(aws secretsmanager get-secret-value --secret-id ${porkbunApiSecret.secretName} --query SecretString --output text --region ${this.region})`,
          'PORKBUN_API_KEY=$(echo "$PORKBUN_CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)[\'apiKey\'])")',
          'PORKBUN_SECRET_KEY=$(echo "$PORKBUN_CREDS" | python3 -c "import sys,json; print(json.load(sys.stdin)[\'secretApiKey\'])")',
          '',
          'mkdir -p /etc/letsencrypt',
          'cat > /etc/letsencrypt/porkbun.ini << PORKBUNEOF',
          'dns_porkbun_key = $PORKBUN_API_KEY',
          'dns_porkbun_secret = $PORKBUN_SECRET_KEY',
          'PORKBUNEOF',
          'chmod 600 /etc/letsencrypt/porkbun.ini',
          '',
          'unset PORKBUN_CREDS PORKBUN_API_KEY PORKBUN_SECRET_KEY',
          '',
          `certbot certonly --non-interactive --agree-tos --email ${email} \\`,
          `  --authenticator dns-porkbun \\`,
          `  --dns-porkbun-credentials /etc/letsencrypt/porkbun.ini \\`,
          `  --dns-porkbun-propagation-seconds 60 \\`,
          `  -d ${customDomain}`,
          '',
          'echo "0 3 * * * root certbot renew --quiet --post-hook \\"systemctl reload nginx\\"" > /etc/cron.d/certbot-renew',
          ''
        );
      }

      if (enableTls) {
        userDataCommands.push(
          `cat > /etc/nginx/conf.d/glitch-proxy.conf << 'NGINXEOF'`,
          '# Redirect HTTP to HTTPS',
          'server {',
          '    listen 80;',
          `    server_name ${serverNames};`,
          `    return 301 https://${customDomain}$request_uri;`,
          '}',
          '',
          'server {',
          '    listen 443 ssl;',
          '    http2 on;',
          `    server_name ${serverNames};`,
          '',
          `    ssl_certificate /etc/letsencrypt/live/${customDomain}/fullchain.pem;`,
          `    ssl_certificate_key /etc/letsencrypt/live/${customDomain}/privkey.pem;`,
          '    ssl_protocols TLSv1.2 TLSv1.3;',
          '    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;',
          '    ssl_prefer_server_ciphers off;',
          '',
          '    location / {',
          `        proxy_pass http://${uiBucketName}.s3-website-${this.region}.amazonaws.com;`,
          `        proxy_set_header Host ${uiBucketName}.s3-website-${this.region}.amazonaws.com;`,
          '        proxy_set_header X-Real-IP $remote_addr;',
          '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
          '        proxy_set_header X-Forwarded-Proto $scheme;',
          '    }',
          '',
          '    location /api/ {',
          `        proxy_pass ${gatewayUrl}/api/;`,
          `        proxy_set_header Host ${lambdaHost};`,
          '        proxy_set_header X-Real-IP $remote_addr;',
          '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
          '        proxy_set_header X-Forwarded-Proto https;',
          '        proxy_ssl_server_name on;',
          '    }',
          '',
          '    location /invocations {',
          `        proxy_pass ${gatewayUrl}/invocations;`,
          `        proxy_set_header Host ${lambdaHost};`,
          '        proxy_set_header X-Real-IP $remote_addr;',
          '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
          '        proxy_set_header X-Forwarded-Proto https;',
          '        proxy_ssl_server_name on;',
          '        proxy_read_timeout 300s;',
          '        proxy_connect_timeout 60s;',
          '        proxy_send_timeout 60s;',
          '    }',
          '',
          '    location /health {',
          `        proxy_pass ${gatewayUrl}/health;`,
          `        proxy_set_header Host ${lambdaHost};`,
          '        proxy_set_header X-Real-IP $remote_addr;',
          '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
          '        proxy_set_header X-Forwarded-Proto https;',
          '        proxy_ssl_server_name on;',
          '    }',
          '}',
          'NGINXEOF'
        );
      } else {
        userDataCommands.push(
          `cat > /etc/nginx/conf.d/glitch-proxy.conf << 'NGINXEOF'`,
          'server {',
          '    listen 80;',
          `    server_name ${serverNames};`,
          '',
          '    location / {',
          `        proxy_pass http://${uiBucketName}.s3-website-${this.region}.amazonaws.com;`,
          `        proxy_set_header Host ${uiBucketName}.s3-website-${this.region}.amazonaws.com;`,
          '        proxy_set_header X-Real-IP $remote_addr;',
          '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
          '        proxy_set_header X-Forwarded-Proto $scheme;',
          '    }',
          '',
          '    location /api/ {',
          `        proxy_pass ${gatewayUrl}/api/;`,
          `        proxy_set_header Host ${lambdaHost};`,
          '        proxy_set_header X-Real-IP $remote_addr;',
          '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
          '        proxy_set_header X-Forwarded-Proto https;',
          '        proxy_ssl_server_name on;',
          '    }',
          '',
          '    location /invocations {',
          `        proxy_pass ${gatewayUrl}/invocations;`,
          `        proxy_set_header Host ${lambdaHost};`,
          '        proxy_set_header X-Real-IP $remote_addr;',
          '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
          '        proxy_set_header X-Forwarded-Proto https;',
          '        proxy_ssl_server_name on;',
          '        proxy_read_timeout 300s;',
          '        proxy_connect_timeout 60s;',
          '        proxy_send_timeout 60s;',
          '    }',
          '',
          '    location /health {',
          `        proxy_pass ${gatewayUrl}/health;`,
          `        proxy_set_header Host ${lambdaHost};`,
          '        proxy_set_header X-Real-IP $remote_addr;',
          '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
          '        proxy_set_header X-Forwarded-Proto https;',
          '        proxy_ssl_server_name on;',
          '    }',
          '}',
          'NGINXEOF'
        );
      }

      userDataCommands.push(
        '',
        'rm -f /etc/nginx/conf.d/default.conf',
        'systemctl enable nginx',
        'systemctl start nginx'
      );

      if (!enableTls) {
        userDataCommands.push(
          '',
          'echo "Enabling Tailscale Serve for HTTPS..."',
          'tailscale serve --bg http://127.0.0.1:80',
          'echo "Tailscale Serve enabled. UI available via Tailscale HTTPS URL."'
        );
      } else {
        userDataCommands.push(
          '',
          `echo "TLS enabled with Let's Encrypt. UI available at https://${customDomain}"`
        );
      }
    }

    userData.addCommands(...userDataCommands);

    this.instance = new ec2.Instance(this, `TailscaleInstanceBootstrap${bootstrapVersion}`, {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.NANO),
      machineImage: ec2.MachineImage.latestAmazonLinux2023({
        cpuType: ec2.AmazonLinuxCpuType.ARM_64,
        cachedInContext: false,
      }),
      securityGroup: this.securityGroup,
      role,
      userData,
      requireImdsv2: true,
      ssmSessionPermissions: true,
      associatePublicIpAddress: true,
      sourceDestCheck: false,
    });

    cdk.Tags.of(this.instance).add('Name', 'GlitchTailscaleConnector');
    cdk.Tags.of(this.instance).add('Purpose', 'Tailscale-AWS-Bridge');

    const eniLookup = new cr.AwsCustomResource(this, 'TailscalePrimaryEniLookup', {
      onUpdate: {
        service: 'EC2',
        action: 'describeInstances',
        parameters: {
          InstanceIds: [this.instance.instanceId],
        },
        physicalResourceId: cr.PhysicalResourceId.of(this.instance.instanceId),
        outputPaths: ['Reservations.0.Instances.0.NetworkInterfaces.0.NetworkInterfaceId'],
      },
      policy: cr.AwsCustomResourcePolicy.fromSdkCalls({
        resources: cr.AwsCustomResourcePolicy.ANY_RESOURCE,
      }),
    });
    eniLookup.node.addDependency(this.instance);

    const primaryEniId = eniLookup.getResponseField(
      'Reservations.0.Instances.0.NetworkInterfaces.0.NetworkInterfaceId'
    );

    const isolatedSubnets = vpc.isolatedSubnets;
    for (let i = 0; i < isolatedSubnets.length; i++) {
      const subnet = isolatedSubnets[i];
      const routeTable = (subnet as ec2.PrivateSubnet).routeTable;
      if (!routeTable) continue;
      new ec2.CfnRoute(this, `OnPremRoute${i}`, {
        routeTableId: routeTable.routeTableId,
        destinationCidrBlock: '10.10.110.0/24',
        networkInterfaceId: primaryEniId,
      });
    }

    new cdk.CfnOutput(this, 'InstanceId', {
      value: this.instance.instanceId,
      description: 'Tailscale EC2 instance ID',
    });

    new cdk.CfnOutput(this, 'SecurityGroupId', {
      value: this.securityGroup.securityGroupId,
      description: 'Tailscale security group ID',
    });

    new cdk.CfnOutput(this, 'PrivateIp', {
      value: this.instance.instancePrivateIp,
      description: 'Tailscale EC2 private IP',
    });

    new cdk.CfnOutput(this, 'PublicIp', {
      value: this.instance.instancePublicIp,
      description: 'Tailscale EC2 public IP',
    });

    if (enableUiProxy) {
      if (enableTls && customDomain) {
        new cdk.CfnOutput(this, 'GlitchUiUrl', {
          value: `https://${customDomain}`,
          description: 'Glitch UI URL (TLS via Let\'s Encrypt). Accessible only from Tailscale network.',
        });
      } else {
        new cdk.CfnOutput(this, 'TailscaleUiUrl', {
          value: 'https://glitch-tailscale.YOUR_TAILNET.ts.net',
          description: 'Glitch UI via Tailscale Serve. Replace YOUR_TAILNET with your Tailscale network name.',
        });
      }
    }
  }
}

// --- AgentCoreStack ---

export interface AgentCoreStackProps extends cdk.StackProps {
  readonly vpc: ec2.IVpc;
  readonly agentCoreSecurityGroup: ec2.ISecurityGroup;
  /** Runtime role to attach policies to (from GlitchFoundationStack) */
  readonly runtimeRole: iam.IRole;
}

export class AgentCoreStack extends cdk.Stack {
  public readonly agentRuntimeRole: iam.IRole;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { vpc, agentCoreSecurityGroup, runtimeRole } = props;
    this.agentRuntimeRole = runtimeRole;

    // Add egress rules for Ollama proxy
    agentCoreSecurityGroup.addEgressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(11434),
      'Ollama native API via EC2 nginx proxy'
    );
    agentCoreSecurityGroup.addEgressRule(
      ec2.Peer.ipv4(vpc.vpcCidrBlock),
      ec2.Port.tcp(8080),
      'OpenAI-compatible API via EC2 nginx proxy'
    );

    // Attach policies to the runtime role
    new iam.ManagedPolicy(this, 'AgentRuntimeRoleDefaultPolicy', {
      roles: [runtimeRole],
      document: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            sid: 'BedrockModelAccess',
            effect: iam.Effect.ALLOW,
            actions: [
              'bedrock:InvokeModel',
              'bedrock:InvokeModelWithResponseStream',
            ],
            resources: [
              'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0',
              'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0',
              'arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-20250514-v1:0',
              `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
              `arn:aws:bedrock:${this.region}::inference-profile/*`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'ECRImageAccess',
            effect: iam.Effect.ALLOW,
            actions: ['ecr:BatchGetImage', 'ecr:GetDownloadUrlForLayer'],
            resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`],
          }),
          new iam.PolicyStatement({
            sid: 'ECRTokenAccess',
            effect: iam.Effect.ALLOW,
            actions: ['ecr:GetAuthorizationToken'],
            resources: ['*'],
          }),
          new iam.PolicyStatement({
            sid: 'AgentCoreMemoryAccess',
            effect: iam.Effect.ALLOW,
            actions: [
              'bedrock-agentcore:CreateEvent',
              'bedrock-agentcore:GetEvent',
              'bedrock-agentcore:ListEvents',
              'bedrock-agentcore:ListSessions',
              'bedrock-agentcore:CreateMemoryRecord',
              'bedrock-agentcore:GetMemoryRecord',
              'bedrock-agentcore:ListMemoryRecords',
              'bedrock-agentcore:RetrieveMemoryRecords',
            ],
            resources: ['*'],
          }),
          new iam.PolicyStatement({
            sid: 'SecretsManagerAccess',
            effect: iam.Effect.ALLOW,
            actions: ['secretsmanager:GetSecretValue'],
            resources: [
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/api-keys*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/telegram-bot-token*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/pihole-api*`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'CloudWatchLogs',
            effect: iam.Effect.ALLOW,
            actions: [
              'logs:CreateLogGroup',
              'logs:CreateLogStream',
              'logs:PutLogEvents',
              'logs:GetLogEvents',
              'logs:DescribeLogStreams',
            ],
            resources: [
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*:*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*:*`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'TelegramConfigTableAccess',
            effect: iam.Effect.ALLOW,
            actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem', 'dynamodb:Query'],
            resources: [`arn:aws:dynamodb:${this.region}:${this.account}:table/glitch-telegram-config`],
          }),
          new iam.PolicyStatement({
            sid: 'SoulS3Access',
            effect: iam.Effect.ALLOW,
            actions: ['s3:GetObject', 's3:PutObject'],
            resources: [
              `arn:aws:s3:::glitch-agent-state-${this.account}-${this.region}`,
              `arn:aws:s3:::glitch-agent-state-${this.account}-${this.region}/*`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'SoulSsmRead',
            effect: iam.Effect.ALLOW,
            actions: ['ssm:GetParameter', 'ssm:GetParameters'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/s3-bucket`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/s3-key`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/poet-soul-s3-key`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'CloudWatchMetricsWrite',
            effect: iam.Effect.ALLOW,
            actions: ['cloudwatch:PutMetricData'],
            resources: ['*'],
            conditions: { StringEquals: { 'cloudwatch:namespace': 'Glitch/Agent' } },
          }),
        ],
      }),
    });

    new cdk.CfnOutput(this, 'AgentRuntimeRoleArn', {
      value: runtimeRole.roleArn,
      description: 'IAM role ARN for AgentCore Runtime',
    });

    new cdk.CfnOutput(this, 'AgentCoreSecurityGroupId', {
      value: agentCoreSecurityGroup.securityGroupId,
      description: 'Security group ID for AgentCore ENIs',
    });

    new cdk.CfnOutput(this, 'VpcConfigForAgentCore', {
      value: JSON.stringify({
        subnets: vpc.isolatedSubnets.map(s => s.subnetId),
        securityGroups: [agentCoreSecurityGroup.securityGroupId],
      }),
      description: 'VPC configuration for AgentCore Runtime (JSON)',
    });
  }
}

// --- StorageStackMigrationStack ---

/**
 * One-time migration stack: creates the legacy role and four inline policies
 * so that when GlitchStorageStack is updated (custom resources removed),
 * the existing Custom::AWS Delete handlers can run deleteRolePolicy successfully.
 */
const LEGACY_ROLE_NAME = 'AmazonBedrockAgentCoreSDKRuntime-us-west-2-14980158e2';
const POLICY_NAMES = [
  'GlitchTelegramConfigAccess',
  'GlitchSoulS3Access',
  'GlitchSoulSsmRead',
  'GlitchTelemetryAccess',
] as const;

export class StorageStackMigrationStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const role = new iam.Role(this, 'LegacyRole', {
      roleName: LEGACY_ROLE_NAME,
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: 'Temporary role for GlitchStorageStack custom resource migration; delete this stack after StorageStack update succeeds.',
    });

    const minimalPolicy = {
      Version: '2012-10-17' as const,
      Statement: [{ Effect: 'Allow' as const, Action: 'sts:GetCallerIdentity', Resource: '*' }],
    };
    for (const policyName of POLICY_NAMES) {
      new iam.CfnRolePolicy(this, `Policy${policyName.replace(/[^a-zA-Z0-9]/g, '')}`, {
        roleName: role.roleName,
        policyName: policyName,
        policyDocument: minimalPolicy,
      });
    }

    new cdk.CfnOutput(this, 'LegacyRoleName', {
      value: role.roleName,
      description: 'Role that GlitchStorageStack Delete handlers will target; delete this stack after StorageStack update completes.',
    });
  }
}
