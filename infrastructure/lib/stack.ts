/**
 * All Glitch CDK stacks in a single file.
 * Order: dependency-friendly (interfaces and stacks used by others come first).
 */
import { CfnDeletionPolicy, CfnOutput, CustomResource, Duration, Fn, RemovalPolicy, Stack } from 'aws-cdk-lib';
import type { StackProps } from 'aws-cdk-lib';
import { Certificate } from 'aws-cdk-lib/aws-certificatemanager';
import { AllowedMethods, CachePolicy, CfnDistribution, CfnOriginAccessControl, Distribution, OriginProtocolPolicy, OriginRequestPolicy, ViewerProtocolPolicy } from 'aws-cdk-lib/aws-cloudfront';
import { HttpOrigin, S3BucketOrigin } from 'aws-cdk-lib/aws-cloudfront-origins';
import { Table } from 'aws-cdk-lib/aws-dynamodb';
import type { ITable } from 'aws-cdk-lib/aws-dynamodb';
import { CfnVPNGateway, InterfaceVpcEndpoint, InterfaceVpcEndpointAwsService, InstanceType as Ec2InstanceType, IpAddresses, Peer, Port, PrivateSubnet, PublicSubnet, SecurityGroup, SubnetType, Vpc } from 'aws-cdk-lib/aws-ec2';
import type { ISubnet, IVpc } from 'aws-cdk-lib/aws-ec2';
import { Rule, RuleTargetInput, Schedule } from 'aws-cdk-lib/aws-events';
import { LambdaFunction as LambdaFunctionTarget } from 'aws-cdk-lib/aws-events-targets';
import { Effect, ManagedPolicy, PolicyDocument, PolicyStatement, Role, ServicePrincipal } from 'aws-cdk-lib/aws-iam';
import type { IRole } from 'aws-cdk-lib/aws-iam';
import { Code, Function as LambdaFunction, FunctionUrlAuthType, HttpMethod, Runtime } from 'aws-cdk-lib/aws-lambda';
import type { IFunction } from 'aws-cdk-lib/aws-lambda';
import { LogGroup } from 'aws-cdk-lib/aws-logs';
import type { ILogGroup } from 'aws-cdk-lib/aws-logs';
import { BlockPublicAccess, Bucket, BucketEncryption } from 'aws-cdk-lib/aws-s3';
import type { IBucket } from 'aws-cdk-lib/aws-s3';
import { BucketDeployment, CacheControl, Source } from 'aws-cdk-lib/aws-s3-deployment';
import { Secret } from 'aws-cdk-lib/aws-secretsmanager';
import type { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { StringParameter } from 'aws-cdk-lib/aws-ssm';
import { DatabaseInstance, DatabaseInstanceEngine, PostgresEngineVersion, StorageType, Credentials } from 'aws-cdk-lib/aws-rds';
import type { IDatabaseInstance } from 'aws-cdk-lib/aws-rds';
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

// Sentinel excludes Opus to control cost for an always-on ops agent
const SENTINEL_BEDROCK_MODEL_ARNS = [
  'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-20250514-v1:0',
  'arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-5-20250929-v1:0',
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

    new StringParameter(this, 'SsmOllamaProxyHost', {
      parameterName: SSM_PARAMS.OLLAMA_PROXY_HOST,
      stringValue: 'home.awoo.agency',
      description: 'DDNS hostname for on-prem Ollama proxy (Chat:11434, Vision:18080)',
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
  }
}

// --- GlitchVpnStack ---

export interface GlitchVpnStackProps extends StackProps {
  /** UDM-Pro public IP for the Customer Gateway. Pass on first deploy via context: -c onPremPublicIp=x.x.x.x */
  readonly onPremPublicIp?: string;
  /** BGP ASN for the on-prem Customer Gateway. UDM-Pro default is 65000. */
  readonly onPremBgpAsn?: number;
  /** VPC from GlitchFoundationStack. */
  readonly vpc: IVpc;
}

/**
 * GlitchVpnStack — Site-to-Site VPN resources (VGW, Customer Gateway, VPN Connection).
 *
 * Deploy once after GlitchFoundationStack, then leave alone.
 * All VPN resources have DeletionPolicy: RETAIN.
 *
 * Static routes 10.10.100.0/24 and 10.10.110.0/24 send traffic to on-prem (Protect DB at 10.10.100.230, models on 10.10.110.x).
 * On-prem must route 10.0.0.0/16 (AWS VPC) via the tunnel. See infrastructure/docs/IPSEC-ONPREM-PROTECT-DB.md.
 *
 * First deploy (creates Customer Gateway + VPN Connection):
 *   cdk deploy GlitchVpnStack -c onPremPublicIp=<UDM-Pro WAN IP>
 *
 * Subsequent deploys (no context needed):
 *   cdk deploy GlitchVpnStack
 */
export class GlitchVpnStack extends Stack {
  public readonly vpnGatewayId: string;

  constructor(scope: Construct, id: string, props: GlitchVpnStackProps) {
    super(scope, id, props);

    const onPremPublicIp = props.onPremPublicIp ?? this.node.tryGetContext('onPremPublicIp') as string | undefined;
    const onPremBgpAsn = props.onPremBgpAsn ?? Number(this.node.tryGetContext('onPremBgpAsn') ?? '65000');
    const { vpc } = props;

    // ========== VPN Gateway (no CfnVPCGatewayAttachment — avoids "already exists in GlitchFoundationStack") ==========
    // We attach the VGW to the VPC via a Lambda so CloudFormation never creates a resource with
    // physical ID "VGW|vpc-xxx". That phantom ID was blocking us. Foundation stack stays untouched.
    // amazonSideAsn 64513: use 64513 so CloudFormation replaces VGW if the previous one was deleted (Ref pointed to non-existent vgw-xxx).
    const vpnGateway = new CfnVPNGateway(this, 'VpnGateway', {
      type: 'ipsec.1',
      amazonSideAsn: 64513,
      tags: [{ key: 'Name', value: 'glitch-vpn-gateway' }],
    });
    vpnGateway.cfnOptions.deletionPolicy = CfnDeletionPolicy.RETAIN;
    this.vpnGatewayId = vpnGateway.ref;

    const attachAndPropagateRole = new Role(this, 'VgwAttachRole', {
      assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
      inlinePolicies: {
        Ec2: new PolicyDocument({
          statements: [
            new PolicyStatement({
              actions: [
                'ec2:AttachVpnGateway',
                'ec2:DetachVpnGateway',
                'ec2:DescribeVpnGateways',
                'ec2:DescribeRouteTables',
                'ec2:EnableVgwRoutePropagation',
                'ec2:DisableVgwRoutePropagation',
              ],
              resources: ['*'],
            }),
          ],
        }),
      },
    });

    const allRouteTableIds = [
      ...vpc.privateSubnets.map(s => (s as PrivateSubnet).routeTable.routeTableId),
      ...vpc.publicSubnets.map(s => (s as PublicSubnet).routeTable.routeTableId),
    ];

    const attachAndPropagateFn = new LambdaFunction(this, 'VgwAttachFn', {
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromInline(`
import json, time, boto3, urllib.request

def send(event, context, status, data=None, reason=''):
    data = data or {}
    body = json.dumps({
        'Status': status, 'Reason': reason or context.log_stream_name,
        'PhysicalResourceId': event.get('PhysicalResourceId') or context.log_stream_name,
        'StackId': event['StackId'], 'RequestId': event['RequestId'],
        'LogicalResourceId': event['LogicalResourceId'], 'Data': data,
    }).encode()
    req = urllib.request.Request(event['ResponseURL'], data=body,
        headers={'Content-Type': 'application/json', 'Content-Length': str(len(body))}, method='PUT')
    urllib.request.urlopen(req, timeout=10)

def ensure_attached(ec2_client, vgw_id, vpc_id):
    resp = ec2_client.describe_vpn_gateways(VpnGatewayIds=[vgw_id])
    attachments = resp['VpnGateways'][0].get('VpcAttachments', [])
    if any(a['VpcId'] == vpc_id and a['State'] == 'attached' for a in attachments):
        return
    ec2_client.attach_vpn_gateway(VpnGatewayId=vgw_id, VpcId=vpc_id)
    for _ in range(36):
        time.sleep(5)
        resp = ec2_client.describe_vpn_gateways(VpnGatewayIds=[vgw_id])
        attachments = resp['VpnGateways'][0].get('VpcAttachments', [])
        if any(a['VpcId'] == vpc_id and a['State'] == 'attached' for a in attachments):
            return
    raise RuntimeError('Timeout waiting for VGW attach')

def get_main_route_table_id(ec2_client, vpc_id):
    resp = ec2_client.describe_route_tables(Filters=[
        {'Name': 'vpc-id', 'Values': [vpc_id]},
        {'Name': 'association.main', 'Values': ['true']},
    ])
    for rt in resp.get('RouteTables', []):
        return rt['RouteTableId']
    return None

def handler(event, context):
    props = event.get('ResourceProperties', {})
    vgw_id, vpc_id = props['VgwId'], props['VpcId']
    route_table_ids = list(props.get('RouteTableIds', []))
    region = props.get('Region', 'us-west-2')
    ec2 = boto3.client('ec2', region_name=region)
    try:
        if event['RequestType'] == 'Delete':
            send(event, context, 'SUCCESS')
            return
        ensure_attached(ec2, vgw_id, vpc_id)
        main_rt = get_main_route_table_id(ec2, vpc_id)
        if main_rt and main_rt not in route_table_ids:
            route_table_ids.append(main_rt)
        for rt_id in route_table_ids:
            ec2.enable_vgw_route_propagation(GatewayId=vgw_id, RouteTableId=rt_id)
        send(event, context, 'SUCCESS', {'VgwId': vgw_id})
    except Exception as e:
        send(event, context, 'FAILED', reason=str(e))
`),
      role: attachAndPropagateRole,
      timeout: Duration.seconds(120),
    });

    // PropagationVersion: bump to force custom resource to re-run (enables propagation on all route tables including main).
    const attachResource = new CustomResource(this, 'VgwAttachAndPropagate', {
      serviceToken: attachAndPropagateFn.functionArn,
      properties: {
        VgwId: vpnGateway.ref,
        VpcId: vpc.vpcId,
        RouteTableIds: allRouteTableIds,
        Region: this.region,
        PropagationVersion: '2',
      },
    });
    attachResource.node.addDependency(vpnGateway);

    // ========== Customer Gateway (get or create) + VPN Connection ==========
    // Only created when onPremPublicIp is provided. Use a custom resource to look up an existing
    // Customer Gateway by IP (and BGP ASN) so we don't fail with "already exists" when the CGW
    // was created by a previous deploy or retained after a failed delete.
    if (onPremPublicIp) {
      const getOrCreateCgwRole = new Role(this, 'GetOrCreateCgwRole', {
        assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          Ec2: new PolicyDocument({
            statements: [
              new PolicyStatement({
                actions: ['ec2:DescribeCustomerGateways', 'ec2:CreateCustomerGateway', 'ec2:CreateTags'],
                resources: ['*'],
              }),
            ],
          }),
        },
      });

      const getOrCreateCgwFn = new LambdaFunction(this, 'GetOrCreateCgwFn', {
        runtime: Runtime.PYTHON_3_12,
        handler: 'index.handler',
        role: getOrCreateCgwRole,
        timeout: Duration.seconds(30),
        code: Code.fromInline(`
import json, urllib.request, boto3

def send(event, context, status, data=None, reason=''):
    rid = (data.get('CgwId') if data else None) or event.get('PhysicalResourceId') or context.log_stream_name
    body = json.dumps({'Status': status, 'Reason': reason or '', 'PhysicalResourceId': rid, 'StackId': event['StackId'],
        'RequestId': event['RequestId'], 'LogicalResourceId': event['LogicalResourceId'], 'Data': data or {}}).encode()
    req = urllib.request.Request(event['ResponseURL'], data=body, headers={'Content-Type': 'application/json'}, method='PUT')
    urllib.request.urlopen(req, timeout=10)

def handler(event, context):
    props = event.get('ResourceProperties', {})
    ip, asn = props.get('OnPremPublicIp'), int(props.get('OnPremBgpAsn', 65000))
    region = props.get('Region', 'us-west-2')
    ec2 = boto3.client('ec2', region_name=region)
    try:
        if event['RequestType'] == 'Delete':
            send(event, context, 'SUCCESS', {})
            return
        resp = ec2.describe_customer_gateways(Filters=[
            {'Name': 'state', 'Values': ['available']},
            {'Name': 'type', 'Values': ['ipsec.1']},
            {'Name': 'ip-address', 'Values': [ip]},
        ])
        gateways = resp.get('CustomerGateways', [])
        for gw in gateways:
            if str(gw.get('BgpAsn')) == str(asn):
                cgw_id = gw['CustomerGatewayId']
                send(event, context, 'SUCCESS', {'CgwId': cgw_id})
                return
        create = ec2.create_customer_gateway(Type='ipsec.1', BgpAsn=asn, PublicIp=ip,
            TagSpecifications=[{'ResourceType': 'customer-gateway', 'Tags': [{'Key': 'Name', 'Value': 'glitch-udmpro-customer-gateway'}]}])
        cgw_id = create['CustomerGateway']['CustomerGatewayId']
        send(event, context, 'SUCCESS', {'CgwId': cgw_id})
    except Exception as e:
        send(event, context, 'FAILED', reason=str(e))
`),
      });

      const getOrCreateCgw = new CustomResource(this, 'GetOrCreateCustomerGateway', {
        serviceToken: getOrCreateCgwFn.functionArn,
        properties: {
          OnPremPublicIp: onPremPublicIp,
          OnPremBgpAsn: onPremBgpAsn,
          Region: this.region,
        },
        resourceType: 'Custom::GetOrCreateCustomerGateway',
      });
      getOrCreateCgw.node.addDependency(attachResource);

      // Use the CGW ID from the custom resource (existing or newly created).
      const customerGatewayId = getOrCreateCgw.getAttString('CgwId');

      // Get-or-create VPN Connection (same "already exists" issue: reuse existing CGW+VGW connection).
      const getOrCreateVpnRole = new Role(this, 'GetOrCreateVpnRole', {
        assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          Ec2: new PolicyDocument({
            statements: [
              new PolicyStatement({
                actions: [
                  'ec2:DescribeVpnConnections',
                  'ec2:CreateVpnConnection',
                  'ec2:CreateVpnConnectionRoute',
                  'ec2:CreateTags',
                ],
                resources: ['*'],
              }),
            ],
          }),
        },
      });

      const getOrCreateVpnFn = new LambdaFunction(this, 'GetOrCreateVpnFn', {
        runtime: Runtime.PYTHON_3_12,
        handler: 'index.handler',
        role: getOrCreateVpnRole,
        timeout: Duration.seconds(60),
        code: Code.fromInline(`
import json, urllib.request, boto3

def send(event, context, status, data=None, reason=''):
    rid = (data.get('VpnConnectionId') if data else None) or event.get('PhysicalResourceId') or context.log_stream_name
    body = json.dumps({'Status': status, 'Reason': reason or '', 'PhysicalResourceId': rid, 'StackId': event['StackId'],
        'RequestId': event['RequestId'], 'LogicalResourceId': event['LogicalResourceId'], 'Data': data or {}}).encode()
    req = urllib.request.Request(event['ResponseURL'], data=body, headers={'Content-Type': 'application/json'}, method='PUT')
    urllib.request.urlopen(req, timeout=10)

ROUTES = ['10.10.100.0/24', '10.10.110.0/24']

def ensure_routes(ec2, vpn_id):
    for cidr in ROUTES:
        try:
            ec2.create_vpn_connection_route(VpnConnectionId=vpn_id, DestinationCidrBlock=cidr)
        except Exception as e:
            if 'RouteAlreadyExists' not in str(e) and 'DuplicateRoute' not in str(e):
                raise

def handler(event, context):
    props = event.get('ResourceProperties', {})
    cgw_id, vgw_id = props.get('CgwId'), props.get('VgwId')
    region = props.get('Region', 'us-west-2')
    ec2 = boto3.client('ec2', region_name=region)
    try:
        if event['RequestType'] == 'Delete':
            send(event, context, 'SUCCESS', {})
            return
        resp = ec2.describe_vpn_connections(Filters=[
            {'Name': 'customer-gateway-id', 'Values': [cgw_id]},
            {'Name': 'vpn-gateway-id', 'Values': [vgw_id]},
            {'Name': 'state', 'Values': ['available', 'pending']},
        ])
        conns = resp.get('VpnConnections', [])
        # Prefer an existing static VPN so we don't create duplicates when both BGP and static exist.
        for c in conns:
            if (c.get('Options') or {}).get('StaticRoutesOnly'):
                vpn_id = c['VpnConnectionId']
                ensure_routes(ec2, vpn_id)
                send(event, context, 'SUCCESS', {'VpnConnectionId': vpn_id})
                return
        # No static VPN found (only BGP or none). create_vpn_connection_route() only works with static.
        # Create a new static VPN; the old BGP VPN remains (user can delete it in the console after cutover).
        create = ec2.create_vpn_connection(Type='ipsec.1', CustomerGatewayId=cgw_id, VpnGatewayId=vgw_id,
            Options={'StaticRoutesOnly': True},
            TagSpecifications=[{'ResourceType': 'vpn-connection', 'Tags': [{'Key': 'Name', 'Value': 'glitch-udmpro-vpn'}]}])
        vpn_id = create['VpnConnection']['VpnConnectionId']
        ensure_routes(ec2, vpn_id)
        send(event, context, 'SUCCESS', {'VpnConnectionId': vpn_id})
    except Exception as e:
        send(event, context, 'FAILED', reason=str(e))
`),
      });

      // StaticRoutesOnlyVersion: bump to force re-run so we create/use a static VPN (cannot convert BGP→static in place).
      const getOrCreateVpn = new CustomResource(this, 'GetOrCreateVpnConnection', {
        serviceToken: getOrCreateVpnFn.functionArn,
        properties: {
          CgwId: customerGatewayId,
          VgwId: vpnGateway.ref,
          Region: this.region,
          StaticRoutesOnlyVersion: '2',
        },
        resourceType: 'Custom::GetOrCreateVpnConnection',
      });
      getOrCreateVpn.node.addDependency(getOrCreateCgw);

      const vpnConnectionId = getOrCreateVpn.getAttString('VpnConnectionId');

      new CfnOutput(this, 'CustomerGatewayId', {
        value: customerGatewayId,
        description: 'Customer Gateway ID — configure matching entry on UDM-Pro (VPN > Site-to-Site)',
      });
      new CfnOutput(this, 'VpnConnectionId', {
        value: vpnConnectionId,
        description: 'VPN Connection ID — download tunnel config from AWS Console for UDM-Pro',
      });
    }

    new CfnOutput(this, 'VpnGatewayId', {
      value: vpnGateway.ref,
      description: 'VPN Gateway ID',
    });
  }
}

