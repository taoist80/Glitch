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
        const { vpc, tailscaleAuthKeySecret, gatewayFunctionUrl, uiBucketName } = props;
        const bootstrapVersion = props.instanceBootstrapVersion ??
            this.node.tryGetContext('glitchTailscaleBootstrapVersion') ?? '5';
        const enableUiProxy = Boolean(gatewayFunctionUrl && uiBucketName);
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
            const gatewayUrl = gatewayFunctionUrl.replace(/\/$/, '');
            userDataCommands.push('', 'echo "Setting up nginx UI proxy..."', 'yum install -y nginx', '', `cat > /etc/nginx/conf.d/glitch-proxy.conf << 'NGINXEOF'`, 'server {', '    listen 80;', '    server_name _;', '', '    location / {', `        proxy_pass http://${uiBucketName}.s3-website-${this.region}.amazonaws.com;`, `        proxy_set_header Host ${uiBucketName}.s3-website-${this.region}.amazonaws.com;`, '        proxy_set_header X-Real-IP $remote_addr;', '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;', '        proxy_set_header X-Forwarded-Proto $scheme;', '    }', '', '    location /api/ {', `        proxy_pass ${gatewayUrl}/api/;`, '        proxy_set_header Host $host;', '        proxy_set_header X-Real-IP $remote_addr;', '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;', '        proxy_set_header X-Forwarded-Proto $scheme;', '        proxy_ssl_server_name on;', '    }', '', '    location /invocations {', `        proxy_pass ${gatewayUrl}/invocations;`, '        proxy_set_header Host $host;', '        proxy_set_header X-Real-IP $remote_addr;', '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;', '        proxy_set_header X-Forwarded-Proto $scheme;', '        proxy_ssl_server_name on;', '    }', '', '    location /health {', `        proxy_pass ${gatewayUrl}/health;`, '        proxy_set_header Host $host;', '        proxy_set_header X-Real-IP $remote_addr;', '        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;', '        proxy_set_header X-Forwarded-Proto $scheme;', '        proxy_ssl_server_name on;', '    }', '}', 'NGINXEOF', '', 'rm -f /etc/nginx/conf.d/default.conf', 'systemctl enable nginx', 'systemctl start nginx', '', 'echo "Enabling Tailscale Serve for HTTPS..."', 'tailscale serve --bg http://127.0.0.1:80', 'echo "Tailscale Serve enabled. UI available via Tailscale HTTPS URL."');
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
exports.TailscaleStack = TailscaleStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidGFpbHNjYWxlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsidGFpbHNjYWxlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBaUIzQyxNQUFhLGNBQWUsU0FBUSxHQUFHLENBQUMsS0FBSztJQUkzQyxZQUFZLEtBQWdCLEVBQUUsRUFBVSxFQUFFLEtBQTBCO1FBQ2xFLEtBQUssQ0FBQyxLQUFLLEVBQUUsRUFBRSxFQUFFLEtBQUssQ0FBQyxDQUFDO1FBRXhCLE1BQU0sRUFBRSxHQUFHLEVBQUUsc0JBQXNCLEVBQUUsa0JBQWtCLEVBQUUsWUFBWSxFQUFFLEdBQUcsS0FBSyxDQUFDO1FBQ2hGLE1BQU0sZ0JBQWdCLEdBQUcsS0FBSyxDQUFDLHdCQUF3QjtZQUNyRCxJQUFJLENBQUMsSUFBSSxDQUFDLGFBQWEsQ0FBQyxpQ0FBaUMsQ0FBQyxJQUFJLEdBQUcsQ0FBQztRQUNwRSxNQUFNLGFBQWEsR0FBRyxPQUFPLENBQUMsa0JBQWtCLElBQUksWUFBWSxDQUFDLENBQUM7UUFFbEUsSUFBSSxDQUFDLGFBQWEsR0FBRyxJQUFJLEdBQUcsQ0FBQyxhQUFhLENBQUMsSUFBSSxFQUFFLHdCQUF3QixFQUFFO1lBQ3pFLEdBQUc7WUFDSCxXQUFXLEVBQUUsNENBQTRDO1lBQ3pELGdCQUFnQixFQUFFLEtBQUs7U0FDeEIsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLGFBQWEsQ0FBQyxhQUFhLENBQzlCLEdBQUcsQ0FBQyxJQUFJLENBQUMsT0FBTyxFQUFFLEVBQ2xCLEdBQUcsQ0FBQyxJQUFJLENBQUMsR0FBRyxDQUFDLEdBQUcsQ0FBQyxFQUNqQix3REFBd0QsQ0FDekQsQ0FBQztRQUVGLElBQUksQ0FBQyxhQUFhLENBQUMsYUFBYSxDQUM5QixHQUFHLENBQUMsSUFBSSxDQUFDLE9BQU8sRUFBRSxFQUNs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LEVBQUU7Z0JBQ3hDLEtBQUssRUFBRSw4Q0FBOEM7Z0JBQ3JELFdBQVcsRUFBRSxzTUFBc007YUFDcE4sQ0FBQyxDQUFDO1FBQ0wsQ0FBQztJQUNILENBQUM7Q0FDRjtBQTdNRCx3Q0E2TUMiLCJzb3VyY2VzQ29udGVudCI6WyJpbXBvcnQgKiBhcyBjZGsgZnJvbSAnYXdzLWNkay1saWInO1xuaW1wb3J0ICogYXMgZWMyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1lYzInO1xuaW1wb3J0ICogYXMgaWFtIGZyb20gJ2F3cy1jZGstbGliL2F3cy1pYW0nO1xuaW1wb3J0ICogYXMgc2VjcmV0c21hbmFnZXIgZnJvbSAnYXdzLWNkay1saWIvYXdzLXNlY3JldHNtYW5hZ2VyJztcbmltcG9ydCB7IENvbnN0cnVjdCB9IGZyb20gJ2NvbnN0cnVjdHMnO1xuXG5leHBvcnQgaW50ZXJmYWNlIFRhaWxzY2FsZVN0YWNrUHJvcHMgZXh0ZW5kcyBjZGsuU3RhY2tQcm9wcyB7XG4gIHJlYWRvbmx5IHZwYzogZWMyLklWcGM7XG4gIHJlYWRvbmx5IHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQ6IHNlY3JldHNtYW5hZ2VyLklTZWNyZXQ7XG4gIHJlYWRvbmx5IGFnZW50Q29yZVNlY3VyaXR5R3JvdXA/OiBlYzIuSVNlY3VyaXR5R3JvdXA7XG4gIHJlYWRvbmx5IGFnZW50Q29yZVJ1bnRpbWVBcm4/OiBzdHJpbmc7XG4gIC8qKiBCdW1wIHRoaXMgdG8gZm9yY2UgRUMyIGluc3RhbmNlIHJlcGxhY2VtZW50IChuZXcgaW5zdGFuY2UgcnVucyB1c2VyIGRhdGEgZnJvbSBzY3JhdGNoKS4gKi9cbiAgcmVhZG9ubHkgaW5zdGFuY2VCb290c3RyYXBWZXJzaW9uPzogc3RyaW5nO1xuICAvKiogR2F0ZXdheSBMYW1iZGEgRnVuY3Rpb24gVVJMIGZvciBuZ2lueCBwcm94eSAoVUkgQVBJIGFuZCBpbnZvY2F0aW9ucykuICovXG4gIHJlYWRvbmx5IGdhdGV3YXlGdW5jdGlvblVybD86IHN0cmluZztcbiAgLyoqIFMzIFVJIGJ1Y2tldCBuYW1lIGZvciBuZ2lueCB0byBwcm94eSBzdGF0aWMgZmlsZXMuICovXG4gIHJlYWRvbmx5IHVpQnVja2V0TmFtZT86IHN0cmluZztcbn1cblxuZXhwb3J0IGNsYXNzIFRhaWxzY2FsZVN0YWNrIGV4dGVuZHMgY2RrLlN0YWNrIHtcbiAgcHVibGljIHJlYWRvbmx5IGluc3RhbmNlOiBlYzIuSW5zdGFuY2U7XG4gIHB1YmxpYyByZWFkb25seSBzZWN1cml0eUdyb3VwOiBlYzIuU2VjdXJpdHlHcm91cDtcblxuICBjb25zdHJ1Y3RvcihzY29wZTogQ29uc3RydWN0LCBpZDogc3RyaW5nLCBwcm9wczogVGFpbHNjYWxlU3RhY2tQcm9wcykge1xuICAgIHN1cGVyKHNjb3BlLCBpZCwgcHJvcHMpO1xuXG4gICAgY29uc3QgeyB2cGMsIHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQsIGdhdGV3YXlGdW5jdGlvblVybCwgdWlCdWNrZXROYW1lIH0gPSBwcm9wcztcbiAgICBjb25zdCBib290c3RyYXBWZXJzaW9uID0gcHJvcHMuaW5zdGFuY2VCb290c3RyYXBWZXJzaW9uID8/XG4gICAgICB0aGlzLm5vZGUudHJ5R2V0Q29udGV4dCgnZ2xpdGNoVGFpbHNjYWxlQm9vdHN0cmFwVmVyc2lvbicpID8/ICc1JztcbiAgICBjb25zdCBlbmFibGVVaVByb3h5ID0gQm9vbGVhbihnYXRld2F5RnVuY3Rpb25VcmwgJiYgdWlCdWNrZXROYW1lKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cCA9IG5ldyBlYzIuU2VjdXJpdHlHcm91cCh0aGlzLCAnVGFpbHNjYWxlU2VjdXJpdHlHcm91cCcsIHtcbiAgICAgIHZwYyxcbiAgICAgIGRlc2NyaXB0aW9uOiAnU2VjdXJpdHkgZ3JvdXAgZm9yIFRhaWxzY2FsZSBFQzIgY29ubmVjdG9yJyxcbiAgICAgIGFsbG93QWxsT3V0Ym91bmQ6IGZhbHNlLFxuICAgIH0pO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC50Y3AoNDQzKSxcbiAgICAgICdIVFRQUyB0byBUYWlsc2NhbGUgY29vcmRpbmF0aW9uIHNlcnZlciBhbmQgREVSUCByZWxheXMnXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudWRwKDQxNjQxKSxcbiAgICAgICdXaXJlR3VhcmQgZGlyZWN0IHBlZXItdG8tcGVlciB0dW5uZWxzJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnVkcCgzNDc4KSxcbiAgICAgICdTVFVOIHByb3RvY29sIGZvciBOQVQgdHJhdmVyc2FsJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnRjcCg4MCksXG4gICAgICAnSFRUUCBmYWxsYmFjayBhbmQgY2FwdGl2ZSBwb3J0YWwgZGV0ZWN0aW9uJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC51ZHAoNDE2NDEpLFxuICAgICAgJ0FsbG93IGluYm91bmQgV2lyZUd1YXJkIGZvciBkaXJlY3QgY29ubmVjdGlvbnMnXG4gICAgKTtcblxuICAgIGlmIChwcm9wcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwKSB7XG4gICAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICAgIHByb3BzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAsXG4gICAgICAgIGVjMi5Qb3J0LmFsbFRyYWZmaWMoKSxcbiAgICAgICAgJ0FsbG93IGFsbCB0cmFmZmljIGZyb20gQWdlbnRDb3JlIEVOSXMnXG4gICAgICApO1xuICAgIH1cblxuICAgIGNvbnN0IHJvbGUgPSBuZXcgaWFtLlJvbGUodGhpcywgJ1RhaWxzY2FsZUluc3RhbmNlUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdlYzIuYW1hem9uYXdzLmNvbScpLFxuICAgICAgZGVzY3JpcHRpb246ICdJQU0gcm9sZSBmb3IgVGFpbHNjYWxlIEVDMiBjb25uZWN0b3InLFxuICAgICAgbWFuYWdlZFBvbGljaWVzOiBbXG4gICAgICAgIGlhbS5NYW5hZ2VkUG9saWN5LmZyb21Bd3NNYW5hZ2VkUG9saWN5TmFtZSgnQW1hem9uU1NNTWFuYWdlZEluc3RhbmNlQ29yZScpLFxuICAgICAgXSxcbiAgICB9KTtcblxuICAgIHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQuZ3JhbnRSZWFkKHJvbGUpO1xuXG4gICAgY29uc3QgdXNlckRhdGEgPSBlYzIuVXNlckRhdGEuZm9yTGludXgoKTtcbiAgICBcbiAgICBjb25zdCB1c2VyRGF0YUNvbW1hbmRzID0gW1xuICAgICAgJyMhL2Jpbi9iYXNoJyxcbiAgICAgICdzZXQgLWUnLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIkluc3RhbGxpbmcgQVdTIENMSSBhbmQgcmV0cmlldmluZyBUYWlsc2NhbGUgYXV0aCBrZXkuLi5cIicsXG4gICAgICAneXVtIGluc3RhbGwgLXkgYXdzLWNsaScsXG4gICAgICAnJyxcbiAgICAgIGBUQUlMU0NBTEVfQVVUSF9LRVk9JChhd3Mgc2VjcmV0c21hbmFnZXIgZ2V0LXNlY3JldC12YWx1ZSAtLXNlY3JldC1pZCAke3RhaWxzY2FsZUF1dGhLZXlTZWNyZXQuc2VjcmV0TmFtZX0gLS1xdWVyeSBTZWNyZXRTdHJpbmcgLS1vdXRwdXQgdGV4dCAtLXJlZ2lvbiAke3RoaXMucmVnaW9ufSlgLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIlNldHRpbmcgaG9zdG5hbWUgZm9yIHByZWRpY3RhYmxlIFRhaWxzY2FsZSBVUkwuLi5cIicsXG4gICAgICAnaG9zdG5hbWVjdGwgc2V0LWhvc3RuYW1lIGdsaXRjaC10YWlsc2NhbGUnLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIkluc3RhbGxpbmcgVGFpbHNjYWxlLi4uXCInLFxuICAgICAgJ2N1cmwgLWZzU0wgaHR0cHM6Ly90YWlsc2NhbGUuY29tL2luc3RhbGwuc2ggfCBzaCcsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiRW5hYmxpbmcgSVAgZm9yd2FyZGluZy4uLlwiJyxcbiAgICAgICdlY2hvIFwibmV0LmlwdjQuaXBfZm9yd2FyZCA9IDFcIiA+PiAvZXRjL3N5c2N0bC5jb25mJyxcbiAgICAgICdlY2hvIFwibmV0LmlwdjYuY29uZi5hbGwuZm9yd2FyZGluZyA9IDFcIiA+PiAvZXRjL3N5c2N0bC5jb25mJyxcbiAgICAgICdzeXNjdGwgLXAgL2V0Yy9zeXNjdGwuY29uZicsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiU3RhcnRpbmcgVGFpbHNjYWxlIHdpdGggYXV0aCBrZXkuLi5cIicsXG4gICAgICAndGFpbHNjYWxlIHVwIC0tYXV0aGtleT1cIiRUQUlMU0NBTEVfQVVUSF9LRVlcIiAtLWFkdmVydGlzZS10YWdzPXRhZzphd3MtYWdlbnQgLS1hY2NlcHQtcm91dGVzJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJDbGVhcmluZyBhdXRoIGtleSBmcm9tIG1lbW9yeS4uLlwiJyxcbiAgICAgICd1bnNldCBUQUlMU0NBTEVfQVVUSF9LRVknLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIlRhaWxzY2FsZSBzZXR1cCBjb21wbGV0ZSFcIicsXG4gICAgICAndGFpbHNjYWxlIHN0YXR1cycsXG4gICAgXTtcblxuICAgIGlmIChlbmFibGVVaVByb3h5KSB7XG4gICAgICBjb25zdCBnYXRld2F5VXJsID0gZ2F0ZXdheUZ1bmN0aW9uVXJsIS5yZXBsYWNlKC9cXC8kLywgJycpO1xuICAgICAgdXNlckRhdGFDb21tYW5kcy5wdXNoKFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJTZXR0aW5nIHVwIG5naW54IFVJIHByb3h5Li4uXCInLFxuICAgICAgICAneXVtIGluc3RhbGwgLXkgbmdpbngnLFxuICAgICAgICAnJyxcbiAgICAgICAgYGNhdCA+IC9ldGMvbmdpbngvY29uZi5kL2dsaXRjaC1wcm94eS5jb25mIDw8ICdOR0lOWEVPRidgLFxuICAgICAgICAnc2VydmVyIHsnLFxuICAgICAgICAnICAgIGxpc3RlbiA4MDsnLFxuICAgICAgICAnICAgIHNlcnZlcl9uYW1lIF87JyxcbiAgICAgICAgJycsXG4gICAgICAgICcgICAgbG9jYXRpb24gLyB7JyxcbiAgICAgICAgYCAgICAgICAgcHJveHlfcGFzcyBodHRwOi8vJHt1aUJ1Y2tldE5hbWV9LnMzLXdlYnNpdGUtJHt0aGlzLnJlZ2lvbn0uYW1hem9uYXdzLmNvbTtgLFxuICAgICAgICBgICAgICAgICBwcm94eV9zZXRfaGVhZGVyIEhvc3QgJHt1aUJ1Y2tldE5hbWV9LnMzLXdlYnNpdGUtJHt0aGlzLnJlZ2lvbn0uYW1hem9uYXdzLmNvbTtgLFxuICAgICAgICAnICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtUmVhbC1JUCAkcmVtb3RlX2FkZHI7JyxcbiAgICAgICAgJyAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLUZvcndhcmRlZC1Gb3IgJHByb3h5X2FkZF94X2ZvcndhcmRlZF9mb3I7JyxcbiAgICAgICAgJyAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLUZvcndhcmRlZC1Qcm90byAkc2NoZW1lOycsXG4gICAgICAgICcgICAgfScsXG4gICAgICAgICcnLFxuICAgICAgICAnICAgIGxvY2F0aW9uIC9hcGkvIHsnLFxuICAgICAgICBgICAgICAgICBwcm94eV9wYXNzICR7Z2F0ZXdheVVybH0vYXBpLztgLFxuICAgICAgICAnICAgICAgICBwcm94eV9zZXRfaGVhZGVyIEhvc3QgJGhvc3Q7JyxcbiAgICAgICAgJyAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLVJlYWwtSVAgJHJlbW90ZV9hZGRyOycsXG4gICAgICAgICcgICAgICAgIHByb3h5X3NldF9oZWFkZXIgWC1Gb3J3YXJkZWQtRm9yICRwcm94eV9hZGRfeF9mb3J3YXJkZWRfZm9yOycsXG4gICAgICAgICcgICAgICAgIHByb3h5X3NldF9oZWFkZXIgWC1Gb3J3YXJkZWQtUHJvdG8gJHNjaGVtZTsnLFxuICAgICAgICAnICAgICAgICBwcm94eV9zc2xfc2VydmVyX25hbWUgb247JyxcbiAgICAgICAgJyAgICB9JyxcbiAgICAgICAgJycsXG4gICAgICAgICcgICAgbG9jYXRpb24gL2ludm9jYXRpb25zIHsnLFxuICAgICAgICBgICAgICAgICBwcm94eV9wYXNzICR7Z2F0ZXdheVVybH0vaW52b2NhdGlvbnM7YCxcbiAgICAgICAgJyAgICAgICAgcHJveHlfc2V0X2hlYWRlciBIb3N0ICRob3N0OycsXG4gICAgICAgICcgICAgICAgIHByb3h5X3NldF9oZWFkZXIgWC1SZWFsLUlQICRyZW1vdGVfYWRkcjsnLFxuICAgICAgICAnICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLUZvciAkcHJveHlfYWRkX3hfZm9yd2FyZGVkX2ZvcjsnLFxuICAgICAgICAnICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLVByb3RvICRzY2hlbWU7JyxcbiAgICAgICAgJyAgICAgICAgcHJveHlfc3NsX3NlcnZlcl9uYW1lIG9uOycsXG4gICAgICAgICcgICAgfScsXG4gICAgICAgICcnLFxuICAgICAgICAnICAgIGxvY2F0aW9uIC9oZWFsdGggeycsXG4gICAgICAgIGAgICAgICAgIHByb3h5X3Bhc3MgJHtnYXRld2F5VXJsfS9oZWFsdGg7YCxcbiAgICAgICAgJyAgICAgICAgcHJveHlfc2V0X2hlYWRlciBIb3N0ICRob3N0OycsXG4gICAgICAgICcgICAgICAgIHByb3h5X3NldF9oZWFkZXIgWC1SZWFsLUlQICRyZW1vdGVfYWRkcjsnLFxuICAgICAgICAnICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLUZvciAkcHJveHlfYWRkX3hfZm9yd2FyZGVkX2ZvcjsnLFxuICAgICAgICAnICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLVByb3RvICRzY2hlbWU7JyxcbiAgICAgICAgJyAgICAgICAgcHJveHlfc3NsX3NlcnZlcl9uYW1lIG9uOycsXG4gICAgICAgICcgICAgfScsXG4gICAgICAgICd9JyxcbiAgICAgICAgJ05HSU5YRU9GJyxcbiAgICAgICAgJycsXG4gICAgICAgICdybSAtZiAvZXRjL25naW54L2NvbmYuZC9kZWZhdWx0LmNvbmYnLFxuICAgICAgICAnc3lzdGVtY3RsIGVuYWJsZSBuZ2lueCcsXG4gICAgICAgICdzeXN0ZW1jdGwgc3RhcnQgbmdpbngnLFxuICAgICAgICAnJyxcbiAgICAgICAgJ2VjaG8gXCJFbmFibGluZyBUYWlsc2NhbGUgU2VydmUgZm9yIEhUVFBTLi4uXCInLFxuICAgICAgICAndGFpbHNjYWxlIHNlcnZlIC0tYmcgaHR0cDovLzEyNy4wLjAuMTo4MCcsXG4gICAgICAgICdlY2hvIFwiVGFpbHNjYWxlIFNlcnZlIGVuYWJsZWQuIFVJIGF2YWlsYWJsZSB2aWEgVGFpbHNjYWxlIEhUVFBTIFVSTC5cIidcbiAgICAgICk7XG4gICAgfVxuXG4gICAgdXNlckRhdGEuYWRkQ29tbWFuZHMoLi4udXNlckRhdGFDb21tYW5kcyk7XG5cbiAgICB0aGlzLmluc3RhbmNlID0gbmV3IGVjMi5JbnN0YW5jZSh0aGlzLCBgVGFpbHNjYWxlSW5zdGFuY2VCb290c3RyYXAke2Jvb3RzdHJhcFZlcnNpb259YCwge1xuICAgICAgdnBjLFxuICAgICAgdnBjU3VibmV0czogeyBzdWJuZXRUeXBlOiBlYzIuU3VibmV0VHlwZS5QVUJMSUMgfSxcbiAgICAgIGluc3RhbmNlVHlwZTogZWMyLkluc3RhbmNlVHlwZS5vZihlYzIuSW5zdGFuY2VDbGFzcy5UNEcsIGVjMi5JbnN0YW5jZVNpemUuTkFOTyksXG4gICAgICBtYWNoaW5lSW1hZ2U6IGVjMi5NYWNoaW5lSW1hZ2UubGF0ZXN0QW1hem9uTGludXgyMDIzKHtcbiAgICAgICAgY3B1VHlwZTogZWMyLkFtYXpvbkxpbnV4Q3B1VHlwZS5BUk1fNjQsXG4gICAgICAgIGNhY2hlZEluQ29udGV4dDogZmFsc2UsXG4gICAgICB9KSxcbiAgICAgIHNlY3VyaXR5R3JvdXA6IHRoaXMuc2VjdXJpdHlHcm91cCxcbiAgICAgIHJvbGUsXG4gICAgICB1c2VyRGF0YSxcbiAgICAgIHJlcXVpcmVJbWRzdjI6IHRydWUsXG4gICAgICBzc21TZXNzaW9uUGVybWlzc2lvbnM6IHRydWUsXG4gICAgICBhc3NvY2lhdGVQdWJsaWNJcEFkZHJlc3M6IHRydWUsXG4gICAgfSk7XG5cbiAgICBjZGsuVGFncy5vZih0aGlzLmluc3RhbmNlKS5hZGQoJ05hbWUnLCAnR2xpdGNoVGFpbHNjYWxlQ29ubmVjdG9yJyk7XG4gICAgY2RrLlRhZ3Mub2YodGhpcy5pbnN0YW5jZSkuYWRkKCdQdXJwb3NlJywgJ1RhaWxzY2FsZS1BV1MtQnJpZGdlJyk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnSW5zdGFuY2VJZCcsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmluc3RhbmNlLmluc3RhbmNlSWQsXG4gICAgICBkZXNjcmlwdGlvbjogJ1RhaWxzY2FsZSBFQzIgaW5zdGFuY2UgSUQnLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1NlY3VyaXR5R3JvdXBJZCcsIHtcbiAgICAgIHZhbHVlOiB0aGlzLnNlY3VyaXR5R3JvdXAuc2VjdXJpdHlHcm91cElkLFxuICAgICAgZGVzY3JpcHRpb246ICdUYWlsc2NhbGUgc2VjdXJpdHkgZ3JvdXAgSUQnLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1ByaXZhdGVJcCcsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmluc3RhbmNlLmluc3RhbmNlUHJpdmF0ZUlwLFxuICAgICAgZGVzY3JpcHRpb246ICdUYWlsc2NhbGUgRUMyIHByaXZhdGUgSVAnLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1B1YmxpY0lwJywge1xuICAgICAgdmFsdWU6IHRoaXMuaW5zdGFuY2UuaW5zdGFuY2VQdWJsaWNJcCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIEVDMiBwdWJsaWMgSVAnLFxuICAgIH0pO1xuXG4gICAgaWYgKGVuYWJsZVVpUHJveHkpIHtcbiAgICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdUYWlsc2NhbGVVaVVybCcsIHtcbiAgICAgICAgdmFsdWU6ICdodHRwczovL2dsaXRjaC10YWlsc2NhbGUuWU9VUl9UQUlMTkVULnRzLm5ldCcsXG4gICAgICAgIGRlc2NyaXB0aW9uOiAnR2xpdGNoIFVJIHZpYSBUYWlsc2NhbGUgU2VydmUuIFJlcGxhY2UgWU9VUl9UQUlMTkVUIHdpdGggeW91ciBUYWlsc2NhbGUgbmV0d29yayBuYW1lIChlLmcuIGZyb20gYWRtaW4udGFpbHNjYWxlLmNvbSBvciB0YWlsc2NhbGUgc3RhdHVzKS4gVXNlIG9ubHkgb24gYSBkZXZpY2Ugam9pbmVkIHRvIHRoZSBzYW1lIFRhaWxzY2FsZSBuZXR3b3JrLicsXG4gICAgICB9KTtcbiAgICB9XG4gIH1cbn1cbiJdfQ==