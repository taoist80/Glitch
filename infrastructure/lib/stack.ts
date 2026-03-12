/**
 * All Glitch CDK stacks in a single file.
 * Order: dependency-friendly (interfaces and stacks used by others come first).
 */
import { CfnOutput, CustomResource, Duration, Fn, RemovalPolicy, Stack } from 'aws-cdk-lib';
import type { StackProps } from 'aws-cdk-lib';
import { Certificate } from 'aws-cdk-lib/aws-certificatemanager';
import { AllowedMethods, CachePolicy, CfnDistribution, CfnOriginAccessControl, Distribution, OriginProtocolPolicy, OriginRequestPolicy, ViewerProtocolPolicy } from 'aws-cdk-lib/aws-cloudfront';
import { HttpOrigin, S3BucketOrigin } from 'aws-cdk-lib/aws-cloudfront-origins';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import type { ITable } from 'aws-cdk-lib/aws-dynamodb';
import { InterfaceVpcEndpoint, InterfaceVpcEndpointAwsService, InstanceType as Ec2InstanceType, IpAddresses, Peer, Port, SecurityGroup, SubnetType, Vpc } from 'aws-cdk-lib/aws-ec2';
import type { ISubnet, IVpc } from 'aws-cdk-lib/aws-ec2';
import { Rule, RuleTargetInput, Schedule } from 'aws-cdk-lib/aws-events';
import { LambdaFunction as LambdaFunctionTarget } from 'aws-cdk-lib/aws-events-targets';
import { Effect, ManagedPolicy, PolicyDocument, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import type { IRole } from 'aws-cdk-lib/aws-iam';
import { Code, Function as LambdaFunction, FunctionUrlAuthType, HttpMethod, LayerVersion, Runtime } from 'aws-cdk-lib/aws-lambda';
import type { IFunction, ILayerVersion } from 'aws-cdk-lib/aws-lambda';
import { LogGroup } from 'aws-cdk-lib/aws-logs';
import type { ILogGroup } from 'aws-cdk-lib/aws-logs';
import { BlockPublicAccess, Bucket, BucketEncryption } from 'aws-cdk-lib/aws-s3';
import type { IBucket } from 'aws-cdk-lib/aws-s3';
import { BucketDeployment, CacheControl, Source } from 'aws-cdk-lib/aws-s3-deployment';
import { Secret } from 'aws-cdk-lib/aws-secretsmanager';
import type { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { StringParameter } from 'aws-cdk-lib/aws-ssm';
import { DatabaseInstance, DatabaseInstanceEngine, PostgresEngineVersion, StorageType, Credentials } from 'aws-cdk-lib/aws-rds';
import { CfnIPSet, CfnWebACL } from 'aws-cdk-lib/aws-wafv2';
import { AwsCustomResource, AwsCustomResourcePolicy, PhysicalResourceId } from 'aws-cdk-lib/custom-resources';
import { Construct } from 'constructs';
import * as path from 'path';

// --- Shared constants ---
const BEDROCK_MODEL_ARNS = [
  'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0',
  'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0',
  'arn:aws:bedrock:*::foundation-model/anthropic.claude-opus-4-20250514-v1:0',
] as const;


const TABLE_NAMES = {
  TELEGRAM_CONFIG: 'glitch-telegram-config',
} as const;

const SECRET_NAMES = {
  TELEGRAM_BOT_TOKEN: 'glitch/telegram-bot-token',
  API_KEYS: 'glitch/api-keys',
  SSH_KEY: 'glitch/ssh-key',
  PIHOLE_API: 'glitch/pihole-api',
  GITHUB_TOKEN: 'glitch/github-token',
  UNIFI_CONTROLLER: 'glitch/unifi-controller',
} as const;

/** S3 bucket name for Glitch agent state (SOUL.md, story book). */
const soulBucketName = (account: string, region: string) =>
  `glitch-agent-state-${account}-${region}`;

// --- SSM Parameter Names (single source of truth) ---
export const SSM_PARAMS = {
  VPC_ID: '/glitch/vpc/id',
  PRIVATE_SUBNET_IDS: '/glitch/vpc/private-subnet-ids',
  PUBLIC_SUBNET_IDS: '/glitch/vpc/public-subnet-ids',
  RUNTIME_ROLE_ARN: '/glitch/iam/runtime-role-arn',
  CODEBUILD_ROLE_ARN: '/glitch/iam/codebuild-role-arn',
  TELEGRAM_WEBHOOK_URL: '/glitch/telegram/webhook-url',
  TELEGRAM_CONFIG_TABLE: '/glitch/telegram/config-table',
  OLLAMA_PROXY_HOST: '/glitch/ollama/proxy-host',
} as const;

// --- GlitchFoundationStack ---
// Consolidated stack: VPC + IAM Roles + SSM Parameters.
// AgentCore runtimes run in PUBLIC network mode -- no VPC ENIs, no VPC endpoints needed.
// The VPC exists for the Site-to-Site VPN (on-prem LLM access via UDM-Pro gateway).

export interface GlitchFoundationStackProps extends StackProps {
  readonly vpcCidr?: string;
}

export class GlitchFoundationStack extends Stack {
  public readonly vpc: Vpc;
  public readonly privateSubnets: ISubnet[];
  public readonly publicSubnets: ISubnet[];
  public readonly runtimeRole: Role;
  public readonly codeBuildRole: Role;

  // Secrets (imported from Secrets Manager — formerly SecretsStack)
  public readonly apiKeysSecret: ISecret;
  public readonly telegramBotTokenSecret: ISecret;
  // Storage (imported pre-existing resources — formerly GlitchStorageStack)
  public readonly configTable: ITable;
  public readonly soulBucket: IBucket;
  public readonly telemetryLogGroup: ILogGroup;

  // Shared Lambda layer: agentcore_utils (parse_runtime_arn, get_data_plane_endpoint)
  public readonly agentcoreUtilsLayer: ILayerVersion;

  constructor(scope: Construct, id: string, props?: GlitchFoundationStackProps) {
    super(scope, id, props);

    // ========== VPC ==========
    // No NAT Gateway; agents use PUBLIC mode. Private subnets exist for VPN route propagation only (no internet egress).
    this.vpc = new Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 0,
      ipAddresses: IpAddresses.cidr(props?.vpcCidr || '10.0.0.0/16'),
      subnetConfiguration: [
        { name: 'Public', subnetType: SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'Private', subnetType: SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
      ],
      enableDnsHostnames: true,
      enableDnsSupport: true,
    });

    this.privateSubnets = this.vpc.privateSubnets;
    this.publicSubnets = this.vpc.publicSubnets;

    // ========== IAM Roles (NO hardcoded names) ==========

    this.runtimeRole = new Role(this, 'RuntimeRole', {
      assumedBy: new ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: 'IAM role for AgentCore Runtime (Glitch + Sentinel)',
    });

    // CloudWatch Logs — minimum set for AgentCore runtime startup.
    // Broader log permissions are added per-agent in AgentCoreStack / GlitchSentinelStack.
    this.runtimeRole.addToPolicy(new PolicyStatement({
      sid: 'CloudWatchLogsDescribeGroups',
      effect: Effect.ALLOW,
      actions: ['logs:DescribeLogGroups'],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:*`],
    }));

    // X-Ray: OTEL ADOT traces exporter.
    this.runtimeRole.addToPolicy(new PolicyStatement({
      sid: 'XRayTracing',
      effect: Effect.ALLOW,
      actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords', 'xray:GetSamplingRules', 'xray:GetSamplingTargets'],
      resources: ['*'],
    }));

    // CloudWatch metrics: OTEL ADOT metrics exporter.
    // Scoped to known namespaces to prevent metric pollution.
    this.runtimeRole.addToPolicy(new PolicyStatement({
      sid: 'CloudWatchMetrics',
      effect: Effect.ALLOW,
      actions: ['cloudwatch:PutMetricData'],
      resources: ['*'],
      conditions: {
        StringEquals: {
          'cloudwatch:namespace': ['bedrock-agentcore', 'Glitch/Agent', 'Glitch/Sentinel'],
        },
      },
    }));

    // CodeBuild role for container builds
    this.codeBuildRole = new Role(this, 'CodeBuildRole', {
      assumedBy: new ServicePrincipal('codebuild.amazonaws.com'),
      description: 'IAM role for AgentCore CodeBuild container builds',
    });

    this.codeBuildRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:/aws/codebuild/*`],
    }));

    this.codeBuildRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['s3:GetObject', 's3:GetObjectVersion', 's3:PutObject'],
      resources: [
        `arn:aws:s3:::bedrock-agentcore-codebuild-sources-${this.account}-${this.region}`,
        `arn:aws:s3:::bedrock-agentcore-codebuild-sources-${this.account}-${this.region}/*`,
      ],
    }));

    this.codeBuildRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['s3:GetBucketAcl', 's3:GetBucketLocation'],
      resources: [`arn:aws:s3:::bedrock-agentcore-codebuild-sources-${this.account}-${this.region}`],
    }));

    this.codeBuildRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['ecr:GetAuthorizationToken'],
      resources: ['*'],
    }));

    this.codeBuildRole.addToPolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: [
        'ecr:BatchCheckLayerAvailability',
        'ecr:GetDownloadUrlForLayer',
        'ecr:BatchGetImage',
        'ecr:PutImage',
        'ecr:InitiateLayerUpload',
        'ecr:UploadLayerPart',
        'ecr:CompleteLayerUpload',
      ],
      resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`],
    }));

    // ========== SSM Parameters (for cross-stack references) ==========
    new StringParameter(this, 'SsmVpcId', {
      parameterName: SSM_PARAMS.VPC_ID,
      stringValue: this.vpc.vpcId,
      description: 'Glitch VPC ID',
    });

    new StringParameter(this, 'SsmPrivateSubnets', {
      parameterName: SSM_PARAMS.PRIVATE_SUBNET_IDS,
      stringValue: this.privateSubnets.map(s => s.subnetId).join(','),
      description: 'Glitch private subnet IDs (comma-separated)',
    });

    new StringParameter(this, 'SsmPublicSubnets', {
      parameterName: SSM_PARAMS.PUBLIC_SUBNET_IDS,
      stringValue: this.publicSubnets.map(s => s.subnetId).join(','),
      description: 'Glitch public subnet IDs (comma-separated)',
    });

    new StringParameter(this, 'SsmRuntimeRoleArn', {
      parameterName: SSM_PARAMS.RUNTIME_ROLE_ARN,
      stringValue: this.runtimeRole.roleArn,
      description: 'AgentCore runtime role ARN',
    });

    new StringParameter(this, 'SsmCodeBuildRoleArn', {
      parameterName: SSM_PARAMS.CODEBUILD_ROLE_ARN,
      stringValue: this.codeBuildRole.roleArn,
      description: 'CodeBuild role ARN for agentcore deploy',
    });

    // Use AwsCustomResource + PutParameter Overwrite so re-running the stack (or a param created
    // outside CDK) does not fail with "parameter already exists".
    new AwsCustomResource(this, 'SsmOllamaProxyHost', {
      onUpdate: {
        service: 'SSM',
        action: 'putParameter',
        parameters: {
          Name: SSM_PARAMS.OLLAMA_PROXY_HOST,
          Value: 'home.awoo.agency',
          Type: 'String',
          Overwrite: true,
          Description: 'DDNS hostname for on-prem Ollama proxy (Chat:11434, Vision:18080)',
        },
        physicalResourceId: PhysicalResourceId.of(SSM_PARAMS.OLLAMA_PROXY_HOST),
      },
      policy: AwsCustomResourcePolicy.fromStatements([
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ['ssm:PutParameter'],
          resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter${SSM_PARAMS.OLLAMA_PROXY_HOST}`],
        }),
      ]),
    });

    // ========== Shared Lambda Layer ==========
    this.agentcoreUtilsLayer = new LayerVersion(this, 'AgentcoreUtilsLayer', {
      code: Code.fromAsset(path.join(__dirname, '../lambda/_shared')),
      compatibleRuntimes: [Runtime.PYTHON_3_12],
      description: 'Shared AgentCore helpers: parse_runtime_arn, get_data_plane_endpoint',
    });

    // ========== Secrets (formerly SecretsStack) ==========
    this.apiKeysSecret = Secret.fromSecretNameV2(this, 'ApiKeys', 'glitch/api-keys');
    this.telegramBotTokenSecret = Secret.fromSecretNameV2(this, 'TelegramBotToken', 'glitch/telegram-bot-token');
    // ========== Storage (formerly GlitchStorageStack) ==========
    this.configTable = Table.fromTableName(this, 'ConfigTable', TABLE_NAMES.TELEGRAM_CONFIG);
    this.soulBucket = Bucket.fromBucketName(this, 'GlitchSoulBucket', soulBucketName(this.account, this.region));
    this.telemetryLogGroup = LogGroup.fromLogGroupName(this, 'GlitchTelemetryLogGroup', '/glitch/telemetry');

    new StringParameter(this, 'SoulS3Bucket', {
      parameterName: '/glitch/soul/s3-bucket',
      stringValue: this.soulBucket.bucketName,
      description: 'S3 bucket for Glitch SOUL.md and poet-soul (runtime discovery)',
    });
    new StringParameter(this, 'SoulS3Key', {
      parameterName: '/glitch/soul/s3-key',
      stringValue: 'soul.md',
      description: 'S3 key for SOUL.md',
    });
    new StringParameter(this, 'SoulPoetSoulKey', {
      parameterName: '/glitch/soul/poet-soul-s3-key',
      stringValue: 'poet-soul.md',
      description: 'S3 key for poet-soul.md',
    });
    new StringParameter(this, 'SoulStoryBookKey', {
      parameterName: '/glitch/soul/story-book-s3-key',
      stringValue: 'story-book.md',
      description: 'S3 key for story-book.md',
    });

    // ========== Outputs ==========
    new CfnOutput(this, 'VpcId', { value: this.vpc.vpcId, description: 'VPC ID' });
    new CfnOutput(this, 'PrivateSubnetIds', {
      value: this.privateSubnets.map(s => s.subnetId).join(','),
      description: 'Private subnet IDs',
    });
    new CfnOutput(this, 'RuntimeRoleArn', {
      value: this.runtimeRole.roleArn,
      description: 'Runtime role ARN (use with agentcore configure --execution-role)',
    });
    new CfnOutput(this, 'CodeBuildRoleArn', {
      value: this.codeBuildRole.roleArn,
      description: 'CodeBuild role ARN (set in agent/.bedrock_agentcore.yaml codebuild.execution_role)',
    });
    new CfnOutput(this, 'GlitchSoulBucketName', {
      value: this.soulBucket.bucketName,
      description: 'S3 bucket for Glitch SOUL.md',
    });
  }
}

