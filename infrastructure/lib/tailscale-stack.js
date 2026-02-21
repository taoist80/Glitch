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
            userDataCommands.push('', '# ============================================', '# Glitch UI Server Setup', '# ============================================', '', 'echo "Installing Python 3.12 and dependencies..."', 'yum install -y python3.12 python3.12-pip git', '', 'echo "Creating glitch user..."', 'useradd -r -s /bin/false glitch || true', '', 'echo "Fetching Glitch source (S3 bundle or git)..."', `BUNDLE_S3="s3://glitch-agent-state-${this.account}-${this.region}/deploy/glitch-ui-bundle.tar.gz"`, `if aws s3 cp "$BUNDLE_S3" /tmp/glitch-ui-bundle.tar.gz --region ${this.region} 2>/dev/null; then`, '  echo "Using Glitch bundle from S3..."', '  tar -xzf /tmp/glitch-ui-bundle.tar.gz -C /tmp', '  mkdir -p /opt/glitch', '  mv /tmp/agent /opt/glitch/ && mv /tmp/ui /opt/glitch/', '  rm -f /tmp/glitch-ui-bundle.tar.gz', 'else', '  echo "No S3 bundle; cloning from GitHub (public repo only)..."', '  cd /opt && git clone https://github.com/taoist80/Glitch.git glitch || (cd glitch && git pull)', 'fi', 'chown -R glitch:glitch /opt/glitch 2>/dev/null || true', '', 'echo "Setting up Python virtual environment..."', 'cd /opt/glitch/agent', 'python3.12 -m venv .venv', '.venv/bin/pip install --upgrade pip', '.venv/bin/pip install -r requirements.txt', '.venv/bin/pip install bedrock-agentcore fastapi "python-telegram-bot[webhooks]"', '', 'echo "Building UI..."', '( cd /opt/glitch/ui && curl -fsSL https://get.pnpm.io/install.sh | sh - && export PNPM_HOME="/root/.local/share/pnpm" && export PATH="$PNPM_HOME:$PATH" && CI=true pnpm install && pnpm build )', '', 'echo "Creating systemd service..."', 'cat > /etc/systemd/system/glitch-ui.service << \'EOF\'', '[Unit]', 'Description=Glitch UI Server', 'After=network.target tailscaled.service', 'Wants=tailscaled.service', '', '[Service]', 'Type=simple', 'User=root', 'WorkingDirectory=/opt/glitch/agent', 'Environment=PYTHONPATH=/opt/glitch/agent/src', 'Environment=GLITCH_UI_MODE=proxy', 'Environment=GLITCH_MODE=server', 'Environment=GLITCH_AGENT_NAME=Glitch', `Environment=AWS_DEFAULT_REGION=${this.region}`, 'ExecStart=/opt/glitch/agent/.venv/bin/python -m glitch', 'Restart=always', 'RestartSec=10', '', '[Install]', 'WantedBy=multi-user.target', 'EOF', '', 'echo "Enabling and starting Glitch UI service..."', 'systemctl daemon-reload', 'systemctl enable glitch-ui', 'systemctl start glitch-ui', '', 'echo "Glitch UI server setup complete!"', 'echo "Access via Tailscale at http://$(tailscale ip -4):8080/"');
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidGFpbHNjYWxlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsidGFpbHNjYWxlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBYzNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxjQUFjLEdBQUcsSUFBSSxFQUFFLEdBQUcsS0FBSyxDQUFDO1FBQ3JFLE1BQU0sZ0JBQWdCLEdBQUcsS0FBSyxDQUFDLHdCQUF3QjtZQUNyRCxJQUFJLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQyxpQ0FBaUMsQ0FBQyxJQUFJLEdBQUcsQ0FBQztRQUVwRSxJQUFJLENBQUMsYUFBYSxHQUFHLElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDekUsR0FBRztZQUNILFdBQVcsRUFBRSw0Q0FBNEM7WUFDekQsZ0JBQWdCLEVBQUUsS0FBSztTQUN4QixDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsYUFBYSxDQUFDLGFBQWEsQ0FDOUIsR0FBRyxDQUFDLElBQUksQ0FBQyxPQUFPLEVBQUUsRUFDbEIsR0FBRyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsR0FBRyxDQUFDLEVBQ2pCLHdEQUF3RCxDQUN6RCxDQUFDO1FBRUYsSUFBSSxDQUFDLGFBQWEsQ0FBQyxhQUFhLENBQzlCLEdBQUcsQ0FBQyxJQUFJLENBQUMsT0FBTyxFQUFFLEVBQ2xCLEdBQUcsQ0FBQyxJQUFJLENBQUMsR0FBRyxDQUFDLEtBQUssQ0FBQyxFQUNuQix1Q0FBdUMsQ0FDeEMs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LENBQUMsU0FBUyxFQUFFLGNBQWMsQ0FBQyxDQUFDLENBQUMseUJBQXlCLENBQUMsQ0FBQyxDQUFDLHNCQUFzQixDQUFDLENBQUM7UUFFL0csSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxZQUFZLEVBQUU7WUFDcEMsS0FBSyxFQUFFLElBQUksQ0FBQyxRQUFRLENBQUMsVUFBVTtZQUMvQixXQUFXLEVBQUUsMkJBQTJCO1NBQ3pDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsaUJBQWlCLEVBQUU7WUFDekMsS0FBSyxFQUFFLElBQUksQ0FBQyxhQUFhLENBQUMsZUFBZTtZQUN6QyxXQUFXLEVBQUUsNkJBQTZCO1NBQzNDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsV0FBVyxFQUFFO1lBQ25DLEtBQUssRUFBRSxJQUFJLENBQUMsUUFBUSxDQUFDLGlCQUFpQjtZQUN0QyxXQUFXLEVBQUUsMEJBQTBCO1NBQ3hDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsVUFBVSxFQUFFO1lBQ2xDLEtBQUssRUFBRSxJQUFJLENBQUMsUUFBUSxDQUFDLGdCQUFnQjtZQUNyQyxXQUFXLEVBQUUseUJBQXlCO1NBQ3ZDLENBQUMsQ0FBQztRQUVILElBQUksY0FBYyxFQUFFLENBQUM7WUFDbkIsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxjQUFjLEVBQUU7Z0JBQ3RDLEtBQUssRUFBRSxzREFBc0Q7Z0JBQzdELFdBQVcsRUFBRSw2QkFBNkI7YUFDM0MsQ0FBQyxDQUFDO1FBQ0wsQ0FBQztJQUNILENBQUM7Q0FDRjtBQTVRRCx3Q0E0UUMiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0ICogYXMgZWMyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lYzInO1xuaW1wb3J0ICogYXMgaWFtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1pYW0nO1xuaW1wb3J0ICogYXMgc2VjcmV0c21hbmFnZXIgZnJvbSAnYXdzLWNkay1saWIvYXdzLXNlY3JldHNtYW5hZ2VyJztcbmltcG9ydCB7IENvbnN0cnVjdCB9IGZyb20gJ2NvbnN0cnVjdHMnO1xuXG5leHBvcnQgaW50ZXJmYWNlIFRhaWxzY2FsZVN0YWNrUHJvcHMgZXh0ZW5kcyBjZGsuU3RhY2tQcm9wcyB7XG4gIHJlYWRvbmx5IHZwYzogZWMyLklWcGM7XG4gIHJlYWRvbmx5IHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHJlYWRvbmx5IGFnZW50Q29yZVNlY3VyaXR5R3JvdXA/OiBlYzIuSVNlY3VyaXR5R3JvdXA7XG4gIHJlYWRvbmx5IGFnZW50Q29yZVJ1bnRpbWVBcm4/OiBzdHJpbmc7XG4gIHJlYWRvbmx5IGVuYWJsZVVpU2VydmVyPzogYm9vbGVhbjtcbiAgLyoqIEJ1bXAgdGhpcyB0byBmb3JjZSBFQzIgaW5zdGFuY2UgcmVwbGFjZW1lbnQgKG5ldyBpbnN0YW5jZSBydW5zIHVzZXIgZGF0YSBmcm9tIHNjcmF0Y2gpLiAqL1xuICByZWFkb25seSBpbnN0YW5jZUJvb3RzdHJhcFZlcnNpb24/OiBzdHJpbmc7XG59XG5cbmV4cG9ydCBjbGFzcyBUYWlsc2NhbGVTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSBpbnN0YW5jZTogZWMyLkluc3RhbmNlO1xuICBwdWJsaWMgcmVhZG9ubHkgc2VjdXJpdHlHcm91cDogZWMyLlNlY3VyaXR5R3JvdXA7XG5cbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM6IFRhaWxzY2FsZVN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIGNvbnN0IHsgdnBjLCB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0LCBlbmFibGVVaVNlcnZlciA9IHRydWUgfSA9IHByb3BzO1xuICAgIGNvbnN0IGJvb3RzdHJhcFZlcnNpb24gPSBwcm9wcy5pbnN0YW5jZUJvb3RzdHJhcFZlcnNpb24gPz9cbiAgICAgIHRoaXMubm9kZS50cnlHZXRDb250ZXh0KCdnbGl0Y2hUYWlsc2NhbGVCb290c3RyYXBWZXJzaW9uJykgPz8gJzInO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwID0gbmV3IGVjMi5TZWN1cml0eUdyb3VwKHRoaXMsICdUYWlsc2NhbGVTZWN1cml0eUdyb3VwJywge1xuICAgICAgdnBjLFxuICAgICAgZGVzY3JpcHRpb246ICdTZWN1cml0eSBncm91cCBmb3IgVGFpbHNjYWxlIEVDMiBjb25uZWN0b3InLFxuICAgICAgYWxsb3dBbGxPdXRib3VuZDogZmFsc2UsXG4gICAgfSk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnRjcCg0NDMpLFxuICAgICAgJ0hUVFBTIHRvIFRhaWxzY2FsZSBjb29yZGluYXRpb24gc2VydmVyIGFuZCBERVJQIHJlbGF5cydcbiAgICApO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC51ZHAoNDE2NDEpLFxuICAgICAgJ1dpcmVHdWFyZCBkaXJlY3QgcGVlci10by1wZWVyIHR1bm5lbHMnXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudWRwKDM0NzgpLFxuICAgICAgJ1NUVU4gcHJvdG9jb2wgZm9yIE5BVCB0cmF2ZXJzYWwnXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudGNwKDgwKSxcbiAgICAgICdIVFRQIGZhbGxiYWNrIGFuZCBjYXB0aXZlIHBvcnRhbCBkZXRlY3Rpb24nXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRJbmdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnVkcCg0MTY0MSksXG4gICAgICAnQWxsb3cgaW5ib3VuZCBXaXJlR3VhcmQgZm9yIGRpcmVjdCBjb25uZWN0aW9ucydcbiAgICApO1xuXG4gICAgaWYgKHByb3BzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXApIHtcbiAgICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRJbmdyZXNzUnVsZShcbiAgICAgICAgcHJvcHMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cCxcbiAgICAgICAgZWMyLlBvcnQuYWxsVHJhZmZpYygpLFxuICAgICAgICAnQWxsb3cgYWxsIHRyYWZmaWMgZnJvbSBBZ2VudENvcmUgRU5JcydcbiAgICAgICk7XG4gICAgfVxuXG4gICAgaWYgKGVuYWJsZVVpU2VydmVyKSB7XG4gICAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICAgIGVjMi5QZWVyLmlwdjQoJzEwMC42NC4wLjAvMTAnKSxcbiAgICAgICAgZWMyLlBvcnQudGNwKDgwODApLFxuICAgICAgICAnQWxsb3cgR2xpdGNoIFVJIGZyb20gVGFpbHNjYWxlIG5ldHdvcmsnXG4gICAgICApO1xuICAgIH1cblxuICAgIGNvbnN0IHJvbGUgPSBuZXcgaWFtLlJvbGUodGhpcywgJ1RhaWxzY2FsZUluc3RhbmNlUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdlYzIuYW1hem9uYXdzLmNvbScpLFxuICAgICAgZGVzY3JpcHRpb246ICdJQU0gcm9sZSBmb3IgVGFpbHNjYWxlIEVDMiBjb25uZWN0b3Igd2l0aCBVSSBzZXJ2ZXInLFxuICAgICAgbWFuYWdlZFBvbGljaWVzOiBbXG4gICAgICAgIGlhbS5NYW5hZ2VkUG9saWN5LmZyb21Bd3NNYW5hZ2VkUG9saWN5TmFtZSgnQW1hem9uU1NNTWFuYWdlZEluc3RhbmNlQ29yZScpLFxuICAgICAgXSxcbiAgICB9KTtcblxuICAgIHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQuZ3JhbnRSZWFkKHJvbGUpO1xuXG4gICAgaWYgKGVuYWJsZVVpU2VydmVyKSB7XG4gICAgICByb2xlLmFkZFRvUG9saWN5KG5ldyBpYW0uUG9saWN5U3RhdGVtZW50KHtcbiAgICAgICAgZWZmZWN0OiBpYW0uRWZmZWN0LkFMTE9XLFxuICAgICAgICBhY3Rpb25zOiBbXG4gICAgICAgICAgJ2JlZHJvY2stYWdlbnRjb3JlOkludm9rZUFnZW50UnVudGltZScsXG4gICAgICAgIF0sXG4gICAgICAgIHJlc291cmNlczogcHJvcHMuYWdlbnRDb3JlUnVudGltZUFybiBcbiAgICAgICAgICA/IFtwcm9wcy5hZ2VudENvcmVSdW50aW1lQXJuLCBgJHtwcm9wcy5hZ2VudENvcmVSdW50aW1lQXJufS8qYF1cbiAgICAgICAgICA6IFtgYXJuOmF3czpiZWRyb2NrLWFnZW50Y29yZToke3RoaXMucmVnaW9ufToke3RoaXMuYWNjb3VudH06cnVudGltZS8qYF0sXG4gICAgICB9KSk7XG5cbiAgICAgIHJvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFtcbiAgICAgICAgICAnYmVkcm9jay1hZ2VudGNvcmUtY29udHJvbDpMaXN0QWdlbnRSdW50aW1lcycsXG4gICAgICAgIF0sXG4gICAgICAgIHJlc291cmNlczogWycqJ10sXG4gICAgICB9KSk7XG5cbiAgICAgIHJvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFsnc3NtOkdldFBhcmFtZXRlciddLFxuICAgICAgICByZXNvdXJjZXM6IFtcbiAgICAgICAgICBgYXJuOmF3czpzc206JHt0aGlzLnJlZ2lvbn06JHt0aGlzLmFjY291bnR9OnBhcmFtZXRlci9nbGl0Y2gvKmAsXG4gICAgICAgIF0sXG4gICAgICB9KSk7XG5cbiAgICAgIHJvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFsnczM6R2V0T2JqZWN0J10sXG4gICAgICAgIHJlc291cmNlczogW1xuICAgICAgICAgIGBhcm46YXdzOnMzOjo6Z2xpdGNoLWFnZW50LXN0YXRlLSR7dGhpcy5hY2NvdW50fS0ke3RoaXMucmVnaW9ufS8qYCxcbiAgICAgICAgXSxcbiAgICAgIH0pKTtcbiAgICB9XG5cbiAgICBjb25zdCB1c2VyRGF0YSA9IGVjMi5Vc2VyRGF0YS5mb3JMaW51eCgpO1xuICAgIFxuICAgIGNvbnN0IHVzZXJEYXRhQ29tbWFuZHMgPSBbXG4gICAgICAnIyEvYmluL2Jhc2gnLFxuICAgICAgJ3NldCAtZScsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiSW5zdGFsbGluZyBBV1MgQ0xJIGFuZCByZXRyaWV2aW5nIFRhaWxzY2FsZSBhdXRoIGtleS4uLlwiJyxcbiAgICAgICd5dW0gaW5zdGFsbCAteSBhd3MtY2xpJyxcbiAgICAgICcnLFxuICAgICAgYFRBSUxTQ0FMRV9BVVRIX0tFWT0kKGF3cyBzZWNyZXRzbWFuYWdlciBnZXQtc2VjcmV0LXZhbHVlIC0tc2VjcmV0LWlkICR7dGFpbHNjYWxlQXV0aEtleVNlY3JldC5zZWNyZXROYW1lfSAtLXF1ZXJ5IFNlY3JldFN0cmluZyAtLW91dHB1dCB0ZXh0IC0tcmVnaW9uICR7dGhpcy5yZWdpb259KWAsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiSW5zdGFsbGluZyBUYWlsc2NhbGUuLi5cIicsXG4gICAgICAnY3VybCAtZnNTTCBodHRwczovL3RhaWxzY2FsZS5jb20vaW5zdGFsbC5zaCB8IHNoJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJFbmFibGluZyBJUCBmb3J3YXJkaW5nLi4uXCInLFxuICAgICAgJ2VjaG8gXCJuZXQuaXB2NC5pcF9mb3J3YXJkID0gMVwiID4+IC9ldGMvc3lzY3RsLmNvbmYnLFxuICAgICAgJ2VjaG8gXCJuZXQuaXB2Ni5jb25mLmFsbC5mb3J3YXJkaW5nID0gMVwiID4+IC9ldGMvc3lzY3RsLmNvbmYnLFxuICAgICAgJ3N5c2N0bCAtcCAvZXRjL3N5c2N0bC5jb25mJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJTdGFydGluZyBUYWlsc2NhbGUgd2l0aCBhdXRoIGtleS4uLlwiJyxcbiAgICAgICd0YWlsc2NhbGUgdXAgLS1hdXRoa2V5PVwiJFRBSUxTQ0FMRV9BVVRIX0tFWVwiIC0tYWR2ZXJ0aXNlLXRhZ3M9dGFnOmF3cy1hZ2VudCAtLWFjY2VwdC1yb3V0ZXMnLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIkNsZWFyaW5nIGF1dGgga2V5IGZyb20gbWVtb3J5Li4uXCInLFxuICAgICAgJ3Vuc2V0IFRBSUxTQ0FMRV9BVVRIX0tFWScsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiVGFpbHNjYWxlIHNldHVwIGNvbXBsZXRlIVwiJyxcbiAgICAgICd0YWlsc2NhbGUgc3RhdHVzJyxcbiAgICBdO1xuXG4gICAgaWYgKGVuYWJsZVVpU2VydmVyKSB7XG4gICAgICB1c2VyRGF0YUNvbW1hbmRzLnB1c2goXG4gICAgICAgICcnLFxuICAgICAgICAnIyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PScsXG4gICAgICAgICcjIEdsaXRjaCBVSSBTZXJ2ZXIgU2V0dXAnLFxuICAgICAgICAnIyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PScsXG4gICAgICAgICcnLFxuICAgICAgICAnZWNobyBcIkluc3RhbGxpbmcgUHl0aG9uIDMuMTIgYW5kIGRlcGVuZGVuY2llcy4uLlwiJyxcbiAgICAgICAgJ3l1bSBpbnN0YWxsIC15IHB5dGhvbjMuMTIgcHl0aG9uMy4xMi1waXAgZ2l0JyxcbiAgICAgICAgJycsXG4gICAgICAgICdlY2hvIFwiQ3JlYXRpbmcgZ2xpdGNoIHVzZXIuLi5cIicsXG4gICAgICAgICd1c2VyYWRkIC1yIC1zIC9iaW4vZmFsc2UgZ2xpdGNoIHx8IHRydWUnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJGZXRjaGluZyBHbGl0Y2ggc291cmNlIChTMyBidW5kbGUgb3IgZ2l0KS4uLlwiJyxcbiAgICAgICAgYEJVTkRMRV9TMz1cInMzOi8vZ2xpdGNoLWFnZW50LXN0YXRlLSR7dGhpcy5hY2NvdW50fS0ke3RoaXMucmVnaW9ufS9kZXBsb3kvZ2xpdGNoLXVpLWJ1bmRsZS50YXIuZ3pcImAsXG4gICAgICAgIGBpZiBhd3MgczMgY3AgXCIkQlVORExFX1MzXCIgL3RtcC9nbGl0Y2gtdWktYnVuZGxlLnRhci5neiAtLXJlZ2lvbiAke3RoaXMucmVnaW9ufSAyPi9kZXYvbnVsbDsgdGhlbmAsXG4gICAgICAgICcgIGVjaG8gXCJVc2luZyBHbGl0Y2ggYnVuZGxlIGZyb20gUzMuLi5cIicsXG4gICAgICAgICcgIHRhciAteHpmIC90bXAvZ2xpdGNoLXVpLWJ1bmRsZS50YXIuZ3ogLUMgL3RtcCcsXG4gICAgICAgICcgIG1rZGlyIC1wIC9vcHQvZ2xpdGNoJyxcbiAgICAgICAgJyAgbXYgL3RtcC9hZ2VudCAvb3B0L2dsaXRjaC8gJiYgbXYgL3RtcC91aSAvb3B0L2dsaXRjaC8nLFxuICAgICAgICAnICBybSAtZiAvdG1wL2dsaXRjaC11aS1idW5kbGUudGFyLmd6JyxcbiAgICAgICAgJ2Vsc2UnLFxuICAgICAgICAnICBlY2hvIFwiTm8gUzMgYnVuZGxlOyBjbG9uaW5nIGZyb20gR2l0SHViIChwdWJsaWMgcmVwbyBvbmx5KS4uLlwiJyxcbiAgICAgICAgJyAgY2QgL29wdCAmJiBnaXQgY2xvbmUgaHR0cHM6Ly9naXRodWIuY29tL3Rhb2lzdDgwL0dsaXRjaC5naXQgZ2xpdGNoIHx8IChjZCBnbGl0Y2ggJiYgZ2l0IHB1bGwpJyxcbiAgICAgICAgJ2ZpJyxcbiAgICAgICAgJ2Nob3duIC1SIGdsaXRjaDpnbGl0Y2ggL29wdC9nbGl0Y2ggMj4vZGV2L251bGwgfHwgdHJ1ZScsXG4gICAgICAgICcnLFxuICAgICAgICAnZWNobyBcIlNldHRpbmcgdXAgUHl0aG9uIHZpcnR1YWwgZW52aXJvbm1lbnQuLi5cIicsXG4gICAgICAgICdjZCAvb3B0L2dsaXRjaC9hZ2VudCcsXG4gICAgICAgICdweXRob24zLjEyIC1tIHZlbnYgLnZlbnYnLFxuICAgICAgICAnLnZlbnYvYmluL3BpcCBpbnN0YWxsIC0tdXBncmFkZSBwaXAnLFxuICAgICAgICAnLnZlbnYvYmluL3BpcCBpbnN0YWxsIC1yIHJlcXVpcmVtZW50cy50eHQnLFxuICAgICAgICAnLnZlbnYvYmluL3BpcCBpbnN0YWxsIGJlZHJvY2stYWdlbnRjb3JlIGZhc3RhcGkgXCJweXRob24tdGVsZWdyYW0tYm90W3dlYmhvb2tzXVwiJyxcbiAgICAgICAgJycsXG4gICAgICAgICdlY2hvIFwiQnVpbGRpbmcgVUkuLi5cIicsXG4gICAgICAgICcoIGNkIC9vcHQvZ2xpdGNoL3VpICYmIGN1cmwgLWZzU0wgaHR0cHM6Ly9nZXQucG5wbS5pby9pbnN0YWxsLnNoIHwgc2ggLSAmJiBleHBvcnQgUE5QTV9IT01FPVwiL3Jvb3QvLmxvY2FsL3NoYXJlL3BucG1cIiAmJiBleHBvcnQgUEFUSD1cIiRQTlBNX0hPTUU6JFBBVEhcIiAmJiBDST10cnVlIHBucG0gaW5zdGFsbCAmJiBwbnBtIGJ1aWxkICknLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJDcmVhdGluZyBzeXN0ZW1kIHNlcnZpY2UuLi5cIicsXG4gICAgICAgICdjYXQgPiAvZXRjL3N5c3RlbWQvc3lzdGVtL2dsaXRjaC11aS5zZXJ2aWNlIDw8IFxcJ0VPRlxcJycsXG4gICAgICAgICdbVW5pdF0nLFxuICAgICAgICAnRGVzY3JpcHRpb249R2xpdGNoIFVJIFNlcnZlcicsXG4gICAgICAgICdBZnRlcj1uZXR3b3JrLnRhcmdldCB0YWlsc2NhbGVkLnNlcnZpY2UnLFxuICAgICAgICAnV2FudHM9dGFpbHNjYWxlZC5zZXJ2aWNlJyxcbiAgICAgICAgJycsXG4gICAgICAgICdbU2VydmljZV0nLFxuICAgICAgICAnVHlwZT1zaW1wbGUnLFxuICAgICAgICAnVXNlcj1yb290JyxcbiAgICAgICAgJ1dvcmtpbmdEaXJlY3Rvcnk9L29wdC9nbGl0Y2gvYWdlbnQnLFxuICAgICAgICAnRW52aXJvbm1lbnQ9UFlUSE9OUEFUSD0vb3B0L2dsaXRjaC9hZ2VudC9zcmMnLFxuICAgICAgICAnRW52aXJvbm1lbnQ9R0xJVENIX1VJX01PREU9cHJveHknLFxuICAgICAgICAnRW52aXJvbm1lbnQ9R0xJVENIX01PREU9c2VydmVyJyxcbiAgICAgICAgJ0Vudmlyb25tZW50PUdMSVRDSF9BR0VOVF9OQU1FPUdsaXRjaCcsXG4gICAgICAgIGBFbnZpcm9ubWVudD1BV1NfREVGQVVMVF9SRUdJT049JHt0aGlzLnJlZ2lvbn1gLFxuICAgICAgICAnRXhlY1N0YXJ0PS9vcHQvZ2xpdGNoL2FnZW50Ly52ZW52L2Jpbi9weXRob24gLW0gZ2xpdGNoJyxcbiAgICAgICAgJ1Jlc3RhcnQ9YWx3YXlzJyxcbiAgICAgICAgJ1Jlc3RhcnRTZWM9MTAnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ1tJbnN0YWxsXScsXG4gICAgICAgICdXYW50ZWRCeT1tdWx0aS11c2VyLnRhcmdldCcsXG4gICAgICAgICdFT0YnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJFbmFibGluZyBhbmQgc3RhcnRpbmcgR2xpdGNoIFVJIHNlcnZpY2UuLi5cIicsXG4gICAgICAgICdzeXN0ZW1jdGwgZGFlbW9uLXJlbG9hZCcsXG4gICAgICAgICdzeXN0ZW1jdGwgZW5hYmxlIGdsaXRjaC11aScsXG4gICAgICAgICdzeXN0ZW1jdGwgc3RhcnQgZ2xpdGNoLXVpJyxcbiAgICAgICAgJycsXG4gICAgICAgICdlY2hvIFwiR2xpdGNoIFVJIHNlcnZlciBzZXR1cCBjb21wbGV0ZSFcIicsXG4gICAgICAgICdlY2hvIFwiQWNjZXNzIHZpYSBUYWlsc2NhbGUgYXQgaHR0cDovLyQodGFpbHNjYWxlIGlwIC00KTo4MDgwL1wiJyxcbiAgICAgICk7XG4gICAgfVxuXG4gICAgdXNlckRhdGEuYWRkQ29tbWFuZHMoLi4udXNlckRhdGFDb21tYW5kcyk7XG5cbiAgICBjb25zdCBpbnN0YW5jZVR5cGUgPSBlbmFibGVVaVNlcnZlclxuICAgICAgPyBlYzIuSW5zdGFuY2VUeXBlLm9mKGVjMi5JbnN0YW5jZUNsYXNzLlQ0RywgZWMyLkluc3RhbmNlU2l6ZS5TTUFMTClcbiAgICAgIDogZWMyLkluc3RhbmNlVHlwZS5vZihlYzIuSW5zdGFuY2VDbGFzcy5UNEcsIGVjMi5JbnN0YW5jZVNpemUuTkFOTyk7XG5cbiAgICB0aGlzLmluc3RhbmNlID0gbmV3IGVjMi5JbnN0YW5jZSh0aGlzLCBgVGFpbHNjYWxlSW5zdGFuY2VCb290c3RyYXAke2Jvb3RzdHJhcFZlcnNpb259YCwge1xuICAgICAgdnBjLFxuICAgICAgdnBjU3VibmV0czogeyBzdWJuZXRUeXBlOiBlYzIuU3VibmV0VHlwZS5QVUJMSUMgfSxcbiAgICAgIGluc3RhbmNlVHlwZSxcbiAgICAgIG1hY2hpbmVJbWFnZTogZWMyLk1hY2hpbmVJbWFnZS5sYXRlc3RBbWF6b25MaW51eDIwMjMoe1xuICAgICAgICBjcHVUeXBlOiBlYzIuQW1hem9uTGludXhDcHVUeXBlLkFSTV82NCxcbiAgICAgICAgY2FjaGVkSW5Db250ZXh0OiBmYWxzZSxcbiAgICAgIH0pLFxuICAgICAgc2VjdXJpdHlHcm91cDogdGhpcy5zZWN1cml0eUdyb3VwLFxuICAgICAgcm9sZSxcbiAgICAgIHVzZXJEYXRhLFxuICAgICAgcmVxdWlyZUltZHN2MjogdHJ1ZSxcbiAgICAgIHNzbVNlc3Npb25QZXJtaXNzaW9uczogdHJ1ZSxcbiAgICAgIGFzc29jaWF0ZVB1YmxpY0lwQWRkcmVzczogdHJ1ZSxcbiAgICAgIGJsb2NrRGV2aWNlczogZW5hYmxlVWlTZXJ2ZXIgPyBbe1xuICAgICAgICBkZXZpY2VOYW1lOiAnL2Rldi94dmRhJyxcbiAgICAgICAgdm9sdW1lOiBlYzIuQmxvY2tEZXZpY2VWb2x1bWUuZWJzKDIwLCB7XG4gICAgICAgICAgdm9sdW1lVHlwZTogZWMyLkVic0RldmljZVZvbHVtZVR5cGUuR1AzLFxuICAgICAgICAgIGVuY3J5cHRlZDogdHJ1ZSxcbiAgICAgICAgfSksXG4gICAgICB9XSA6IHVuZGVmaW5lZCxcbiAgICB9KTtcblxuICAgIGNkay5UYWdzLm9mKHRoaXMuaW5zdGFuY2UpLmFkZCgnTmFtZScsICdHbGl0Y2hUYWlsc2NhbGVDb25uZWN0b3InKTtcbiAgICBjZGsuVGFncy5vZih0aGlzLmluc3RhbmNlKS5hZGQoJ1B1cnBvc2UnLCBlbmFibGVVaVNlcnZlciA/ICdUYWlsc2NhbGUtQVdTLUJyaWRnZS1VSScgOiAnVGFpbHNjYWxlLUFXUy1CcmlkZ2UnKTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdJbnN0YW5jZUlkJywge1xuICAgICAgdmFsdWU6IHRoaXMuaW5zdGFuY2UuaW5zdGFuY2VJZCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIEVDMiBpbnN0YW5jZSBJRCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnU2VjdXJpdHlHcm91cElkJywge1xuICAgICAgdmFsdWU6IHRoaXMuc2VjdXJpdHlHcm91cC5zZWN1cml0eUdyb3VwSWQsXG4gICAgICBkZXNjcmlwdGlvbjogJ1RhaWxzY2FsZSBzZWN1cml0eSBncm91cCBJRCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnUHJpdmF0ZUlwJywge1xuICAgICAgdmFsdWU6IHRoaXMuaW5zdGFuY2UuaW5zdGFuY2VQcml2YXRlSXAsXG4gICAgICBkZXNjcmlwdGlvbjogJ1RhaWxzY2FsZSBFQzIgcHJpdmF0ZSBJUCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnUHVibGljSXAnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5pbnN0YW5jZS5pbnN0YW5jZVB1YmxpY0lwLFxuICAgICAgZGVzY3JpcHRpb246ICdUYWlsc2NhbGUgRUMyIHB1YmxpYyBJUCcsXG4gICAgfSk7XG5cbiAgICBpZiAoZW5hYmxlVWlTZXJ2ZXIpIHtcbiAgICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdVaUFjY2Vzc0luZm8nLCB7XG4gICAgICAgIHZhbHVlOiAnQWNjZXNzIFVJIHZpYSBUYWlsc2NhbGU6IGh0dHA6Ly88dGFpbHNjYWxlLWlwPjo4MDgwLycsXG4gICAgICAgIGRlc2NyaXB0aW9uOiAnSG93IHRvIGFjY2VzcyB0aGUgR2xpdGNoIFVJJyxcbiAgICAgIH0pO1xuICAgIH1cbiAgfVxufVxuIl19