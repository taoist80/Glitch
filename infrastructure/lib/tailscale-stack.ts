import * as cdk from 'aws-cdk-lib';
import * as cr from 'aws-cdk-lib/custom-resources';
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
      // Use explicit hostname for Host header (Lambda Function URLs require correct Host). Passed from app via Fn.select/Fn.split.
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

      // If TLS is enabled, set up certbot with Porkbun DNS plugin
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
          '# Create Porkbun credentials file for certbot',
          'mkdir -p /etc/letsencrypt',
          'cat > /etc/letsencrypt/porkbun.ini << PORKBUNEOF',
          'dns_porkbun_key = $PORKBUN_API_KEY',
          'dns_porkbun_secret = $PORKBUN_SECRET_KEY',
          'PORKBUNEOF',
          'chmod 600 /etc/letsencrypt/porkbun.ini',
          '',
          '# Clear credentials from memory',
          'unset PORKBUN_CREDS PORKBUN_API_KEY PORKBUN_SECRET_KEY',
          '',
          '# Obtain certificate using DNS-01 challenge',
          `certbot certonly --non-interactive --agree-tos --email ${email} \\`,
          `  --authenticator dns-porkbun \\`,
          `  --dns-porkbun-credentials /etc/letsencrypt/porkbun.ini \\`,
          `  --dns-porkbun-propagation-seconds 60 \\`,
          `  -d ${customDomain}`,
          '',
          '# Set up auto-renewal cron job',
          'echo "0 3 * * * root certbot renew --quiet --post-hook \\"systemctl reload nginx\\"" > /etc/cron.d/certbot-renew',
          ''
        );
      }

      // Write nginx config - HTTPS if TLS enabled, HTTP otherwise
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
        // HTTP-only config (Tailscale Serve handles TLS)
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

      // Only use Tailscale Serve if TLS is NOT enabled (Serve handles TLS for *.ts.net domains)
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
        // CloudFormation custom resource response limit is 4KB; return only the ENI ID to stay under it
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
          description: 'Glitch UI via Tailscale Serve. Replace YOUR_TAILNET with your Tailscale network name (e.g. from admin.tailscale.com or tailscale status). Use only on a device joined to the same Tailscale network.',
        });
      }
    }
  }
}
