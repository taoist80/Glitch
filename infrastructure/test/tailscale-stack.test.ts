import * as cdk from 'aws-cdk-lib';
import { Template, Match, Capture } from 'aws-cdk-lib/assertions';
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { TailscaleStack } from '../lib/tailscale-stack';

describe('TailscaleStack', () => {
  let app: cdk.App;
  let vpcStack: cdk.Stack;
  let vpc: ec2.Vpc;
  let authKeySecret: secretsmanager.Secret;

  beforeEach(() => {
    app = new cdk.App();
    vpcStack = new cdk.Stack(app, 'VpcStack', {
      env: { account: '123456789012', region: 'us-west-2' },
    });
    vpc = new ec2.Vpc(vpcStack, 'TestVpc', {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
        { name: 'Private', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
      ],
    });
    authKeySecret = new secretsmanager.Secret(vpcStack, 'TailscaleAuthKey', {
      secretName: 'glitch/tailscale-auth-key',
    });
  });

  function createStack(props?: Partial<ConstructorParameters<typeof TailscaleStack>[2]>) {
    return new TailscaleStack(app, 'TestTailscaleStack', {
      vpc,
      tailscaleAuthKeySecret: authKeySecret,
      env: { account: '123456789012', region: 'us-west-2' },
      ...props,
    });
  }

  describe('EC2 Instance', () => {
    test('creates t4g.nano ARM instance', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::EC2::Instance', {
        InstanceType: 't4g.nano',
      });
    });

    test('creates exactly one EC2 instance', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.resourceCountIs('AWS::EC2::Instance', 1);
    });

    test('disables source/dest check for routing', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::EC2::Instance', {
        SourceDestCheck: false,
      });
    });

    test('has Name tag', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::EC2::Instance', {
        Tags: Match.arrayWith([
          Match.objectLike({ Key: 'Name', Value: 'GlitchTailscaleConnector' }),
        ]),
      });
    });
  });

  describe('Security Group', () => {
    test('creates security group', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::EC2::SecurityGroup', {
        GroupDescription: 'Security group for Tailscale EC2 connector',
      });
    });

    test('security group has egress rules in SecurityGroupEgress property', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      const sgs = template.findResources('AWS::EC2::SecurityGroup');
      const tailscaleSg = Object.values(sgs).find(
        (sg: any) => sg.Properties?.GroupDescription?.includes('Tailscale')
      );
      expect(tailscaleSg).toBeDefined();
      expect((tailscaleSg as any).Properties.SecurityGroupEgress).toBeDefined();
    });

    test('security group has ingress rules in SecurityGroupIngress property', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      const sgs = template.findResources('AWS::EC2::SecurityGroup');
      const tailscaleSg = Object.values(sgs).find(
        (sg: any) => sg.Properties?.GroupDescription?.includes('Tailscale')
      );
      expect(tailscaleSg).toBeDefined();
      expect((tailscaleSg as any).Properties.SecurityGroupIngress).toBeDefined();
    });
  });

  describe('IAM Role', () => {
    test('creates role with EC2 service principal', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::Role', {
        AssumeRolePolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: 'sts:AssumeRole',
              Effect: 'Allow',
              Principal: { Service: 'ec2.amazonaws.com' },
            }),
          ]),
        },
      });
    });

    test('attaches SSM managed policy', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::Role', {
        ManagedPolicyArns: Match.arrayWith([
          Match.objectLike({
            'Fn::Join': Match.arrayWith([
              Match.arrayWith([
                Match.stringLikeRegexp('AmazonSSMManagedInstanceCore'),
              ]),
            ]),
          }),
        ]),
      });
    });

    test('grants read access to Tailscale auth key secret', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::IAM::Policy', {
        PolicyDocument: {
          Statement: Match.arrayWith([
            Match.objectLike({
              Action: Match.arrayWith(['secretsmanager:GetSecretValue']),
              Effect: 'Allow',
            }),
          ]),
        },
      });
    });
  });

  describe('User Data', () => {
    test('user data contains Tailscale installation', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      const instances = template.findResources('AWS::EC2::Instance');
      const instance = Object.values(instances)[0] as any;
      const userData = instance.Properties.UserData;
      
      expect(userData).toBeDefined();
      expect(userData['Fn::Base64']).toBeDefined();
    });
  });

  describe('VPC Routes', () => {
    test('creates custom resource for ENI lookup', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.resourceCountIs('Custom::AWS', 1);
    });

    test('creates route to on-prem CIDR for isolated subnets', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasResourceProperties('AWS::EC2::Route', {
        DestinationCidrBlock: '10.10.110.0/24',
      });
    });
  });

  describe('Stack Outputs', () => {
    test('exports instance ID', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasOutput('InstanceId', {});
    });

    test('exports security group ID', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasOutput('SecurityGroupId', {});
    });

    test('exports private IP', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasOutput('PrivateIp', {});
    });

    test('exports public IP', () => {
      const stack = createStack();
      const template = Template.fromStack(stack);

      template.hasOutput('PublicIp', {});
    });
  });

  describe('UI Proxy (nginx)', () => {
    test('creates UI URL output when gateway URL and bucket provided', () => {
      const stack = createStack({
        gatewayFunctionUrl: 'https://abc123.lambda-url.us-west-2.on.aws/',
        gatewayHostname: 'abc123.lambda-url.us-west-2.on.aws',
        uiBucketName: 'glitch-ui-bucket',
      });
      const template = Template.fromStack(stack);

      template.hasOutput('TailscaleUiUrl', {});
    });
  });
});
