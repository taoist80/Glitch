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
                    'bedrock-agentcore:ListAgentRuntimes',
                ],
                resources: props.agentCoreRuntimeArn
                    ? [props.agentCoreRuntimeArn, `${props.agentCoreRuntimeArn}/*`]
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
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidGFpbHNjYWxlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsidGFpbHNjYWxlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBYzNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxjQUFjLEdBQUcsSUFBSSxFQUFFLEdBQUcsS0FBSyxDQUFDO1FBQ3JFLE1BQU0sZ0JBQWdCLEdBQUcsS0FBSyxDQUFDLHdCQUF3QjtZQUNyRCxJQUFJLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQyxpQ0FBaUMsQ0FBQyxJQUFJLEdBQUcsQ0FBQztRQUVwRSxJQUFJLENBQUMsYUFBYSxHQUFHLElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDekUsR0FBRztZQUNILFdBQVcsRUFBRSw0Q0FBNEM7WUFDekQsZ0JBQWdCLEVBQUUsS0FBSztTQUN4QixDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsYUFBYSxDQUFDLGFBQWEsQ0FDOUIsR0FBRyxDQUFDLElBQUksQ0FBQyxPQUFPLEVBQUUsRUFDbEIsR0FBRyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsR0FBRyxDQUFDLEVBQ2pCLHdEQUF3RCxDQUN6RCxDQUFDO1FBRUYsSUFBSSxDQUFDLGFBQWEsQ0FBQyxhQUFhLENBQzlCLEdBQUcsQ0FBQyxJQUFJLENBQUMsT0FBTyxFQUFFLEVBQ2xCLEdBQUcsQ0FBQyxJQUFJLENBQUMsR0FBRyxDQUFDLEtBQUssQ0FBQyxFQUNuQix1Q0FBdUMsQ0FDeEMs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WUFDL0IsV0FBVyxFQUFFLDJCQUEyQjtTQUN6QyxDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLGlCQUFpQixFQUFFO1lBQ3pDLEtBQUssRUFBRSxJQUFJLENBQUMsYUFBYSxDQUFDLGVBQWU7WUFDekMsV0FBVyxFQUFFLDZCQUE2QjtTQUMzQyxDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLFdBQVcsRUFBRTtZQUNuQyxLQUFLLEVBQUUsSUFBSSxDQUFDLFFBQVEsQ0FBQyxpQkFBaUI7WUFDdEMsV0FBVyxFQUFFLDBCQUEwQjtTQUN4QyxDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLFVBQVUsRUFBRTtZQUNsQyxLQUFLLEVBQUUsSUFBSSxDQUFDLFFBQVEsQ0FBQyxnQkFBZ0I7WUFDckMsV0FBVyxFQUFFLHlCQUF5QjtTQUN2QyxDQUFDLENBQUM7UUFFSCxJQUFJLGNBQWMsRUFBRSxDQUFDO1lBQ25CLElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsY0FBYyxFQUFFO2dCQUN0QyxLQUFLLEVBQUUsc0RBQXNEO2dCQUM3RCxXQUFXLEVBQUUsNkJBQTZCO2FBQzNDLENBQUMsQ0FBQztRQUNMLENBQUM7SUFDSCxDQUFDO0NBQ0Y7QUFyUUQsd0NBcVFDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIGVjMiBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZWMyJztcbmltcG9ydCAqIGFzIGlhbSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtaWFtJztcbmltcG9ydCAqIGFzIHNlY3JldHNtYW5hZ2VyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1zZWNyZXRzbWFuYWdlcic7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcblxuZXhwb3J0IGludGVyZmFjZSBUYWlsc2NhbGVTdGFja1Byb3BzIGV4dGVuZHMgY2RrLlN0YWNrUHJvcHMge1xuICByZWFkb25seSB2cGM6IGVjMi5JVnBjO1xuICByZWFkb25seSB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuICByZWFkb25seSBhZ2VudENvcmVTZWN1cml0eUdyb3VwPzogZWMyLklTZWN1cml0eUdyb3VwO1xuICByZWFkb25seSBhZ2VudENvcmVSdW50aW1lQXJuPzogc3RyaW5nO1xuICByZWFkb25seSBlbmFibGVVaVNlcnZlcj86IGJvb2xlYW47XG4gIC8qKiBCdW1wIHRoaXMgdG8gZm9yY2UgRUMyIGluc3RhbmNlIHJlcGxhY2VtZW50IChuZXcgaW5zdGFuY2UgcnVucyB1c2VyIGRhdGEgZnJvbSBzY3JhdGNoKS4gKi9cbiAgcmVhZG9ubHkgaW5zdGFuY2VCb290c3RyYXBWZXJzaW9uPzogc3RyaW5nO1xufVxuXG5leHBvcnQgY2xhc3MgVGFpbHNjYWxlU3RhY2sgZXh0ZW5kcyBjZGsuU3RhY2sge1xuICBwdWJsaWMgcmVhZG9ubHkgaW5zdGFuY2U6IGVjMi5JbnN0YW5jZTtcbiAgcHVibGljIHJlYWRvbmx5IHNlY3VyaXR5R3JvdXA6IGVjMi5TZWN1cml0eUdyb3VwO1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBUYWlsc2NhbGVTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICBjb25zdCB7IHZwYywgdGFpbHNjYWxlQXV0aEtleVNlY3JldCwgZW5hYmxlVWlTZXJ2ZXIgPSB0cnVlIH0gPSBwcm9wcztcbiAgICBjb25zdCBib290c3RyYXBWZXJzaW9uID0gcHJvcHMuaW5zdGFuY2VCb290c3RyYXBWZXJzaW9uID8/XG4gICAgICB0aGlzLm5vZGUudHJ5R2V0Q29udGV4dCgnZ2xpdGNoVGFpbHNjYWxlQm9vdHN0cmFwVmVyc2lvbicpID8/ICcyJztcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cCA9IG5ldyBlYzIuU2VjdXJpdHlHcm91cCh0aGlzLCAnVGFpbHNjYWxlU2VjdXJpdHlHcm91cCcsIHtcbiAgICAgIHZwYyxcbiAgICAgIGRlc2NyaXB0aW9uOiAnU2VjdXJpdHkgZ3JvdXAgZm9yIFRhaWxzY2FsZSBFQzIgY29ubmVjdG9yJyxcbiAgICAgIGFsbG93QWxsT3V0Ym91bmQ6IGZhbHNlLFxuICAgIH0pO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC50Y3AoNDQzKSxcbiAgICAgICdIVFRQUyB0byBUYWlsc2NhbGUgY29vcmRpbmF0aW9uIHNlcnZlciBhbmQgREVSUCByZWxheXMnXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudWRwKDQxNjQxKSxcbiAgICAgICdXaXJlR3VhcmQgZGlyZWN0IHBlZXItdG8tcGVlciB0dW5uZWxzJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnVkcCgzNDc4KSxcbiAgICAgICdTVFVOIHByb3RvY29sIGZvciBOQVQgdHJhdmVyc2FsJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnRjcCg4MCksXG4gICAgICAnSFRUUCBmYWxsYmFjayBhbmQgY2FwdGl2ZSBwb3J0YWwgZGV0ZWN0aW9uJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC51ZHAoNDE2NDEpLFxuICAgICAgJ0FsbG93IGluYm91bmQgV2lyZUd1YXJkIGZvciBkaXJlY3QgY29ubmVjdGlvbnMnXG4gICAgKTtcblxuICAgIGlmIChwcm9wcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwKSB7XG4gICAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICAgIHByb3BzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAsXG4gICAgICAgIGVjMi5Qb3J0LmFsbFRyYWZmaWMoKSxcbiAgICAgICAgJ0FsbG93IGFsbCB0cmFmZmljIGZyb20gQWdlbnRDb3JlIEVOSXMnXG4gICAgICApO1xuICAgIH1cblxuICAgIGlmIChlbmFibGVVaVNlcnZlcikge1xuICAgICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEluZ3Jlc3NSdWxlKFxuICAgICAgICBlYzIuUGVlci5pcHY0KCcxMDAuNjQuMC4wLzEwJyksXG4gICAgICAgIGVjMi5Qb3J0LnRjcCg4MDgwKSxcbiAgICAgICAgJ0FsbG93IEdsaXRjaCBVSSBmcm9tIFRhaWxzY2FsZSBuZXR3b3JrJ1xuICAgICAgKTtcbiAgICB9XG5cbiAgICBjb25zdCByb2xlID0gbmV3IGlhbS5Sb2xlKHRoaXMsICdUYWlsc2NhbGVJbnN0YW5jZVJvbGUnLCB7XG4gICAgICBhc3N1bWVkQnk6IG5ldyBpYW0uU2VydmljZVByaW5jaXBhbCgnZWMyLmFtYXpvbmF3cy5jb20nKSxcbiAgICAgIGRlc2NyaXB0aW9uOiAnSUFNIHJvbGUgZm9yIFRhaWxzY2FsZSBFQzIgY29ubmVjdG9yIHdpdGggVUkgc2VydmVyJyxcbiAgICAgIG1hbmFnZWRQb2xpY2llczogW1xuICAgICAgICBpYW0uTWFuYWdlZFBvbGljeS5mcm9tQXdzTWFuYWdlZFBvbGljeU5hbWUoJ0FtYXpvblNTTU1hbmFnZWRJbnN0YW5jZUNvcmUnKSxcbiAgICAgIF0sXG4gICAgfSk7XG5cbiAgICB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0LmdyYW50UmVhZChyb2xlKTtcblxuICAgIGlmIChlbmFibGVVaVNlcnZlcikge1xuICAgICAgcm9sZS5hZGRUb1BvbGljeShuZXcgaWFtLlBvbGljeVN0YXRlbWVudCh7XG4gICAgICAgIGVmZmVjdDogaWFtLkVmZmVjdC5BTExPVyxcbiAgICAgICAgYWN0aW9uczogW1xuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpJbnZva2VBZ2VudFJ1bnRpbWUnLFxuICAgICAgICAgICdiZWRyb2NrLWFnZW50Y29yZTpMaXN0QWdlbnRSdW50aW1lcycsXG4gICAgICAgIF0sXG4gICAgICAgIHJlc291cmNlczogcHJvcHMuYWdlbnRDb3JlUnVudGltZUFybiBcbiAgICAgICAgICA/IFtwcm9wcy5hZ2VudENvcmVSdW50aW1lQXJuLCBgJHtwcm9wcy5hZ2VudENvcmVSdW50aW1lQXJufS8qYF1cbiAgICAgICAgICA6IFtgYXJuOmF3czpiZWRyb2NrLWFnZW50Y29yZToke3RoaXMucmVnaW9ufToke3RoaXMuYWNjb3VudH06cnVudGltZS8qYF0sXG4gICAgICB9KSk7XG5cbiAgICAgIHJvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFsnc3NtOkdldFBhcmFtZXRlciddLFxuICAgICAgICByZXNvdXJjZXM6IFtcbiAgICAgICAgICBgYXJuOmF3czpzc206JHt0aGlzLnJlZ2lvbn06JHt0aGlzLmFjY291bnR9OnBhcmFtZXRlci9nbGl0Y2gvKmAsXG4gICAgICAgIF0sXG4gICAgICB9KSk7XG5cbiAgICAgIHJvbGUuYWRkVG9Qb2xpY3kobmV3IGlhbS5Qb2xpY3lTdGF0ZW1lbnQoe1xuICAgICAgICBlZmZlY3Q6IGlhbS5FZmZlY3QuQUxMT1csXG4gICAgICAgIGFjdGlvbnM6IFsnczM6R2V0T2JqZWN0J10sXG4gICAgICAgIHJlc291cmNlczogW1xuICAgICAgICAgIGBhcm46YXdzOnMzOjo6Z2xpdGNoLWFnZW50LXN0YXRlLSR7dGhpcy5hY2NvdW50fS0ke3RoaXMucmVnaW9ufS8qYCxcbiAgICAgICAgXSxcbiAgICAgIH0pKTtcbiAgICB9XG5cbiAgICBjb25zdCB1c2VyRGF0YSA9IGVjMi5Vc2VyRGF0YS5mb3JMaW51eCgpO1xuICAgIFxuICAgIGNvbnN0IHVzZXJEYXRhQ29tbWFuZHMgPSBbXG4gICAgICAnIyEvYmluL2Jhc2gnLFxuICAgICAgJ3NldCAtZScsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiSW5zdGFsbGluZyBBV1MgQ0xJIGFuZCByZXRyaWV2aW5nIFRhaWxzY2FsZSBhdXRoIGtleS4uLlwiJyxcbiAgICAgICd5dW0gaW5zdGFsbCAteSBhd3MtY2xpJyxcbiAgICAgICcnLFxuICAgICAgYFRBSUxTQ0FMRV9BVVRIX0tFWT0kKGF3cyBzZWNyZXRzbWFuYWdlciBnZXQtc2VjcmV0LXZhbHVlIC0tc2VjcmV0LWlkICR7dGFpbHNjYWxlQXV0aEtleVNlY3JldC5zZWNyZXROYW1lfSAtLXF1ZXJ5IFNlY3JldFN0cmluZyAtLW91dHB1dCB0ZXh0IC0tcmVnaW9uICR7dGhpcy5yZWdpb259KWAsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiSW5zdGFsbGluZyBUYWlsc2NhbGUuLi5cIicsXG4gICAgICAnY3VybCAtZnNTTCBodHRwczovL3RhaWxzY2FsZS5jb20vaW5zdGFsbC5zaCB8IHNoJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJFbmFibGluZyBJUCBmb3J3YXJkaW5nLi4uXCInLFxuICAgICAgJ2VjaG8gXCJuZXQuaXB2NC5pcF9mb3J3YXJkID0gMVwiID4+IC9ldGMvc3lzY3RsLmNvbmYnLFxuICAgICAgJ2VjaG8gXCJuZXQuaXB2Ni5jb25mLmFsbC5mb3J3YXJkaW5nID0gMVwiID4+IC9ldGMvc3lzY3RsLmNvbmYnLFxuICAgICAgJ3N5c2N0bCAtcCAvZXRjL3N5c2N0bC5jb25mJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJTdGFydGluZyBUYWlsc2NhbGUgd2l0aCBhdXRoIGtleS4uLlwiJyxcbiAgICAgICd0YWlsc2NhbGUgdXAgLS1hdXRoa2V5PVwiJFRBSUxTQ0FMRV9BVVRIX0tFWVwiIC0tYWR2ZXJ0aXNlLXRhZ3M9dGFnOmF3cy1hZ2VudCAtLWFjY2VwdC1yb3V0ZXMnLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIkNsZWFyaW5nIGF1dGgga2V5IGZyb20gbWVtb3J5Li4uXCInLFxuICAgICAgJ3Vuc2V0IFRBSUxTQ0FMRV9BVVRIX0tFWScsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiVGFpbHNjYWxlIHNldHVwIGNvbXBsZXRlIVwiJyxcbiAgICAgICd0YWlsc2NhbGUgc3RhdHVzJyxcbiAgICBdO1xuXG4gICAgaWYgKGVuYWJsZVVpU2VydmVyKSB7XG4gICAgICB1c2VyRGF0YUNvbW1hbmRzLnB1c2goXG4gICAgICAgICcnLFxuICAgICAgICAnIyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PScsXG4gICAgICAgICcjIEdsaXRjaCBVSSBTZXJ2ZXIgU2V0dXAnLFxuICAgICAgICAnIyA9PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PT09PScsXG4gICAgICAgICcnLFxuICAgICAgICAnZWNobyBcIkluc3RhbGxpbmcgUHl0aG9uIDMuMTIgYW5kIGRlcGVuZGVuY2llcy4uLlwiJyxcbiAgICAgICAgJ3l1bSBpbnN0YWxsIC15IHB5dGhvbjMuMTIgcHl0aG9uMy4xMi1waXAgZ2l0JyxcbiAgICAgICAgJycsXG4gICAgICAgICdlY2hvIFwiQ3JlYXRpbmcgZ2xpdGNoIHVzZXIuLi5cIicsXG4gICAgICAgICd1c2VyYWRkIC1yIC1zIC9iaW4vZmFsc2UgZ2xpdGNoIHx8IHRydWUnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJGZXRjaGluZyBHbGl0Y2ggc291cmNlIChTMyBidW5kbGUgb3IgZ2l0KS4uLlwiJyxcbiAgICAgICAgYEJVTkRMRV9TMz1cInMzOi8vZ2xpdGNoLWFnZW50LXN0YXRlLSR7dGhpcy5hY2NvdW50fS0ke3RoaXMucmVnaW9ufS9kZXBsb3kvZ2xpdGNoLXVpLWJ1bmRsZS50YXIuZ3pcImAsXG4gICAgICAgIGBpZiBhd3MgczMgY3AgXCIkQlVORExFX1MzXCIgL3RtcC9nbGl0Y2gtdWktYnVuZGxlLnRhci5neiAtLXJlZ2lvbiAke3RoaXMucmVnaW9ufSAyPi9kZXYvbnVsbDsgdGhlbmAsXG4gICAgICAgICcgIGVjaG8gXCJVc2luZyBHbGl0Y2ggYnVuZGxlIGZyb20gUzMuLi5cIicsXG4gICAgICAgICcgIHRhciAteHpmIC90bXAvZ2xpdGNoLXVpLWJ1bmRsZS50YXIuZ3ogLUMgL3RtcCcsXG4gICAgICAgICcgIG1rZGlyIC1wIC9vcHQvZ2xpdGNoJyxcbiAgICAgICAgJyAgbXYgL3RtcC9hZ2VudCAvb3B0L2dsaXRjaC8gJiYgbXYgL3RtcC91aSAvb3B0L2dsaXRjaC8nLFxuICAgICAgICAnICBybSAtZiAvdG1wL2dsaXRjaC11aS1idW5kbGUudGFyLmd6JyxcbiAgICAgICAgJ2Vsc2UnLFxuICAgICAgICAnICBlY2hvIFwiTm8gUzMgYnVuZGxlOyBjbG9uaW5nIGZyb20gR2l0SHViIChwdWJsaWMgcmVwbyBvbmx5KS4uLlwiJyxcbiAgICAgICAgJyAgY2QgL29wdCAmJiBnaXQgY2xvbmUgaHR0cHM6Ly9naXRodWIuY29tL3Rhb2lzdDgwL0dsaXRjaC5naXQgZ2xpdGNoIHx8IChjZCBnbGl0Y2ggJiYgZ2l0IHB1bGwpJyxcbiAgICAgICAgJ2ZpJyxcbiAgICAgICAgJ2Nob3duIC1SIGdsaXRjaDpnbGl0Y2ggL29wdC9nbGl0Y2ggMj4vZGV2L251bGwgfHwgdHJ1ZScsXG4gICAgICAgICcnLFxuICAgICAgICAnZWNobyBcIlNldHRpbmcgdXAgUHl0aG9uIHZpcnR1YWwgZW52aXJvbm1lbnQuLi5cIicsXG4gICAgICAgICdjZCAvb3B0L2dsaXRjaC9hZ2VudCcsXG4gICAgICAgICdweXRob24zLjEyIC1tIHZlbnYgLnZlbnYnLFxuICAgICAgICAnLnZlbnYvYmluL3BpcCBpbnN0YWxsIC0tdXBncmFkZSBwaXAnLFxuICAgICAgICAnLnZlbnYvYmluL3BpcCBpbnN0YWxsIC1yIHJlcXVpcmVtZW50cy50eHQnLFxuICAgICAgICAnLnZlbnYvYmluL3BpcCBpbnN0YWxsIGJlZHJvY2stYWdlbnRjb3JlIGZhc3RhcGkgXCJweXRob24tdGVsZWdyYW0tYm90W3dlYmhvb2tzXVwiJyxcbiAgICAgICAgJycsXG4gICAgICAgICdlY2hvIFwiQnVpbGRpbmcgVUkuLi5cIicsXG4gICAgICAgICcoIGNkIC9vcHQvZ2xpdGNoL3VpICYmIGN1cmwgLWZzU0wgaHR0cHM6Ly9nZXQucG5wbS5pby9pbnN0YWxsLnNoIHwgc2ggLSAmJiBleHBvcnQgUE5QTV9IT01FPVwiL3Jvb3QvLmxvY2FsL3NoYXJlL3BucG1cIiAmJiBleHBvcnQgUEFUSD1cIiRQTlBNX0hPTUU6JFBBVEhcIiAmJiBDST10cnVlIHBucG0gaW5zdGFsbCAmJiBwbnBtIGJ1aWxkICknLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJDcmVhdGluZyBzeXN0ZW1kIHNlcnZpY2UuLi5cIicsXG4gICAgICAgICdjYXQgPiAvZXRjL3N5c3RlbWQvc3lzdGVtL2dsaXRjaC11aS5zZXJ2aWNlIDw8IFxcJ0VPRlxcJycsXG4gICAgICAgICdbVW5pdF0nLFxuICAgICAgICAnRGVzY3JpcHRpb249R2xpdGNoIFVJIFNlcnZlcicsXG4gICAgICAgICdBZnRlcj1uZXR3b3JrLnRhcmdldCB0YWlsc2NhbGVkLnNlcnZpY2UnLFxuICAgICAgICAnV2FudHM9dGFpbHNjYWxlZC5zZXJ2aWNlJyxcbiAgICAgICAgJycsXG4gICAgICAgICdbU2VydmljZV0nLFxuICAgICAgICAnVHlwZT1zaW1wbGUnLFxuICAgICAgICAnVXNlcj1yb290JyxcbiAgICAgICAgJ1dvcmtpbmdEaXJlY3Rvcnk9L29wdC9nbGl0Y2gvYWdlbnQnLFxuICAgICAgICAnRW52aXJvbm1lbnQ9UFlUSE9OUEFUSD0vb3B0L2dsaXRjaC9hZ2VudC9zcmMnLFxuICAgICAgICAnRW52aXJvbm1lbnQ9R0xJVENIX1VJX01PREU9cHJveHknLFxuICAgICAgICAnRW52aXJvbm1lbnQ9R0xJVENIX01PREU9c2VydmVyJyxcbiAgICAgICAgJ0Vudmlyb25tZW50PUdMSVRDSF9BR0VOVF9OQU1FPUdsaXRjaCcsXG4gICAgICAgIGBFbnZpcm9ubWVudD1BV1NfREVGQVVMVF9SRUdJT049JHt0aGlzLnJlZ2lvbn1gLFxuICAgICAgICAnRXhlY1N0YXJ0PS9vcHQvZ2xpdGNoL2FnZW50Ly52ZW52L2Jpbi9weXRob24gLW0gZ2xpdGNoJyxcbiAgICAgICAgJ1Jlc3RhcnQ9YWx3YXlzJyxcbiAgICAgICAgJ1Jlc3RhcnRTZWM9MTAnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ1tJbnN0YWxsXScsXG4gICAgICAgICdXYW50ZWRCeT1tdWx0aS11c2VyLnRhcmdldCcsXG4gICAgICAgICdFT0YnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJFbmFibGluZyBhbmQgc3RhcnRpbmcgR2xpdGNoIFVJIHNlcnZpY2UuLi5cIicsXG4gICAgICAgICdzeXN0ZW1jdGwgZGFlbW9uLXJlbG9hZCcsXG4gICAgICAgICdzeXN0ZW1jdGwgZW5hYmxlIGdsaXRjaC11aScsXG4gICAgICAgICdzeXN0ZW1jdGwgc3RhcnQgZ2xpdGNoLXVpJyxcbiAgICAgICAgJycsXG4gICAgICAgICdlY2hvIFwiR2xpdGNoIFVJIHNlcnZlciBzZXR1cCBjb21wbGV0ZSFcIicsXG4gICAgICAgICdlY2hvIFwiQWNjZXNzIHZpYSBUYWlsc2NhbGUgYXQgaHR0cDovLyQodGFpbHNjYWxlIGlwIC00KTo4MDgwL1wiJyxcbiAgICAgICk7XG4gICAgfVxuXG4gICAgdXNlckRhdGEuYWRkQ29tbWFuZHMoLi4udXNlckRhdGFDb21tYW5kcyk7XG5cbiAgICBjb25zdCBpbnN0YW5jZVR5cGUgPSBlbmFibGVVaVNlcnZlclxuICAgICAgPyBlYzIuSW5zdGFuY2VUeXBlLm9mKGVjMi5JbnN0YW5jZUNsYXNzLlQ0RywgZWMyLkluc3RhbmNlU2l6ZS5TTUFMTClcbiAgICAgIDogZWMyLkluc3RhbmNlVHlwZS5vZihlYzIuSW5zdGFuY2VDbGFzcy5UNEcsIGVjMi5JbnN0YW5jZVNpemUuTkFOTyk7XG5cbiAgICB0aGlzLmluc3RhbmNlID0gbmV3IGVjMi5JbnN0YW5jZSh0aGlzLCBgVGFpbHNjYWxlSW5zdGFuY2VCb290c3RyYXAke2Jvb3RzdHJhcFZlcnNpb259YCwge1xuICAgICAgdnBjLFxuICAgICAgdnBjU3VibmV0czogeyBzdWJuZXRUeXBlOiBlYzIuU3VibmV0VHlwZS5QVUJMSUMgfSxcbiAgICAgIGluc3RhbmNlVHlwZSxcbiAgICAgIG1hY2hpbmVJbWFnZTogZWMyLk1hY2hpbmVJbWFnZS5sYXRlc3RBbWF6b25MaW51eDIwMjMoe1xuICAgICAgICBjcHVUeXBlOiBlYzIuQW1hem9uTGludXhDcHVUeXBlLkFSTV82NCxcbiAgICAgICAgY2FjaGVkSW5Db250ZXh0OiBmYWxzZSxcbiAgICAgIH0pLFxuICAgICAgc2VjdXJpdHlHcm91cDogdGhpcy5zZWN1cml0eUdyb3VwLFxuICAgICAgcm9sZSxcbiAgICAgIHVzZXJEYXRhLFxuICAgICAgcmVxdWlyZUltZHN2MjogdHJ1ZSxcbiAgICAgIHNzbVNlc3Npb25QZXJtaXNzaW9uczogdHJ1ZSxcbiAgICAgIGFzc29jaWF0ZVB1YmxpY0lwQWRkcmVzczogdHJ1ZSxcbiAgICAgIGJsb2NrRGV2aWNlczogZW5hYmxlVWlTZXJ2ZXIgPyBbe1xuICAgICAgICBkZXZpY2VOYW1lOiAnL2Rldi94dmRhJyxcbiAgICAgICAgdm9sdW1lOiBlYzIuQmxvY2tEZXZpY2VWb2x1bWUuZWJzKDIwLCB7XG4gICAgICAgICAgdm9sdW1lVHlwZTogZWMyLkVic0RldmljZVZvbHVtZVR5cGUuR1AzLFxuICAgICAgICAgIGVuY3J5cHRlZDogdHJ1ZSxcbiAgICAgICAgfSksXG4gICAgICB9XSA6IHVuZGVmaW5lZCxcbiAgICB9KTtcblxuICAgIGNkay5UYWdzLm9mKHRoaXMuaW5zdGFuY2UpLmFkZCgnTmFtZScsICdHbGl0Y2hUYWlsc2NhbGVDb25uZWN0b3InKTtcbiAgICBjZGsuVGFncy5vZih0aGlzLmluc3RhbmNlKS5hZGQoJ1B1cnBvc2UnLCBlbmFibGVVaVNlcnZlciA/ICdUYWlsc2NhbGUtQVdTLUJyaWRnZS1VSScgOiAnVGFpbHNjYWxlLUFXUy1CcmlkZ2UnKTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdJbnN0YW5jZUlkJywge1xuICAgICAgdmFsdWU6IHRoaXMuaW5zdGFuY2UuaW5zdGFuY2VJZCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIEVDMiBpbnN0YW5jZSBJRCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnU2VjdXJpdHlHcm91cElkJywge1xuICAgICAgdmFsdWU6IHRoaXMuc2VjdXJpdHlHcm91cC5zZWN1cml0eUdyb3VwSWQsXG4gICAgICBkZXNjcmlwdGlvbjogJ1RhaWxzY2FsZSBzZWN1cml0eSBncm91cCBJRCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnUHJpdmF0ZUlwJywge1xuICAgICAgdmFsdWU6IHRoaXMuaW5zdGFuY2UuaW5zdGFuY2VQcml2YXRlSXAsXG4gICAgICBkZXNjcmlwdGlvbjogJ1RhaWxzY2FsZSBFQzIgcHJpdmF0ZSBJUCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnUHVibGljSXAnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5pbnN0YW5jZS5pbnN0YW5jZVB1YmxpY0lwLFxuICAgICAgZGVzY3JpcHRpb246ICdUYWlsc2NhbGUgRUMyIHB1YmxpYyBJUCcsXG4gICAgfSk7XG5cbiAgICBpZiAoZW5hYmxlVWlTZXJ2ZXIpIHtcbiAgICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdVaUFjY2Vzc0luZm8nLCB7XG4gICAgICAgIHZhbHVlOiAnQWNjZXNzIFVJIHZpYSBUYWlsc2NhbGU6IGh0dHA6Ly88dGFpbHNjYWxlLWlwPjo4MDgwLycsXG4gICAgICAgIGRlc2NyaXB0aW9uOiAnSG93IHRvIGFjY2VzcyB0aGUgR2xpdGNoIFVJJyxcbiAgICAgIH0pO1xuICAgIH1cbiAgfVxufVxuIl19