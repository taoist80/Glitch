import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as iam from 'aws-cdk-lib/aws-iam';
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
      timeout: cdk.Duration.seconds(30),
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


def get_config():
    """Get current config from DynamoDB."""
    try:
        response = table.get_item(Key={'pk': 'CONFIG', 'sk': 'main'})
        if 'Item' in response:
            return response['Item']
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
    return None


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


def invoke_agent(prompt: str, session_id: str) -> str:
    """Invoke AgentCore Runtime via signed HTTP request."""
    if not AGENTCORE_RUNTIME_ARN:
        return "Agent runtime not configured."
    
    import urllib.request
    
    try:
        # Parse ARN to get region and runtime ID
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        
        # Build data plane URL
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        
        # Prepare request body
        payload = {"prompt": prompt, "session_id": session_id}
        body = json.dumps(payload).encode('utf-8')
        
        # Create AWS request for signing
        headers = {
            'Content-Type': 'application/json',
            'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
        }
        
        aws_request = AWSRequest(method='POST', url=url, data=body, headers=headers)
        
        # Sign with SigV4
        credentials = session.get_credentials()
        if credentials:
            SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
        
        # Make the request
        req = urllib.request.Request(
            url,
            data=body,
            headers=dict(aws_request.headers),
            method='POST'
        )
        
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.loads(response.read().decode())
            if isinstance(result, dict):
                return result.get('response', result.get('message', str(result)))
            return str(result)
            
    except Exception as e:
        logger.error(f"Failed to invoke agent: {e}", exc_info=True)
        return f"Error: {e}"


def handler(event, context):
    """Lambda handler for Telegram webhook."""
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
    
    bot_token = get_bot_token()
    
    message = body.get('message', {})
    if not message:
        return {'statusCode': 200, 'body': 'OK'}
    
    chat_id = message.get('chat', {}).get('id')
    user_id = message.get('from', {}).get('id')
    text = message.get('text', '')
    
    if not chat_id or not text:
        return {'statusCode': 200, 'body': 'OK'}
    
    logger.info(f"Message from user {user_id} in chat {chat_id}: {text[:100]}")
    
    config = get_config()
    is_claimed = config and config.get('status') in ('claimed', 'locked')
    
    if not is_claimed:
        if validate_pairing_code(text.strip(), user_id):
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
        if cmd == '/help' or cmd == '/start':
            help_text = "🤖 *Glitch Bot Commands*\\n\\n"
            help_text += "• /new - Start new conversation\\n"
            help_text += "• /status - Show bot status\\n"
            help_text += "• /help - Show this message"
            send_telegram_message(chat_id, help_text, bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/status':
            owner_id = config.get('owner_id', 'Unknown')
            status_text = f"📊 *Bot Status*\\n\\nOwner: \`{owner_id}\`\\nStatus: {config.get('status', 'unknown')}"
            send_telegram_message(chat_id, status_text, bot_token)
            return {'statusCode': 200, 'body': 'OK'}
    
    session_id = f"telegram-chat-{chat_id}-session-00000000"
    response_text = invoke_agent(text, session_id)
    send_telegram_message(chat_id, response_text, bot_token)
    
    return {'statusCode': 200, 'body': 'OK'}
`;
  }
}
