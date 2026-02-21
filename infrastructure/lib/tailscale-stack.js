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
        const bootstrapVersion = props.instanceBootstrapVersion ??
            this.node.tryGetContext('glitchTailscaleBootstrapVersion') ?? '5';
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
    }
}
exports.TailscaleStack = TailscaleStack;
//# sourceMappingURL=data:application/json;base64,eyJ2ZXJzaW9uIjozLCJmaWxlIjoidGFpbHNjYWxlLXN0YWNrLmpzIiwic291cmNlUm9vdCI6IiIsInNvdXJjZXMiOlsidGFpbHNjYWxlLXN0YWNrLnRzIl0sIm5hbWVzIjpbXSwibWFwcGluZ3MiOiI7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7OztBQUFBLGlEQUFtQztBQUNuQyx5REFBMkM7QUFDM0MseURBQTJDO0FBYTNDLE1BQWEsY0FBZSxTQUFRLEdBQUcsQ0FBQyxLQUFLO0lBSTNDLFlBQVksS0FBZ0IsRUFBRSxFQUFVLEVBQUUsS0FBMEI7UUFDbEUsS0FBSyxDQUFDLEtBQUssRUFBRSxFQUFFLEVBQUUsS0FBSyxDQUFDLENBQUM7UUFFeEIsTUFBTSxFQUFFLEdBQUcsRUFBRSxzQkFBc0IsRUFBRSxHQUFHLEtBQUssQ0FBQztRQUM5QyxNQUFNLGdCQUFnQixHQUFHLEtBQUssQ0FBQyx3QkFBd0I7WUFDckQsSUFBSSxDQUFDLElBQUksQ0FBQyxhQUFhLENBQUMsaUNBQWlDLENBQUMsSUFBSSxHQUFHLENBQUM7UUFFcEUsSUFBSSxDQUFDLGFBQWEsR0FBRyxJQUFJLEdBQUcsQ0FBQyxhQUFhLENBQUMsSUFBSSxFQUFFLHdCQUF3QixFQUFFO1lBQ3pFLEdBQUc7WUFDSCxXQUFXLEVBQUUsNENBQTRDO1lBQ3pELGdCQUFnQixFQUFFLEtBQUs7U0FDeEIsQ0FBQyxDQUFDO1FBRUgsSUFBSSxDQUFDLGFBQWEsQ0FBQyxhQUFhLENBQzlCLEdBQUcsQ0FBQyxJQUFJLENBQUMsT0FBTyxFQUFFLEVBQ2xCLEdBQUcsQ0FBQyxJQUFJLENBQUMsR0FBRyxDQUFDLEdBQUcsQ0FBQyxFQUNqQix3REFBd0QsQ0FDekQsQ0FBQztRQUVGLElBQUksQ0FBQyxhQUFhLENBQUMsYUFBYSxDQUM5QixHQUFHLENBQUMsSUFBSSxDQUFDLE9BQU8sRUFBRSxFQUNsQixHQUFHLENBQUMsSUFBSSxDQUFDLEdBQUcsQ0FBQyxLQUFLLENBQUMsRUFDbkIsdUNBQXVDLENBQ3hDLENBQUM7UUFFRixJQUFJLENBQUMs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Qy9CLENBQUMsQ0FBQztRQUVILEdBQUcsQ0FBQyxJQUFJLENBQUMsRUFBRSxDQUFDLElBQUksQ0FBQyxRQUFRLENBQUMsQ0FBQyxHQUFHLENBQUMsTUFBTSxFQUFFLDBCQUEwQixDQUFDLENBQUM7UUFDbkUsR0FBRyxDQUFDLElBQUksQ0FBQyxFQUFFLENBQUMsSUFBSSxDQUFDLFFBQVEsQ0FBQyxDQUFDLEdBQUcsQ0FBQyxTQUFTLEVBQUUsc0JBQXNCLENBQUMsQ0FBQztRQUVsRSxJQUFJLEdBQUcsQ0FBQyxTQUFTLENBQUMsSUFBSSxFQUFFLFlBQVksRUFBRTtZQUNwQyxLQUFLLEVBQUUsSUFBSSxDQUFDLFFBQVEsQ0FBQyxVQUFVO1lBQy9CLFdBQVcsRUFBRSwyQkFBMkI7U0FDekMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxpQkFBaUIsRUFBRTtZQUN6QyxLQUFLLEVBQUUsSUFBSSxDQUFDLGFBQWEsQ0FBQyxlQUFlO1lBQ3pDLFdBQVcsRUFBRSw2QkFBNkI7U0FDM0MsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxXQUFXLEVBQUU7WUFDbkMsS0FBSyxFQUFFLElBQUksQ0FBQyxRQUFRLENBQUMsaUJBQWlCO1lBQ3RDLFdBQVcsRUFBRSwwQkFBMEI7U0FDeEMsQ0FBQyxDQUFDO1FBRUgsSUFBSSxHQUFHLENBQUMsU0FBUyxDQUFDLElBQUksRUFBRSxVQUFVLEVBQUU7WUFDbEMsS0FBSyxFQUFFLElBQUksQ0FBQyxRQUFRLENBQUMsZ0JBQWdCO1lBQ3JDLFdBQVcsRUFBRSx5QkFBeUI7U0FDdkMsQ0FBQyxDQUFDO0lBQ0wsQ0FBQztDQUNGO0FBdklELHdDQXVJQyIsInNvdXJjZXNDb250ZW50IjpbImltcG9ydCAqIGFzIGNkayBmcm9tICdhd3MtY2RrLWxpYic7XG5pbXBvcnQgKiBhcyBlYzIgZnJvbSAnYXdzLWNkay1saWIvYXdzLWVjMic7XG5pbXBvcnQgKiBhcyBpYW0gZnJvbSAnYXdzLWNkay1saWIvYXdzLWlhbSc7XG5pbXBvcnQgKiBhcyBzZWNyZXRzbWFuYWdlciBmcm9tICdhd3MtY2RrLWxpYi9hd3Mtc2VjcmV0c21hbmFnZXInO1xuaW1wb3J0IHsgQ29uc3RydWN0IH0gZnJvbSAnY29uc3RydWN0cyc7XG5cbmV4cG9ydCBpbnRlcmZhY2UgVGFpbHNjYWxlU3RhY2tQcm9wcyBleHRlbmRzIGNkay5TdGFja1Byb3BzIHtcbiAgcmVhZG9ubHkgdnBjOiBlYzIuSVZwYztcbiAgcmVhZG9ubHkgdGFpbHNjYWxlQXV0aEtleVNlY3JldDogc2VjcmV0c21hbmFnZXIuSVNlY3JldDtcbiAgcmVhZG9ubHkgYWdlbnRDb3JlU2VjdXJpdHlHcm91cD86IGVjMi5JU2VjdXJpdHlHcm91cDtcbiAgcmVhZG9ubHkgYWdlbnRDb3JlUnVudGltZUFybj86IHN0cmluZztcbiAgLyoqIEJ1bXAgdGhpcyB0byBmb3JjZSBFQzIgaW5zdGFuY2UgcmVwbGFjZW1lbnQgKG5ldyBpbnN0YW5jZSBydW5zIHVzZXIgZGF0YSBmcm9tIHNjcmF0Y2gpLiAqL1xuICByZWFkb25seSBpbnN0YW5jZUJvb3RzdHJhcFZlcnNpb24/OiBzdHJpbmc7XG59XG5cbmV4cG9ydCBjbGFzcyBUYWlsc2NhbGVTdGFjayBleHRlbmRzIGNkay5TdGFjayB7XG4gIHB1YmxpYyByZWFkb25seSBpbnN0YW5jZTogZWMyLkluc3RhbmNlO1xuICBwdWJsaWMgcmVhZG9ubHkgc2VjdXJpdHlHcm91cDogZWMyLlNlY3VyaXR5R3JvdXA7XG5cbiAgY29uc3RydWN0b3Ioc2NvcGU6IENvbnN0cnVjdCwgaWQ6IHN0cmluZywgcHJvcHM6IFRhaWxzY2FsZVN0YWNrUHJvcHMpIHtcbiAgICBzdXBlcihzY29wZSwgaWQsIHByb3BzKTtcblxuICAgIGNvbnN0IHsgdnBjLCB0YWlsc2NhbGVBdXRoS2V5U2VjcmV0IH0gPSBwcm9wcztcbiAgICBjb25zdCBib290c3RyYXBWZXJzaW9uID0gcHJvcHMuaW5zdGFuY2VCb290c3RyYXBWZXJzaW9uID8/XG4gICAgICB0aGlzLm5vZGUudHJ5R2V0Q29udGV4dCgnZ2xpdGNoVGFpbHNjYWxlQm9vdHN0cmFwVmVyc2lvbicpID8/ICc1JztcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cCA9IG5ldyBlYzIuU2VjdXJpdHlHcm91cCh0aGlzLCAnVGFpbHNjYWxlU2VjdXJpdHlHcm91cCcsIHtcbiAgICAgIHZwYyxcbiAgICAgIGRlc2NyaXB0aW9uOiAnU2VjdXJpdHkgZ3JvdXAgZm9yIFRhaWxzY2FsZSBFQzIgY29ubmVjdG9yJyxcbiAgICAgIGFsbG93QWxsT3V0Ym91bmQ6IGZhbHNlLFxuICAgIH0pO1xuXG4gICAgdGhpcy5zZWN1cml0eUdyb3VwLmFkZEVncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC50Y3AoNDQzKSxcbiAgICAgICdIVFRQUyB0byBUYWlsc2NhbGUgY29vcmRpbmF0aW9uIHNlcnZlciBhbmQgREVSUCByZWxheXMnXG4gICAgKTtcblxuICAgIHRoaXMuc2VjdXJpdHlHcm91cC5hZGRFZ3Jlc3NSdWxlKFxuICAgICAgZWMyLlBlZXIuYW55SXB2NCgpLFxuICAgICAgZWMyLlBvcnQudWRwKDQxNjQxKSxcbiAgICAgICdXaXJlR3VhcmQgZGlyZWN0IHBlZXItdG8tcGVlciB0dW5uZWxzJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnVkcCgzNDc4KSxcbiAgICAgICdTVFVOIHByb3RvY29sIGZvciBOQVQgdHJhdmVyc2FsJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkRWdyZXNzUnVsZShcbiAgICAgIGVjMi5QZWVyLmFueUlwdjQoKSxcbiAgICAgIGVjMi5Qb3J0LnRjcCg4MCksXG4gICAgICAnSFRUUCBmYWxsYmFjayBhbmQgY2FwdGl2ZSBwb3J0YWwgZGV0ZWN0aW9uJ1xuICAgICk7XG5cbiAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICBlYzIuUGVlci5hbnlJcHY0KCksXG4gICAgICBlYzIuUG9ydC51ZHAoNDE2NDEpLFxuICAgICAgJ0FsbG93IGluYm91bmQgV2lyZUd1YXJkIGZvciBkaXJlY3QgY29ubmVjdGlvbnMnXG4gICAgKTtcblxuICAgIGlmIChwcm9wcy5hZ2VudENvcmVTZWN1cml0eUdyb3VwKSB7XG4gICAgICB0aGlzLnNlY3VyaXR5R3JvdXAuYWRkSW5ncmVzc1J1bGUoXG4gICAgICAgIHByb3BzLmFnZW50Q29yZVNlY3VyaXR5R3JvdXAsXG4gICAgICAgIGVjMi5Qb3J0LmFsbFRyYWZmaWMoKSxcbiAgICAgICAgJ0FsbG93IGFsbCB0cmFmZmljIGZyb20gQWdlbnRDb3JlIEVOSXMnXG4gICAgICApO1xuICAgIH1cblxuICAgIGNvbnN0IHJvbGUgPSBuZXcgaWFtLlJvbGUodGhpcywgJ1RhaWxzY2FsZUluc3RhbmNlUm9sZScsIHtcbiAgICAgIGFzc3VtZWRCeTogbmV3IGlhbS5TZXJ2aWNlUHJpbmNpcGFsKCdlYzIuYW1hem9uYXdzLmNvbScpLFxuICAgICAgZGVzY3JpcHRpb246ICdJQU0gcm9sZSBmb3IgVGFpbHNjYWxlIEVDMiBjb25uZWN0b3InLFxuICAgICAgbWFuYWdlZFBvbGljaWVzOiBbXG4gICAgICAgIGlhbS5NYW5hZ2VkUG9saWN5LmZyb21Bd3NNYW5hZ2VkUG9saWN5TmFtZSgnQW1hem9uU1NNTWFuYWdlZEluc3RhbmNlQ29yZScpLFxuICAgICAgXSxcbiAgICB9KTtcblxuICAgIHRhaWxzY2FsZUF1dGhLZXlTZWNyZXQuZ3JhbnRSZWFkKHJvbGUpO1xuXG4gICAgY29uc3QgdXNlckRhdGEgPSBlYzIuVXNlckRhdGEuZm9yTGludXgoKTtcbiAgICBcbiAgICBjb25zdCB1c2VyRGF0YUNvbW1hbmRzID0gW1xuICAgICAgJyMhL2Jpbi9iYXNoJyxcbiAgICAgICdzZXQgLWUnLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIkluc3RhbGxpbmcgQVdTIENMSSBhbmQgcmV0cmlldmluZyBUYWlsc2NhbGUgYXV0aCBrZXkuLi5cIicsXG4gICAgICAneXVtIGluc3RhbGwgLXkgYXdzLWNsaScsXG4gICAgICAnJyxcbiAgICAgIGBUQUlMU0NBTEVfQVVUSF9LRVk9JChhd3Mgc2VjcmV0c21hbmFnZXIgZ2V0LXNlY3JldC12YWx1ZSAtLXNlY3JldC1pZCAke3RhaWxzY2FsZUF1dGhLZXlTZWNyZXQuc2VjcmV0TmFtZX0gLS1xdWVyeSBTZWNyZXRTdHJpbmcgLS1vdXRwdXQgdGV4dCAtLXJlZ2lvbiAke3RoaXMucmVnaW9ufSlgLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIkluc3RhbGxpbmcgVGFpbHNjYWxlLi4uXCInLFxuICAgICAgJ2N1cmwgLWZzU0wgaHR0cHM6Ly90YWlsc2NhbGUuY29tL2luc3RhbGwuc2ggfCBzaCcsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiRW5hYmxpbmcgSVAgZm9yd2FyZGluZy4uLlwiJyxcbiAgICAgICdlY2hvIFwibmV0LmlwdjQuaXBfZm9yd2FyZCA9IDFcIiA+PiAvZXRjL3N5c2N0bC5jb25mJyxcbiAgICAgICdlY2hvIFwibmV0LmlwdjYuY29uZi5hbGwuZm9yd2FyZGluZyA9IDFcIiA+PiAvZXRjL3N5c2N0bC5jb25mJyxcbiAgICAgICdzeXNjdGwgLXAgL2V0Yy9zeXNjdGwuY29uZicsXG4gICAgICAnJyxcbiAgICAgICdlY2hvIFwiU3RhcnRpbmcgVGFpbHNjYWxlIHdpdGggYXV0aCBrZXkuLi5cIicsXG4gICAgICAndGFpbHNjYWxlIHVwIC0tYXV0aGtleT1cIiRUQUlMU0NBTEVfQVVUSF9LRVlcIiAtLWFkdmVydGlzZS10YWdzPXRhZzphd3MtYWdlbnQgLS1hY2NlcHQtcm91dGVzJyxcbiAgICAgICcnLFxuICAgICAgJ2VjaG8gXCJDbGVhcmluZyBhdXRoIGtleSBmcm9tIG1lbW9yeS4uLlwiJyxcbiAgICAgICd1bnNldCBUQUlMU0NBTEVfQVVUSF9LRVknLFxuICAgICAgJycsXG4gICAgICAnZWNobyBcIlRhaWxzY2FsZSBzZXR1cCBjb21wbGV0ZSFcIicsXG4gICAgICAndGFpbHNjYWxlIHN0YXR1cycsXG4gICAgXTtcblxuICAgIHVzZXJEYXRhLmFkZENvbW1hbmRzKC4uLnVzZXJEYXRhQ29tbWFuZHMpO1xuXG4gICAgdGhpcy5pbnN0YW5jZSA9IG5ldyBlYzIuSW5zdGFuY2UodGhpcywgYFRhaWxzY2FsZUluc3RhbmNlQm9vdHN0cmFwJHtib290c3RyYXBWZXJzaW9ufWAsIHtcbiAgICAgIHZwYyxcbiAgICAgIHZwY1N1Ym5ldHM6IHsgc3VibmV0VHlwZTogZWMyLlN1Ym5ldFR5cGUuUFVCTElDIH0sXG4gICAgICBpbnN0YW5jZVR5cGU6IGVjMi5JbnN0YW5jZVR5cGUub2YoZWMyLkluc3RhbmNlQ2xhc3MuVDRHLCBlYzIuSW5zdGFuY2VTaXplLk5BTk8pLFxuICAgICAgbWFjaGluZUltYWdlOiBlYzIuTWFjaGluZUltYWdlLmxhdGVzdEFtYXpvbkxpbnV4MjAyMyh7XG4gICAgICAgIGNwdVR5cGU6IGVjMi5BbWF6b25MaW51eENwdVR5cGUuQVJNXzY0LFxuICAgICAgICBjYWNoZWRJbkNvbnRleHQ6IGZhbHNlLFxuICAgICAgfSksXG4gICAgICBzZWN1cml0eUdyb3VwOiB0aGlzLnNlY3VyaXR5R3JvdXAsXG4gICAgICByb2xlLFxuICAgICAgdXNlckRhdGEsXG4gICAgICByZXF1aXJlSW1kc3YyOiB0cnVlLFxuICAgICAgc3NtU2Vzc2lvblBlcm1pc3Npb25zOiB0cnVlLFxuICAgICAgYXNzb2NpYXRlUHVibGljSXBBZGRyZXNzOiB0cnVlLFxuICAgIH0pO1xuXG4gICAgY2RrLlRhZ3Mub2YodGhpcy5pbnN0YW5jZSkuYWRkKCdOYW1lJywgJ0dsaXRjaFRhaWxzY2FsZUNvbm5lY3RvcicpO1xuICAgIGNkay5UYWdzLm9mKHRoaXMuaW5zdGFuY2UpLmFkZCgnUHVycG9zZScsICdUYWlsc2NhbGUtQVdTLUJyaWRnZScpO1xuXG4gICAgbmV3IGNkay5DZm5PdXRwdXQodGhpcywgJ0luc3RhbmNlSWQnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5pbnN0YW5jZS5pbnN0YW5jZUlkLFxuICAgICAgZGVzY3JpcHRpb246ICdUYWlsc2NhbGUgRUMyIGluc3RhbmNlIElEJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdTZWN1cml0eUdyb3VwSWQnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5zZWN1cml0eUdyb3VwLnNlY3VyaXR5R3JvdXBJZCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIHNlY3VyaXR5IGdyb3VwIElEJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdQcml2YXRlSXAnLCB7XG4gICAgICB2YWx1ZTogdGhpcy5pbnN0YW5jZS5pbnN0YW5jZVByaXZhdGVJcCxcbiAgICAgIGRlc2NyaXB0aW9uOiAnVGFpbHNjYWxlIEVDMiBwcml2YXRlIElQJyxcbiAgICB9KTtcblxuICAgIG5ldyBjZGsuQ2ZuT3V0cHV0KHRoaXMsICdQdWJsaWNJcCcsIHtcbiAgICAgIHZhbHVlOiB0aGlzLmluc3RhbmNlLmluc3RhbmNlUHVibGljSXAsXG4gICAgICBkZXNjcmlwdGlvbjogJ1RhaWxzY2FsZSBFQzIgcHVibGljIElQJyxcbiAgICB9KTtcbiAgfVxufVxuIl19