// --- GlitchProtectDbStack ---

export interface GlitchProtectDbStackProps extends StackProps {
  readonly vpc: IVpc;
}

/**
 * RDS Postgres (db.t4g.micro, single-AZ) for the Protect tab.
 *
 * IAM authentication is the ONLY supported auth method — no password-based
 * connections are permitted. Two IAM DB users exist:
 *   - glitch_iam  — used by the protect-query Lambda (read-only UI queries)
 *   - sentinel_iam — used by the Sentinel agent (event writes)
 *
 * The instance is publicly accessible so that the Sentinel AgentCore runtime
 * (which runs in PUBLIC network mode with no VPC ENIs) can connect. Network
 * security is provided entirely by RDS IAM authentication; no plaintext
 * password ever crosses the wire.
 *
 * Master credentials (for one-time DB setup) are in glitch/protect-db-master.
 * The RDS endpoint is stored in SSM /glitch/protect-db/host so the Sentinel
 * pre-deploy script can pick it up automatically.
 */
export class GlitchProtectDbStack extends Stack {
  public readonly db: DatabaseInstance;

  constructor(scope: Construct, id: string, props: GlitchProtectDbStackProps) {
    super(scope, id, props);
    const { vpc } = props;

    const dbSg = new SecurityGroup(this, 'ProtectDbSg', {
      vpc,
      description: 'protect-db RDS: inbound Postgres (IAM auth only)',
      allowAllOutbound: false,
    });
    // Allow VPC-internal callers (Lambda protect-query)
    dbSg.addIngressRule(Peer.ipv4(vpc.vpcCidrBlock), Port.tcp(5432), 'VPC Postgres access');
    // Allow Sentinel AgentCore runtime (PUBLIC mode, no VPC) over the internet.
    // Auth is enforced exclusively by RDS IAM — no password logins are possible.
    dbSg.addIngressRule(Peer.anyIpv4(), Port.tcp(5432), 'Sentinel AgentCore PUBLIC mode IAM auth');

    this.db = new DatabaseInstance(this, 'ProtectDb', {
      engine: DatabaseInstanceEngine.postgres({ version: PostgresEngineVersion.VER_16 }),
      instanceType: new Ec2InstanceType('t4g.micro'),
      vpc,
      vpcSubnets: { subnetType: SubnetType.PUBLIC },
      securityGroups: [dbSg],
      multiAz: false,
      allocatedStorage: 20,
      storageType: StorageType.GP3,
      databaseName: 'glitch_protect',
      iamAuthentication: true,
      credentials: Credentials.fromGeneratedSecret('glitch', {
        secretName: 'glitch/protect-db-master',
      }),
      deletionProtection: true,
      backupRetention: Duration.days(7),
      storageEncrypted: true,
      publiclyAccessible: true,
    });

    // Store DB connection info in SSM so pre-deploy-configure.py picks it up automatically.
    // Use AwsCustomResource with Overwrite:true so re-deploys succeed even if the
    // parameters were previously created outside CloudFormation.
    const ssmPolicy = AwsCustomResourcePolicy.fromStatements([
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ['ssm:PutParameter'],
        resources: [
          `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect-db/host`,
          `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect-db/port`,
          `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect-db/dbname`,
          `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect-db/sentinel-iam-user`,
        ],
      }),
    ]);

    new AwsCustomResource(this, 'ProtectDbHostParam', {
      onUpdate: {
        service: 'SSM',
        action: 'putParameter',
        parameters: {
          Name: '/glitch/protect-db/host',
          Value: this.db.dbInstanceEndpointAddress,
          Type: 'String',
          Overwrite: true,
          Description: 'Protect DB RDS endpoint hostname (read by Sentinel pre-deploy script)',
        },
        physicalResourceId: PhysicalResourceId.of('/glitch/protect-db/host'),
      },
      policy: ssmPolicy,
    });

    new AwsCustomResource(this, 'ProtectDbPortParam', {
      onUpdate: {
        service: 'SSM',
        action: 'putParameter',
        parameters: {
          Name: '/glitch/protect-db/port',
          Value: '5432',
          Type: 'String',
          Overwrite: true,
          Description: 'Protect DB RDS port',
        },
        physicalResourceId: PhysicalResourceId.of('/glitch/protect-db/port'),
      },
      policy: ssmPolicy,
    });

    new AwsCustomResource(this, 'ProtectDbNameParam', {
      onUpdate: {
        service: 'SSM',
        action: 'putParameter',
        parameters: {
          Name: '/glitch/protect-db/dbname',
          Value: 'glitch_protect',
          Type: 'String',
          Overwrite: true,
          Description: 'Protect DB database name',
        },
        physicalResourceId: PhysicalResourceId.of('/glitch/protect-db/dbname'),
      },
      policy: ssmPolicy,
    });

    new AwsCustomResource(this, 'ProtectDbSentinelUserParam', {
      onUpdate: {
        service: 'SSM',
        action: 'putParameter',
        parameters: {
          Name: '/glitch/protect-db/sentinel-iam-user',
          Value: 'sentinel_iam',
          Type: 'String',
          Overwrite: true,
          Description: 'Protect DB IAM DB username for Sentinel agent',
        },
        physicalResourceId: PhysicalResourceId.of('/glitch/protect-db/sentinel-iam-user'),
      },
      policy: ssmPolicy,
    });

    new CfnOutput(this, 'ProtectDbEndpoint', {
      value: this.db.dbInstanceEndpointAddress,
      description: 'Protect DB RDS endpoint hostname',
    });

    // ── One-shot fix: create sentinel_iam DB user ──────────────────────────────
    // Invoke with: aws lambda invoke --function-name glitch-fix-sentinel-iam \
    //   --payload '{"username":"<master_user>","password":"<master_pass>"}' /tmp/fix.json
    const fixSentinelIamSg = new SecurityGroup(this, 'FixSentinelIamSg', {
      vpc,
      allowAllOutbound: true,
      description: 'fix-sentinel-iam Lambda: outbound Postgres to RDS',
    });
    this.db.connections.allowFrom(fixSentinelIamSg, Port.tcp(5432));
    new LambdaFunction(this, 'FixSentinelIamFn', {
      functionName: 'glitch-fix-sentinel-iam',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/fix-sentinel-iam'), {
        bundling: {
          image: Runtime.PYTHON_3_12.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output',
          ],
        },
      }),
      timeout: Duration.seconds(30),
      description: 'One-shot: create sentinel_iam DB user with rds_iam grant',
      vpc,
      vpcSubnets: { subnetType: SubnetType.PUBLIC },
      allowPublicSubnet: true,
      securityGroups: [fixSentinelIamSg],
      environment: {
        PROTECT_DB_HOST: this.db.dbInstanceEndpointAddress,
        PROTECT_DB_PORT: '5432',
        PROTECT_DB_NAME: 'glitch_protect',
      },
    });
  }
}