// --- GlitchProtectDbStack ---

export interface GlitchProtectDbStackProps extends StackProps {
  readonly vpc: IVpc;
}

/**
 * RDS Postgres (db.t4g.micro, single-AZ) for the Protect tab.
 * IAM authentication enabled — no password secret needed at runtime.
 * Master credentials stored in glitch/protect-db-master (for initial DB setup only).
 */
export class GlitchProtectDbStack extends Stack {
  public readonly db: DatabaseInstance;

  constructor(scope: Construct, id: string, props: GlitchProtectDbStackProps) {
    super(scope, id, props);
    const { vpc } = props;

    const dbSg = new SecurityGroup(this, 'ProtectDbSg', {
      vpc,
      description: 'protect-db RDS: inbound Postgres from VPC',
      allowAllOutbound: false,
    });
    dbSg.addIngressRule(Peer.ipv4(vpc.vpcCidrBlock), Port.tcp(5432), 'VPC Postgres access');

    this.db = new DatabaseInstance(this, 'ProtectDb', {
      engine: DatabaseInstanceEngine.postgres({ version: PostgresEngineVersion.VER_16 }),
      instanceType: new Ec2InstanceType('t4g.micro'),
      vpc,
      vpcSubnets: { subnetType: SubnetType.PRIVATE_WITH_EGRESS },
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
      publiclyAccessible: false,
    });

    new CfnOutput(this, 'ProtectDbEndpoint', {
      value: this.db.dbInstanceEndpointAddress,
      description: 'Protect DB RDS endpoint hostname',
    });
  }
}

