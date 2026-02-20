import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export interface TelegramWebhookStackProps extends cdk.StackProps {
  readonly telegramBotTokenSecret: secretsmanager.ISecret;
  readonly agentCoreRuntimeArn: string;
  readonly defaultExecutionRoleArn: string;
}

export class TelegramWebhookStack extends cdk.Stack {
  public readonly configTable: dynamodb.Table;
  public readonly webhookFunction: lambda.Function;
  public readonly webhookUrl: string;
  /** S3 bucket for persistent agent state (e.g. SOUL.md). Set GLITCH_SOUL_S3_BUCKET to this in runtime env. */
  public readonly soulBucket: s3.Bucket;
  /** CloudWatch Logs log group for telemetry. Set GLITCH_TELEMETRY_LOG_GROUP to this in runtime env. */
  public readonly telemetryLogGroup: logs.LogGroup;

  constructor(scope: Construct, id: string, props: TelegramWebhookStackProps) {
    super(scope, id, props);

    const { telegramBotTokenSecret, agentCoreRuntimeArn, defaultExecutionRoleArn } = props;

    // DynamoDB table for shared Telegram config
    this.configTable = new dynamodb.Table(this, 'TelegramConfigTable', {
      tableName: 'glitch-telegram-config',
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'sk', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      timeToLiveAttribute: 'ttl',
    });

    // Lambda function for webhook
    this.webhookFunction = new lambda.Function(this, 'TelegramWebhookFunction', {
      functionName: 'glitch-telegram-webhook',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromInline(this.getLambdaCode()),
      timeout: cdk.Duration.seconds(120),
      memorySize: 256,
      environment: {
        CONFIG_TABLE_NAME: this.configTable.tableName,
        TELEGRAM_SECRET_NAME: 'glitch/telegram-bot-token',
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
      },
    });

    // Grant Lambda access to DynamoDB
    this.configTable.grantReadWriteData(this.webhookFunction);

    // Grant Lambda access to Secrets Manager for bot token
    telegramBotTokenSecret.grantRead(this.webhookFunction);

    // Grant Lambda permission to invoke AgentCore Runtime (identity-based). Runtime is created by
    // agentcore deploy; resource-based policy on the runtime may also be required (see AWS docs).
    this.webhookFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'InvokeAgentCoreRuntime',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [agentCoreRuntimeArn, `${agentCoreRuntimeArn}/*`],
      })
    );

    // Note: Log group /aws/lambda/glitch-telegram-webhook is created automatically by Lambda.
    // We don't manage it in CDK to avoid conflicts with pre-existing log groups.

    // Create Function URL (public, Telegram will call this)
    const functionUrl = this.webhookFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [lambda.HttpMethod.POST],
      },
    });

    this.webhookUrl = functionUrl.url;

    // Keepalive Lambda: invokes runtime every 10 min so idleRuntimeSessionTimeout (15 min default) does not tear down the session.
    const keepaliveFunction = new lambda.Function(this, 'AgentCoreKeepaliveFunction', {
      functionName: 'glitch-agentcore-keepalive',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromInline(this.getKeepaliveLambdaCode()),
      timeout: cdk.Duration.seconds(30),
      memorySize: 128,
      environment: { AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn },
    });
    keepaliveFunction.addToRolePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: [agentCoreRuntimeArn, `${agentCoreRuntimeArn}/*`],
      })
    );
    new events.Rule(this, 'AgentCoreKeepaliveSchedule', {
      schedule: events.Schedule.rate(cdk.Duration.minutes(10)),
      targets: [new targets.LambdaFunction(keepaliveFunction)],
      description: 'Invoke AgentCore runtime keepalive every 10 min to avoid session termination',
    });

    // S3 bucket for persistent SOUL.md (personality) so Telegram and chat agents can read/write it.
    this.soulBucket = new s3.Bucket(this, 'GlitchSoulBucket', {
      bucketName: `glitch-agent-state-${cdk.Stack.of(this).account}-${cdk.Stack.of(this).region}`,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
    });
    new cdk.CfnOutput(this, 'GlitchSoulBucketName', {
      value: this.soulBucket.bucketName,
      description: 'S3 bucket for Glitch SOUL.md; set GLITCH_SOUL_S3_BUCKET to this in runtime env',
      exportName: 'GlitchSoulBucketName',
    });

    // Grant AgentCore runtime role access to DynamoDB via AwsCustomResource.
    // This bypasses CloudFormation's ResourceExistenceCheck hook which fails when
    // referencing external IAM roles not managed by this stack.
    const roleName = cdk.Arn.extractResourceName(defaultExecutionRoleArn, 'role');
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

    new cdk.custom_resources.AwsCustomResource(this, 'AgentCoreRolePolicyAttachment', {
      onCreate: {
        service: 'IAM',
        action: 'putRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: policyName,
          PolicyDocument: policyDocument,
        },
        physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(`${roleName}-${policyName}`),
      },
      onUpdate: {
        service: 'IAM',
        action: 'putRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: policyName,
          PolicyDocument: policyDocument,
        },
        physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(`${roleName}-${policyName}`),
      },
      onDelete: {
        service: 'IAM',
        action: 'deleteRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: policyName,
        },
      },
      policy: cdk.custom_resources.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['iam:PutRolePolicy', 'iam:DeleteRolePolicy'],
          resources: [defaultExecutionRoleArn],
        }),
      ]),
    });

    // Grant AgentCore runtime role permission to read webhook Lambda URL (for runtime to fetch
    // and display webhook URL; same role, same AwsCustomResource pattern).
    const lambdaWebhookPolicyName = 'GlitchLambdaWebhookRead';
    const lambdaWebhookPolicyDocument = JSON.stringify({
      Version: '2012-10-17',
      Statement: [
        {
          Sid: 'LambdaWebhookRead',
          Effect: 'Allow',
          Action: ['lambda:GetFunctionUrlConfig', 'lambda:GetFunction'],
          Resource: this.webhookFunction.functionArn,
        },
      ],
    });
    new cdk.custom_resources.AwsCustomResource(this, 'AgentCoreLambdaWebhookReadPolicy', {
      onCreate: {
        service: 'IAM',
        action: 'putRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: lambdaWebhookPolicyName,
          PolicyDocument: lambdaWebhookPolicyDocument,
        },
        physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(
          `${roleName}-${lambdaWebhookPolicyName}`
        ),
      },
      onUpdate: {
        service: 'IAM',
        action: 'putRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: lambdaWebhookPolicyName,
          PolicyDocument: lambdaWebhookPolicyDocument,
        },
        physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(
          `${roleName}-${lambdaWebhookPolicyName}`
        ),
      },
      onDelete: {
        service: 'IAM',
        action: 'deleteRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: lambdaWebhookPolicyName,
        },
      },
      policy: cdk.custom_resources.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['iam:PutRolePolicy', 'iam:DeleteRolePolicy'],
          resources: [defaultExecutionRoleArn],
        }),
      ]),
    });

    // Grant AgentCore runtime role read/write access to SOUL.md in S3 (same AwsCustomResource pattern).
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
        physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(
          `${roleName}-${soulPolicyName}`
        ),
      },
      onUpdate: {
        service: 'IAM',
        action: 'putRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: soulPolicyName,
          PolicyDocument: soulPolicyDocument,
        },
        physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(
          `${roleName}-${soulPolicyName}`
        ),
      },
      onDelete: {
        service: 'IAM',
        action: 'deleteRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: soulPolicyName,
        },
      },
      policy: cdk.custom_resources.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['iam:PutRolePolicy', 'iam:DeleteRolePolicy'],
          resources: [defaultExecutionRoleArn],
        }),
      ]),
    });

    // CloudWatch Logs log group for telemetry (per-invocation JSON events + alerts).
    // Retention: 30 days for detailed logs; use CloudWatch Metrics for longer retention.
    this.telemetryLogGroup = new logs.LogGroup(this, 'GlitchTelemetryLogGroup', {
      logGroupName: '/glitch/telemetry',
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.RETAIN,
    });
    new cdk.CfnOutput(this, 'GlitchTelemetryLogGroupName', {
      value: this.telemetryLogGroup.logGroupName,
      description: 'CloudWatch Logs group for telemetry; set GLITCH_TELEMETRY_LOG_GROUP to this in runtime env',
      exportName: 'GlitchTelemetryLogGroupName',
    });

    // Grant AgentCore runtime role permission to write telemetry to CloudWatch Logs and Metrics.
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
              StringEquals: {
                'cloudwatch:namespace': 'Glitch/Agent',
              },
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
        parameters: {
          RoleName: roleName,
          PolicyName: telemetryPolicyName,
        },
      },
      policy: cdk.custom_resources.AwsCustomResourcePolicy.fromStatements([
        new iam.PolicyStatement({
          actions: ['iam:PutRolePolicy', 'iam:DeleteRolePolicy'],
          resources: [defaultExecutionRoleArn],
        }),
      ]),
    });
  }

  private getLambdaCode(): string {
    return `
import json
import os
import logging
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from datetime import datetime, timedelta
from urllib.parse import quote

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')
session = boto3.Session()

CONFIG_TABLE_NAME = os.environ['CONFIG_TABLE_NAME']
TELEGRAM_SECRET_NAME = os.environ['TELEGRAM_SECRET_NAME']
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')

table = dynamodb.Table(CONFIG_TABLE_NAME)


def get_data_plane_endpoint(region: str) -> str:
    """Get AgentCore data plane endpoint for region."""
    return f"https://bedrock-agentcore.{region}.amazonaws.com"


def parse_runtime_arn(runtime_arn: str) -> dict:
    """Parse runtime ARN to extract region, account, and runtime ID."""
    # Format: arn:aws:bedrock-agentcore:{region}:{account}:runtime/{runtime_id}
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


def get_bot_token():
    """Get bot token from Secrets Manager."""
    response = secrets_client.get_secret_value(SecretId=TELEGRAM_SECRET_NAME)
    return response['SecretString']


def get_webhook_secret():
    """Get or create webhook secret for validation."""
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': 'webhook_secret'})
        if 'Item' in response:
            return response['Item']['value']
    except Exception as e:
        logger.warning(f"Failed to get webhook secret: {e}")
    
    import secrets
    new_secret = secrets.token_hex(32)
    table.put_item(Item={'pk': 'CONFIG', 'sk': 'webhook_secret', 'value': new_secret})
    return new_secret


def _int_or(v, default=None):
    """Coerce to int (handles DynamoDB Decimal and str)."""
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_config():
    """Get current config from DynamoDB."""
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': 'main'})
        if 'Item' in response:
            item = response['Item']
            if 'owner_id' in item:
                item = {**item, 'owner_id': _int_or(item['owner_id'], item['owner_id'])}
            return item
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
    return None


_bot_info_cache = {}


def get_bot_info(bot_token: str) -> dict:
    """Get bot username and id from Telegram getMe. Cached per cold start."""
    if bot_token in _bot_info_cache:
        return _bot_info_cache[bot_token]
    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data.get('ok') and data.get('result'):
                r = data['result']
                _bot_info_cache[bot_token] = {'username': (r.get('username') or '').lower(), 'id': r.get('id')}
                return _bot_info_cache[bot_token]
    except Exception as e:
        logger.warning(f"getMe failed: {e}")
    _bot_info_cache[bot_token] = {'username': '', 'id': None}
    return _bot_info_cache[bot_token]


def is_group_chat(chat: dict) -> bool:
    """True if chat is a group or supergroup (mention required)."""
    return (chat or {}).get('type') in ('group', 'supergroup')


def is_private_chat(chat: dict) -> bool:
    """True if chat is a private DM."""
    return (chat or {}).get('type') == 'private'


def is_bot_mentioned(message: dict, bot_username: str, bot_id) -> bool:
    """True if message explicitly mentions the bot via @username or text_mention."""
    if not bot_username and bot_id is None:
        return False
    text = (message or {}).get('text') or ''
    entities = (message or {}).get('entities') or []
    for e in entities:
        if e.get('type') == 'mention':
            mention = text[e['offset']:e['offset'] + e['length']].lstrip('@').lower()
            if mention == bot_username:
                return True
        if e.get('type') == 'text_mention':
            if e.get('user', {}).get('id') == bot_id:
                return True
    return False


def strip_bot_mention_from_text(message: dict, bot_username: str, bot_id) -> str:
    """Remove the bot mention from message text so the agent receives clean input."""
    text = (message or {}).get('text') or ''
    entities = (message or {}).get('entities') or []
    for e in sorted(entities, key=lambda x: -x.get('offset', 0)):
        if e.get('type') == 'mention':
            mention = text[e['offset']:e['offset'] + e['length']].lstrip('@').lower()
            if mention == bot_username:
                before = text[:e['offset']].strip()
                after = text[e['offset'] + e['length']:].strip()
                return ' '.join([before, after]).strip() or ''
        if e.get('type') == 'text_mention' and e.get('user', {}).get('id') == bot_id:
            before = text[:e['offset']].strip()
            after = text[e['offset'] + e['length']:].strip()
            return ' '.join([before, after]).strip() or ''
    return text.strip()


def is_user_allowed_dm(user_id, config: dict) -> bool:
    """True if user is owner or explicitly allowed to DM."""
    if not config:
        return False
    owner_id = _int_or(config.get('owner_id'))
    if owner_id is not None and owner_id == _int_or(user_id):
        return True
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': f"allowed_dm#{user_id}"})
        return 'Item' in response
    except Exception:
        return False


def allow_dm(user_id: int) -> None:
    """Grant a user permission to DM the bot (owner only)."""
    table.put_item(Item={'pk': 'CONFIG', 'sk': f"allowed_dm#{user_id}", 'user_id': user_id})
    logger.info(f"Allowed DM for user {user_id}")


def revoke_dm(user_id: int) -> None:
    """Revoke a user's permission to DM the bot (owner only)."""
    table.delete_item(Key={'pk': 'CONFIG', 'sk': f"allowed_dm#{user_id}"})
    logger.info(f"Revoked DM for user {user_id}")


def list_allowed_dm_user_ids() -> list:
    """Return list of user_ids who are allowed to DM (excluding owner)."""
    try:
        response = table.query(
            KeyConditionExpression='pk = :pk AND begins_with(sk, :sk)',
            ExpressionAttributeValues={':pk': 'CONFIG', ':sk': 'allowed_dm#'}
        )
        return [int(item['user_id']) for item in response.get('Items', []) if item.get('user_id')]
    except Exception as e:
        logger.warning(f"list_allowed_dm failed: {e}")
        return []


def set_owner(user_id: int):
    """Set owner in DynamoDB."""
    table.put_item(Item={
        'pk': 'CONFIG',
        'sk': 'main',
        'owner_id': user_id,
        'claimed_at': datetime.utcnow().isoformat() + 'Z',
        'status': 'claimed',
    })
    logger.info(f"Owner set to {user_id}")


def get_pairing_code():
    """Get or generate pairing code."""
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': 'pairing'})
        if 'Item' in response:
            item = response['Item']
            expires_at = datetime.fromisoformat(item['expires_at'].rstrip('Z'))
            if datetime.utcnow() < expires_at:
                return item['code']
    except Exception as e:
        logger.warning(f"Failed to get pairing code: {e}")
    
    import secrets
    import string
    alphabet = string.ascii_uppercase + string.digits
    code = ''.join(secrets.choice(alphabet) for _ in range(8))
    expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat() + 'Z'
    ttl = int((datetime.utcnow() + timedelta(hours=2)).timestamp())
    
    table.put_item(Item={
        'pk': 'CONFIG',
        'sk': 'pairing',
        'code': code,
        'expires_at': expires_at,
        'ttl': ttl,
    })
    logger.info(f"Generated new pairing code (expires in 1 hour)")
    return code


def validate_pairing_code(code: str, user_id: int) -> bool:
    """Validate pairing code and claim ownership."""
    config = get_config()
    if config and config.get('status') in ('claimed', 'locked'):
        logger.warning(f"Pairing rejected: already {config.get('status')}")
        return False
    
    stored_code = get_pairing_code()
    if code.upper() == stored_code:
        set_owner(user_id)
        table.delete_item(Key={'pk': 'CONFIG', 'sk': 'pairing'})
        return True
    
    logger.warning(f"Invalid pairing code from user {user_id}")
    return False


def send_telegram_message(chat_id: int, text: str, bot_token: str):
    """Send message via Telegram API."""
    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = json.dumps({'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


def metrics_to_telegram_line(metrics):
    """Format InvocationMetrics as a short Telegram line (Strands telemetry)."""
    if not metrics or not isinstance(metrics, dict):
        return None
    token = metrics.get('token_usage') or {}
    in_t = token.get('input_tokens', 0)
    out_t = token.get('output_tokens', 0)
    cache_r = token.get('cache_read_tokens', 0)
    cache_w = token.get('cache_write_tokens', 0)
    duration = metrics.get('duration_seconds', 0)
    cycles = metrics.get('cycle_count', 0)
    latency_ms = metrics.get('latency_ms', 0)
    tool_usage = metrics.get('tool_usage') or {}
    tool_names = list(tool_usage.keys())
    parts = [f"📊 {in_t} in / {out_t} out"]
    if cache_r or cache_w:
        parts.append(f"cache {cache_r}r/{cache_w}w")
    parts.append(f"{duration:.1f}s")
    if latency_ms:
        parts.append(f"{latency_ms}ms")
    if cycles and cycles > 1:
        parts.append(f"{cycles} cycles")
    if tool_names:
        parts.append(f"tools: {', '.join(tool_names)}")
    return " · ".join(parts)


def invoke_agent(prompt: str, session_id: str):
    """Invoke AgentCore Runtime via signed HTTP request. Returns full result dict or error string."""
    if not AGENTCORE_RUNTIME_ARN:
        logger.warning("AGENTCORE_RUNTIME_ARN not set; agent runtime not configured")
        return "Agent runtime not configured."
    
    arn_preview = (AGENTCORE_RUNTIME_ARN or "")[:70] + ("..." if len(AGENTCORE_RUNTIME_ARN or "") > 70 else "")
    logger.info("Invoking agent: runtime_arn=%s prompt_len=%d session_id=%s", arn_preview, len(prompt or ""), session_id)
    import urllib.request
    
    try:
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        payload = {"prompt": prompt, "session_id": session_id}
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
            logger.info("Invoke agent success: has_message=%s", bool(isinstance(result, dict) and result.get('message')))
            return result if isinstance(result, dict) else str(result)
    except Exception as e:
        is_timeout = "timed out" in str(e).lower() or "timeout" in str(e).lower()
        if is_timeout:
            logger.warning("Invoke agent failed (timeout): type=%s msg=%s", type(e).__name__, str(e)[:200])
        logger.error(f"Failed to invoke agent: {e}", exc_info=True)
        return f"Error: {e}"


def handler(event, context):
    """Lambda handler for Telegram webhook. Always returns 200 to acknowledge receipt."""
    logger.info(f"Received event: {json.dumps(event)[:500]}")
    
    try:
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {})
    except Exception as e:
        logger.error(f"Failed to parse body: {e}")
        return {'statusCode': 400, 'body': 'Invalid JSON'}
    
    headers = event.get('headers', {})
    secret_token = headers.get('x-telegram-bot-api-secret-token')
    expected_secret = get_webhook_secret()
    
    if secret_token and secret_token != expected_secret:
        logger.warning("Invalid webhook secret")
        return {'statusCode': 403, 'body': 'Forbidden'}
    
    try:
        bot_token = get_bot_token()
    except Exception as e:
        logger.error(f"Failed to get bot token: {e}", exc_info=True)
        return {'statusCode': 200, 'body': 'OK'}
    
    message = body.get('message', {})
    if not message:
        return {'statusCode': 200, 'body': 'OK'}
    
    chat_id = message.get('chat', {}).get('id')
    user_id = _int_or(message.get('from', {}).get('id'))
    text = (message.get('text') or '').strip()
    
    if not chat_id or not text:
        return {'statusCode': 200, 'body': 'OK'}
    
    logger.info(f"Message from user {user_id} in chat {chat_id}: {text[:100]}")
    
    try:
        config = get_config()
    except Exception as e:
        logger.error(f"Failed to get config: {e}", exc_info=True)
        return {'statusCode': 200, 'body': 'OK'}
    
    is_claimed = config and config.get('status') in ('claimed', 'locked')
    
    if not is_claimed:
        if validate_pairing_code(text, user_id):
            send_telegram_message(
                chat_id,
                "✅ You are now the owner of this Glitch instance!\\n\\nUse /help to see available commands.",
                bot_token
            )
        else:
            send_telegram_message(
                chat_id,
                "❌ Bot not configured. Owner must send the pairing code first.\\n\\nCheck the startup logs for the code.",
                bot_token
            )
        return {'statusCode': 200, 'body': 'OK'}
    
    if text.startswith('/'):
        cmd = text.split()[0].lower()
        owner_id = _int_or(config.get('owner_id'))
        is_owner = (user_id is not None and owner_id is not None and user_id == owner_id)
        if cmd == '/help' or cmd == '/start':
            help_text = "🤖 *Glitch Bot Commands*\\n\\n"
            help_text += "• /new - Start new conversation\\n"
            help_text += "• /status - Show bot status\\n"
            help_text += "• /help - Show this message"
            if is_owner:
                help_text += "\\n• /allow <user_id> - Allow user to DM (owner)\\n"
                help_text += "• /revoke <user_id> - Revoke DM access (owner)\\n"
                help_text += "• /allowed - List users allowed to DM (owner)"
            send_telegram_message(chat_id, help_text, bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/status':
            status_text = f"📊 *Bot Status*\\n\\nOwner: \`{owner_id}\`\\nStatus: {config.get('status', 'unknown')}"
            send_telegram_message(chat_id, status_text, bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/allow' and is_owner:
            parts = text.split()
            target_id = None
            if len(parts) >= 2 and parts[1].isdigit():
                target_id = int(parts[1])
            reply = message.get('reply_to_message')
            if reply and reply.get('from'):
                target_id = reply['from'].get('id')
            if target_id is not None:
                allow_dm(target_id)
                send_telegram_message(chat_id, f"✅ User \`{target_id}\` can now DM the bot.", bot_token)
            else:
                send_telegram_message(chat_id, "Usage: /allow <user_id> or reply to a user and send /allow", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/revoke' and is_owner:
            parts = text.split()
            target_id = None
            if len(parts) >= 2 and parts[1].isdigit():
                target_id = int(parts[1])
            reply = message.get('reply_to_message')
            if reply and reply.get('from'):
                target_id = reply['from'].get('id')
            if target_id is not None:
                revoke_dm(target_id)
                send_telegram_message(chat_id, f"Revoked DM access for user \`{target_id}\`.", bot_token)
            else:
                send_telegram_message(chat_id, "Usage: /revoke <user_id> or reply to a user and send /revoke", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/allowed' and is_owner:
            allowed = list_allowed_dm_user_ids()
            if not allowed:
                send_telegram_message(chat_id, "No additional users allowed to DM (only owner).", bot_token)
            else:
                send_telegram_message(chat_id, "Users allowed to DM: " + ", ".join(str(u) for u in allowed), bot_token)
            return {'statusCode': 200, 'body': 'OK'}
    
    chat = message.get('chat', {})
    if is_group_chat(chat):
        bot_info = get_bot_info(bot_token)
        if not is_bot_mentioned(message, bot_info.get('username'), bot_info.get('id')):
            logger.info("Group message ignored: bot not @mentioned (mention @%s to get a reply)", bot_info.get('username') or "bot")
            return {'statusCode': 200, 'body': 'OK'}
        text = strip_bot_mention_from_text(message, bot_info.get('username'), bot_info.get('id'))
        if not text:
            logger.info("Group message ignored: text empty after stripping mention")
            return {'statusCode': 200, 'body': 'OK'}
    elif is_private_chat(chat):
        if not is_user_allowed_dm(user_id, config):
            send_telegram_message(
                chat_id,
                "You are not authorized to DM this bot. Only the owner and users granted access can message here.",
                bot_token
            )
            return {'statusCode': 200, 'body': 'OK'}
    
    try:
        session_id = f"telegram-chat-{chat_id}-session-00000000"
        result = invoke_agent(text, session_id)
        if isinstance(result, dict):
            message_text = result.get('message') or result.get('response') or str(result)
            send_telegram_message(chat_id, message_text, bot_token)
        else:
            send_telegram_message(chat_id, result, bot_token)
    except Exception as e:
        logger.error(f"Error processing message: {e}", exc_info=True)
        try:
            send_telegram_message(chat_id, "Sorry, something went wrong. Please try again.", bot_token)
        except Exception:
            pass
    
    return {'statusCode': 200, 'body': 'OK'}
`;
  }

  private getKeepaliveLambdaCode(): string {
    return `
import json
import os
import urllib.request
from urllib.parse import quote
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

def get_data_plane_endpoint(region):
    return f"https://bedrock-agentcore.{region}.amazonaws.com"

def parse_runtime_arn(arn):
    parts = arn.split(':')
    if len(parts) != 6 or not (parts[5] or '').startswith('runtime/'):
        raise ValueError(f"Invalid runtime ARN: {arn}")
    return {'region': parts[3], 'account_id': parts[4], 'runtime_id': parts[5].split('/', 1)[1]}

def handler(event, context):
    arn = os.environ.get('AGENTCORE_RUNTIME_ARN', '')
    if not arn:
        return
    try:
        parts = parse_runtime_arn(arn)
        region = parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(arn, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        payload = {"prompt": "ping", "session_id": "system:keepalive"}
        body = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': 'system:keepalive'}
        session = boto3.Session()
        creds = session.get_credentials()
        if creds:
            req = AWSRequest(method='POST', url=url, data=body, headers=headers)
            SigV4Auth(creds, 'bedrock-agentcore', region).add_auth(req)
            headers = dict(req.headers)
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except Exception as e:
        import logging
        logging.getLogger().warning("Keepalive invoke failed: %s", e)
`;
  }
}
