/**
 * All Glitch CDK stacks in a single file.
 * Order: dependency-friendly (interfaces and stacks used by others come first).
 */
import * as cdk from 'aws-cdk-lib';
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
import * as wafv2 from 'aws-cdk-lib/aws-wafv2';
import * as cr from 'aws-cdk-lib/custom-resources';
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
} as const;

// --- GlitchFoundationStack ---
// Consolidated stack: VPC + IAM Roles + SSM Parameters.
// AgentCore runtimes run in PUBLIC network mode -- no VPC ENIs, no VPC endpoints needed.
// The VPC exists for the Site-to-Site VPN (on-prem LLM access via UDM-Pro gateway).

export interface GlitchFoundationStackProps extends cdk.StackProps {
  readonly vpcCidr?: string;
}

export class GlitchFoundationStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly privateSubnets: ec2.ISubnet[];
  public readonly publicSubnets: ec2.ISubnet[];
  public readonly runtimeRole: iam.Role;
  public readonly codeBuildRole: iam.Role;

  constructor(scope: Construct, id: string, props?: GlitchFoundationStackProps) {
    super(scope, id, props);

    // ========== VPC ==========
    // No NAT Gateway; agents use PUBLIC mode. Private subnets exist for VPN route propagation only (no internet egress).
    this.vpc = new ec2.Vpc(this, 'Vpc', {
      maxAzs: 2,
      natGateways: 0,
      ipAddresses: ec2.IpAddresses.cidr(props?.vpcCidr || '10.0.0.0/16'),
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
      ],
      enableDnsHostnames: true,
      enableDnsSupport: true,
    });

    this.privateSubnets = this.vpc.privateSubnets;
    this.publicSubnets = this.vpc.publicSubnets;

    // ========== IAM Roles (NO hardcoded names) ==========

    this.runtimeRole = new iam.Role(this, 'RuntimeRole', {
      assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
      description: 'IAM role for AgentCore Runtime (Glitch + Sentinel)',
    });

    // CloudWatch Logs — minimum set for AgentCore runtime startup.
    // Broader log permissions are added per-agent in AgentCoreStack / GlitchSentinelStack.
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      sid: 'CloudWatchLogsDescribeGroups',
      effect: iam.Effect.ALLOW,
      actions: ['logs:DescribeLogGroups'],
      resources: [`arn:aws:logs:${this.region}:${this.account}:log-group:*`],
    }));

    // X-Ray: OTEL ADOT traces exporter.
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      sid: 'XRayTracing',
      effect: iam.Effect.ALLOW,
      actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords', 'xray:GetSamplingRules', 'xray:GetSamplingTargets'],
      resources: ['*'],
    }));

    // CloudWatch metrics: OTEL ADOT metrics exporter.
    // Scoped to known namespaces to prevent metric pollution.
    this.runtimeRole.addToPolicy(new iam.PolicyStatement({
      sid: 'CloudWatchMetrics',
      effect: iam.Effect.ALLOW,
      actions: ['cloudwatch:PutMetricData'],
      resources: ['*'],
      conditions: {
        StringEquals: {
          'cloudwatch:namespace': ['bedrock-agentcore', 'Glitch/Agent', 'Glitch/Sentinel'],
        },
      },
    }));

    // CodeBuild role for container builds
    this.codeBuildRole = new iam.Role(this, 'CodeBuildRole', {
      assumedBy: new iam.ServicePrincipal('codebuild.amazonaws.com'),
      description: 'IAM role for AgentCore CodeBuild container builds',
    });

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
      resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`],
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

// --- GlitchVpnStack ---

export interface GlitchVpnStackProps extends cdk.StackProps {
  /** UDM-Pro public IP for the Customer Gateway. Pass on first deploy via context: -c onPremPublicIp=x.x.x.x */
  readonly onPremPublicIp?: string;
  /** BGP ASN for the on-prem Customer Gateway. UDM-Pro default is 65000. */
  readonly onPremBgpAsn?: number;
  /** VPC from GlitchFoundationStack. */
  readonly vpc: ec2.IVpc;
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
export class GlitchVpnStack extends cdk.Stack {
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
    const vpnGateway = new ec2.CfnVPNGateway(this, 'VpnGateway', {
      type: 'ipsec.1',
      amazonSideAsn: 64513,
      tags: [{ key: 'Name', value: 'glitch-vpn-gateway' }],
    });
    vpnGateway.cfnOptions.deletionPolicy = cdk.CfnDeletionPolicy.RETAIN;
    this.vpnGatewayId = vpnGateway.ref;

    const attachAndPropagateRole = new iam.Role(this, 'VgwAttachRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
      inlinePolicies: {
        Ec2: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
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
      ...vpc.privateSubnets.map(s => (s as ec2.PrivateSubnet).routeTable.routeTableId),
      ...vpc.publicSubnets.map(s => (s as ec2.PublicSubnet).routeTable.routeTableId),
    ];

    const attachAndPropagateFn = new lambda.Function(this, 'VgwAttachFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromInline(`
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
      timeout: cdk.Duration.seconds(120),
    });

    // PropagationVersion: bump to force custom resource to re-run (enables propagation on all route tables including main).
    const attachResource = new cdk.CustomResource(this, 'VgwAttachAndPropagate', {
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
      const getOrCreateCgwRole = new iam.Role(this, 'GetOrCreateCgwRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          Ec2: new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
                actions: ['ec2:DescribeCustomerGateways', 'ec2:CreateCustomerGateway', 'ec2:CreateTags'],
                resources: ['*'],
              }),
            ],
          }),
        },
      });

      const getOrCreateCgwFn = new lambda.Function(this, 'GetOrCreateCgwFn', {
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: 'index.handler',
        role: getOrCreateCgwRole,
        timeout: cdk.Duration.seconds(30),
        code: lambda.Code.fromInline(`
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

      const getOrCreateCgw = new cdk.CustomResource(this, 'GetOrCreateCustomerGateway', {
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
      const getOrCreateVpnRole = new iam.Role(this, 'GetOrCreateVpnRole', {
        assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
        managedPolicies: [
          iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
        ],
        inlinePolicies: {
          Ec2: new iam.PolicyDocument({
            statements: [
              new iam.PolicyStatement({
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

      const getOrCreateVpnFn = new lambda.Function(this, 'GetOrCreateVpnFn', {
        runtime: lambda.Runtime.PYTHON_3_12,
        handler: 'index.handler',
        role: getOrCreateVpnRole,
        timeout: cdk.Duration.seconds(60),
        code: lambda.Code.fromInline(`
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
      const getOrCreateVpn = new cdk.CustomResource(this, 'GetOrCreateVpnConnection', {
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

      new cdk.CfnOutput(this, 'CustomerGatewayId', {
        value: customerGatewayId,
        description: 'Customer Gateway ID — configure matching entry on UDM-Pro (VPN > Site-to-Site)',
      });
      new cdk.CfnOutput(this, 'VpnConnectionId', {
        value: vpnConnectionId,
        description: 'VPN Connection ID — download tunnel config from AWS Console for UDM-Pro',
      });
    }

    new cdk.CfnOutput(this, 'VpnGatewayId', {
      value: vpnGateway.ref,
      description: 'VPN Gateway ID',
    });
  }
}

// --- SecretsStack ---

export interface SecretsStackProps extends cdk.StackProps {
  // No IAM role props: secret read access for the AgentCore runtime role is granted
  // in AgentCoreStack (SecretsManagerAccess policy) to avoid deploy-order and 404 issues.
}

export class SecretsStack extends cdk.Stack {
  public readonly apiKeysSecret: secretsmanager.ISecret;
  public readonly telegramBotTokenSecret: secretsmanager.ISecret;
  public readonly porkbunApiSecret: secretsmanager.ISecret;
  public readonly piholeApiSecret: secretsmanager.ISecret;

  constructor(scope: Construct, id: string, props?: SecretsStackProps) {
    super(scope, id, props);

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
export class GlitchStorageStack extends cdk.Stack {
  public readonly configTable: dynamodb.ITable;
  public readonly soulBucket: s3.IBucket;
  public readonly telemetryLogGroup: logs.ILogGroup;

  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const tableName = TABLE_NAMES.TELEGRAM_CONFIG;
    const bucketName = soulBucketName(this.account, this.region);
    const logGroupName = '/glitch/telemetry';

    this.configTable = dynamodb.Table.fromTableName(this, 'ConfigTable', tableName);
    this.soulBucket = s3.Bucket.fromBucketName(this, 'GlitchSoulBucket', bucketName);
    this.telemetryLogGroup = logs.LogGroup.fromLogGroupName(this, 'GlitchTelemetryLogGroup', logGroupName);

    new ssm.StringParameter(this, 'SoulS3Bucket', {
      parameterName: SOUL_SSM.S3_BUCKET,
      stringValue: this.soulBucket.bucketName,
      description: 'S3 bucket for Glitch SOUL.md and poet-soul (runtime discovery)',
    });
    new ssm.StringParameter(this, 'SoulS3Key', {
      parameterName: SOUL_SSM.S3_KEY,
      stringValue: 'soul.md',
      description: 'S3 key for SOUL.md',
    });
    new ssm.StringParameter(this, 'SoulPoetSoulKey', {
      parameterName: SOUL_SSM.POET_SOUL_KEY,
      stringValue: 'poet-soul.md',
      description: 'S3 key for poet-soul.md',
    });
    new ssm.StringParameter(this, 'SoulStoryBookKey', {
      parameterName: SOUL_SSM.STORY_BOOK_KEY,
      stringValue: 'story-book.md',
      description: 'S3 key for story-book.md',
    });

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

    // protect-query Lambda: direct Postgres reader for UI Protect tab (bypasses LLM)
    const protectDbSecret = secretsmanager.Secret.fromSecretNameV2(
      this,
      'ProtectDbSecret',
      'glitch/protect-db',
    );

    const protectQueryFn = new lambda.Function(this, 'ProtectQueryFunction', {
      functionName: 'glitch-protect-query',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/protect-query'), {
        bundling: {
          image: lambda.Runtime.PYTHON_3_12.bundlingImage,
          command: [
            'bash', '-c',
            'pip install -r requirements.txt -t /asset-output && cp -au . /asset-output',
          ],
        },
      }),
      timeout: cdk.Duration.seconds(30),
      memorySize: 256,
      environment: {
        PROTECT_DB_SECRET_NAME: 'glitch/protect-db',
      },
    });

    protectDbSecret.grantRead(protectQueryFn);

    this.gatewayFunction = new lambda.Function(this, 'GatewayFunction', {
      functionName: 'glitch-gateway',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/gateway')),
      timeout: cdk.Duration.seconds(300),
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
      new iam.PolicyStatement({
        sid: 'BedrockAgentCoreAccess',
        effect: iam.Effect.ALLOW,
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
      authType: lambda.FunctionUrlAuthType.NONE,
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
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/telegram-webhook')),
      timeout: cdk.Duration.seconds(300),
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
      new iam.PolicyStatement({
        sid: 'InvokeAgentCoreRuntime',
        effect: iam.Effect.ALLOW,
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
      new iam.PolicyStatement({
        sid: 'ReadOwnWebhookUrlFromSsm',
        effect: iam.Effect.ALLOW,
        actions: ['ssm:GetParameter'],
        resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter${SSM_PARAMS.TELEGRAM_WEBHOOK_URL}`],
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
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/telegram-keepalive')),
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

    // SsmTelegramConfigTable: safe to write here (no circular dep — table name is not a FunctionUrl token).
    new ssm.StringParameter(this, 'SsmTelegramConfigTable', {
      parameterName: SSM_PARAMS.TELEGRAM_CONFIG_TABLE,
      stringValue: configTable.tableName,
      description: 'DynamoDB config table name (for runtime GLITCH_CONFIG_TABLE)',
    });

    // NOTE: SsmTelegramWebhookUrl is written in app.ts (GlitchTelegramSsmStack) to avoid a
    // CloudFormation circular dependency: FunctionUrl → Function → ServiceRole → Policy → FunctionUrl.
    // The CfnOutput below is for reference only.
    new cdk.CfnOutput(this, 'TelegramWebhookUrl', {
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

export interface GlitchEdgeStackProps extends cdk.StackProps {
  /**
   * IPv4 CIDRs to allow. When provided, these override the SSM/custom-resource lookup.
   * Pass via CDK context: -c allowedIpAddresses=1.2.3.4/32,5.6.7.8/32
   */
  readonly allowedIpAddresses?: string[];
}

export class GlitchEdgeStack extends cdk.Stack {
  public readonly webAclArn: string;

  constructor(scope: Construct, id: string, props: GlitchEdgeStackProps) {
    super(scope, id, props);

    // ── Porkbun IP lookup custom resource ─────────────────────────────────────
    // Runs at deploy time: calls Porkbun ping API → gets current public IP →
    // writes to SSM /glitch/waf/allowed-ipv4 → WAF IP set uses the result.
    // The Porkbun secret lives in us-west-2; the Lambda reads it cross-region.

    const porkbunLookupRole = new iam.Role(this, 'PorkbunLookupRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
      inlinePolicies: {
        PorkbunLookup: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
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

    const porkbunLookupFn = new lambda.Function(this, 'PorkbunIpLookupFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/porkbun-ip-lookup')),
      role: porkbunLookupRole,
      timeout: cdk.Duration.seconds(30),
      description: 'Custom resource: reads /glitch/waf/allowed-ipv4 from SSM for WAF allowlist',
    });

    // FallbackIpCidr is read from cdk.context.json (SSM lookup cached at synth time).
    // It is only used if the ddns-updater webhook has never been called and SSM is empty.
    const fallbackIpCidr = ssm.StringParameter.valueFromLookup(this, WAF_SSM_IPV4);

    const porkbunIpResource = new cdk.CustomResource(this, 'PorkbunIpLookup', {
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
      const ssmIpv4Raw = ssm.StringParameter.valueFromLookup(this, WAF_SSM_IPV4);
      const fromSsm = parseIps(ssmIpv4Raw);
      allowedIps = fromSsm.length ? fromSsm : [porkbunIpResource.getAttString('IpCidr')];
    }

    const ipv4Set = new wafv2.CfnIPSet(this, 'AllowedIpSet', {
      name: 'GlitchAllowedIPs',
      scope: 'CLOUDFRONT',
      ipAddressVersion: 'IPV4',
      addresses: allowedIps,
      description: 'Allowed IPv4 CIDRs for Glitch dashboard',
    });
    ipv4Set.node.addDependency(porkbunIpResource);

    const rules: wafv2.CfnWebACL.RuleProperty[] = [
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
    const webAcl = new wafv2.CfnWebACL(this, 'WebAcl', {
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

    new cdk.CfnOutput(this, 'WebAclArn', {
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
    const ddnsTokenSecret = new secretsmanager.Secret(this, 'DdnsTokenSecret', {
      secretName: 'glitch/ddns-token',
      description: 'Bearer token for the DDNS updater webhook Lambda',
      generateSecretString: {
        passwordLength: 32,
        excludePunctuation: true,
      },
    });

    const ddnsUpdaterRole = new iam.Role(this, 'DdnsUpdaterRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole'),
      ],
      inlinePolicies: {
        DdnsUpdater: new iam.PolicyDocument({
          statements: [
            new iam.PolicyStatement({
              sid: 'ReadSecrets',
              actions: ['secretsmanager:GetSecretValue'],
              resources: [
                // Porkbun API keys (us-west-2)
                'arn:aws:secretsmanager:us-west-2:999776382415:secret:glitch/porkbun-api-*',
                // DDNS bearer token (us-east-1, this stack's region)
                ddnsTokenSecret.secretArn,
              ],
            }),
            new iam.PolicyStatement({
              sid: 'UpdateWafIpSet',
              actions: ['wafv2:GetIPSet', 'wafv2:UpdateIPSet'],
              resources: [ipv4Set.attrArn],
            }),
            new iam.PolicyStatement({
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

    const ddnsUpdaterFn = new lambda.Function(this, 'DdnsUpdaterFn', {
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/ddns-updater')),
      role: ddnsUpdaterRole,
      timeout: cdk.Duration.seconds(30),
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
      authType: lambda.FunctionUrlAuthType.NONE,
    });

    new cdk.CfnOutput(this, 'DdnsUpdaterUrl', {
      value: ddnsUpdaterUrl.url,
      description: 'DDNS updater webhook URL — POST with Authorization: Bearer <glitch/ddns-token>',
    });
  }
}

// --- GlitchUiHostingStack ---
// CloudFront + S3 (OAC) + Lambda Function URL (OAC/IAM) + WAF association.
// CloudFront-based UI hosting with WAF IP allowlist and Lambda origin.

export interface GlitchUiHostingStackProps extends cdk.StackProps {
  readonly gatewayFunction: lambda.IFunction;
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

export class GlitchUiHostingStack extends cdk.Stack {
  public readonly uiBucket: s3.Bucket;
  public readonly distribution: cloudfront.Distribution;

  constructor(scope: Construct, id: string, props: GlitchUiHostingStackProps) {
    super(scope, id, props);

    const { gatewayFunction, gatewayFunctionUrl, customDomain, webAclArn, certificateArn } = props;

    // ========== S3 Bucket (fully private; only CloudFront OAC can read) ==========
    this.uiBucket = new s3.Bucket(this, 'UiBucket', {
      bucketName: `glitch-ui-${this.account}-${this.region}`,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    // ========== CloudFront OAC for Lambda Function URL ==========
    // Signs every origin request with SigV4 so the IAM-auth FURL is only reachable via CF.
    const lambdaOac = new cloudfront.CfnOriginAccessControl(this, 'LambdaOac', {
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
      principal: new iam.ServicePrincipal('cloudfront.amazonaws.com'),
      action: 'lambda:InvokeFunctionUrl',
      sourceArn: `arn:aws:cloudfront::${this.account}:distribution/*`,
    });

    // ========== ACM Certificate (optional; must be in us-east-1) ==========
    const certificate = certificateArn
      ? acm.Certificate.fromCertificateArn(this, 'Certificate', certificateArn)
      : undefined;

    // ========== CloudFront Origins ==========
    const lambdaUrlHostname = cdk.Fn.select(2, cdk.Fn.split('/', gatewayFunctionUrl));

    const s3Origin = origins.S3BucketOrigin.withOriginAccessControl(this.uiBucket);

    // Origin response timeout 60s so agent invocations (chat) don't 504; default is 30s.
    const lambdaOrigin = new origins.HttpOrigin(lambdaUrlHostname, {
      protocolPolicy: cloudfront.OriginProtocolPolicy.HTTPS_ONLY,
      originId: 'GlitchGatewayLambda',
      readTimeout: cdk.Duration.seconds(60),
    });

    // ========== CloudFront Distribution ==========
    // /api/* and Lambda paths use CACHING_DISABLED (CloudFront rejects HeaderBehavior when TTL=0).
    // IPv6 disabled: WAF IP allowlist is IPv4-only; disabling IPv6 ensures browsers always
    // connect via IPv4 so the WAF allowlist matches correctly.
    this.distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: 'Glitch Agent UI',
      ...(certificate ? { certificate, domainNames: [customDomain] } : {}),
      ...(webAclArn ? { webAclId: webAclArn } : {}),
      enableIpv6: false,
      defaultRootObject: 'index.html',
      defaultBehavior: {
        origin: s3Origin,
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
        compress: true,
      },
      additionalBehaviors: {
        '/api/*': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
        '/invocations*': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        },
        '/health': {
          origin: lambdaOrigin,
          viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
          cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
          allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD,
          originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
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
      new iam.PolicyStatement({
        sid: 'AllowCloudFrontOACGetObject',
        actions: ['s3:GetObject'],
        resources: [this.uiBucket.arnForObjects('*')],
        principals: [new iam.ServicePrincipal('cloudfront.amazonaws.com')],
        conditions: {
          StringEquals: {
            'AWS:SourceArn': `arn:aws:cloudfront::${this.account}:distribution/${this.distribution.distributionId}`,
          },
        },
      })
    );

    // Apply Lambda OAC to the CloudFront distribution via L1 escape hatch.
    // The Lambda origin is the second entry in the Origins array (index 1; S3 is index 0).
    const cfnDistrib = this.distribution.node.defaultChild as cloudfront.CfnDistribution;
    cfnDistrib.addPropertyOverride(
      'DistributionConfig.Origins.1.OriginAccessControlId',
      lambdaOac.attrId
    );

    // Deploy static UI assets to S3 and invalidate CloudFront cache.
    // Split so index.html (and glitch.svg) use no-cache; hashed assets use long cache.
    // Prune false so the two deployments do not remove each other's files.
    const uiDist = path.join(__dirname, '../../ui/dist');
    new s3deploy.BucketDeployment(this, 'DeployUiHtml', {
      sources: [s3deploy.Source.asset(uiDist, { exclude: ['assets', 'assets/**'] })],
      destinationBucket: this.uiBucket,
      distribution: this.distribution,
      distributionPaths: ['/*'],
      cacheControl: [s3deploy.CacheControl.noCache()],
      prune: false,
    });
    new s3deploy.BucketDeployment(this, 'DeployUiAssets', {
      sources: [s3deploy.Source.asset(uiDist, { exclude: ['index.html', 'glitch.svg'] })],
      destinationBucket: this.uiBucket,
      distribution: this.distribution,
      distributionPaths: ['/*'],
      cacheControl: [
        s3deploy.CacheControl.maxAge(cdk.Duration.days(365)),
        s3deploy.CacheControl.immutable(),
      ],
      prune: false,
    });

    new cdk.CfnOutput(this, 'UiBucketName', {
      value: this.uiBucket.bucketName,
      description: 'S3 bucket for UI static assets (private, served via CloudFront OAC)',
      exportName: 'GlitchUiBucketName',
    });
    new cdk.CfnOutput(this, 'CloudFrontDomainName', {
      value: this.distribution.distributionDomainName,
      description: `CloudFront domain — add CNAME from ${customDomain} to this value in Porkbun DNS`,
      exportName: 'GlitchCloudFrontDomain',
    });
    new cdk.CfnOutput(this, 'CloudFrontDistributionId', {
      value: this.distribution.distributionId,
      exportName: 'GlitchCloudFrontDistributionId',
    });
    new cdk.CfnOutput(this, 'UiUrl', {
      value: certificate ? `https://${customDomain}` : `https://${this.distribution.distributionDomainName}`,
      description: 'Glitch UI URL',
      exportName: 'GlitchUiUrl',
    });
  }
}

// --- AgentCoreStack ---

export interface AgentCoreStackProps extends cdk.StackProps {
  /** Runtime role to attach policies to (from GlitchFoundationStack) */
  readonly runtimeRole: iam.IRole;
}

/**
 * IAM policies for the Glitch AgentCore runtime role.
 * AgentCore runs in PUBLIC network mode — no VPC/SG dependencies.
 * On-prem LLM access is via Site-to-Site VPN (Foundation stack).
 */
export class AgentCoreStack extends cdk.Stack {
  public readonly agentRuntimeRole: iam.IRole;

  constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
    super(scope, id, props);

    const { runtimeRole } = props;
    this.agentRuntimeRole = runtimeRole;

    new iam.ManagedPolicy(this, 'AgentRuntimeRoleDefaultPolicy', {
      roles: [runtimeRole],
      document: new iam.PolicyDocument({
        statements: [
          new iam.PolicyStatement({
            sid: 'BedrockModelAccess',
            effect: iam.Effect.ALLOW,
            actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
            resources: [
              ...BEDROCK_MODEL_ARNS,
              `arn:aws:bedrock:${this.region}:${this.account}:inference-profile/*`,
              `arn:aws:bedrock:${this.region}::inference-profile/*`,
            ],
          }),
          // ECR pull: required for UpdateAgentRuntime / runtime to pull container image.
          new iam.PolicyStatement({
            sid: 'ECRTokenAccess',
            effect: iam.Effect.ALLOW,
            actions: ['ecr:GetAuthorizationToken'],
            resources: ['*'],
          }),
          new iam.PolicyStatement({
            sid: 'ECRImageAccess',
            effect: iam.Effect.ALLOW,
            actions: [
              'ecr:BatchCheckLayerAvailability',
              'ecr:GetDownloadUrlForLayer',
              'ecr:BatchGetImage',
            ],
            resources: [`arn:aws:ecr:${this.region}:${this.account}:repository/bedrock-agentcore-*`],
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
            sid: 'SecretsManagerRead',
            effect: iam.Effect.ALLOW,
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
          new iam.PolicyStatement({
            sid: 'SsmProtectParamsRead',
            effect: iam.Effect.ALLOW,
            actions: ['ssm:GetParameter', 'ssm:GetParameters'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect/*`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect-db/*`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'SecretsManagerWrite',
            effect: iam.Effect.ALLOW,
            actions: ['secretsmanager:CreateSecret', 'secretsmanager:PutSecretValue', 'secretsmanager:UpdateSecret'],
            resources: [`arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/*`],
          }),
          new iam.PolicyStatement({
            sid: 'CloudWatchLogs',
            effect: iam.Effect.ALLOW,
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
          new iam.PolicyStatement({
            sid: 'TelegramConfigTableAccess',
            effect: iam.Effect.ALLOW,
            actions: ['dynamodb:GetItem', 'dynamodb:PutItem', 'dynamodb:UpdateItem', 'dynamodb:DeleteItem', 'dynamodb:Query'],
            resources: [`arn:aws:dynamodb:${this.region}:${this.account}:table/${TABLE_NAMES.TELEGRAM_CONFIG}`],
          }),
          new iam.PolicyStatement({
            sid: 'SoulS3ListBucket',
            effect: iam.Effect.ALLOW,
            actions: ['s3:ListBucket'],
            resources: [`arn:aws:s3:::${soulBucketName(this.account, this.region)}`],
          }),
          new iam.PolicyStatement({
            sid: 'SoulS3Access',
            effect: iam.Effect.ALLOW,
            actions: ['s3:GetObject', 's3:PutObject'],
            resources: [`arn:aws:s3:::${soulBucketName(this.account, this.region)}/*`],
          }),
          new iam.PolicyStatement({
            sid: 'SoulSsmRead',
            effect: iam.Effect.ALLOW,
            actions: ['ssm:GetParameter', 'ssm:GetParameters'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/s3-bucket`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/s3-key`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/poet-soul-s3-key`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/soul/story-book-s3-key`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/ssh/hosts`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'StsGetCallerIdentity',
            effect: iam.Effect.ALLOW,
            actions: ['sts:GetCallerIdentity'],
            resources: ['*'],
          }),
          // SSM write — Glitch updates cross-agent ARN parameters after agentcore deploy.
          new iam.PolicyStatement({
            sid: 'SsmAgentArnWrite',
            effect: iam.Effect.ALLOW,
            actions: ['ssm:PutParameter'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/glitch-runtime-arn`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/runtime-arn`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'CodeBuildDeployStatusRead',
            effect: iam.Effect.ALLOW,
            actions: ['codebuild:ListBuildsForProject', 'codebuild:BatchGetBuilds'],
            resources: [
              `arn:aws:codebuild:${this.region}:${this.account}:project/bedrock-agentcore-glitch-builder`,
              `arn:aws:codebuild:${this.region}:${this.account}:project/bedrock-agentcore-sentinel-builder`,
            ],
          }),
          new iam.PolicyStatement({
            sid: 'TelegramWebhookLambdaUrlRead',
            effect: iam.Effect.ALLOW,
            actions: ['lambda:GetFunctionUrlConfig'],
            resources: [`arn:aws:lambda:${this.region}:${this.account}:function:glitch-telegram-webhook`],
          }),
          new iam.PolicyStatement({
            sid: 'InvokeSentinelAgent',
            effect: iam.Effect.ALLOW,
            actions: ['bedrock-agentcore:InvokeAgentRuntime'],
            resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
            conditions: { StringLike: { 'aws:ResourceTag/Name': 'Sentinel*' } },
          }),
        ],
      }),
    });

    new cdk.CfnOutput(this, 'AgentRuntimeRoleArn', {
      value: runtimeRole.roleArn,
      description: 'IAM role ARN for AgentCore Runtime',
    });
  }
}

// --- GlitchSentinelStack ---

export interface SentinelStackProps extends cdk.StackProps {
  /** Runtime role created by GlitchFoundationStack. */
  runtimeRole: iam.IRole;
  /** Glitch runtime ARN (for A2A invocation permission). */
  glitchRuntimeArn: string;
}

/**
 * IAM policies attached to the Sentinel agent's runtime role.
 * Sentinel owns: CloudWatch Logs read, UniFi Protect, Pi-hole, UniFi Network,
 * DNS Intelligence, Infrastructure Ops, GitHub, Telegram alerting.
 */
export class GlitchSentinelStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: SentinelStackProps) {
    super(scope, id, props);

    const { runtimeRole, glitchRuntimeArn } = props;

    new iam.ManagedPolicy(this, 'SentinelRuntimePolicy', {
      managedPolicyName: `GlitchSentinelRuntimePolicy-${this.region}`,
      roles: [runtimeRole],
      document: new iam.PolicyDocument({
        statements: [
          // Bedrock model access (Sonnet 4 + 4.5; Opus excluded for ops agent cost control)
          new iam.PolicyStatement({
            sid: 'BedrockModelAccess',
            effect: iam.Effect.ALLOW,
            actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
            resources: [
              ...SENTINEL_BEDROCK_MODEL_ARNS,
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
          // CloudWatch Logs — read monitored log groups
          new iam.PolicyStatement({
            sid: 'CloudWatchLogsRead',
            effect: iam.Effect.ALLOW,
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
          new iam.PolicyStatement({
            sid: 'CloudWatchLogsWrite',
            effect: iam.Effect.ALLOW,
            actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents'],
            resources: [
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/aws/bedrock-agentcore/*:*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/sentinel/*`,
              `arn:aws:logs:${this.region}:${this.account}:log-group:/glitch/sentinel/*:*`,
            ],
          }),
          // CloudWatch Metrics — read Lambda metrics, alarms
          new iam.PolicyStatement({
            sid: 'CloudWatchMetricsRead',
            effect: iam.Effect.ALLOW,
            actions: ['cloudwatch:GetMetricData', 'cloudwatch:GetMetricStatistics', 'cloudwatch:ListMetrics', 'cloudwatch:DescribeAlarms'],
            resources: ['*'],
          }),
          // CloudWatch Metrics — write Sentinel metrics and AgentCore OTEL namespace.
          // AWS execution role docs require "bedrock-agentcore" namespace for the runtime's
          // built-in OTEL instrumentation (xray + cloudwatch). "Glitch/Sentinel" is for
          // custom Sentinel metrics.
          new iam.PolicyStatement({
            sid: 'CloudWatchMetricsWrite',
            effect: iam.Effect.ALLOW,
            actions: ['cloudwatch:PutMetricData'],
            resources: ['*'],
            conditions: { StringEquals: { 'cloudwatch:namespace': ['bedrock-agentcore', 'Glitch/Sentinel'] } },
          }),
          // X-Ray tracing
          new iam.PolicyStatement({
            sid: 'XRayTracing',
            effect: iam.Effect.ALLOW,
            actions: ['xray:PutTraceSegments', 'xray:PutTelemetryRecords', 'xray:GetSamplingRules', 'xray:GetSamplingTargets'],
            resources: ['*'],
          }),
          // CloudFormation — read-only for stack inspection and drift detection
          new iam.PolicyStatement({
            sid: 'CloudFormationRead',
            effect: iam.Effect.ALLOW,
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
          new iam.PolicyStatement({
            sid: 'CloudFormationRollback',
            effect: iam.Effect.ALLOW,
            actions: [
              'cloudformation:CancelUpdateStack',
              'cloudformation:ContinueUpdateRollback',
            ],
            resources: [`arn:aws:cloudformation:${this.region}:${this.account}:stack/Glitch*/*`],
          }),
          // Secrets Manager — read credentials for all Sentinel tools
          new iam.PolicyStatement({
            sid: 'SecretsManagerRead',
            effect: iam.Effect.ALLOW,
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
          new iam.PolicyStatement({
            sid: 'TelegramConfigRead',
            effect: iam.Effect.ALLOW,
            actions: ['dynamodb:GetItem', 'dynamodb:Query'],
            resources: [`arn:aws:dynamodb:${this.region}:${this.account}:table/${TABLE_NAMES.TELEGRAM_CONFIG}`],
          }),
          // SSM Parameters — read Sentinel config and Protect config
          new iam.PolicyStatement({
            sid: 'SsmParameterRead',
            effect: iam.Effect.ALLOW,
            actions: ['ssm:GetParameter', 'ssm:GetParameters', 'ssm:GetParametersByPath'],
            resources: [
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/*`,
              `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/protect/*`,
            ],
          }),
          // Workload identity — required by AgentCore Runtime execution role for agent
          // identity features (GetWorkloadAccessToken*). Scoped to the default workload
          // identity directory per the official execution role template.
          new iam.PolicyStatement({
            sid: 'GetWorkloadAccessToken',
            effect: iam.Effect.ALLOW,
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
          new iam.PolicyStatement({
            sid: 'InvokeGlitchAgent',
            effect: iam.Effect.ALLOW,
            actions: ['bedrock-agentcore:InvokeAgentRuntime'],
            resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
            conditions: { StringLike: { 'aws:ResourceTag/Name': 'Glitch*' } },
          }),
        ],
      }),
    });

    // Scheduled Sentinel Protect evaluation (EventBridge + Lambda)
    const protectEvalRole = new iam.Role(this, 'SentinelProtectEvalRole', {
      assumedBy: new iam.ServicePrincipal('lambda.amazonaws.com'),
      description: 'Role for glitch-sentinel-protect-eval Lambda',
    });
    protectEvalRole.addManagedPolicy(
      iam.ManagedPolicy.fromAwsManagedPolicyName('service-role/AWSLambdaBasicExecutionRole')
    );
    protectEvalRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'SsmSentinelArn',
        effect: iam.Effect.ALLOW,
        actions: ['ssm:GetParameter'],
        resources: [`arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/runtime-arn`],
      })
    );
    protectEvalRole.addToPolicy(
      new iam.PolicyStatement({
        sid: 'InvokeSentinelRuntime',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
        conditions: { StringLike: { 'aws:ResourceTag/Name': 'Sentinel*' } },
      })
    );
    const protectEvalFn = new lambda.Function(this, 'SentinelProtectEvalFunction', {
      functionName: 'glitch-sentinel-protect-eval',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/sentinel-protect-eval')),
      timeout: cdk.Duration.seconds(120),
      memorySize: 128,
      role: protectEvalRole,
    });
    new events.Rule(this, 'SentinelProtectEvalSchedule', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(15)),
      targets: [new targets.LambdaFunction(protectEvalFn)],
      description: 'Invoke Sentinel every 15 min for Protect camera evaluation',
    });

    // SSM parameters for Sentinel configuration.
    // Use AwsCustomResource with PutParameter Overwrite so we never fail with "parameter already exists"
    // (e.g. after stack re-create or param created outside the stack).
    new cr.AwsCustomResource(this, 'SentinelGlitchRuntimeArnParam', {
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
        physicalResourceId: cr.PhysicalResourceId.of('/glitch/sentinel/glitch-runtime-arn'),
      },
      policy: cr.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          effect: iam.Effect.ALLOW,
          actions: ['ssm:PutParameter'],
          resources: [
            `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/sentinel/glitch-runtime-arn`,
          ],
        }),
      ]),
    });

    new ssm.StringParameter(this, 'SentinelMonitoredLogGroupsParam', {
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

    new cdk.CfnOutput(this, 'SentinelRuntimeRoleArn', {
      value: runtimeRole.roleArn,
      description: 'IAM role ARN for Sentinel AgentCore Runtime',
    });
  }
}

