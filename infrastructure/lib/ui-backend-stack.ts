import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';
import * as path from 'path';

export interface UiBackendStackProps extends cdk.StackProps {
  readonly agentCoreRuntimeArn: string;
  readonly configTable: dynamodb.ITable;
}

export class UiBackendStack extends cdk.Stack {
  public readonly uiBackendFunction: lambda.Function;
  public readonly functionUrl: string;

  constructor(scope: Construct, id: string, props: UiBackendStackProps) {
    super(scope, id, props);

    const { agentCoreRuntimeArn, configTable } = props;

    this.uiBackendFunction = new lambda.Function(this, 'UiBackendFunction', {
      functionName: 'glitch-ui-backend',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../lambda/ui-backend')),
      timeout: cdk.Duration.seconds(120),
      memorySize: 512,
      environment: {
        CONFIG_TABLE_NAME: configTable.tableName,
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
      },
    });

    configTable.grantReadWriteData(this.uiBackendFunction);

    this.uiBackendFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'InvokeAgentCoreRuntime',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [agentCoreRuntimeArn, `${agentCoreRuntimeArn}/*`],
      })
    );

    this.uiBackendFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'CodeInterpreterAccess',
        effect: iam.Effect.ALLOW,
        actions: [
          'bedrock-agentcore:CreateCodeInterpreter',
          'bedrock-agentcore:StartCodeInterpreterSession',
          'bedrock-agentcore:InvokeCodeInterpreter',
          'bedrock-agentcore:StopCodeInterpreterSession',
          'bedrock-agentcore:DeleteCodeInterpreter',
          'bedrock-agentcore:ListCodeInterpreters',
          'bedrock-agentcore:GetCodeInterpreter',
          'bedrock-agentcore:GetCodeInterpreterSession',
          'bedrock-agentcore:ListCodeInterpreterSessions',
        ],
        resources: [`arn:aws:bedrock-agentcore:${this.region}:${this.account}:code-interpreter/*`],
      })
    );

    const fnUrl = this.uiBackendFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [
          lambda.HttpMethod.GET,
          lambda.HttpMethod.POST,
          lambda.HttpMethod.OPTIONS,
        ],
        allowedHeaders: ['Content-Type', 'X-Client-Id', 'X-Session-Id'],
        maxAge: cdk.Duration.hours(1),
      },
    });

    this.functionUrl = fnUrl.url;

    const keepaliveRule = new events.Rule(this, 'UiBackendKeepaliveRule', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(5)),
      description: 'Keep UI backend Lambda warm to reduce cold starts',
    });
    keepaliveRule.addTarget(new targets.LambdaFunction(this.uiBackendFunction, {
      event: events.RuleTargetInput.fromObject({ path: '/health', method: 'GET' }),
    }));

    new cdk.CfnOutput(this, 'UiBackendFunctionUrl', {
      value: this.functionUrl,
      description: 'UI Backend Lambda Function URL',
      exportName: 'GlitchUiBackendUrl',
    });
  }
}