// --- SecretsStack ---

export interface SecretsStackProps extends StackProps {
  // No IAM role props: secret read access for the AgentCore runtime role is granted
  // in AgentCoreStack (SecretsManagerAccess policy) to avoid deploy-order and 404 issues.
}

export class SecretsStack extends Stack {
  public readonly apiKeysSecret: ISecret;
  public readonly telegramBotTokenSecret: ISecret;
  public readonly porkbunApiSecret: ISecret;
  public readonly piholeApiSecret: ISecret;

  constructor(scope: Construct, id: string, props?: SecretsStackProps) {
    super(scope, id, props);

    this.apiKeysSecret = Secret.fromSecretNameV2(
      this,
      'ApiKeys',
      'glitch/api-keys'
    );

    this.telegramBotTokenSecret = Secret.fromSecretNameV2(
      this,
      'TelegramBotToken',
      'glitch/telegram-bot-token'
    );

    this.porkbunApiSecret = Secret.fromSecretNameV2(
      this,
      'PorkbunApi',
      'glitch/porkbun-api'
    );

    this.piholeApiSecret = Secret.fromSecretNameV2(
      this,
      'PiholeApi',
      'glitch/pihole-api'
    );

    new CfnOutput(this, 'ApiKeysSecretArn', {
      value: this.apiKeysSecret.secretArn,
      description: 'ARN of API keys secret',
      exportName: 'GlitchApiKeysArn',
    });

    new CfnOutput(this, 'TelegramBotTokenSecretArn', {
      value: this.telegramBotTokenSecret.secretArn,
      description: 'ARN of Telegram bot token secret',
      exportName: 'GlitchTelegramBotTokenArn',
    });

    new CfnOutput(this, 'PiholeApiSecretArn', {
      value: this.piholeApiSecret.secretArn,
      description: 'ARN of Pi-hole API credentials secret',
      exportName: 'GlitchPiholeApiArn',
    });

    // AgentCore runtime role secret access is granted in AgentCoreStack (SecretsManagerAccess
    // policy) so this stack has no IAM dependency and deploys reliably.
  }
}

