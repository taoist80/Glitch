/**
 * Glitch Gateway stack: Lambda Function URL for UI invocations, /api/* proxy, and keepalive.
 * Future: Telegram webhook could be consolidated into this gateway (single Lambda for UI + webhook).
 */
import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

export interface GlitchGatewayStackProps extends cdk.StackProps {
  readonly agentCoreRuntimeArn: string;
  readonly configTable: dynamodb.ITable;
}

export class GlitchGatewayStack extends cdk.Stack {
  public readonly gatewayFunction: lambda.Function;
  public readonly functionUrl: string;

  constructor(scope: Construct, id: string, props: GlitchGatewayStackProps) {
    super(scope, id, props);

    const { agentCoreRuntimeArn, configTable } = props;

    this.gatewayFunction = new lambda.Function(this, 'GatewayFunction', {
      functionName: 'glitch-gateway',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromInline(this.getLambdaCode()),
      timeout: cdk.Duration.seconds(120),
      memorySize: 512,
      environment: {
        CONFIG_TABLE_NAME: configTable.tableName,
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
      },
    });

    configTable.grantReadWriteData(this.gatewayFunction);

    this.gatewayFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'InvokeAgentCoreRuntime',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [agentCoreRuntimeArn, `${agentCoreRuntimeArn}/*`],
      })
    );

    this.gatewayFunction.addToRolePolicy(
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

    const fnUrl = this.gatewayFunction.addFunctionUrl({
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

    const keepaliveRule = new events.Rule(this, 'GatewayKeepaliveRule', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(5)),
      description: 'Keep gateway Lambda warm to reduce cold starts',
    });
    keepaliveRule.addTarget(new targets.LambdaFunction(this.gatewayFunction, {
      event: events.RuleTargetInput.fromObject({ path: '/health', method: 'GET' }),
    }));

    new cdk.CfnOutput(this, 'GatewayFunctionUrl', {
      value: this.functionUrl,
      description: 'Gateway Lambda Function URL',
      exportName: 'GlitchGatewayUrl',
    });
  }

  private getLambdaCode(): string {
    return `
import json
import os
import logging
import boto3
import uuid
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from urllib.parse import quote
from decimal import Decimal

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
session = boto3.Session()

CONFIG_TABLE_NAME = os.environ['CONFIG_TABLE_NAME']
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')

table = dynamodb.Table(CONFIG_TABLE_NAME)


def get_data_plane_endpoint(region: str) -> str:
    return f"https://bedrock-agentcore.{region}.amazonaws.com"


def parse_runtime_arn(runtime_arn: str) -> dict:
    parts = runtime_arn.split(':')
    if len(parts) != 6:
        raise ValueError(f"Invalid runtime ARN: {runtime_arn}")
    resource = parts[5]
    if not resource.startswith('runtime/'):
        raise ValueError(f"Invalid runtime ARN resource: {resource}")
    return {
        'region': parts[3],
        'account_id': parts[4],
        'runtime_id': resource.split('/', 1)[1],
    }


def get_or_create_session(client_id: str) -> str:
    """Get existing session_id for client or create new one."""
    try:
        response = table.get_item(Key={'pk': f'UI_SESSION#{client_id}', 'sk': 'session'})
        if 'Item' in response:
            return response['Item']['session_id']
    except Exception as e:
        logger.warning(f"Failed to get session: {e}")
    
    session_id = f"ui-{client_id}-{uuid.uuid4().hex[:8]}"
    try:
        table.put_item(Item={
            'pk': f'UI_SESSION#{client_id}',
            'sk': 'session',
            'session_id': session_id,
            'created_at': str(int(__import__('time').time())),
        })
    except Exception as e:
        logger.warning(f"Failed to save session: {e}")
    
    return session_id


def invoke_agent(prompt: str, session_id: str, stream: bool = False) -> dict:
    """Invoke AgentCore Runtime via signed HTTP request."""
    if not AGENTCORE_RUNTIME_ARN:
        return {"error": "Agent runtime not configured"}
    
    import urllib.request
    
    try:
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        payload = {"prompt": prompt, "session_id": session_id}
        if stream:
            payload["stream"] = True
        body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
        }
        aws_request = AWSRequest(method='POST', url=url, data=body, headers=headers)
        credentials = session.get_credentials()
        if credentials:
            SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
        req = urllib.request.Request(
            url, data=body, headers=dict(aws_request.headers), method='POST'
        )
        with urllib.request.urlopen(req, timeout=90) as response:
            result = json.loads(response.read().decode())
            return result if isinstance(result, dict) else {"message": str(result)}
    except Exception as e:
        logger.error(f"Failed to invoke agent: {e}", exc_info=True)
        return {"error": str(e)}


def invoke_api(path: str, method: str, body: dict, session_id: str) -> dict:
    """Invoke AgentCore Runtime with _ui_api_request payload."""
    if not AGENTCORE_RUNTIME_ARN:
        return {"error": "Agent runtime not configured"}
    
    import urllib.request
    
    try:
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        payload = {
            "_ui_api_request": {
                "path": path,
                "method": method,
                "body": body,
            }
        }
        req_body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
        }
        aws_request = AWSRequest(method='POST', url=url, data=req_body, headers=headers)
        credentials = session.get_credentials()
        if credentials:
            SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
        req = urllib.request.Request(
            url, data=req_body, headers=dict(aws_request.headers), method='POST'
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode())
            return result if isinstance(result, dict) else {"data": result}
    except Exception as e:
        logger.error(f"Failed to invoke API: {e}", exc_info=True)
        return {"error": str(e)}


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj) if obj % 1 else int(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def handler(event, context):
    """Lambda handler for gateway. Routes requests to AgentCore Runtime."""
    logger.info(f"Received event: {json.dumps(event)[:500]}")
    
    # Handle CloudWatch Events keepalive
    if event.get('source') == 'aws.events':
        return {'statusCode': 200, 'body': json.dumps({'status': 'healthy'})}
    
    # Parse request
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')
    path = event.get('rawPath', '/')
    headers = event.get('headers', {})
    
    # Get or create client session
    client_id = headers.get('x-client-id') or headers.get('X-Client-Id') or 'anonymous'
    session_id = get_or_create_session(client_id)
    
    # Parse body
    body = {}
    if event.get('body'):
        try:
            raw_body = event['body']
            if event.get('isBase64Encoded'):
                import base64
                raw_body = base64.b64decode(raw_body).decode('utf-8')
            body = json.loads(raw_body)
        except Exception as e:
            logger.warning(f"Failed to parse body: {e}")
    
    # Route requests
    response_body = {}
    status_code = 200
    
    try:
        # Health check
        if path == '/health' or path == '/':
            response_body = {'status': 'healthy', 'session_id': session_id}
        
        # Chat invocation
        elif path == '/invocations' and http_method == 'POST':
            prompt = body.get('prompt', '')
            stream = body.get('stream', False)
            if not prompt:
                response_body = {'error': 'No prompt provided'}
                status_code = 400
            else:
                response_body = invoke_agent(prompt, session_id, stream=stream)
        
        # API proxy routes
        elif path.startswith('/api/'):
            api_path = path[4:]  # Remove /api prefix
            response_body = invoke_api(api_path, http_method, body, session_id)
        
        else:
            response_body = {'error': f'Unknown path: {path}'}
            status_code = 404
    
    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        response_body = {'error': str(e)}
        status_code = 500
    
    return {
        'statusCode': status_code,
        'headers': {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Headers': 'Content-Type, X-Client-Id, X-Session-Id',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
        },
        'body': json.dumps(response_body, default=decimal_default),
    }
`;
  }
}
