import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

export interface StorageStackProps extends cdk.StackProps {
  readonly defaultExecutionRoleArn?: string;
}

/**
 * Storage stack that imports existing resources created outside CDK.
 * Resources were created manually or by a previous stack and are now adopted.
 */
export class GlitchStorageStack extends cdk.Stack {
  public readonly configTable: dynamodb.ITable;
  public readonly soulBucket: s3.IBucket;
  public readonly telemetryLogGroup: logs.ILogGroup;

  constructor(scope: Construct, id: string, props: StorageStackProps) {
    super(scope, id, props);

    const { defaultExecutionRoleArn } = props;
    
    // Only attach policies to execution role if ARN is provided
    const shouldAttachRolePolicies = !!defaultExecutionRoleArn;
    const roleName = defaultExecutionRoleArn ? cdk.Arn.extractResourceName(defaultExecutionRoleArn, 'role') : '';

    const tableName = 'glitch-telegram-config';
    const bucketName = `glitch-agent-state-${this.account}-${this.region}`;
    const logGroupName = '/glitch/telemetry';

    this.configTable = dynamodb.Table.fromTableName(this, 'ConfigTable', tableName);

    this.soulBucket = s3.Bucket.fromBucketName(this, 'GlitchSoulBucket', bucketName);

    // SSM parameters: create if missing, no-op if exists (upsert pattern not supported,
    // so we build ARNs directly for the IAM policy instead of importing)
    const ssmParamNames = [
      '/glitch/soul/s3-bucket',
      '/glitch/soul/s3-key',
      '/glitch/soul/poet-soul-s3-key',
    ];
    const ssmParamArns = ssmParamNames.map(
      (name) => `arn:aws:ssm:${this.region}:${this.account}:parameter${name}`
    );

    this.telemetryLogGroup = logs.LogGroup.fromLogGroupName(
      this,
      'GlitchTelemetryLogGroup',
      logGroupName
    );

    const policyName = 'GlitchTelegramConfigAccess';
    const policyDocument = JSON.stringify({
      Version: '2012-10-17',
      Statement: [
        {
          Sid: 'TelegramConfigTableAccess',
          Effect: 'Allow',
          Action: [
            'dynamodb:GetItem',
            'dynamodb:PutItem',
            'dynamodb:UpdateItem',
            'dynamodb:DeleteItem',
            'dynamodb:Query',
          ],
          Resource: this.configTable.tableArn,
        },
      ],
    });
    
    // Only attach policies to execution role if ARN is provided (avoids circular dependency)
    if (shouldAttachRolePolicies && defaultExecutionRoleArn) {
      new cdk.custom_resources.AwsCustomResource(this, 'AgentCoreRolePolicyAttachment', {
        onCreate: {
          service: 'IAM',
          action: 'putRolePolicy',
          parameters: { RoleName: roleName, PolicyName: policyName, PolicyDocument: policyDocument },
          physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(`${roleName}-${policyName}`),
        },
        onUpdate: {
          service: 'IAM',
          action: 'putRolePolicy',
          parameters: { RoleName: roleName, PolicyName: policyName, PolicyDocument: policyDocument },
          physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(`${roleName}-${policyName}`),
        },
        onDelete: {
          service: 'IAM',
          action: 'deleteRolePolicy',
          parameters: { RoleName: roleName, PolicyName: policyName },
        },
        policy: cdk.custom_resources.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({
            actions: ['iam:PutRolePolicy', 'iam:DeleteRolePolicy'],
            resources: [defaultExecutionRoleArn],
          }),
        ]),
      });