// --- GlitchGatewayStack ---

export interface GlitchGatewayStackProps extends StackProps {
  readonly agentCoreRuntimeArn: string;
  readonly configTable: ITable;
  readonly vpc: IVpc;
  readonly agentcoreUtilsLayer: ILayerVersion;
}

/**
 * Glitch Gateway stack: Lambda Function URL for UI invocations, /api/* proxy, and keepalive.
 */
export class GlitchGatewayStack extends Stack {
  public readonly gatewayFunction: LambdaFunction;
  public readonly functionUrl: string;

  constructor(scope: Construct, id: string, props: GlitchGatewayStackProps) {
    super(scope, id, props);

    const { agentCoreRuntimeArn, configTable, vpc, agentcoreUtilsLayer } = props;

    // RDS endpoint comes from SSM (written by GlitchProtectDbStack) to avoid
    // cross-stack CloudFormation exports that block stack deletion/replacement.
    const protectDbHost = StringParameter.valueForStringParameter(this, '/glitch/protect-db/host');

    const protectQuerySg = new SecurityGroup(this, 'ProtectQuerySg', {
      vpc,
      description: 'protect-query Lambda: outbound Postgres to RDS in VPC',
      allowAllOutbound: false,
    });
    protectQuerySg.addEgressRule(Peer.ipv4(vpc.vpcCidrBlock), Port.tcp(5432), 'RDS Postgres in VPC');

    const protectQueryFn = new LambdaFunction(this, 'ProtectQueryFunction', {
      functionName: 'glitch-protect-query',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/protect-query'), {
        bundling: {
          image: Runtime.PYTHON_3_12.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output',
          ],
        },
      }),
      timeout: Duration.seconds(30),
      memorySize: 256,
      vpc,
      vpcSubnets: { subnetType: SubnetType.PRIVATE_WITH_EGRESS },
      securityGroups: [protectQuerySg],
      environment: {
        PROTECT_DB_HOST: protectDbHost,
        PROTECT_DB_PORT: '5432',
        PROTECT_DB_NAME: 'glitch_protect',
        PROTECT_DB_USER: 'glitch_iam',
      },
    });

    // IAM auth: rds-db:connect on the glitch_iam DB user (wildcard DBI resource ID
    // since the instance may be replaced; auth is scoped to the DB username).
    protectQueryFn.addToRolePolicy(new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ['rds-db:connect'],
      resources: [
        `arn:aws:rds-db:${this.region}:${this.account}:dbuser:*\/glitch_iam`,
      ],
    }));

    this.gatewayFunction = new LambdaFunction(this, 'GatewayFunction', {
      functionName: 'glitch-gateway',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/gateway')),
      timeout: Duration.seconds(300),
      memorySize: 512,
      layers: [agentcoreUtilsLayer],
      environment: {
        CONFIG_TABLE_NAME: configTable.tableName,
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
        PROTECT_QUERY_FUNCTION_NAME: protectQueryFn.functionName,
      },
    });

    protectQueryFn.grantInvoke(this.gatewayFunction);

    configTable.grantReadWriteData(this.gatewayFunction);

    this.gatewayFunction.addToRolePolicy(
      new PolicyStatement({
        sid: 'BedrockAgentCoreAccess',
        effect: Effect.ALLOW,
        actions: [
          'bedrock-agentcore:InvokeAgentRuntime',
          'bedrock-agentcore:CreateAgentRuntimeSession',
          'bedrock-agentcore:GetAgentRuntimeSession',
          'bedrock-agentcore:DeleteAgentRuntimeSession',
        ],
        resources: [
          agentCoreRuntimeArn,
          `${agentCoreRuntimeArn}/*`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:code-interpreter/*`,
        ],
      })
    );

    // NONE auth: CloudFront OAC does not sign POST/PUT bodies to Lambda URLs, so IAM auth
    // causes "signature does not match" on chat/agents/telegram API. The Function URL is
    // only used as the CloudFront origin; access is protected by WAF IP allowlist on the distribution.
    const fnUrl = this.gatewayFunction.addFunctionUrl({
      authType: FunctionUrlAuthType.NONE,
    });

    this.functionUrl = fnUrl.url;

    const keepaliveRule = new Rule(this, 'GatewayKeepaliveRule', {
      schedule: Schedule.rate(Duration.minutes(5)),
      description: 'Keep gateway Lambda warm to reduce cold starts',
    });
    keepaliveRule.addTarget(new LambdaFunctionTarget(this.gatewayFunction, {
      event: RuleTargetInput.fromObject({ path: '/health', method: 'GET' }),
    }));

    new CfnOutput(this, 'GatewayFunctionUrl', {
      value: this.functionUrl,
      description: 'Gateway Lambda Function URL',
      exportName: 'GlitchGatewayUrl',
    });
  }

}

// --- TelegramWebhookStack ---

export interface TelegramWebhookStackProps extends StackProps {
  readonly configTable: ITable;
  readonly telegramBotTokenSecret: ISecret;
  readonly agentCoreRuntimeArn: string;
  readonly agentcoreUtilsLayer: ILayerVersion;
}

/**
 * Telegram webhook stack: Lambda that receives Telegram updates and invokes AgentCore runtime.
 */
export class TelegramWebhookStack extends Stack {
  public readonly webhookFunction: LambdaFunction;
  public readonly webhookUrl: string;

  constructor(scope: Construct, id: string, props: TelegramWebhookStackProps) {
    super(scope, id, props);

    const { configTable, telegramBotTokenSecret, agentCoreRuntimeArn, agentcoreUtilsLayer } = props;

    // Processor Lambda: handles agent invocation and Telegram reply asynchronously.
    // Invoked with InvocationType=Event by the webhook, so the webhook can return 200
    // to Telegram immediately (preventing Telegram's 60s timeout retry storm).
    const processorFunction = new LambdaFunction(this, 'TelegramProcessorFunction', {
      functionName: 'glitch-telegram-processor',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/telegram-processor')),
      timeout: Duration.seconds(300),
      memorySize: 256,
      layers: [agentcoreUtilsLayer],
      environment: {
        TELEGRAM_SECRET_NAME: SECRET_NAMES.TELEGRAM_BOT_TOKEN,
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
      },
    });

    telegramBotTokenSecret.grantRead(processorFunction);
    processorFunction.addToRolePolicy(
      new PolicyStatement({
        sid: 'ProcessorInvokeAgentCoreRuntime',
        effect: Effect.ALLOW,
        actions: [
          'bedrock-agentcore:InvokeAgentRuntime',
          'bedrock-agentcore:CreateAgentRuntimeSession',
          'bedrock-agentcore:GetAgentRuntimeSession',
          'bedrock-agentcore:DeleteAgentRuntimeSession',
        ],
        resources: [
          agentCoreRuntimeArn,
          `${agentCoreRuntimeArn}/*`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:code-interpreter/*`,
        ],
      })
    );

    this.webhookFunction = new LambdaFunction(this, 'TelegramWebhookFunction', {
      functionName: 'glitch-telegram-webhook',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/telegram-webhook')),
      timeout: Duration.seconds(30),  // Only needs to validate + dedup + async dispatch
      memorySize: 256,
      environment: {
        CONFIG_TABLE_NAME: configTable.tableName,
        TELEGRAM_SECRET_NAME: SECRET_NAMES.TELEGRAM_BOT_TOKEN,
        PROCESSOR_FUNCTION_NAME: processorFunction.functionName,
      },
    });

    configTable.grantReadWriteData(this.webhookFunction);
    telegramBotTokenSecret.grantRead(this.webhookFunction);

    // Webhook invokes processor asynchronously (InvocationType=Event)
    processorFunction.grantInvoke(this.webhookFunction);

    // Read own Function URL from SSM on cold start for Telegram webhook self-registration.
    // The URL is written by GlitchTelegramSsmStack (a separate stack) to avoid a CFN circular dep.
    this.webhookFunction.addToRolePolicy(
      new PolicyStatement({
        sid: 'ReadOwnWebhookUrlFromSsm',
        effect: Effect.ALLOW,
        actions: ['ssm:GetParameter'],
        resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter${SSM_PARAMS.TELEGRAM_WEBHOOK_URL}`],
      })
    );

    const functionUrl = this.webhookFunction.addFunctionUrl({
      authType: FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [HttpMethod.POST],
      },
    });

    this.webhookUrl = functionUrl.url;

    const keepaliveFunction = new LambdaFunction(this, 'AgentCoreKeepaliveFunction', {
      functionName: 'glitch-agentcore-keepalive',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/telegram-keepalive')),
      timeout: Duration.seconds(30),
      memorySize: 128,
      layers: [agentcoreUtilsLayer],
      environment: { AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn },
    });
    keepaliveFunction.addToRolePolicy(
      new PolicyStatement({
        effect: Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [agentCoreRuntimeArn, `${agentCoreRuntimeArn}/*`],
      })
    );
    new Rule(this, 'AgentCoreKeepaliveSchedule', {
      schedule: Schedule.rate(Duration.minutes(4)),
      targets: [new LambdaFunctionTarget(keepaliveFunction)],
      description: 'Invoke AgentCore runtime keepalive every 4 min to keep Claude prompt cache warm (5-min TTL)',
    });

    // SsmTelegramConfigTable: safe to write here (no circular dep — table name is not a FunctionUrl token).
    new StringParameter(this, 'SsmTelegramConfigTable', {
      parameterName: SSM_PARAMS.TELEGRAM_CONFIG_TABLE,
      stringValue: configTable.tableName,
      description: 'DynamoDB config table name (for runtime GLITCH_CONFIG_TABLE)',
    });

    // Write webhook URL to SSM using AwsCustomResource so the webhook Lambda can self-register.
    // AwsCustomResource avoids the CFN circular dep that a plain StringParameter would cause
    // (FunctionUrl → Function → ServiceRole → Policy → FunctionUrl).
    new AwsCustomResource(this, 'SsmTelegramWebhookUrl', {
      onUpdate: {
        service: 'SSM',
        action: 'putParameter',
        parameters: {
          Name: SSM_PARAMS.TELEGRAM_WEBHOOK_URL,
          Value: this.webhookUrl,
          Type: 'String',
          Overwrite: true,
          Description: 'Telegram webhook Lambda Function URL (for runtime GLITCH_TELEGRAM_WEBHOOK_URL)',
        },
        physicalResourceId: PhysicalResourceId.of(SSM_PARAMS.TELEGRAM_WEBHOOK_URL),
      },
      policy: AwsCustomResourcePolicy.fromStatements([
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ['ssm:PutParameter'],
          resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter${SSM_PARAMS.TELEGRAM_WEBHOOK_URL}`],
        }),
      ]),
    });

    new CfnOutput(this, 'TelegramWebhookUrl', {
      value: this.webhookUrl,
      description: 'Telegram webhook Lambda Function URL',
    });
  }


}

// --- GlitchEdgeStack ---
// Must be deployed to us-east-1 (CloudFront scope for WAF + ACM).
// Deploy: cdk deploy GlitchEdgeStack --region us-east-1
//
// IPv4 allowlist is auto-discovered from Porkbun DDNS at deploy time:
//   A Lambda custom resource calls the Porkbun ping API to get your current public IP,
//   writes it to SSM (/glitch/waf/allowed-ipv4), and feeds it into the WAF IP set.
//   No manual IP passing required — just deploy and it picks up your current IP.
//
// To override (e.g. add a second IP or force a specific CIDR):
//   cdk deploy GlitchEdgeStack --region us-east-1 -c allowedIpAddresses=1.2.3.4/32,5.6.7.8/32

const WAF_SSM_IPV4 = '/glitch/waf/allowed-ipv4';
const CLOUDFLARE_SECRET_NAME = 'glitch/cloudflare-api';

export interface GlitchEdgeStackProps extends StackProps {
  /**
   * IPv4 CIDRs to allow. When provided, these override the SSM/custom-resource lookup.
   * Pass via CDK context: -c allowedIpAddresses=1.2.3.4/32,5.6.7.8/32
   */
  readonly allowedIpAddresses?: string[];
}

export class GlitchEdgeStack extends Stack {
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: GlitchEdgeStackProps) {
    super(scope, id, props);

    // ── Porkbun IP lookup custom resource ─────────────────────────────────────
    // Runs at deploy time: calls Porkbun ping API → gets current public IP →
    // writes to SSM /glitch/waf/allowed-ipv4 → WAF IP set uses the result.
    // The IP lookup custom resource reads SSM only (no DNS provider API calls).

    const porkbunLookupRole = new Role(this, 'PorkbunLookupRole', {
      assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
      inlinePolicies: {
        PorkbunLookup: new PolicyDocument({
          statements: [
            new PolicyStatement({
              sid: 'ReadWriteSsmIpv4',
              actions: ['ssm:GetParameter', 'ssm:PutParameter'],
              resources: [
                'arn:aws:ssm:us-east-1:999776382415:parameter/glitch/waf/allowed-ipv4',
              ],
            }),
          ],
        }),
      },
    });

    const porkbunLookupFn = new LambdaFunction(this, 'PorkbunIpLookupFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/porkbun-ip-lookup')),
      role: porkbunLookupRole,
      timeout: Duration.seconds(30),
      description: 'Custom resource: reads /glitch/waf/allowed-ipv4 from SSM for WAF allowlist',
    });

    // FallbackIpCidr is read from cdk.context.json (SSM lookup cached at synth time).
    // It is only used if the ddns-updater webhook has never been called and SSM is empty.
    const fallbackIpCidr = StringParameter.valueFromLookup(this, WAF_SSM_IPV4);

    const porkbunIpResource = new CustomResource(this, 'PorkbunIpLookup', {
      serviceToken: porkbunLookupFn.functionArn,
      properties: {
        // FallbackIpCidr: used only when SSM is empty (first deploy before webhook is called).
        // The ddns-updater webhook keeps SSM current at runtime; this is a bootstrap safety net.
        FallbackIpCidr: fallbackIpCidr,
        // Changing this timestamp forces re-execution on every deploy.
        DeployTime: new Date().toISOString(),
      },
    });

    // ── Resolve final IP list ──────────────────────────────────────────────────
    // Priority: explicit context override > SSM (from previous deploy) > Porkbun result.
    //
    // valueFromLookup contacts SSM at synth time and fails if the parameter doesn't exist.
    // Only call it when no context override is provided — on first deploy the parameter
    // won't exist yet, so we fall through to the Porkbun custom resource result instead.

    const parseIps = (raw: string): string[] => {
      if (!raw || raw.startsWith('dummy-value-for-') || raw === 'none') return [];
      return raw.split(',').map(s => s.trim()).filter(s => s && s !== 'none');
    };

    let allowedIps: string[];
    if (props.allowedIpAddresses?.length) {
      // Explicit override — use as-is, skip SSM lookup entirely.
      allowedIps = props.allowedIpAddresses;
    } else {
      // No override: try SSM (parameter written by a previous deploy).
      // valueFromLookup returns a dummy string when the parameter doesn't exist yet;
      // parseIps treats that as empty and we fall through to the Porkbun result.
      const ssmIpv4Raw = StringParameter.valueFromLookup(this, WAF_SSM_IPV4);
      const fromSsm = parseIps(ssmIpv4Raw);
      allowedIps = fromSsm.length ? fromSsm : [porkbunIpResource.getAttString('IpCidr')];
    }

    const ipv4Set = new CfnIPSet(this, 'AllowedIpSet', {
      name: 'GlitchAllowedIPs',
      scope: 'CLOUDFRONT',
      ipAddressVersion: 'IPV4',
      addresses: allowedIps,
      description: 'Allowed IPv4 CIDRs for Glitch dashboard',
    });
    ipv4Set.node.addDependency(porkbunIpResource);

    const rules: CfnWebACL.RuleProperty[] = [
      {
        name: 'AllowTrustedIPv4',
        priority: 0,
        action: { allow: {} },
        visibilityConfig: {
          cloudWatchMetricsEnabled: true,
          metricName: 'AllowTrustedIPv4',
          sampledRequestsEnabled: true,
        },
        statement: { ipSetReferenceStatement: { arn: ipv4Set.attrArn } },
      },
    ];

    // Default action BLOCK — allow only matched IPs.
    // No login page to attack, no tokens to steal: unauthorized IPs get 403 at the edge.
    const webAcl = new CfnWebACL(this, 'WebAcl', {
      name: 'GlitchDashboardWebAcl',
      scope: 'CLOUDFRONT',
      defaultAction: { block: {} },
      visibilityConfig: {
        cloudWatchMetricsEnabled: true,
        metricName: 'GlitchDashboardWebAcl',
        sampledRequestsEnabled: true,
      },
      rules,
    });

    this.webAclArn = webAcl.attrArn;

    new CfnOutput(this, 'WebAclArn', {
      value: this.webAclArn,
      description: 'WAF WebACL ARN — associate with CloudFront distribution',
      exportName: 'GlitchEdgeWebAclArn',
    });

    // ── DDNS Updater webhook ───────────────────────────────────────────────────
    // Called by the home network to update Cloudflare DNS + WAF IP set + SSM whenever
    // the home IP changes.
    //
    // After deploy: retrieve the token from Secrets Manager and configure a cron
    // on your home device (UDM-Pro, Raspberry Pi, etc.) to call:
    //   curl -s -X POST <DdnsUpdaterUrl> -H "Authorization: Bearer <token>"

    // Bearer token for the webhook. CDK generates a random 32-char secret on first deploy.
    const ddnsTokenSecret = new Secret(this, 'DdnsTokenSecret', {
      secretName: 'glitch/ddns-token',
      description: 'Bearer token for the DDNS updater webhook Lambda',
      generateSecretString: {
        passwordLength: 32,
        excludePunctuation: true,
      },
    });

    const ddnsUpdaterRole = new Role(this, 'DdnsUpdaterRole', {
      assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
      inlinePolicies: {
        DdnsUpdater: new PolicyDocument({
          statements: [
            new PolicyStatement({
              sid: 'ReadSecrets',
              actions: ['secretsmanager:GetSecretValue'],
              resources: [
                // Cloudflare API token + zone ID (us-east-1)
                'arn:aws:secretsmanager:us-east-1:999776382415:secret:glitch/cloudflare-api-*',
                // DDNS bearer token (us-east-1, this stack's region)
                ddnsTokenSecret.secretArn,
              ],
            }),
            new PolicyStatement({
              sid: 'UpdateWafIpSet',
              actions: ['wafv2:GetIPSet', 'wafv2:UpdateIPSet'],
              resources: [ipv4Set.attrArn],
            }),
            new PolicyStatement({
              sid: 'WriteIpSsm',
              actions: ['ssm:PutParameter'],
              resources: [
                'arn:aws:ssm:us-east-1:999776382415:parameter/glitch/waf/allowed-ipv4',
              ],
            }),
          ],
        }),
      },
    });

    const ddnsUpdaterFn = new LambdaFunction(this, 'DdnsUpdaterFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/ddns-updater')),
      role: ddnsUpdaterRole,
      timeout: Duration.seconds(30),
      description: 'DDNS updater webhook: reads caller IP, updates Cloudflare DNS + WAF + SSM',
      environment: {
        DDNS_SUBDOMAIN: 'home',
        DDNS_DOMAIN: 'awoo.agency',
        WAF_IP_SET_ID: ipv4Set.attrId,
        WAF_IP_SET_NAME: 'GlitchAllowedIPs',
        SSM_PARAM: WAF_SSM_IPV4,
        CLOUDFLARE_SECRET_NAME: CLOUDFLARE_SECRET_NAME,
        CLOUDFLARE_SECRET_REGION: 'us-east-1',
        DDNS_TOKEN_SECRET_ARN: ddnsTokenSecret.secretArn,
        TOKEN_SECRET_REGION: this.region,
      },
    });

    // Public Function URL — auth is enforced by the bearer token, not IAM.
    const ddnsUpdaterUrl = ddnsUpdaterFn.addFunctionUrl({
      authType: FunctionUrlAuthType.NONE,
    });

    new CfnOutput(this, 'DdnsUpdaterUrl', {
      value: ddnsUpdaterUrl.url,
      description: 'DDNS updater webhook URL — POST with Authorization: Bearer <glitch/ddns-token>',
    });

  }
}

// --- GlitchUiHostingStack ---
// CloudFront + S3 (OAC) + Lambda Function URL (OAC/IAM) + WAF association.
// CloudFront-based UI hosting with WAF IP allowlist and Lambda origin.

export interface GlitchUiHostingStackProps extends StackProps {
  readonly gatewayFunction: IFunction;
  readonly gatewayFunctionUrl: string;
  readonly customDomain: string;
  /**
   * WAF WebACL ARN from GlitchEdgeStack (us-east-1).
   * If not provided, the CloudFront distribution is created without WAF (blocks no IPs).
   */
  readonly webAclArn?: string;
  /**
   * ACM Certificate ARN for the custom domain (must be in us-east-1 for CloudFront).
   * Create manually:
   *   aws acm request-certificate --domain-name glitch.awoo.agency \
   *     --validation-method DNS --region us-east-1
   * Then add the CNAME record to Porkbun DNS to validate.
   * Pass via CDK context: -c cloudfrontCertArn=arn:aws:acm:us-east-1:...
   */
  readonly certificateArn?: string;
}

export class GlitchUiHostingStack extends Stack {
  public readonly uiBucket: Bucket;
  public readonly distribution: Distribution;

  constructor(scope: Construct, id: string, props: GlitchUiHostingStackProps) {
    super(scope, id, props);

    const { gatewayFunction, gatewayFunctionUrl, customDomain, webAclArn, certificateArn } = props;

    // ========== S3 Bucket (fully private; only CloudFront OAC can read) ==========
    this.uiBucket = new Bucket(this, 'UiBucket', {
      bucketName: `glitch-ui-${this.account}-${this.region}`,
      blockPublicAccess: BlockPublicAccess.BLOCK_ALL,
      encryption: BucketEncryption.S3_MANAGED,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // ========== CloudFront OAC for Lambda Function URL ==========
    // Signs every origin request with SigV4 so the IAM-auth FURL is only reachable via CF.
    const lambdaOac = new CfnOriginAccessControl(this, 'LambdaOac', {
      originAccessControlConfig: {
        name: 'GlitchLambdaFunctionUrlOac',
        description: 'SigV4 OAC for Glitch Gateway Lambda Function URL',
        originAccessControlOriginType: 'lambda',
        signingBehavior: 'always',
        signingProtocol: 'sigv4',
      },
    });

    // Allow CloudFront service principal to invoke the Lambda FURL.
    gatewayFunction.addPermission('CloudFrontInvoke', {
      principal: new ServicePrincipal('cloudfront.amazonaws.com'),
      action: 'lambda:InvokeFunctionUrl',
      sourceArn: `arn:aws:cloudfront::${this.account}:distribution/*`,
    });

    // ========== ACM Certificate (optional; must be in us-east-1) ==========
    const certificate = certificateArn
      ? Certificate.fromCertificateArn(this, 'Certificate', certificateArn)
      : undefined;

    // ========== CloudFront Origins ==========
    const lambdaUrlHostname = Fn.select(2, Fn.split('/', gatewayFunctionUrl));

    const s3Origin = S3BucketOrigin.withOriginAccessControl(this.uiBucket);

    // Origin response timeout 60s so agent invocations (chat) don't 504; default is 30s.
    const lambdaOrigin = new HttpOrigin(lambdaUrlHostname, {
      protocolPolicy: OriginProtocolPolicy.HTTPS_ONLY,
      originId: 'GlitchGatewayLambda',
      readTimeout: Duration.seconds(60),
    });

    // ========== CloudFront Distribution ==========
    // /api/* and Lambda paths use CACHING_DISABLED (CloudFront rejects HeaderBehavior when TTL=0).
    // IPv6 disabled: WAF IP allowlist is IPv4-only; disabling IPv6 ensures browsers always
    // connect via IPv4 so the WAF allowlist matches correctly.
    this.distribution = new Distribution(this, 'Distribution', {
      comment: 'Glitch Agent UI',
      ...(certificate ? { certificate, domainNames: [customDomain] } : {}),
      ...(webAclArn ? { webAclId: webAclArn } : {}),
      enableIpv6: false,
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: s3Origin,
        viewerProtocolPolicy: ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: AllowedMethods.ALLOW_GET_HEAD,
        compress: true,
      },
      additionalBehaviors: {
        '/api/*': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: ViewerProtocolPolicy.HTTPS_ONLY,
          cachePolicy: CachePolicy.CACHING_DISABLED,
          allowedMethods: AllowedMethods.ALLOW_ALL,
          originRequestPolicy: OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
        '/invocations*': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: ViewerProtocolPolicy.HTTPS_ONLY,
          cachePolicy: CachePolicy.CACHING_DISABLED,
          allowedMethods: AllowedMethods.ALLOW_ALL,
          originRequestPolicy: OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
        '/health': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: ViewerProtocolPolicy.HTTPS_ONLY,
          cachePolicy: CachePolicy.CACHING_DISABLED,
          allowedMethods: AllowedMethods.ALLOW_GET_HEAD,
          originRequestPolicy: OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
      },
      // Only 404 → index.html (SPA client-side routes). Do NOT map 403 → index.html,
      // or asset requests that get 403 from S3 (e.g. bucket policy) would receive HTML and fail MIME check.
      errorResponses: [
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html' },
      ],
    });

    // Explicitly allow CloudFront to GetObject on all keys (OAC). withOriginAccessControl
    // adds this; we reinforce it so /assets/* and other keys are never 403.
    this.uiBucket.addToResourcePolicy(
      new PolicyStatement({
        sid: 'AllowCloudFrontOACGetObject',
        actions: ['s3:GetObject'],
        resources: [this.uiBucket.arnForObjects('*')],
        principals: [new ServicePrincipal('cloudfront.amazonaws.com')],
        conditions: {
          StringEquals: {
            'AWS:SourceArn': `arn:aws:cloudfront::${this.account}:distribution/${this.distribution.distributionId}`,
          },
        },
      })
    );

    // Apply Lambda OAC to the CloudFront distribution via L1 escape hatch.
    // The Lambda origin is the second entry in the Origins array (index 1; S3 is index 0).
    const cfnDistrib = this.distribution.node.defaultChild as CfnDistribution;
    cfnDistrib.addPropertyOverride(
      'DistributionConfig.Origins.1.OriginAccessControlId',
      lambdaOac.attrId
    );

    // Deploy static UI assets to S3 and invalidate CloudFront cache.
    // Split so index.html (and glitch.svg) use no-cache; hashed assets use long cache.
    // Prune false so the two deployments do not remove each other's files.
    const uiDist = path.join(__dirname, '../../ui/dist');
    new BucketDeployment(this, 'DeployUiHtml', {
      sources: [Source.asset(uiDist, { exclude: ['assets', 'assets/**'] })],
      destinationBucket: this.uiBucket,
      distribution: this.distribution,
      distributionPaths: ['/*'],
      cacheControl: [CacheControl.noCache()],
      prune: false,
    });
    new BucketDeployment(this, 'DeployUiAssets', {
      sources: [Source.asset(uiDist, { exclude: ['index.html', 'glitch.svg'] })],
      destinationBucket: this.uiBucket,
      distribution: this.distribution,
      distributionPaths: ['/*'],
      cacheControl: [
        CacheControl.maxAge(Duration.days(365)),
        CacheControl.immutable(),
      ],
      prune: false,
    });

    new CfnOutput(this, 'UiBucketName', {
      value: this.uiBucket.bucketName,
      description: 'S3 bucket for UI static assets (private, served via CloudFront OAC)',
      exportName: 'GlitchUiBucketName',
    });
    new CfnOutput(this, 'CloudFrontDomainName', {
      value: this.distribution.distributionDomainName,
      description: `CloudFront domain — add CNAME from ${customDomain} to this value in Porkbun DNS`,
      exportName: 'GlitchCloudFrontDomain',
    });
    new CfnOutput(this, 'CloudFrontDistributionId', {
      value: this.distribution.distributionId,
      exportName: 'GlitchCloudFrontDistributionId',
    });
    new CfnOutput(this, 'UiUrl', {
      value: certificate ? `https://${customDomain}` : `https://${this.distribution.distributionDomainName}`,
      description: 'Glitch UI URL',
      exportName: 'GlitchUiUrl',
    });
  }
}

// --- AgentCoreStack ---

export interface AgentCoreStackProps extends StackProps {
  /** Runtime role to attach policies to (from GlitchFoundationStack) */
  readonly runtimeRole: IRole;
}

/**
 * IAM policies for the Glitch AgentCore runtime role.
 * Glitch is now the single merged agent (Glitch + Sentinel ops capabilities).
 * AgentCore runs in PUBLIC network mode — no VPC/SG dependencies.
 */
export class AgentCoreStack extends Stack {
  public readonly agentRuntimeRole: IRole;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { runtimeRole } = props;
    this.agentRuntimeRole = runtimeRole;

    // Policy 1 of 2: Core Glitch runtime permissions (Bedrock, ECR, memory, secrets, storage, Telegram)
    new ManagedPolicy(this, 'AgentRuntimeCorePolicy', {
      managedPolicyName: `GlitchAgentCorePolicy-${this.region}`,
      roles: [runtimeRole],
      document: new PolicyDocument({
        statements: [
          new PolicyStatement({
            sid: 'BedrockModelAccess',
            effect: Effect.ALLOW,
            actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
            resources: [
              ...BEDROCK_MODEL_ARNS,
              `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
              `arn:aws:bedrock:${this.region}::inference-profile/*`,
            ],
          }),
          new PolicyStatement({
            sid: 'BedrockMarketplace',
            effect: Effect.ALLOW,
            actions: ['aws-marketplace:ViewSubscriptions', 'aws-marketplace:Subscribe', 'aws-marketplace:Unsubscribe'],
            resources: ['*'],
          }),
          new PolicyStatement({
            sid: 'ECRTokenAccess',
            effect: Effect.ALLOW,
            actions: ['ecr:GetAuthorizationToken'],
            resources: ['*'],
          }),
          new PolicyStatement({
            sid: 'ECRImageAccess',
            effect: Effect.ALLOW,
            actions: ['ecr:BatchCheckLayerAvailability', 'ecr:GetDownloadUrlForLayer', 'ecr:BatchGetImage'],
            resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`],
          }),
          new PolicyStatement({
            sid: 'AgentCoreMemoryAccess',
            effect: Effect.ALLOW,
            actions: [
              'bedrock-agentcore:CreateEvent', 'bedrock-agentcore:GetEvent', 'bedrock-agentcore:ListEvents',
              'bedrock-agentcore:ListSessions', 'bedrock-agentcore:CreateMemoryRecord',
              'bedrock-agentcore:GetMemoryRecord', 'bedrock-agentcore:ListMemoryRecords',
              'bedrock-agentcore:RetrieveMemoryRecords',
            ],
            resources: ['*'],
          }),
          new PolicyStatement({
            sid: 'GetWorkloadAccessToken',
            effect: Effect.ALLOW,
            actions: [
              'bedrock-agentcore:GetWorkloadAccessToken',
              'bedrock-agentcore:GetWorkloadAccessTokenForJWT',
              'bedrock-agentcore:GetWorkloadAccessTokenForUserId',
            ],
            resources: [
              `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default`,
              `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/glitch-*`,
            ],
          }),
          new PolicyStatement({
            sid: 'SecretsManagerRead',
            effect: Effect.ALLOW,
            actions: ['secretsmanager:GetSecretValue'],
            resources: [
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.API_KEYS}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.TELEGRAM_BOT_TOKEN}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.SSH_KEY}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.UNIFI_CONTROLLER}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.PIHOLE_API}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.GITHUB_TOKEN}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/protect-api-key*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/protect-db*`,
            ],
          }),
          new PolicyStatement({
            sid: 'SecretsManagerWrite',
            effect: Effect.ALLOW,
            actions: ['secretsmanager:CreateSecret', 'secretsmanager:PutSecretValue', 'secretsmanager:UpdateSecret'],
            resources: [`arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/*`],
          }),
          new PolicyStatement({
            sid: 'CloudWatchLogs',
            effect: Effect.ALLOW,
            actions: [
              'logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents',
              'logs:GetLogEvents', 'logs:DescribeLogStreams', 'logs:StartQuery', 'logs:GetQueryResults',
            ],
            resources: [
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*:*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*:*`,
            ],
          }),
          new PolicyStatement({
            sid: 'TelegramConfigTableAccess',
            effect: Effect.ALLOW,
            actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem', 'dynamodb:Query'],
            resources: [`arn:aws:dynamodb:${this.region}:${this.account}:table/${TABLE_NAMES.TELEGRAM_CONFIG}`],
          }),
          new PolicyStatement({
            sid: 'SoulS3Access',
            effect: Effect.ALLOW,
            actions: ['s3:ListBucket', 's3:GetObject', 's3:PutObject'],
            resources: [
              `arn:aws:s3:::${soulBucketName(this.account, this.region)}`,
              `arn:aws:s3:::${soulBucketName(this.account, this.region)}/*`,
            ],
          }),
          new PolicyStatement({
            sid: 'SsmCoreRead',
            effect: Effect.ALLOW,
            actions: ['ssm:GetParameter', 'ssm:GetParameters'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/s3-bucket`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/s3-key`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/poet-soul-s3-key`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/story-book-s3-key`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/ssh/hosts`,
            ],
          }),
          new PolicyStatement({
            sid: 'StsGetCallerIdentity',
            effect: Effect.ALLOW,
            actions: ['sts:GetCallerIdentity'],
            resources: ['*'],
          }),
          new PolicyStatement({
            sid: 'TelegramWebhookLambdaUrlRead',
            effect: Effect.ALLOW,
            actions: ['lambda:GetFunctionUrlConfig'],
            resources: [`arn:aws:lambda:${this.region}:${this.account}:function:glitch-telegram-webhook`],
          }),
          new PolicyStatement({
            sid: 'CodeBuildDeployStatusRead',
            effect: Effect.ALLOW,
            actions: ['codebuild:ListBuildsForProject', 'codebuild:BatchGetBuilds'],
            resources: [`arn:aws:codebuild:${this.region}:${this.account}:project/bedrock-agentcore-glitch-builder`],
          }),
          new PolicyStatement({
            sid: 'SsmAgentArnWrite',
            effect: Effect.ALLOW,
            actions: ['ssm:PutParameter'],
            resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/agent/runtime-arn`],
          }),
        ],
      }),
    });

    // Policy 2 of 2: Ops capabilities (CloudWatch monitoring, CloudFormation, Protect, RDS, GitHub, X-Ray)
    new ManagedPolicy(this, 'AgentRuntimeOpsPolicy', {
      managedPolicyName: `GlitchAgentOpsPolicy-${this.region}`,
      roles: [runtimeRole],
      document: new PolicyDocument({
        statements: [
          new PolicyStatement({
            sid: 'CloudWatchLogsRead',
            effect: Effect.ALLOW,
            actions: [
              'logs:DescribeLogGroups', 'logs:DescribeLogStreams', 'logs:FilterLogEvents',
              'logs:GetLogEvents', 'logs:StartQuery', 'logs:GetQueryResults',
            ],
            resources: [
              // AgentCore runtime
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*:*`,
              // All Glitch Lambda functions
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/lambda/glitch-*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/lambda/glitch-*:*`,
              // Custom Glitch log groups
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*:*`,
              // RDS enhanced monitoring
              `arn:aws:logs:${this.region}:${this.account}:log-group:RDSOSMetrics`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:RDSOSMetrics:*`,
              // VPC Flow Logs (VPN/networking diagnostics)
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/vpc/flowlogs*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/vpc/flowlogs*:*`,
              // CDK custom resource Lambda (troubleshoot deploy issues)
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/lambda/GlitchFoundation*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/lambda/GlitchFoundation*:*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/lambda/GlitchProtect*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/lambda/GlitchProtect*:*`,
              // WAF (us-east-1 only — Insights queries must target the correct region)
              `arn:aws:logs:us-east-1:${this.account}:log-group:aws-waf-logs-*`,
              `arn:aws:logs:us-east-1:${this.account}:log-group:aws-waf-logs-*:*`,
            ],
          }),
          new PolicyStatement({
            sid: 'CloudWatchMetrics',
            effect: Effect.ALLOW,
            actions: [
              'cloudwatch:GetMetricData', 'cloudwatch:GetMetricStatistics',
              'cloudwatch:ListMetrics', 'cloudwatch:DescribeAlarms', 'cloudwatch:PutMetricData',
            ],
            resources: ['*'],
          }),
          new PolicyStatement({
            sid: 'XRayTracing',
            effect: Effect.ALLOW,
            actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords', 'xray:GetSamplingRules', 'xray:GetSamplingTargets'],
            resources: ['*'],
          }),
          new PolicyStatement({
            sid: 'CloudFormationRead',
            effect: Effect.ALLOW,
            actions: [
              'cloudformation:DescribeStacks', 'cloudformation:DescribeStackEvents',
              'cloudformation:DescribeStackResources', 'cloudformation:DetectStackDrift',
              'cloudformation:DescribeStackDriftDetectionStatus', 'cloudformation:DescribeStackResourceDrifts',
              'cloudformation:ListStacks', 'cloudformation:GetTemplate',
              'cloudformation:CancelUpdateStack', 'cloudformation:ContinueUpdateRollback',
            ],
            resources: [`arn:aws:cloudformation:${this.region}:${this.account}:stack/*/*`],
          }),
          new PolicyStatement({
            sid: 'RdsIamConnect',
            effect: Effect.ALLOW,
            actions: ['rds-db:connect'],
            resources: [`arn:aws:rds-db:${this.region}:${this.account}:dbuser:*/sentinel_iam`],
          }),
          new PolicyStatement({
            sid: 'SsmOpsRead',
            effect: Effect.ALLOW,
            actions: ['ssm:GetParameter', 'ssm:GetParameters', 'ssm:GetParametersByPath'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect/*`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect-db/*`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/*`,
            ],
          }),
        ],
      }),
    });

    // SSM parameter: monitored log groups for CloudWatch scan tools
    // Use AwsCustomResource + PutParameter Overwrite so re-deploys and existing parameters
    // (e.g. previously owned by GlitchSentinelStack) don't cause "already exists" failures.
    new AwsCustomResource(this, 'MonitoredLogGroupsParam', {
      onUpdate: {
        service: 'SSM',
        action: 'putParameter',
        parameters: {
          Name: '/glitch/sentinel/monitored-log-groups',
          Value: JSON.stringify([
            '/aws/bedrock-agentcore/runtimes',
            '/aws/lambda/glitch-telegram-webhook',
            '/aws/lambda/glitch-gateway',
            '/aws/lambda/glitch-agentcore-keepalive',
            '/glitch/telemetry',
          ]),
          Type: 'String',
          Overwrite: true,
          Description: 'JSON array of CloudWatch log groups for Glitch ops to monitor',
        },
        physicalResourceId: PhysicalResourceId.of('/glitch/sentinel/monitored-log-groups'),
      },
      policy: AwsCustomResourcePolicy.fromStatements([
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ['ssm:PutParameter'],
          resources: [
            `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/monitored-log-groups`,
          ],
        }),
      ]),
    });

    new CfnOutput(this, 'AgentRuntimeRoleArn', {
      value: runtimeRole.roleArn,
      description: 'IAM role ARN for AgentCore Runtime',
    });
  }
}




