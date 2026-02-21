"use strict";
var __createBinding = (this && this.__createBinding) || (Object.create ? (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    var desc = Object.getOwnPropertyDescriptor(m, k);
    if (!desc || ("get" in desc ? !m.__esModule : desc.writable || desc.configurable)) {
      desc = { enumerable: true, get: function() { return m[k]; } };
    }
    Object.defineProperty(o, k2, desc);
}) : (function(o, m, k, k2) {
    if (k2 === undefined) k2 = k;
    o[k2] = m[k];
}));
var __setModuleDefault = (this && this.__setModuleDefault) || (Object.create ? (function(o, v) {
    Object.defineProperty(o, "default", { enumerable: true, value: v });
}) : function(o, v) {
    o["default"] = v;
});
var __importStar = (this && this.__importStar) || (function () {
    var ownKeys = function(o) {
        ownKeys = Object.getOwnPropertyNames || function (o) {
            var ar = [];
            for (var k in o) if (Object.prototype.hasOwnProperty.call(o, k)) ar[ar.length] = k;
            return ar;
        };
        return ownKeys(o);
    };
    return function (mod) {
        if (mod && mod.__esModule) return mod;
        var result = {};
        if (mod != null) for (var k = ownKeys(mod), i = 0; i < k.length; i++) if (k[i] !== "default") __createBinding(result, mod, k[i]);
        __setModuleDefault(result, mod);
        return result;
    };
})();
Object.defineProperty(exports, "__esModule", { value: true });
exports.TailscaleStack = void 0;
const cdk = __importStar(require("aws-cdk-lib"));
const ec2 = __importStar(require("aws-cdk-lib/aws-ec2"));
const iam = __importStar(require("aws-cdk-lib/aws-iam"));
class TailscaleStack extends cdk.Stack {
    constructor(scope, id, props) {
        super(scope, id, props);
        const { vpc, tailscaleAuthKeySecret, enableUiServer = true } = props;
        const bootstrapVersion = props.instanceBootstrapVersion ??
            this.node.tryGetContext('glitchTailscaleBootstrapVersion') ?? '2';
        this.securityGroup = new ec2.SecurityGroup(this, 'TailscaleSecurityGroup', {
            vpc,
            description: 'Security group for Tailscale EC2 connector',
            allowAllOutbound: false,
        });
        this.securityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), 'HTTPS to Tailscale coordination server and DERP relays');
        this.securityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.udp(41641), 'WireGuard direct peer-to-peer tunnels');
        this.securityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.udp(3478), 'STUN protocol for NAT traversal');
        this.securityGroup.addEgressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(80), 'HTTP fallback and captive portal detection');
        this.securityGroup.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.udp(41641), 'Allow inbound WireGuard for direct connections');
        if (props.agentCoreSecurityGroup) {
            this.securityGroup.addIngressRule(props.agentCoreSecurityGroup, ec2.Port.allTraffic(), 'Allow all traffic from AgentCore ENIs');
        }
        if (enableUiServer) {
            this.securityGroup.addIngressRule(ec2.Peer.ipv4('100.64.0.0/10'), ec2.Port.tcp(8080), 'Allow Glitch UI from Tailscale network');
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
                ],
                resources: props.agentCoreRuntimeArn
                    ? [props.agentCoreRuntimeArn, `${props.agentCoreRuntimeArn}/*`]
                    : [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:runtime/*`],
            }));
            role.addToPolicy(new iam.PolicyStatement({
                effect: iam.Effect.ALLOW,
                actions: [
                    'bedrock-agentcore-control:ListAgentRuntimes',
                ],
                resources: ['*'],
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
                actions: ['s3:GetObject'],
                resources: [
                    `arn:aws:s3:::glitch-agent-state-${this.account}-${this.region}/*`,
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
            userDataCommands.push('', '# ============================================', '# Glitch UI Server Setup', '# ============================================', '', 'echo "Installing Python 3.12, Node.js, and dependencies..."', 'yum install -y python3.12 python3.12-pip git nodejs', '', 'echo "Creating glitch user..."', 'useradd -r -s /bin/false glitch || true', '', 'echo "Fetching Glitch source (S3 bundle or git)..."', `BUNDLE_S3="s3://glitch-agent-state-${this.account}-${this.region}/deploy/glitch-ui-bundle.tar.gz"`, `if aws s3 cp "$BUNDLE_S3" /tmp/glitch-ui-bundle.tar.gz --region ${this.region} 2>/dev/null; then`, '  echo "Using Glitch bundle from S3..."', '  tar -xzf /tmp/glitch-ui-bundle.tar.gz -C /tmp', '  mkdir -p /opt/glitch', '  mv /tmp/agent /opt/glitch/ && mv /tmp/ui /opt/glitch/', '  rm -f /tmp/glitch-ui-bundle.tar.gz', 'else', '  echo "No S3 bundle; cloning from GitHub (public repo only)..."', '  cd /opt && git clone https://github.com/taoist80/Glitch.git glitch || (cd glitch && git pull)', 'fi', 'chown -R glitch:glitch /opt/glitch 2>/dev/null || true', '', 'echo "Setting up Python virtual environment..."', 'cd /opt/glitch/agent', 'python3.12 -m venv .venv', '.venv/bin/pip install --upgrade pip', '.venv/bin/pip install -r requirements.txt', '.venv/bin/pip install bedrock-agentcore fastapi "python-telegram-bot[webhooks]"', '', 'echo "Building UI..."', '( cd /opt/glitch/ui && curl -fsSL https://get.pnpm.io/install.sh | sh - && export PNPM_HOME="/root/.local/share/pnpm" && export PATH="$PNPM_HOME:$PATH" && CI=true pnpm install && pnpm build )', '', 'echo "Creating systemd service..."', 'cat > /etc/systemd/system/glitch-ui.service << \'EOF\'', '[Unit]', 'Description=Glitch UI Server', 'After=network.target tailscaled.service', 'Wants=tailscaled.service', '', '[Service]', 'Type=simple', 'User=root', 'WorkingDirectory=/opt/glitch/agent', 'Environment=PYTHONPATH=/opt/glitch/agent/src', 'Environment=GLITCH_UI_MODE=proxy', 'Environment=GLITCH_MODE=server', 'Environment=GLITCH_AGENT_NAME=Glitch', `Environment=AWS_DEFAULT_REGION=${this.region}`, 'ExecStart=/opt/glitch/agent/.venv/bin/python -m glitch', 'Restart=always', 'RestartSec=10', '', '[Install]', 'WantedBy=multi-user.target', 'EOF', '', 'echo "Enabling and starting Glitch UI service..."', 'systemctl daemon-reload', 'systemctl enable glitch-ui', 'systemctl start glitch-ui', '', 'echo "Glitch UI server setup complete!"', 'echo "Access via Tailscale at http://$(tailscale ip -4):8080/"');
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
exports.TailscaleStack = TailscaleStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidGFpbHNjYWxlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsidGFpbHNjYWxlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBYzNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxjQUFjLEdBQUcsSUFBSSxFQUFFLEdBQUcsS0FBSyxDQUFDO1FBQ3JFLE1BQU0sZ0JBQWdCLEdBQUcsS0FBSyxDQUFDLHdCQUF3QjtZQUNyRCxJQUFJLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQyxpQ0FBaUMsQ0FBQyxJQUFJLEdBQUcsQ0FBQztRQUVwRSxJQUFJLENBQUMsYUFBYSxHQUFHLElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDekUsR0FBRztZQUNILFdBQVcsRUFBRSw0Q0FBNEM7WUFDekQsZ0JBQWdCLEVBQUUsS0FBSztTQUN4QixDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsYUFBYSxDQUFDLGFBQWEsQ0FDOUIsR0FBRyxDQUFDLElBQUksQ0FBQyxPQUFPLEVBQUUsRUFDbEIsR0FBRyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsR0FBRyxDQUFDLEVBQ2pCLHdEQUF3RCxDQUN6RCxDQUFDO1FBRUYsSUFBSSxDQUFDLGFBQWEsQ0FBQyxhQUFhLENBQzlCLEdBQUcsQ0FBQyxJQUFJLENBQUMsT0FBTyxFQUFFLEVBQ2xCLEdBQUcsQ0FBQyxJQUFJLENBQUMsR0FBRyxDQUFDLEtBQUssQ0FBQyxFQUNuQix1Q0FBdUMsQ0FDeEMs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LENBQUMsU0FBUyxFQUFFLGNBQWMsQ0FBQyxDQUFDLENBQUMseUJBQXlCLENBQUMsQ0FBQyxDQUFDLHNCQUFzQixDQUFDLENBQUM7UUFFL0csSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxZQUFZLEVBQUU7WUFDcEMsS0FBSyxFQUFFLElBQUksQ0FBQyxRQUFRLENBQUMsVUFBVTtZQUMvQixXQUFXLEVBQUUsMkJBQTJCO1NBQ3pDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsaUJBQWlCLEVBQUU7WUFDekMsS0FBSyxFQUFFLElBQUksQ0FBQyxhQUFhLENBQUMsZUFBZTtZQUN6QyxXQUFXLEVBQUUsNkJBQTZCO1NBQzNDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsV0FBVyxFQUFFO1lBQ25DLEtBQUssRUFBRSxJQUFJLENBQUMsUUFBUSxDQUFDLGlCQUFpQjtZQUN0QyxXQUFXLEVBQUUsMEJBQTBCO1NBQ3hDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsVUFBVSxFQUFFO1lBQ2xDLEtBQUssRUFBRSxJQUFJLENBQUMsUUFBUSxDQUFDLGdCQUFnQjtZQUNyQyxXQUFXLEVBQUUseUJBQXlCO1NBQ3ZDLENBQUMsQ0FBQztRQUVILElBQUksY0FBYyxFQUFFLENBQUM7WUFDbkIsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxjQUFjLEVBQUU7Z0JBQ3RDLEtBQUssRUFBRSxzREFBc0Q7Z0JBQzdELFdBQVcsRUFBRSw2QkFBNkI7YUFDM0MsQ0FBQyxDQUFDO1FBQ0wsQ0FBQztJQUNILENBQUM7Q0FDRjtBQTVRRCx3Q0E0UUMiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0ICogYXMgZWMyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lYzInO1xuaW1wb3J0ICogYXMgaWFtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1pYW0nO1xuaW1wb3J0ICogYXMgc2VjcmV0c21hbmFnZXIgZnJvbSAnYXdzLWNkay1saWIvYXdzLXNlY3JldHNtYW5hZ2VyJztcbmltcG9ydCB7IENvbnN0cnVjdCB9IGZyb20gJ2NvbnN0cnVjdHMnO1xuXG5leHBvcnQgaW50ZXJmYWNlIFRhaWxzY2FsZVN0YWNrUHJvcHMgZXh0ZW5kcyBjZGsuU3RhY2tQcm9wcyB7XG4gIHJlYWRvbmx5IHZwYzogZWMyLklWcGM7XG4gIHJlYWRvbmx5IHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHJlYWRvbmx5IGFnZW50Q29yZVNlY3VyaXR5R3JvdXA/OiBlYzIuSVNlY3VyaXR5R3JvdXA7XG4gIHJlYWRvbmx5IGFnZW50Q29yZVJ1bnRpbWVBcm4/OiBzdHJpbmc7XG4gIHJlYWRvbmx5IGVuYWJsZVVpU2VydmVyPzogYm9vbGVhbjtcbiAgLyoqIEJ1bXAgdGhpcyB0byBmb3JjZSBFQzIgaW5zdGFuY2UgcmVwbGFjZW1lbnQgKG5ldyBpbnN0YW5jZSBydW5zIHVzZXIgZGF0YSBmcm9tIHNjcmF0Y2gpLiAqL1xuICByZWFkb25seSBpbnN0YW5jZUJvb3RzdHJhcFZlcnNpb24/OiBzdHJpbmc7XG59XG5cbmV4cG9ydCBjbGFzcyBUYWlsc2NhbGVTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSBpbnN0YW5jZTogZWMyLkluc3RhbmNlO1xuICBwdWJsaWMgcmVhZG9ubHkgc2VjdXJpdHlHcm91cDogZWMyLlNlY3VyaXR5R3JvdXA7XG5cbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM6IFRhaWxzY2FsZVN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIGNvbnN0IHsgdnBjLCB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0LCBlbmFibGVVaVNlcnZlciA9IHRydWUgfSA9IHByb3BzO1xuICAgIGNvbnN0IGJvb3RzdHJhcFZlcnNpb24gPSBwcm9wcy5pbnN0YW5jZUJvb3RzdHJhcFZlcnNpb24gPz9cbiAgICAgIHRoaXMubm9kZS50cnlHZXRDb250ZXh0KCdnbGl0Y2hUYWlsc2NhbGVCb290c3RyYXBWZXJzaW9uJykgPz8gJzInO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwID0gbmV3IGVjMi5TZWN1cml0eUdyb3VwKHRoaXMsICdUYWlsc2NhbGVTZWN1cml0eUdyb3VwJywge1xuICAgICAgdnBjLFxuICAgICAgZGVzY3JpcHRpb246ICdTZWN1cml0eSBncm91cCBmb3IgVGFpbHNjYWxlIEVDMiBjb25uZWN0b3InLFxuICAgICAgYWxsb3dBbGxPdXRib3VuZDogZmFsc2UsXG4gICAgfSk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnRjcCg0NDMpLFxuICAgICAgJ0hUVFBTIHRvIFRhaWxzY2FsZSBjb29yZGluYXRpb24gc2VydmVyIGFuZCBERVJQIHJlbGF5cydcbiAgICApO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC51ZHAoNDE2NDEpLFxuICAgICAgJ1dpcmVHdWFyZCBkaXJlY3QgcGVlci10by1wZWVyIHR1bm5lbHMnXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudWRwKDM0NzgpLFxuICAgICAgJ1NUVU4gcHJvdG9jb2wgZm9yIE5BVCB0cmF2ZXJzYWwnXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudGNwKDgwKSxcbiAgICAgICdIVFRQIGZhbGxiYWNrIGFuZCBjYXB0aXZlIHBvcnRhbCBkZXRlY3Rpb24nXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRJbmdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnVkcCg0MTY0MSksXG4gICAgICAnQWxsb3cgaW5ib3VuZCBXaXJlR3VhcmQgZm9yIGRpcmVjdCBjb25uZWN0aW9ucydcbiAgICApO1xuXG4gICAgaWYgKHByb3BzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXApIHtcbiAgICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRJbmdyZXNzUnVsZShcbiAgICAgICAgcHJvcHMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cCxcbiAgICAgICAgZWMyLlBvcnQuYWxsVHJhZmZpYygpLFxuICAgICAgICAnQWxsb3cgYWxsIHRyYWZmaWMgZnJvbSBBZ2VudENvcmUgRU5JcydcbiAgICAgICk7XG4gICAgfVxuXG4gICAgaWYgKGVuYWJsZVVpU2VydmVyKSB7XG4gICAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICAgIGVjMi5QZWVyLmlwdjQoJzEwMC42NC4wLjAvMTAnKSxcbiAgICAgICAgZWMyLlBvcnQudGNwKDgwODApLFxuICAgICAgICAnQWxsb3cgR2xpdGNoIFVJIGZyb20gVGFpbHNjYWxlIG5ldHdvcmsnXG4gICAgICApO1xuICAgIH1cblxuICAgIGNvbnN0IHJvbGUgPSBuZXcgaWFtLlJvbGUodGhpcywgJ1RhaWxzY2FsZUluc3RhbmNlUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdlYzIuYW1hem9uYXdzLmNvbScpLFxuICAgICAgZGVzY3JpcHRpb246ICdJQU0gcm9sZSBmb3IgVGFpbHNjYWxlIEVDMiBjb25uZWN0b3Igd2l0aCBVSSBzZXJ2ZXInLFxuICAgICAgbWFuYWdlZFBvbGljaWVzOiBbXG4gICAgICAgIGlhbS5NYW5hZ2VkUG9saWN5LmZyb21Bd3NNYW5hZ2VkUG9saWN5TmFtZSgnQW1hem9uU1NNTWFuYWdlZEluc3RhbmNlQ29yZScpLFxuICAgICAgXSxcbiAgICB9KTtcblxuICAgIHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQuZ3JhbnRSZWFkKHJvbGUpO1xuXG4gICAgaWYgKGVuYWJsZVVpU2VydmVyKSB7XG4gICAgICByb2xlLmFkZFRvUG9saWN5KG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkludm9rZUFnZW50UnVudGltZScsXG4gICAgICAgIF0sXG4gICAgICAgIHJlc291cmNlczogcHJvcHMuYWdlbnRDb3JlUnVudGltZUFybiBcbiAgICAgICAgICA/IFtwcm9wcy5hZ2VudENvcmVSdW50aW1lQXJuLCBgJHtwcm9wcy5hZ2VudENvcmVSdW50aW1lQXJufS8qYF1cbiAgICAgICAgICA6IFtgYXJuOmF3czpiZWRyb2NrLWFnZW50Y29yZToke3RoaXMucmVnaW9ufToke3RoaXMuYWNjb3VudH06cnVudGltZS8qYF0sXG4gICAgICB9KSk7XG5cbiAgICAgIHJvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmUtY29udHJvbDpMaXN0QWdlbnRSdW50aW1lcycsXG4gICAgICAgIF0sXG4gICAgICAgIHJlc291cmNlczogWycqJ10sXG4gICAgICB9KSk7XG5cbiAgICAgIHJvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFsnc3NtOkdldFBhcmFtZXRlciddLFxuICAgICAgICByZXNvdXJjZXM6IFtcbiAgICAgICAgICBgYXJuOmF3czpzc206JHt0aGlzLnJlZ2lvbn06JHt0aGlzLmFjY291bnR9OnBhcmFtZXRlci9nbGl0Y2gvKmAsXG4gICAgICAgIF0sXG4gICAgICB9KSk7XG5cbiAgICAgIHJvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFsnczM6R2V0T2JqZWN0J10sXG4gICAgICAgIHJlc291cmNlczogW1xuICAgICAgICAgIGBhcm46YXdzOnMzOjo6Z2xpdGNoLWFnZW50LXN0YXRlLSR7dGhpcy5hY2NvdW50fS0ke3RoaXMucmVnaW9ufS8qYCxcbiAgICAgICAgXSxcbiAgICAgIH0pKTtcbiAgICB9XG5cbiAgICBjb25zdCB1c2VyRGF0YSA9IGVjMi5Vc2VyRGF0YS5mb3JMaW51eCgpO1xuICAgIFxuICAgIGNvbnN0IHVzZXJEYXRhQ29tbWFuZHMgPSBbXG4gICAgICAnIyEvYmluL2Jhc2gnLFxuICAgICAgJ3NldCAtZScsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiSW5zdGFsbGluZyBBV1MgQ0xJIGFuZCByZXRyaWV2aW5nIFRhaWxzY2FsZSBhdXRoIGtleS4uLlwiJyxcbiAgICAgICd5dW0gaW5zdGFsbCAteSBhd3MtY2xpJyxcbiAgICAgICcnLFxuICAgICAgYFRBSUxTQ0FMRV9BVVRIX0tFWT0kKGF3cyBzZWNyZXRzbWFuYWdlciBnZXQtc2VjcmV0LXZhbHVlIC0tc2VjcmV0LWlkICR7dGFpbHNjYWxlQXV0aEtleVNlY3JldC5zZWNyZXROYW1lfSAtLXF1ZXJ5IFNlY3JldFN0cmluZyAtLW91dHB1dCB0ZXh0IC0tcmVnaW9uICR7dGhpcy5yZWdpb259KWAsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiSW5zdGFsbGluZyBUYWlsc2NhbGUuLi5cIicsXG4gICAgICAnY3VybCAtZnNTTCBodHRwczovL3RhaWxzY2FsZS5jb20vaW5zdGFsbC5zaCB8IHNoJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJFbmFibGluZyBJUCBmb3J3YXJkaW5nLi4uXCInLFxuICAgICAgJ2VjaG8gXCJuZXQuaXB2NC5pcF9mb3J3YXJkID0gMVwiID4+IC9ldGMvc3lzY3RsLmNvbmYnLFxuICAgICAgJ2VjaG8gXCJuZXQuaXB2Ni5jb25mLmFsbC5mb3J3YXJkaW5nID0gMVwiID4+IC9ldGMvc3lzY3RsLmNvbmYnLFxuICAgICAgJ3N5c2N0bCAtcCAvZXRjL3N5c2N0bC5jb25mJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJTdGFydGluZyBUYWlsc2NhbGUgd2l0aCBhdXRoIGtleS4uLlwiJyxcbiAgICAgICd0YWlsc2NhbGUgdXAgLS1hdXRoa2V5PVwiJFRBSUxTQ0FMRV9BVVRIX0tFWVwiIC0tYWR2ZXJ0aXNlLXRhZ3M9dGFnOmF3cy1hZ2VudCAtLWFjY2VwdC1yb3V0ZXMnLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIkNsZWFyaW5nIGF1dGgga2V5IGZyb20gbWVtb3J5Li4uXCInLFxuICAgICAgJ3Vuc2V0IFRBSUxTQ0FMRV9BVVRIX0tFWScsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiVGFpbHNjYWxlIHNldHVwIGNvbXBsZXRlIVwiJyxcbiAgICAgICd0YWlsc2NhbGUgc3RhdHVzJyxcbiAgICBdO1xuXG4gICAgaWYgKGVuYWJsZVVpU2VydmVyKSB7XG4gICAgICB1c2VyRGF0YUNvbW1hbmRzLnB1c2goXG4gICAgICAgICcnLFxuICAgICAgICAnIyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PScsXG4gICAgICAgICcjIEdsaXRjaCBVSSBTZXJ2ZXIgU2V0dXAnLFxuICAgICAgICAnIyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PScsXG4gICAgICAgICcnLFxuICAgICAgICAnZWNobyBcIkluc3RhbGxpbmcgUHl0aG9uIDMuMTIsIE5vZGUuanMsIGFuZCBkZXBlbmRlbmNpZXMuLi5cIicsXG4gICAgICAgICd5dW0gaW5zdGFsbCAteSBweXRob24zLjEyIHB5dGhvbjMuMTItcGlwIGdpdCBub2RlanMnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJDcmVhdGluZyBnbGl0Y2ggdXNlci4uLlwiJyxcbiAgICAgICAgJ3VzZXJhZGQgLXIgLXMgL2Jpbi9mYWxzZSBnbGl0Y2ggfHwgdHJ1ZScsXG4gICAgICAgICcnLFxuICAgICAgICAnZWNobyBcIkZldGNoaW5nIEdsaXRjaCBzb3VyY2UgKFMzIGJ1bmRsZSBvciBnaXQpLi4uXCInLFxuICAgICAgICBgQlVORExFX1MzPVwiczM6Ly9nbGl0Y2gtYWdlbnQtc3RhdGUtJHt0aGlzLmFjY291bnR9LSR7dGhpcy5yZWdpb259L2RlcGxveS9nbGl0Y2gtdWktYnVuZGxlLnRhci5nelwiYCxcbiAgICAgICAgYGlmIGF3cyBzMyBjcCBcIiRCVU5ETEVfUzNcIiAvdG1wL2dsaXRjaC11aS1idW5kbGUudGFyLmd6IC0tcmVnaW9uICR7dGhpcy5yZWdpb259IDI+L2Rldi9udWxsOyB0aGVuYCxcbiAgICAgICAgJyAgZWNobyBcIlVzaW5nIEdsaXRjaCBidW5kbGUgZnJvbSBTMy4uLlwiJyxcbiAgICAgICAgJyAgdGFyIC14emYgL3RtcC9nbGl0Y2gtdWktYnVuZGxlLnRhci5neiAtQyAvdG1wJyxcbiAgICAgICAgJyAgbWtkaXIgLXAgL29wdC9nbGl0Y2gnLFxuICAgICAgICAnICBtdiAvdG1wL2FnZW50IC9vcHQvZ2xpdGNoLyAmJiBtdiAvdG1wL3VpIC9vcHQvZ2xpdGNoLycsXG4gICAgICAgICcgIHJtIC1mIC90bXAvZ2xpdGNoLXVpLWJ1bmRsZS50YXIuZ3onLFxuICAgICAgICAnZWxzZScsXG4gICAgICAgICcgIGVjaG8gXCJObyBTMyBidW5kbGU7IGNsb25pbmcgZnJvbSBHaXRIdWIgKHB1YmxpYyByZXBvIG9ubHkpLi4uXCInLFxuICAgICAgICAnICBjZCAvb3B0ICYmIGdpdCBjbG9uZSBodHRwczovL2dpdGh1Yi5jb20vdGFvaXN0ODAvR2xpdGNoLmdpdCBnbGl0Y2ggfHwgKGNkIGdsaXRjaCAmJiBnaXQgcHVsbCknLFxuICAgICAgICAnZmknLFxuICAgICAgICAnY2hvd24gLVIgZ2xpdGNoOmdsaXRjaCAvb3B0L2dsaXRjaCAyPi9kZXYvbnVsbCB8fCB0cnVlJyxcbiAgICAgICAgJycsXG4gICAgICAgICdlY2hvIFwiU2V0dGluZyB1cCBQeXRob24gdmlydHVhbCBlbnZpcm9ubWVudC4uLlwiJyxcbiAgICAgICAgJ2NkIC9vcHQvZ2xpdGNoL2FnZW50JyxcbiAgICAgICAgJ3B5dGhvbjMuMTIgLW0gdmVudiAudmVudicsXG4gICAgICAgICcudmVudi9iaW4vcGlwIGluc3RhbGwgLS11cGdyYWRlIHBpcCcsXG4gICAgICAgICcudmVudi9iaW4vcGlwIGluc3RhbGwgLXIgcmVxdWlyZW1lbnRzLnR4dCcsXG4gICAgICAgICcudmVudi9iaW4vcGlwIGluc3RhbGwgYmVkcm9jay1hZ2VudGNvcmUgZmFzdGFwaSBcInB5dGhvbi10ZWxlZ3JhbS1ib3Rbd2ViaG9va3NdXCInLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJCdWlsZGluZyBVSS4uLlwiJyxcbiAgICAgICAgJyggY2QgL29wdC9nbGl0Y2gvdWkgJiYgY3VybCAtZnNTTCBodHRwczovL2dldC5wbnBtLmlvL2luc3RhbGwuc2ggfCBzaCAtICYmIGV4cG9ydCBQTlBNX0hPTUU9XCIvcm9vdC8ubG9jYWwvc2hhcmUvcG5wbVwiICYmIGV4cG9ydCBQQVRIPVwiJFBOUE1fSE9NRTokUEFUSFwiICYmIENJPXRydWUgcG5wbSBpbnN0YWxsICYmIHBucG0gYnVpbGQgKScsXG4gICAgICAgICcnLFxuICAgICAgICAnZWNobyBcIkNyZWF0aW5nIHN5c3RlbWQgc2VydmljZS4uLlwiJyxcbiAgICAgICAgJ2NhdCA+IC9ldGMvc3lzdGVtZC9zeXN0ZW0vZ2xpdGNoLXVpLnNlcnZpY2UgPDwgXFwnRU9GXFwnJyxcbiAgICAgICAgJ1tVbml0XScsXG4gICAgICAgICdEZXNjcmlwdGlvbj1HbGl0Y2ggVUkgU2VydmVyJyxcbiAgICAgICAgJ0FmdGVyPW5ldHdvcmsudGFyZ2V0IHRhaWxzY2FsZWQuc2VydmljZScsXG4gICAgICAgICdXYW50cz10YWlsc2NhbGVkLnNlcnZpY2UnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ1tTZXJ2aWNlXScsXG4gICAgICAgICdUeXBlPXNpbXBsZScsXG4gICAgICAgICdVc2VyPXJvb3QnLFxuICAgICAgICAnV29ya2luZ0RpcmVjdG9yeT0vb3B0L2dsaXRjaC9hZ2VudCcsXG4gICAgICAgICdFbnZpcm9ubWVudD1QWVRIT05QQVRIPS9vcHQvZ2xpdGNoL2FnZW50L3NyYycsXG4gICAgICAgICdFbnZpcm9ubWVudD1HTElUQ0hfVUlfTU9ERT1wcm94eScsXG4gICAgICAgICdFbnZpcm9ubWVudD1HTElUQ0hfTU9ERT1zZXJ2ZXInLFxuICAgICAgICAnRW52aXJvbm1lbnQ9R0xJVENIX0FHRU5UX05BTUU9R2xpdGNoJyxcbiAgICAgICAgYEVudmlyb25tZW50PUFXU19ERUZBVUxUX1JFR0lPTj0ke3RoaXMucmVnaW9ufWAsXG4gICAgICAgICdFeGVjU3RhcnQ9L29wdC9nbGl0Y2gvYWdlbnQvLnZlbnYvYmluL3B5dGhvbiAtbSBnbGl0Y2gnLFxuICAgICAgICAnUmVzdGFydD1hbHdheXMnLFxuICAgICAgICAnUmVzdGFydFNlYz0xMCcsXG4gICAgICAgICcnLFxuICAgICAgICAnW0luc3RhbGxdJyxcbiAgICAgICAgJ1dhbnRlZEJ5PW11bHRpLXVzZXIudGFyZ2V0JyxcbiAgICAgICAgJ0VPRicsXG4gICAgICAgICcnLFxuICAgICAgICAnZWNobyBcIkVuYWJsaW5nIGFuZCBzdGFydGluZyBHbGl0Y2ggVUkgc2VydmljZS4uLlwiJyxcbiAgICAgICAgJ3N5c3RlbWN0bCBkYWVtb24tcmVsb2FkJyxcbiAgICAgICAgJ3N5c3RlbWN0bCBlbmFibGUgZ2xpdGNoLXVpJyxcbiAgICAgICAgJ3N5c3RlbWN0bCBzdGFydCBnbGl0Y2gtdWknLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJHbGl0Y2ggVUkgc2VydmVyIHNldHVwIGNvbXBsZXRlIVwiJyxcbiAgICAgICAgJ2VjaG8gXCJBY2Nlc3MgdmlhIFRhaWxzY2FsZSBhdCBodHRwOi8vJCh0YWlsc2NhbGUgaXAgLTQpOjgwODAvXCInLFxuICAgICAgKTtcbiAgICB9XG5cbiAgICB1c2VyRGF0YS5hZGRDb21tYW5kcyguLi51c2VyRGF0YUNvbW1hbmRzKTtcblxuICAgIGNvbnN0IGluc3RhbmNlVHlwZSA9IGVuYWJsZVVpU2VydmVyXG4gICAgICA/IGVjMi5JbnN0YW5jZVR5cGUub2YoZWMyLkluc3RhbmNlQ2xhc3MuVDRHLCBlYzIuSW5zdGFuY2VTaXplLlNNQUxMKVxuICAgICAgOiBlYzIuSW5zdGFuY2VUeXBlLm9mKGVjMi5JbnN0YW5jZUNsYXNzLlQ0RywgZWMyLkluc3RhbmNlU2l6ZS5OQU5PKTtcblxuICAgIHRoaXMuaW5zdGFuY2UgPSBuZXcgZWMyLkluc3RhbmNlKHRoaXMsIGBUYWlsc2NhbGVJbnN0YW5jZUJvb3RzdHJhcCR7Ym9vdHN0cmFwVmVyc2lvbn1gLCB7XG4gICAgICB2cGMsXG4gICAgICB2cGNTdWJuZXRzOiB7IHN1Ym5ldFR5cGU6IGVjMi5TdWJuZXRUeXBlLlBVQkxJQyB9LFxuICAgICAgaW5zdGFuY2VUeXBlLFxuICAgICAgbWFjaGluZUltYWdlOiBlYzIuTWFjaGluZUltYWdlLmxhdGVzdEFtYXpvbkxpbnV4MjAyMyh7XG4gICAgICAgIGNwdVR5cGU6IGVjMi5BbWF6b25MaW51eENwdVR5cGUuQVJNXzY0LFxuICAgICAgICBjYWNoZWRJbkNvbnRleHQ6IGZhbHNlLFxuICAgICAgfSksXG4gICAgICBzZWN1cml0eUdyb3VwOiB0aGlzLnNlY3VyaXR5R3JvdXAsXG4gICAgICByb2xlLFxuICAgICAgdXNlckRhdGEsXG4gICAgICByZXF1aXJlSW1kc3YyOiB0cnVlLFxuICAgICAgc3NtU2Vzc2lvblBlcm1pc3Npb25zOiB0cnVlLFxuICAgICAgYXNzb2NpYXRlUHVibGljSXBBZGRyZXNzOiB0cnVlLFxuICAgICAgYmxvY2tEZXZpY2VzOiBlbmFibGVVaVNlcnZlciA/IFt7XG4gICAgICAgIGRldmljZU5hbWU6ICcvZGV2L3h2ZGEnLFxuICAgICAgICB2b2x1bWU6IGVjMi5CbG9ja0RldmljZVZvbHVtZS5lYnMoMjAsIHtcbiAgICAgICAgICB2b2x1bWVUeXBlOiBlYzIuRWJzRGV2aWNlVm9sdW1lVHlwZS5HUDMsXG4gICAgICAgICAgZW5jcnlwdGVkOiB0cnVlLFxuICAgICAgICB9KSxcbiAgICAgIH1dIDogdW5kZWZpbmVkLFxuICAgIH0pO1xuXG4gICAgY2RrLlRhZ3Mub2YodGhpcy5pbnN0YW5jZSkuYWRkKCdOYW1lJywgJ0dsaXRjaFRhaWxzY2FsZUNvbm5lY3RvcicpO1xuICAgIGNkay5UYWdzLm9mKHRoaXMuaW5zdGFuY2UpLmFkZCgnUHVycG9zZScsIGVuYWJsZVVpU2VydmVyID8gJ1RhaWxzY2FsZS1BV1MtQnJpZGdlLVVJJyA6ICdUYWlsc2NhbGUtQVdTLUJyaWRnZScpO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0luc3RhbmNlSWQnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5pbnN0YW5jZS5pbnN0YW5jZUlkLFxuICAgICAgZGVzY3JpcHRpb246ICdUYWlsc2NhbGUgRUMyIGluc3RhbmNlIElEJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdTZWN1cml0eUdyb3VwSWQnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5zZWN1cml0eUdyb3VwLnNlY3VyaXR5R3JvdXBJZCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIHNlY3VyaXR5IGdyb3VwIElEJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdQcml2YXRlSXAnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5pbnN0YW5jZS5pbnN0YW5jZVByaXZhdGVJcCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIEVDMiBwcml2YXRlIElQJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdQdWJsaWNJcCcsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmluc3RhbmNlLmluc3RhbmNlUHVibGljSXAsXG4gICAgICBkZXNjcmlwdGlvbjogJ1RhaWxzY2FsZSBFQzIgcHVibGljIElQJyxcbiAgICB9KTtcblxuICAgIGlmIChlbmFibGVVaVNlcnZlcikge1xuICAgICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1VpQWNjZXNzSW5mbycsIHtcbiAgICAgICAgdmFsdWU6ICdBY2Nlc3MgVUkgdmlhIFRhaWxzY2FsZTogaHR0cDovLzx0YWlsc2NhbGUtaXA+OjgwODAvJyxcbiAgICAgICAgZGVzY3JpcHRpb246ICdIb3cgdG8gYWNjZXNzIHRoZSBHbGl0Y2ggVUknLFxuICAgICAgfSk7XG4gICAgfVxuICB9XG59XG4iXX0=