// --- GlitchStorageStack ---

/** SSM parameter names for soul bucket discovery (runtime reads these when GLITCH_SOUL_S3_BUCKET is not set). */
const SOUL_SSM = {
  S3_BUCKET: '/glitch/soul/s3-bucket',
  S3_KEY: '/glitch/soul/s3-key',
  POET_SOUL_KEY: '/glitch/soul/poet-soul-s3-key',
  STORY_BOOK_KEY: '/glitch/soul/story-book-s3-key',
} as const;

/**
 * Storage stack: imports existing S3 bucket and log group, creates /glitch/soul/* SSM parameters
 * so the agent can discover the bucket without GLITCH_SOUL_S3_BUCKET env.
 *
 * The bucket (glitch-agent-state-{account}-{region}) and log group (/glitch/telemetry) are
 * pre-existing resources; this stack manages the SSM parameters that point to them.
 */
export class GlitchStorageStack extends Stack {
  public readonly configTable: ITable;
  public readonly soulBucket: IBucket;
  public readonly telemetryLogGroup: ILogGroup;

  constructor(scope: Construct, id: string, props?: StackProps) {
    super(scope, id, props);

    const tableName = TABLE_NAMES.TELEGRAM_CONFIG;
    const bucketName = soulBucketName(this.account, this.region);
    const logGroupName = '/glitch/telemetry';

    this.configTable = Table.fromTableName(this, 'ConfigTable', tableName);
    this.soulBucket = Bucket.fromBucketName(this, 'GlitchSoulBucket', bucketName);
    this.telemetryLogGroup = LogGroup.fromLogGroupName(this, 'GlitchTelemetryLogGroup', logGroupName);

    new StringParameter(this, 'SoulS3Bucket', {
      parameterName: SOUL_SSM.S3_BUCKET,
      stringValue: this.soulBucket.bucketName,
      description: 'S3 bucket for Glitch SOUL.md and poet-soul (runtime discovery)',
    });
    new StringParameter(this, 'SoulS3Key', {
      parameterName: SOUL_SSM.S3_KEY,
      stringValue: 'soul.md',
      description: 'S3 key for SOUL.md',
    });
    new StringParameter(this, 'SoulPoetSoulKey', {
      parameterName: SOUL_SSM.POET_SOUL_KEY,
      stringValue: 'poet-soul.md',
      description: 'S3 key for poet-soul.md',
    });
    new StringParameter(this, 'SoulStoryBookKey', {
      parameterName: SOUL_SSM.STORY_BOOK_KEY,
      stringValue: 'story-book.md',
      description: 'S3 key for story-book.md',
    });

    new CfnOutput(this, 'GlitchSoulBucketName', {
      value: this.soulBucket.bucketName,
      description: 'S3 bucket for Glitch SOUL.md',
      exportName: 'GlitchSoulBucketName',
    });
    new CfnOutput(this, 'GlitchTelemetryLogGroupName', {
      value: this.telemetryLogGroup.logGroupName,
      description: 'CloudWatch Logs group for telemetry',
      exportName: 'GlitchTelemetryLogGroupName',
    });
  }
}

