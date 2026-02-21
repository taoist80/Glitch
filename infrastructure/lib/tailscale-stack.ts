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
  readonly enableUiServer?: boolean;
  /** Bump this to force EC2 instance replacement (new instance runs user data from scratch). */
  readonly instanceBootstrapVersion?: string;
}

export class TailscaleStack extends cdk.Stack {
  public readonly instance: ec2.Instance;
  public readonly securityGroup: ec2.SecurityGroup;

  constructor(scope: Construct, id: string, props: TailscaleStackProps) {
    super(scope, id, props);

    const { vpc, tailscaleAuthKeySecret, enableUiServer = true } = props;
    const bootstrapVersion = props.instanceBootstrapVersion ??
      this.node.tryGetContext('glitchTailscaleBootstrapVersion') ?? '2';

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

    if (enableUiServer) {
      this.securityGroup.addIngressRule(
        ec2.Peer.ipv4('100.64.0.0/10'),
        ec2.Port.tcp(8080),
        'Allow Glitch UI from Tailscale network'
      );
    }

    const role = new iam.Role(this, 'TailscaleInstanceRole', {
      assumedBy: new iam.ServicePrincipal('ec2.amazonaws.com'),
      description: 'IAM role for Tailscale EC2 connector with UI server',
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName('AmazonSSMManagedInstanceCore'),
      ],
    });

    tailscaleAuthKeySecret.grantRead(role);

    if (enableUiServer) {
      role.addToPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock-agentcore:InvokeAgentRuntime',
          'bedrock-agentcore:ListAgentRuntimes',
        ],
        resources: props.agentCoreRuntimeArn 
          ? [props.agentCoreRuntimeArn, `${props.agentCoreRuntimeArn}/*`, `arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`]
          : [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
      }));

      role.addToPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['ssm:GetParameter'],
        resources: [
          `arn:aws:ssm:${this.region}:${this.account}:parameter/glitch/*`,
        ],
      }));

      role.addToPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['s3:GetObject', 's3:ListBucket'],
        resources: [
          `arn:aws:s3:::glitch-agent-state-${this.account}-${this.region}`,
          `arn:aws:s3:::glitch-agent-state-${this.account}-${this.region}/*`,
        ],
      }));

      role.addToPolicy(new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['secretsmanager:GetSecretValue'],
        resources: [
          `arn:aws:secretsmanager:${this.region}:${this.account}:secret:glitch/*`,
        ],
      }));
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

    if (enableUiServer) {
      userDataCommands.push(
        '',
        '# ============================================',
        '# Glitch UI Server Setup',
        '# ============================================',
        '',
        'echo "Installing Python 3.12, Node.js, and dependencies..."',
        'yum install -y python3.12 python3.12-pip git nodejs',
        '',
        'echo "Creating glitch user..."',
        'useradd -r -s /bin/false glitch || true',
        '',
        'echo "Fetching Glitch source (S3 bundle or git)..."',
        `BUNDLE_S3="s3://glitch-agent-state-${this.account}-${this.region}/deploy/glitch-ui-bundle.tar.gz"`,
        `if aws s3 cp "$BUNDLE_S3" /tmp/glitch-ui-bundle.tar.gz --region ${this.region} 2>/dev/null; then`,
        '  echo "Using Glitch bundle from S3..."',
        '  tar -xzf /tmp/glitch-ui-bundle.tar.gz -C /tmp',
        '  mkdir -p /opt/glitch',
        '  mv /tmp/agent /opt/glitch/ && mv /tmp/ui /opt/glitch/',
        '  rm -f /tmp/glitch-ui-bundle.tar.gz',
        'else',
        '  echo "No S3 bundle; cloning from GitHub (public repo only)..."',
        '  cd /opt && git clone https://github.com/taoist80/Glitch.git glitch || (cd glitch && git pull)',
        'fi',
        'chown -R glitch:glitch /opt/glitch 2>/dev/null || true',
        '',
        'echo "Setting up Python virtual environment..."',
        'cd /opt/glitch/agent',
        'python3.12 -m venv .venv',
        '.venv/bin/pip install --upgrade pip',
        '.venv/bin/pip install -r requirements.txt',
        '.venv/bin/pip install bedrock-agentcore fastapi "python-telegram-bot[webhooks]"',
        '',
        'echo "Building UI..."',
        '( cd /opt/glitch/ui && curl -fsSL https://get.pnpm.io/install.sh | sh - && export PNPM_HOME="/root/.local/share/pnpm" && export PATH="$PNPM_HOME:$PATH" && CI=true pnpm install && pnpm build )',
        '',
        'echo "Creating systemd service..."',
        'cat > /etc/systemd/system/glitch-ui.service << \'EOF\'',
        '[Unit]',
        'Description=Glitch UI Server',
        'After=network.target tailscaled.service',
        'Wants=tailscaled.service',
        '',
        '[Service]',
        'Type=simple',
        'User=root',
        'WorkingDirectory=/opt/glitch/agent',
        'Environment=PYTHONPATH=/opt/glitch/agent/src',
        'Environment=GLITCH_UI_MODE=proxy',
        'Environment=GLITCH_MODE=server',
        'Environment=GLITCH_AGENT_NAME=Glitch',
        `Environment=AWS_DEFAULT_REGION=${this.region}`,
        'ExecStart=/opt/glitch/agent/.venv/bin/python -m glitch',
        'Restart=always',
        'RestartSec=10',
        '',
        '[Install]',
        'WantedBy=multi-user.target',
        'EOF',
        '',
        'echo "Enabling and starting Glitch UI service..."',
        'systemctl daemon-reload',
        'systemctl enable glitch-ui',
        'systemctl start glitch-ui',
        '',
        'echo "Glitch UI server setup complete!"',
        'echo "Access via Tailscale at http://$(tailscale ip -4):8080/"',
      );
    }

    userData.addCommands(...userDataCommands);

    const instanceType = enableUiServer
      ? ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.SMALL)
      : ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.NANO);

    this.instance = new ec2.Instance(this, `TailscaleInstanceBootstrap${bootstrapVersion}`, {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PUBLIC },
      instanceType,
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
      blockDevices: enableUiServer ? [{
        deviceName: '/dev/xvda',
        volume: ec2.BlockDeviceVolume.ebs(20, {
          volumeType: ec2.EbsDeviceVolumeType.GP3,
          encrypted: true,
        }),
      }] : undefined,
    });

    cdk.Tags.of(this.instance).add('Name', 'GlitchTailscaleConnector');
    cdk.Tags.of(this.instance).add('Purpose', enableUiServer ? 'Tailscale-AWS-Bridge-UI' : 'Tailscale-AWS-Bridge');

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

    if (enableUiServer) {
      new cdk.CfnOutput(this, 'UiAccessInfo', {
        value: 'Access UI via Tailscale: http://<tailscale-ip>:8080/',
        description: 'How to access the Glitch UI',
      });
    }
  }
}
