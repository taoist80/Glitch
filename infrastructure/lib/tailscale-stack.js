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
        const { vpc, tailscaleAuthKeySecret } = props;
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
        userData.addCommands('#!/bin/bash', 'set -e', '', 'echo "Installing AWS CLI and retrieving Tailscale auth key..."', 'yum install -y aws-cli', '', `TAILSCALE_AUTH_KEY=$(aws secretsmanager get-secret-value --secret-id ${tailscaleAuthKeySecret.secretName} --query SecretString --output text --region ${this.region})`, '', 'echo "Installing Tailscale..."', 'curl -fsSL https://tailscale.com/install.sh | sh', '', 'echo "Enabling IP forwarding..."', 'echo "net.ipv4.ip_forward = 1" >> /etc/sysctl.conf', 'echo "net.ipv6.conf.all.forwarding = 1" >> /etc/sysctl.conf', 'sysctl -p /etc/sysctl.conf', '', 'echo "Starting Tailscale with auth key..."', 'tailscale up --authkey="$TAILSCALE_AUTH_KEY" --advertise-tags=tag:aws-agent --accept-routes', '', 'echo "Clearing auth key from memory..."', 'unset TAILSCALE_AUTH_KEY', '', 'echo "Tailscale setup complete!"', 'tailscale status');
        this.instance = new ec2.Instance(this, 'TailscaleInstance', {
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
            exportName: 'GlitchTailscaleInstanceId',
        });
        new cdk.CfnOutput(this, 'SecurityGroupId', {
            value: this.securityGroup.securityGroupId,
            description: 'Tailscale security group ID',
            exportName: 'GlitchTailscaleSecurityGroupId',
        });
        new cdk.CfnOutput(this, 'PrivateIp', {
            value: this.instance.instancePrivateIp,
            description: 'Tailscale EC2 private IP',
            exportName: 'GlitchTailscalePrivateIp',
        });
        new cdk.CfnOutput(this, 'PublicIp', {
            value: this.instance.instancePublicIp,
            description: 'Tailscale EC2 public IP',
            exportName: 'GlitchTailscalePublicIp',
        });
    }
}
exports.TailscaleStack = TailscaleStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidGFpbHNjYWxlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsidGFpbHNjYWxlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBVTNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxHQUFHLEtBQUssQ0FBQztRQUU5QyxJQUFJLENBQUMsYUFBYSxHQUFHLElBQUksR0FBRyxDQUFDLGFBQWEsQ0FBQyxJQUFJLEVBQUUsd0JBQXdCLEVBQUU7WUFDekUsR0FBRztZQUNILFdBQVcsRUFBRSw0Q0FBNEM7WUFDekQsZ0JBQWdCLEVBQUUsS0FBSztTQUN4QixDQUFDLENBQUM7UUFFSCxJQUFJLENBQUMsYUFBYSxDQUFDLGFBQWEsQ0FDOUIsR0FBRyxDQUFDLElBQUksQ0FBQyxPQUFPLEVBQUUsRUFDbEIsR0FBRyxDQUFDLElBQUksQ0FBQyxHQUFHLENBQUMsR0FBRyxDQUFDLEVBQ2pCLHdEQUF3RCxDQUN6RCxDQUFDO1FBRUYsSUFBSSxDQUFDLGFBQWEsQ0FBQyxhQUFhLENBQzlCLEdBQUcsQ0FBQyxJQUFJLENBQUMsT0FBTyxFQUFFLEVBQ2xCLEdBQUcsQ0FBQyxJQUFJLENBQUMsR0FBRyxDQUFDLEtBQUssQ0FBQyxFQUNuQix1Q0FBdUMsQ0FDeEMsQ0FBQztRQUVGLElBQUksQ0FBQyxhQUFhLENBQUMsYUFBYSxDQUM5QixHQUFHLENBQUMsSUFBSSxDQUFDLE9BQU8sRUFBRSxFQUNsQixHQUFHLENBQUMsSUFBSSxDQUFDLEdBQUcsQ0FBQyxJQUFJLENBQUMsRUFDbEIs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QyxDQUFDLEdBQUcsQ0FBQyxTQUFTLEVBQUUsc0JBQXNCLENBQUMsQ0FBQztRQUVsRSxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLFlBQVksRUFBRTtZQUNwQyxLQUFLLEVBQUUsSUFBSSxDQUFDLFFBQVEsQ0FBQyxVQUFVO1lBQy9CLFdBQVcsRUFBRSwyQkFBMkI7WUFDeEMsVUFBVSxFQUFFLDJCQUEyQjtTQUN4QyxDQUFDLENBQUM7UUFFSCxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLGlCQUFpQixFQUFFO1lBQ3pDLEtBQUssRUFBRSxJQUFJLENBQUMsYUFBYSxDQUFDLGVBQWU7WUFDekMsV0FBVyxFQUFFLDZCQUE2QjtZQUMxQyxVQUFVLEVBQUUsZ0NBQWdDO1NBQzdDLENBQUMsQ0FBQztRQUVILElBQUksR0FBRyxDQUFDLFNBQVMsQ0FBQyxJQUFJLEVBQUUsV0FBVyxFQUFFO1lBQ25DLEtBQUssRUFBRSxJQUFJLENBQUMsUUFBUSxDQUFDLGlCQUFpQjtZQUN0QyxXQUFXLEVBQUUsMEJBQTBCO1lBQ3ZDLFVBQVUsRUFBRSwwQkFBMEI7U0FDdkMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxVQUFVLEVBQUU7WUFDbEMsS0FBSyxFQUFFLElBQUksQ0FBQyxRQUFRLENBQUMsZ0JBQWdCO1lBQ3JDLFdBQVcsRUFBRSx5QkFBeUI7WUFDdEMsVUFBVSxFQUFFLHlCQUF5QjtTQUN0QyxDQUFDLENBQUM7SUFDTCxDQUFDO0NBQ0Y7QUF0SUQsd0NBc0lDIiwic291cmNlc0NvbnRlbnQiOlsiaW1wb3J0ICogYXMgY2RrIGZyb20gJ2F3cy1jZGstbGliJztcbmltcG9ydCAqIGFzIGVjMiBmcm9tICdhd3MtY2RrLWxpYi9hd3MtZWMyJztcbmltcG9ydCAqIGFzIGlhbSBmcm9tICdhd3MtY2RrLWxpYi9hd3MtaWFtJztcbmltcG9ydCAqIGFzIHNlY3JldHNtYW5hZ2VyIGZyb20gJ2F3cy1jZGstbGliL2F3cy1zZWNyZXRzbWFuYWdlcic7XG5pbXBvcnQgeyBDb25zdHJ1Y3QgfSBmcm9tICdjb25zdHJ1Y3RzJztcblxuZXhwb3J0IGludGVyZmFjZSBUYWlsc2NhbGVTdGFja1Byb3BzIGV4dGVuZHMgY2RrLlN0YWNrUHJvcHMge1xuICByZWFkb25seSB2cGM6IGVjMi5JVnBjO1xuICByZWFkb25seSB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0OiBzZWNyZXRzbWFuYWdlci5JU2VjcmV0O1xuICByZWFkb25seSBhZ2VudENvcmVTZWN1cml0eUdyb3VwPzogZWMyLklTZWN1cml0eUdyb3VwO1xufVxuXG5leHBvcnQgY2xhc3MgVGFpbHNjYWxlU3RhY2sgZXh0ZW5kcyBjZGsuU3RhY2sge1xuICBwdWJsaWMgcmVhZG9ubHkgaW5zdGFuY2U6IGVjMi5JbnN0YW5jZTtcbiAgcHVibGljIHJlYWRvbmx5IHNlY3VyaXR5R3JvdXA6IGVjMi5TZWN1cml0eUdyb3VwO1xuXG4gIGNvbnN0cnVjdG9yKHNjb3BlOiBDb25zdHJ1Y3QsIGlkOiBzdHJpbmcsIHByb3BzOiBUYWlsc2NhbGVTdGFja1Byb3BzKSB7XG4gICAgc3VwZXIoc2NvcGUsIGlkLCBwcm9wcyk7XG5cbiAgICBjb25zdCB7IHZwYywgdGFpbHNjYWxlQXV0aEtleVNlY3JldCB9ID0gcHJvcHM7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAgPSBuZXcgZWMyLlNlY3VyaXR5R3JvdXAodGhpcywgJ1RhaWxzY2FsZVNlY3VyaXR5R3JvdXAnLCB7XG4gICAgICB2cGMsXG4gICAgICBkZXNjcmlwdGlvbjogJ1NlY3VyaXR5IGdyb3VwIGZvciBUYWlsc2NhbGUgRUMyIGNvbm5lY3RvcicsXG4gICAgICBhbGxvd0FsbE91dGJvdW5kOiBmYWxzZSxcbiAgICB9KTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudGNwKDQ0MyksXG4gICAgICAnSFRUUFMgdG8gVGFpbHNjYWxlIGNvb3JkaW5hdGlvbiBzZXJ2ZXIgYW5kIERFUlAgcmVsYXlzJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnVkcCg0MTY0MSksXG4gICAgICAnV2lyZUd1YXJkIGRpcmVjdCBwZWVyLXRvLXBlZXIgdHVubmVscydcbiAgICApO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC51ZHAoMzQ3OCksXG4gICAgICAnU1RVTiBwcm90b2NvbCBmb3IgTkFUIHRyYXZlcnNhbCdcbiAgICApO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC50Y3AoODApLFxuICAgICAgJ0hUVFAgZmFsbGJhY2sgYW5kIGNhcHRpdmUgcG9ydGFsIGRldGVjdGlvbidcbiAgICApO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEluZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudWRwKDQxNjQxKSxcbiAgICAgICdBbGxvdyBpbmJvdW5kIFdpcmVHdWFyZCBmb3IgZGlyZWN0IGNvbm5lY3Rpb25zJ1xuICAgICk7XG5cbiAgICBpZiAocHJvcHMuYWdlbnRDb3JlU2VjdXJpdHlHcm91cCkge1xuICAgICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEluZ3Jlc3NSdWxlKFxuICAgICAgICBwcm9wcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwLFxuICAgICAgICBlYzIuUG9ydC5hbGxUcmFmZmljKCksXG4gICAgICAgICdBbGxvdyBhbGwgdHJhZmZpYyBmcm9tIEFnZW50Q29yZSBFTklzJ1xuICAgICAgKTtcbiAgICB9XG5cbiAgICBjb25zdCByb2xlID0gbmV3IGlhbS5Sb2xlKHRoaXMsICdUYWlsc2NhbGVJbnN0YW5jZVJvbGUnLCB7XG4gICAgICBhc3N1bWVkQnk6IG5ldyBpYW0uU2VydmljZVByaW5jaXBhbCgnZWMyLmFtYXpvbmF3cy5jb20nKSxcbiAgICAgIGRlc2NyaXB0aW9uOiAnSUFNIHJvbGUgZm9yIFRhaWxzY2FsZSBFQzIgY29ubmVjdG9yJyxcbiAgICAgIG1hbmFnZWRQb2xpY2llczogW1xuICAgICAgICBpYW0uTWFuYWdlZFBvbGljeS5mcm9tQXdzTWFuYWdlZFBvbGljeU5hbWUoJ0FtYXpvblNTTU1hbmFnZWRJbnN0YW5jZUNvcmUnKSxcbiAgICAgIF0sXG4gICAgfSk7XG5cbiAgICB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0LmdyYW50UmVhZChyb2xlKTtcblxuICAgIGNvbnN0IHVzZXJEYXRhID0gZWMyLlVzZXJEYXRhLmZvckxpbnV4KCk7XG4gICAgdXNlckRhdGEuYWRkQ29tbWFuZHMoXG4gICAgICAnIyEvYmluL2Jhc2gnLFxuICAgICAgJ3NldCAtZScsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiSW5zdGFsbGluZyBBV1MgQ0xJIGFuZCByZXRyaWV2aW5nIFRhaWxzY2FsZSBhdXRoIGtleS4uLlwiJyxcbiAgICAgICd5dW0gaW5zdGFsbCAteSBhd3MtY2xpJyxcbiAgICAgICcnLFxuICAgICAgYFRBSUxTQ0FMRV9BVVRIX0tFWT0kKGF3cyBzZWNyZXRzbWFuYWdlciBnZXQtc2VjcmV0LXZhbHVlIC0tc2VjcmV0LWlkICR7dGFpbHNjYWxlQXV0aEtleVNlY3JldC5zZWNyZXROYW1lfSAtLXF1ZXJ5IFNlY3JldFN0cmluZyAtLW91dHB1dCB0ZXh0IC0tcmVnaW9uICR7dGhpcy5yZWdpb259KWAsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiSW5zdGFsbGluZyBUYWlsc2NhbGUuLi5cIicsXG4gICAgICAnY3VybCAtZnNTTCBodHRwczovL3RhaWxzY2FsZS5jb20vaW5zdGFsbC5zaCB8IHNoJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJFbmFibGluZyBJUCBmb3J3YXJkaW5nLi4uXCInLFxuICAgICAgJ2VjaG8gXCJuZXQuaXB2NC5pcF9mb3J3YXJkID0gMVwiID4+IC9ldGMvc3lzY3RsLmNvbmYnLFxuICAgICAgJ2VjaG8gXCJuZXQuaXB2Ni5jb25mLmFsbC5mb3J3YXJkaW5nID0gMVwiID4+IC9ldGMvc3lzY3RsLmNvbmYnLFxuICAgICAgJ3N5c2N0bCAtcCAvZXRjL3N5c2N0bC5jb25mJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJTdGFydGluZyBUYWlsc2NhbGUgd2l0aCBhdXRoIGtleS4uLlwiJyxcbiAgICAgICd0YWlsc2NhbGUgdXAgLS1hdXRoa2V5PVwiJFRBSUxTQ0FMRV9BVVRIX0tFWVwiIC0tYWR2ZXJ0aXNlLXRhZ3M9dGFnOmF3cy1hZ2VudCAtLWFjY2VwdC1yb3V0ZXMnLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIkNsZWFyaW5nIGF1dGgga2V5IGZyb20gbWVtb3J5Li4uXCInLFxuICAgICAgJ3Vuc2V0IFRBSUxTQ0FMRV9BVVRIX0tFWScsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiVGFpbHNjYWxlIHNldHVwIGNvbXBsZXRlIVwiJyxcbiAgICAgICd0YWlsc2NhbGUgc3RhdHVzJ1xuICAgICk7XG5cbiAgICB0aGlzLmluc3RhbmNlID0gbmV3IGVjMi5JbnN0YW5jZSh0aGlzLCAnVGFpbHNjYWxlSW5zdGFuY2UnLCB7XG4gICAgICB2cGMsXG4gICAgICB2cGNTdWJuZXRzOiB7IHN1Ym5ldFR5cGU6IGVjMi5TdWJuZXRUeXBlLlBVQkxJQyB9LFxuICAgICAgaW5zdGFuY2VUeXBlOiBlYzIuSW5zdGFuY2VUeXBlLm9mKGVjMi5JbnN0YW5jZUNsYXNzLlQ0RywgZWMyLkluc3RhbmNlU2l6ZS5OQU5PKSxcbiAgICAgIG1hY2hpbmVJbWFnZTogZWMyLk1hY2hpbmVJbWFnZS5sYXRlc3RBbWF6b25MaW51eDIwMjMoe1xuICAgICAgICBjcHVUeXBlOiBlYzIuQW1hem9uTGludXhDcHVUeXBlLkFSTV82NCxcbiAgICAgICAgY2FjaGVkSW5Db250ZXh0OiBmYWxzZSxcbiAgICAgIH0pLFxuICAgICAgc2VjdXJpdHlHcm91cDogdGhpcy5zZWN1cml0eUdyb3VwLFxuICAgICAgcm9sZSxcbiAgICAgIHVzZXJEYXRhLFxuICAgICAgcmVxdWlyZUltZHN2MjogdHJ1ZSxcbiAgICAgIHNzbVNlc3Npb25QZXJtaXNzaW9uczogdHJ1ZSxcbiAgICAgIGFzc29jaWF0ZVB1YmxpY0lwQWRkcmVzczogdHJ1ZSxcbiAgICB9KTtcblxuICAgIGNkay5UYWdzLm9mKHRoaXMuaW5zdGFuY2UpLmFkZCgnTmFtZScsICdHbGl0Y2hUYWlsc2NhbGVDb25uZWN0b3InKTtcbiAgICBjZGsuVGFncy5vZih0aGlzLmluc3RhbmNlKS5hZGQoJ1B1cnBvc2UnLCAnVGFpbHNjYWxlLUFXUy1CcmlkZ2UnKTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdJbnN0YW5jZUlkJywge1xuICAgICAgdmFsdWU6IHRoaXMuaW5zdGFuY2UuaW5zdGFuY2VJZCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIEVDMiBpbnN0YW5jZSBJRCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoVGFpbHNjYWxlSW5zdGFuY2VJZCcsXG4gICAgfSk7XG5cbiAgICBuZXcgY2RrLkNmbk91dHB1dCh0aGlzLCAnU2VjdXJpdHlHcm91cElkJywge1xuICAgICAgdmFsdWU6IHRoaXMuc2VjdXJpdHlHcm91cC5zZWN1cml0eUdyb3VwSWQsXG4gICAgICBkZXNjcmlwdGlvbjogJ1RhaWxzY2FsZSBzZWN1cml0eSBncm91cCBJRCcsXG4gICAgICBleHBvcnROYW1lOiAnR2xpdGNoVGFpbHNjYWxlU2VjdXJpdHlHcm91cElkJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdQcml2YXRlSXAnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5pbnN0YW5jZS5pbnN0YW5jZVByaXZhdGVJcCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIEVDMiBwcml2YXRlIElQJyxcbiAgICAgIGV4cG9ydE5hbWU6ICdHbGl0Y2hUYWlsc2NhbGVQcml2YXRlSXAnLFxuICAgIH0pO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ1B1YmxpY0lwJywge1xuICAgICAgdmFsdWU6IHRoaXMuaW5zdGFuY2UuaW5zdGFuY2VQdWJsaWNJcCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIEVDMiBwdWJsaWMgSVAnLFxuICAgICAgZXhwb3J0TmFtZTogJ0dsaXRjaFRhaWxzY2FsZVB1YmxpY0lwJyxcbiAgICB9KTtcbiAgfVxufVxuIl19