// --- GlitchGatewayStack ---

export interface GlitchGatewayStackProps extends StackProps {
  readonly agentCoreRuntimeArn: string;
  readonly configTable: ITable;
  readonly vpc: IVpc;
  /** RDS Postgres instance from GlitchProtectDbStack — Lambda connects via IAM auth. */
  readonly protectDb: IDatabaseInstance;
}

/**
 * Glitch Gateway stack: Lambda Function URL for UI invocations, /api/* proxy, and keepalive.
 */
export class GlitchGatewayStack extends Stack {
  public readonly gatewayFunction: LambdaFunction;
  public readonly functionUrl: string;

  constructor(scope: Construct, id: string, props: GlitchGatewayStackProps) {
    super(scope, id, props);

    const { agentCoreRuntimeArn, configTable, vpc, protectDb } = props;

    // protect-query Lambda: direct Postgres reader for UI Protect tab (bypasses LLM)
    // Security group: outbound TCP 5432 to VPC CIDR only (reaches RDS in private subnets).
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
        PROTECT_DB_HOST: protectDb.dbInstanceEndpointAddress,
        PROTECT_DB_PORT: '5432',
        PROTECT_DB_NAME: 'glitch_protect',
        PROTECT_DB_USER: 'glitch_iam',
      },
    });

    // IAM authentication: Lambda role gets rds-db:connect on the glitch_iam DB user.
    protectDb.grantConnect(protectQueryFn, 'glitch_iam');

    this.gatewayFunction = new LambdaFunction(this, 'GatewayFunction', {
      functionName: 'glitch-gateway',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/gateway')),
      timeout: Duration.seconds(300),
      memorySize: 512,
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
}

/**
 * Telegram webhook stack: Lambda that receives Telegram updates and invokes AgentCore runtime.
 */
export class TelegramWebhookStack extends Stack {
  public readonly webhookFunction: LambdaFunction;
  public readonly webhookUrl: string;

  constructor(scope: Construct, id: string, props: TelegramWebhookStackProps) {
    super(scope, id, props);

    const { configTable, telegramBotTokenSecret, agentCoreRuntimeArn } = props;

    this.webhookFunction = new LambdaFunction(this, 'TelegramWebhookFunction', {
      functionName: 'glitch-telegram-webhook',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/telegram-webhook')),
      timeout: Duration.seconds(300),
      memorySize: 256,
      environment: {
        CONFIG_TABLE_NAME: configTable.tableName,
        TELEGRAM_SECRET_NAME: SECRET_NAMES.TELEGRAM_BOT_TOKEN,
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
        // WEBHOOK_FUNCTION_URL is added below after the Function URL is created
      },
    });

    configTable.grantReadWriteData(this.webhookFunction);
    telegramBotTokenSecret.grantRead(this.webhookFunction);

    this.webhookFunction.addToRolePolicy(
      new PolicyStatement({
        sid: 'InvokeAgentCoreRuntime',
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

    // NOTE: SsmTelegramWebhookUrl is written in app.ts (GlitchTelegramSsmStack) to avoid a
    // CloudFormation circular dependency: FunctionUrl → Function → ServiceRole → Policy → FunctionUrl.
    // The CfnOutput below is for reference only.
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
const PORKBUN_SECRET_NAME = 'glitch/porkbun-api';

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
    // The Porkbun secret lives in us-west-2; the Lambda reads it cross-region.

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
    // Called by the home network to update Porkbun DNS + WAF IP set + SSM whenever
    // the home IP changes. Replaces the porkbun-ddns-update.sh shell script.
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
                // Porkbun API keys (us-west-2)
                'arn:aws:secretsmanager:us-west-2:999776382415:secret:glitch/porkbun-api-*',
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
      description: 'DDNS updater webhook: reads caller IP, updates Porkbun DNS + WAF + SSM',
      environment: {
        DDNS_SUBDOMAIN: 'home',
        DDNS_DOMAIN: 'awoo.agency',
        WAF_IP_SET_ID: ipv4Set.attrId,
        WAF_IP_SET_NAME: 'GlitchAllowedIPs',
        SSM_PARAM: WAF_SSM_IPV4,
        PORKBUN_SECRET_NAME: PORKBUN_SECRET_NAME,
        PORKBUN_SECRET_REGION: 'us-west-2',
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
 * AgentCore runs in PUBLIC network mode — no VPC/SG dependencies.
 * On-prem LLM access is via Site-to-Site VPN (Foundation stack).
 */
export class AgentCoreStack extends Stack {
  public readonly agentRuntimeRole: IRole;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { runtimeRole } = props;
    this.agentRuntimeRole = runtimeRole;

    new ManagedPolicy(this, 'AgentRuntimeRoleDefaultPolicy', {
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
          // ECR pull: required for UpdateAgentRuntime / runtime to pull container image.
          new PolicyStatement({
            sid: 'ECRTokenAccess',
            effect: Effect.ALLOW,
            actions: ['ecr:GetAuthorizationToken'],
            resources: ['*'],
          }),
          new PolicyStatement({
            sid: 'ECRImageAccess',
            effect: Effect.ALLOW,
            actions: [
              'ecr:BatchCheckLayerAvailability',
              'ecr:GetDownloadUrlForLayer',
              'ecr:BatchGetImage',
            ],
            resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`],
          }),
          new PolicyStatement({
            sid: 'AgentCoreMemoryAccess',
            effect: Effect.ALLOW,
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
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/protect-db*`,
            ],
          }),
          new PolicyStatement({
            sid: 'SsmProtectParamsRead',
            effect: Effect.ALLOW,
            actions: ['ssm:GetParameter', 'ssm:GetParameters'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect/*`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect-db/*`,
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
            sid: 'SoulS3ListBucket',
            effect: Effect.ALLOW,
            actions: ['s3:ListBucket'],
            resources: [`arn:aws:s3:::${soulBucketName(this.account, this.region)}`],
          }),
          new PolicyStatement({
            sid: 'SoulS3Access',
            effect: Effect.ALLOW,
            actions: ['s3:GetObject', 's3:PutObject'],
            resources: [`arn:aws:s3:::${soulBucketName(this.account, this.region)}/*`],
          }),
          new PolicyStatement({
            sid: 'SoulSsmRead',
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
          // SSM write — Glitch updates cross-agent ARN parameters after agentcore deploy.
          new PolicyStatement({
            sid: 'SsmAgentArnWrite',
            effect: Effect.ALLOW,
            actions: ['ssm:PutParameter'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/glitch-runtime-arn`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/runtime-arn`,
            ],
          }),
          new PolicyStatement({
            sid: 'CodeBuildDeployStatusRead',
            effect: Effect.ALLOW,
            actions: ['codebuild:ListBuildsForProject', 'codebuild:BatchGetBuilds'],
            resources: [
              `arn:aws:codebuild:${this.region}:${this.account}:project/bedrock-agentcore-glitch-builder`,
              `arn:aws:codebuild:${this.region}:${this.account}:project/bedrock-agentcore-sentinel-builder`,
            ],
          }),
          new PolicyStatement({
            sid: 'TelegramWebhookLambdaUrlRead',
            effect: Effect.ALLOW,
            actions: ['lambda:GetFunctionUrlConfig'],
            resources: [`arn:aws:lambda:${this.region}:${this.account}:function:glitch-telegram-webhook`],
          }),
          new PolicyStatement({
            sid: 'InvokeSentinelAgent',
            effect: Effect.ALLOW,
            actions: ['bedrock-agentcore:InvokeAgentRuntime'],
            resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
            conditions: { StringLike: { 'aws:ResourceTag/Name': 'Sentinel*' } },
          }),
        ],
      }),
    });

    new CfnOutput(this, 'AgentRuntimeRoleArn', {
      value: runtimeRole.roleArn,
      description: 'IAM role ARN for AgentCore Runtime',
    });
  }
}

// --- GlitchSentinelStack ---

export interface SentinelStackProps extends StackProps {
  /** Runtime role created by GlitchFoundationStack. */
  runtimeRole: IRole;
  /** Glitch runtime ARN (for A2A invocation permission). */
  glitchRuntimeArn: string;
}

/**
 * IAM policies attached to the Sentinel agent's runtime role.
 * Sentinel owns: CloudWatch Logs read, UniFi Protect, Pi-hole, UniFi Network,
 * DNS Intelligence, Infrastructure Ops, GitHub, Telegram alerting.
 */
export class GlitchSentinelStack extends Stack {
  constructor(scope: Construct, id: string, props: SentinelStackProps) {
    super(scope, id, props);

    const { runtimeRole, glitchRuntimeArn } = props;

    new ManagedPolicy(this, 'SentinelRuntimePolicy', {
      managedPolicyName: `GlitchSentinelRuntimePolicy-${this.region}`,
      roles: [runtimeRole],
      document: new PolicyDocument({
        statements: [
          // Bedrock model access (Sonnet 4 + 4.5; Opus excluded for ops agent cost control)
          new PolicyStatement({
            sid: 'BedrockModelAccess',
            effect: Effect.ALLOW,
            actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
            resources: [
              ...SENTINEL_BEDROCK_MODEL_ARNS,
              `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
              `arn:aws:bedrock:${this.region}::inference-profile/*`,
            ],
          }),
          new PolicyStatement({
            sid: 'ECRImageAccess',
            effect: Effect.ALLOW,
            actions: ['ecr:BatchGetImage', 'ecr:GetDownloadUrlForLayer'],
            resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`],
          }),
          new PolicyStatement({
            sid: 'ECRTokenAccess',
            effect: Effect.ALLOW,
            actions: ['ecr:GetAuthorizationToken'],
            resources: ['*'],
          }),
          // CloudWatch Logs — read monitored log groups
          new PolicyStatement({
            sid: 'CloudWatchLogsRead',
            effect: Effect.ALLOW,
            actions: [
              'logs:DescribeLogGroups',
              'logs:DescribeLogStreams',
              'logs:FilterLogEvents',
              'logs:GetLogEvents',
              'logs:StartQuery',
              'logs:GetQueryResults',
            ],
            resources: [
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/runtimes/*:*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/lambda/glitch-*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/lambda/glitch-*:*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/*:*`,
            ],
          }),
          // CloudWatch Logs — write Sentinel's own logs
          new PolicyStatement({
            sid: 'CloudWatchLogsWrite',
            effect: Effect.ALLOW,
            actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
            resources: [
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*:*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/sentinel/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/sentinel/*:*`,
            ],
          }),
          // CloudWatch Metrics — read Lambda metrics, alarms
          new PolicyStatement({
            sid: 'CloudWatchMetricsRead',
            effect: Effect.ALLOW,
            actions: ['cloudwatch:GetMetricData', 'cloudwatch:GetMetricStatistics', 'cloudwatch:ListMetrics', 'cloudwatch:DescribeAlarms'],
            resources: ['*'],
          }),
          // CloudWatch Metrics — write Sentinel metrics and AgentCore OTEL namespace.
          // AWS execution role docs require "bedrock-agentcore" namespace for the runtime's
          // built-in OTEL instrumentation (xray + cloudwatch). "Glitch/Sentinel" is for
          // custom Sentinel metrics.
          new PolicyStatement({
            sid: 'CloudWatchMetricsWrite',
            effect: Effect.ALLOW,
            actions: ['cloudwatch:PutMetricData'],
            resources: ['*'],
            conditions: { StringEquals: { 'cloudwatch:namespace': ['bedrock-agentcore', 'Glitch/Sentinel'] } },
          }),
          // X-Ray tracing
          new PolicyStatement({
            sid: 'XRayTracing',
            effect: Effect.ALLOW,
            actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords', 'xray:GetSamplingRules', 'xray:GetSamplingTargets'],
            resources: ['*'],
          }),
          // CloudFormation — read-only for stack inspection and drift detection
          new PolicyStatement({
            sid: 'CloudFormationRead',
            effect: Effect.ALLOW,
            actions: [
              'cloudformation:DescribeStacks',
              'cloudformation:DescribeStackEvents',
              'cloudformation:DescribeStackResources',
              'cloudformation:DetectStackDrift',
              'cloudformation:DescribeStackDriftDetectionStatus',
              'cloudformation:DescribeStackResourceDrifts',
              'cloudformation:ListStacks',
              'cloudformation:GetTemplate',
            ],
            resources: [`arn:aws:cloudformation:${this.region}:${this.account}:stack/*/*`],
          }),
          // CloudFormation — rollback operations
          new PolicyStatement({
            sid: 'CloudFormationRollback',
            effect: Effect.ALLOW,
            actions: [
              'cloudformation:CancelUpdateStack',
              'cloudformation:ContinueUpdateRollback',
            ],
            resources: [`arn:aws:cloudformation:${this.region}:${this.account}:stack/Glitch*/*`],
          }),
          // Secrets Manager — read credentials for all Sentinel tools
          new PolicyStatement({
            sid: 'SecretsManagerRead',
            effect: Effect.ALLOW,
            actions: ['secretsmanager:GetSecretValue'],
            resources: [
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.TELEGRAM_BOT_TOKEN}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.GITHUB_TOKEN}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.PIHOLE_API}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:${SECRET_NAMES.UNIFI_CONTROLLER}*`,
              `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/protect-db*`,
            ],
          }),
          // DynamoDB — read Telegram config for owner chat ID
          new PolicyStatement({
            sid: 'TelegramConfigRead',
            effect: Effect.ALLOW,
            actions: ['dynamodb:GetItem', 'dynamodb:Query'],
            resources: [`arn:aws:dynamodb:${this.region}:${this.account}:table/${TABLE_NAMES.TELEGRAM_CONFIG}`],
          }),
          // SSM Parameters — read Sentinel config and Protect config
          new PolicyStatement({
            sid: 'SsmParameterRead',
            effect: Effect.ALLOW,
            actions: ['ssm:GetParameter', 'ssm:GetParameters', 'ssm:GetParametersByPath'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/*`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect/*`,
            ],
          }),
          // Workload identity — required by AgentCore Runtime execution role for agent
          // identity features (GetWorkloadAccessToken*). Scoped to the default workload
          // identity directory per the official execution role template.
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
              `arn:aws:bedrock-agentcore:${this.region}:${this.account}:workload-identity-directory/default/workload-identity/sentinel-*`,
            ],
          }),
          // A2A: invoke Glitch agent.
          // Widened to wildcard + tag condition so this survives agent redeploys without
          // needing a CDK redeployment when Glitch's runtime ARN changes.
          new PolicyStatement({
            sid: 'InvokeGlitchAgent',
            effect: Effect.ALLOW,
            actions: ['bedrock-agentcore:InvokeAgentRuntime'],
            resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
            conditions: { StringLike: { 'aws:ResourceTag/Name': 'Glitch*' } },
          }),
        ],
      }),
    });

    // Scheduled Sentinel Protect evaluation (EventBridge + Lambda)
    const protectEvalRole = new Role(this, 'SentinelProtectEvalRole', {
      assumedBy: new ServicePrincipal('lambda.amazonaws.com'),
      description: 'Role for glitch-sentinel-protect-eval Lambda',
    });
    protectEvalRole.addManagedPolicy(
      ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole')
    );
    protectEvalRole.addToPolicy(
      new PolicyStatement({
        sid: 'SsmSentinelArn',
        effect: Effect.ALLOW,
        actions: ['ssm:GetParameter'],
        resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/runtime-arn`],
      })
    );
    protectEvalRole.addToPolicy(
      new PolicyStatement({
        sid: 'InvokeSentinelRuntime',
        effect: Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
        conditions: { StringLike: { 'aws:ResourceTag/Name': 'Sentinel*' } },
      })
    );
    const protectEvalFn = new LambdaFunction(this, 'SentinelProtectEvalFunction', {
      functionName: 'glitch-sentinel-protect-eval',
      runtime: Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: Code.fromAsset(path.join(__dirname, '../lambda/sentinel-protect-eval')),
      timeout: Duration.seconds(120),
      memorySize: 128,
      role: protectEvalRole,
    });
    new Rule(this, 'SentinelProtectEvalSchedule', {
      schedule: Schedule.rate(Duration.minutes(15)),
      targets: [new LambdaFunctionTarget(protectEvalFn)],
      description: 'Invoke Sentinel every 15 min for Protect camera evaluation',
    });

    // SSM parameters for Sentinel configuration.
    // Use AwsCustomResource with PutParameter Overwrite so we never fail with "parameter already exists"
    // (e.g. after stack re-create or param created outside the stack).
    new AwsCustomResource(this, 'SentinelGlitchRuntimeArnParam', {
      onUpdate: {
        service: 'SSM',
        action: 'putParameter',
        parameters: {
          Name: '/glitch/sentinel/glitch-runtime-arn',
          Value: glitchRuntimeArn,
          Type: 'String',
          Overwrite: true,
          Description: 'Glitch agent runtime ARN for Sentinel A2A invocation',
        },
        physicalResourceId: PhysicalResourceId.of('/glitch/sentinel/glitch-runtime-arn'),
      },
      policy: AwsCustomResourcePolicy.fromStatements([
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ['ssm:PutParameter'],
          resources: [
            `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/glitch-runtime-arn`,
          ],
        }),
      ]),
    });

    new StringParameter(this, 'SentinelMonitoredLogGroupsParam', {
      parameterName: '/glitch/sentinel/monitored-log-groups',
      stringValue: JSON.stringify([
        '/aws/bedrock-agentcore/runtimes',
        '/aws/lambda/glitch-telegram-webhook',
        '/aws/lambda/glitch-gateway',
        '/aws/lambda/glitch-agentcore-keepalive',
        '/aws/lambda/glitch-sentinel-protect-eval',
        '/glitch/telemetry',
      ]),
      description: 'JSON array of CloudWatch log groups for Sentinel to monitor',
    });

    new CfnOutput(this, 'SentinelRuntimeRoleArn', {
      value: runtimeRole.roleArn,
      description: 'IAM role ARN for Sentinel AgentCore Runtime',
    });
  }
}