      const soulPolicyName = 'GlitchSoulS3Access';
      const soulBucketObjectsArn = this.soulBucket.arnForObjects('*');
      const soulPolicyDocument = cdk.Fn.sub(
        JSON.stringify({
          Version: '2012-10-17',
          Statement: [
            {
              Sid: 'SoulS3Access',
              Effect: 'Allow',
              Action: ['s3:GetObject', 's3:PutObject'],
              Resource: ['${SoulBucketObjectsArn}'],
            },
          ],
        }),
        { SoulBucketObjectsArn: soulBucketObjectsArn }
      );
      new cdk.custom_resources.AwsCustomResource(this, 'AgentCoreSoulS3Policy', {
        onCreate: {
          service: 'IAM',
          action: 'putRolePolicy',
          parameters: {
            RoleName: roleName,
            PolicyName: soulPolicyName,
            PolicyDocument: soulPolicyDocument,
          },
          physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(`${roleName}-${soulPolicyName}`),
        },
        onUpdate: {
          service: 'IAM',
          action: 'putRolePolicy',
          parameters: {
            RoleName: roleName,
            PolicyName: soulPolicyName,
            PolicyDocument: soulPolicyDocument,
          },
          physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(`${roleName}-${soulPolicyName}`),
        },
        onDelete: {
          service: 'IAM',
          action: 'deleteRolePolicy',
          parameters: { RoleName: roleName, PolicyName: soulPolicyName },
        },
        policy: cdk.custom_resources.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({
            actions: ['iam:PutRolePolicy', 'iam:DeleteRolePolicy'],
            resources: [defaultExecutionRoleArn],
          }),
        ]),
      });

      const soulSsmPolicyName = 'GlitchSoulSsmRead';
      const soulSsmPolicyDocument = JSON.stringify({
        Version: '2012-10-17',
        Statement: [
          {
            Sid: 'SoulSsmRead',
            Effect: 'Allow',
            Action: ['ssm:GetParameter', 'ssm:GetParameters'],
            Resource: ssmParamArns,
          },
        ],
      });
      new cdk.custom_resources.AwsCustomResource(this, 'AgentCoreSoulSsmPolicy', {
        onCreate: {
          service: 'IAM',
          action: 'putRolePolicy',
          parameters: {
            RoleName: roleName,
            PolicyName: soulSsmPolicyName,
            PolicyDocument: soulSsmPolicyDocument,
          },
          physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(
            `${roleName}-${soulSsmPolicyName}`
          ),
        },
        onUpdate: {
          service: 'IAM',
          action: 'putRolePolicy',
          parameters: {
            RoleName: roleName,
            PolicyName: soulSsmPolicyName,
            PolicyDocument: soulSsmPolicyDocument,
          },
          physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(
            `${roleName}-${soulSsmPolicyName}`
          ),
        },
        onDelete: {
          service: 'IAM',
          action: 'deleteRolePolicy',
          parameters: { RoleName: roleName, PolicyName: soulSsmPolicyName },
        },
        policy: cdk.custom_resources.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({
            actions: ['iam:PutRolePolicy', 'iam:DeleteRolePolicy'],
            resources: [defaultExecutionRoleArn],
          }),
        ]),
      });

      const telemetryPolicyName = 'GlitchTelemetryAccess';
      const telemetryPolicyDocument = cdk.Fn.sub(
        JSON.stringify({
          Version: '2012-10-17',
          Statement: [
            {
              Sid: 'CloudWatchLogsWrite',
              Effect: 'Allow',
              Action: [
                'logs:CreateLogStream',
                'logs:PutLogEvents',
                'logs:DescribeLogStreams',
              ],
              Resource: ['${LogGroupArn}', '${LogGroupArn}:*'],
            },
            {
              Sid: 'CloudWatchMetricsWrite',
              Effect: 'Allow',
              Action: ['cloudwatch:PutMetricData'],
              Resource: '*',
              Condition: {
                StringEquals: { 'cloudwatch:namespace': 'Glitch/Agent' },
              },
            },
          ],
        }),
        { LogGroupArn: this.telemetryLogGroup.logGroupArn }
      );
      new cdk.custom_resources.AwsCustomResource(this, 'AgentCoreTelemetryPolicy', {
        onCreate: {
          service: 'IAM',
          action: 'putRolePolicy',
          parameters: {
            RoleName: roleName,
            PolicyName: telemetryPolicyName,
            PolicyDocument: telemetryPolicyDocument,
          },
          physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(
            `${roleName}-${telemetryPolicyName}`
          ),
        },
        onUpdate: {
          service: 'IAM',
          action: 'putRolePolicy',
          parameters: {
            RoleName: roleName,
            PolicyName: telemetryPolicyName,
            PolicyDocument: telemetryPolicyDocument,
          },
          physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(
            `${roleName}-${telemetryPolicyName}`
          ),
        },
        onDelete: {
          service: 'IAM',
          action: 'deleteRolePolicy',
          parameters: { RoleName: roleName, PolicyName: telemetryPolicyName },
        },
        policy: cdk.custom_resources.AwsCustomResourcePolicy.fromStatements([
          new iam.PolicyStatement({
            actions: ['iam:PutRolePolicy', 'iam:DeleteRolePolicy'],
            resources: [defaultExecutionRoleArn],
          }),
        ]),
      });
    }

    new cdk.CfnOutput(this, 'GlitchSoulBucketName', {
      value: this.soulBucket.bucketName,
      description: 'S3 bucket for Glitch SOUL.md',
      exportName: 'GlitchSoulBucketName',
    });
    new cdk.CfnOutput(this, 'GlitchTelemetryLogGroupName', {
      value: this.telemetryLogGroup.logGroupName,
      description: 'CloudWatch Logs group for telemetry',
      exportName: 'GlitchTelemetryLogGroupName',
    });
  }
}
