import * as cdk from 'aws-cdk-lib';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as iam from 'aws-cdk-lib/aws-iam';
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
  /** S3 UI bucket name for nginx to proxy static files. */
  readonly uiBucketName?: string;
}

export class TailscaleStack extends cdk.Stack {
  public readonly instance: ec2.Instance;
  public readonly securityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: TailscaleStackProps) {
    super(scope, id, props);

    const { vpc, tailscaleAuthKeySecret, gatewayFunctionUrl, uiBucketName } = props;
    const bootstrapVersion = props.instanceBootstrapVersion ??
      this.node.tryGetContext('glitchTailscaleBootstrapVersion') ?? '5';
    const enableUiProxy = Boolean(gatewayFunctionUrl && uiBucketName);

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
      'tailscale up --authkey="$TAILSCALE_AUTH_KEY" --advertise-tags=tag:aws-agent --accept-routes',
      '',
      'echo "Clearing auth key from memory..."',
      'unset TAILSCALE_AUTH_KEY',
      '',
      'echo "Tailscale setup complete!"',
      'tailscale status',
    ];

    if (enableUiProxy) {
      const gatewayUrl = gatewayFunctionUrl!.replace(/\/$/, '');
      userDataCommands.push(
        '',
        'echo "Setting up nginx UI proxy..."',
        'yum install -y nginx',
        '',
        `cat > /etc/nginx/conf.d/glitch-proxy.conf << 'NGINXEOF'`,
        'server {',
        '    listen 80;',
        '    server_name _;',
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
        '        proxy_set_header Host $host;',
        '        proxy_set_header X-Real-IP $remote_addr;',
        '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
        '        proxy_set_header X-Forwarded-Proto $scheme;',
        '        proxy_ssl_server_name on;',
        '    }',
        '',
        '    location /invocations {',
        `        proxy_pass ${gatewayUrl}/invocations;`,
        '        proxy_set_header Host $host;',
        '        proxy_set_header X-Real-IP $remote_addr;',
        '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
        '        proxy_set_header X-Forwarded-Proto $scheme;',
        '        proxy_ssl_server_name on;',
        '    }',
        '',
        '    location /health {',
        `        proxy_pass ${gatewayUrl}/health;`,
        '        proxy_set_header Host $host;',
        '        proxy_set_header X-Real-IP $remote_addr;',
        '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;',
        '        proxy_set_header X-Forwarded-Proto $scheme;',
        '        proxy_ssl_server_name on;',
        '    }',
        '}',
        'NGINXEOF',
        '',
        'rm -f /etc/nginx/conf.d/default.conf',
        'systemctl enable nginx',
        'systemctl start nginx',
        '',
        'echo "Enabling Tailscale Serve for HTTPS..."',
        'tailscale serve --bg http://127.0.0.1:80',
        'echo "Tailscale Serve enabled. UI available via Tailscale HTTPS URL."'
      );
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
    });

    cdk.Tags.of(this.instance).add('Name', 'GlitchTailscaleConnector');
    cdk.Tags.of(this.instance).add('Purpose', 'Tailscale-AWS-Bridge');

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
      new cdk.CfnOutput(this, 'TailscaleUiUrl', {
        value: 'https://glitch-tailscale.YOUR_TAILNET.ts.net',
        description: 'Glitch UI via Tailscale Serve. Replace YOUR_TAILNET with your Tailscale network name (e.g. from admin.tailscale.com or tailscale status). Use only on a device joined to the same Tailscale network.',
      });
    }
  }
}
