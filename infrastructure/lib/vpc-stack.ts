import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import { Construct } from 'constructs';

export interface VpcStackProps extends cdk.StackProps {
  readonly vpcCidr?: string;
}

export class VpcStack extends cdk.Stack {
  public readonly vpc: ec2.Vpc;
  public readonly privateSubnets: ec2.ISubnet[];
  public readonly publicSubnets: ec2.ISubnet[];
  public readonly agentCoreSecurityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props?: VpcStackProps) {
    super(scope, id, props);

    this.vpc = new ec2.Vpc(this, 'GlitchVpc', {
      maxAzs: 2,
      natGateways: 0,
      ipAddresses: ec2.IpAddresses.cidr(props?.vpcCidr || '10.0.0.0/16'),
      subnetConfiguration: [
        {
          name: 'Public',
          subnetType: ec2.SubnetType.PUBLIC,
          cidrMask: 24,
        },
        {
          name: 'Private',
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
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

    this.vpc.addGatewayEndpoint('S3Endpoint', {
      service: ec2.GatewayVpcEndpointAwsService.S3,
      subnets: [{ subnetType: ec2.SubnetType.PRIVATE_ISOLATED }],
    });

    this.vpc.addInterfaceEndpoint('EcrDockerEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.ECR_DOCKER,
      privateDnsEnabled: true,
      subnets: singleAzSubnetSelection,
    });

    this.vpc.addInterfaceEndpoint('EcrApiEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.ECR,
      privateDnsEnabled: true,
      subnets: singleAzSubnetSelection,
    });

    this.vpc.addInterfaceEndpoint('CloudWatchLogsEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.CLOUDWATCH_LOGS,
      privateDnsEnabled: true,
      subnets: singleAzSubnetSelection,
    });

    this.vpc.addInterfaceEndpoint('SecretsManagerEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.SECRETS_MANAGER,
      privateDnsEnabled: true,
      subnets: singleAzSubnetSelection,
    });

    this.vpc.addInterfaceEndpoint('BedrockAgentCoreEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_AGENT_RUNTIME,
      privateDnsEnabled: true,
      subnets: singleAzSubnetSelection,
    });

    this.vpc.addInterfaceEndpoint('BedrockRuntimeEndpoint', {
      service: ec2.InterfaceVpcEndpointAwsService.BEDROCK_RUNTIME,
      privateDnsEnabled: true,
      subnets: singleAzSubnetSelection,
    });

    this.vpc.addInterfaceEndpoint('BedrockAgentCoreDataPlaneEndpoint', {
      service: new ec2.InterfaceVpcEndpointService(
        `com.amazonaws.${this.region}.bedrock-agentcore`
      ),
      privateDnsEnabled: true,
      subnets: singleAzSubnetSelection,
    });

    new cdk.CfnOutput(this, 'VpcId', {
      value: this.vpc.vpcId,
      description: 'VPC ID for AgentCore Glitch',
      exportName: 'GlitchVpcId',
    });

    new cdk.CfnOutput(this, 'PrivateSubnetIds', {
      value: this.privateSubnets.map(s => s.subnetId).join(','),
      description: 'Private subnet IDs',
      exportName: 'GlitchPrivateSubnetIds',
    });

    new cdk.CfnOutput(this, 'AvailabilityZones', {
      value: this.vpc.availabilityZones.join(','),
      description: 'Availability Zones',
      exportName: 'GlitchAvailabilityZones',
    });

    // Create AgentCore security group here to avoid circular dependency
    // (TailscaleStack needs to reference it, and AgentCoreStack needs to reference TailscaleStack)
    this.agentCoreSecurityGroup = new ec2.SecurityGroup(this, 'AgentCoreSecurityGroup', {
      vpc: this.vpc,
      description: 'Security group for AgentCore runtime ENIs',
      allowAllOutbound: false,
    });

    // Allow HTTPS to AWS services (VPC endpoints)
    this.agentCoreSecurityGroup.addEgressRule(
      ec2.Peer.anyIpv4(),
      ec2.Port.tcp(443),
      'HTTPS to AWS services'
    );

    new cdk.CfnOutput(this, 'AgentCoreSecurityGroupId', {
      value: this.agentCoreSecurityGroup.securityGroupId,
      description: 'AgentCore runtime security group ID',
      exportName: 'GlitchAgentCoreSecurityGroupIdFromVpc',
    });
  }
}
