/**
 * Telegram webhook stack: Lambda that receives Telegram updates and invokes AgentCore runtime.
 * Uses existing config table (from StorageStack). Creates webhook Lambda, Function URL, and
 * keepalive Lambda (from yesterday's template) so idleRuntimeSessionTimeout does not tear down the session.
 */
import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import type { ISecret } from 'aws-cdk-lib/aws-secretsmanager';
import { Construct } from 'constructs';

export interface TelegramWebhookStackProps extends cdk.StackProps {
  readonly configTable: dynamodb.ITable;
  readonly telegramBotTokenSecret: ISecret;
  readonly agentCoreRuntimeArn: string;
  /** Runtime role ARN so we can grant lambda:GetFunctionUrlConfig for webhook registration at startup. */
  readonly defaultExecutionRoleArn: string;
}

export class TelegramWebhookStack extends cdk.Stack {
  public readonly webhookFunction: lambda.Function;
  public readonly webhookUrl: string;

  constructor(scope: Construct, id: string, props: TelegramWebhookStackProps) {
    super(scope, id, props);

    const { configTable, telegramBotTokenSecret, agentCoreRuntimeArn, defaultExecutionRoleArn } = props;

    this.webhookFunction = new lambda.Function(this, 'TelegramWebhookFunction', {
      functionName: 'glitch-telegram-webhook',
      runtime: lambda.Runtime.PYTHON_3_12,
      handler: 'index.handler',
      code: lambda.Code.fromInline(this.getLambdaCode()),
      timeout: cdk.Duration.seconds(300),
      memorySize: 256,
      environment: {
        CONFIG_TABLE_NAME: configTable.tableName,
        TELEGRAM_SECRET_NAME: 'glitch/telegram-bot-token',
        AGENTCORE_RUNTIME_ARN: agentCoreRuntimeArn,
      },
    });

    configTable.grantReadWriteData(this.webhookFunction);
    telegramBotTokenSecret.grantRead(this.webhookFunction);

    this.webhookFunction.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'InvokeAgentCoreRuntime',
        effect: iam.Effect.ALLOW,
        actions: ['bedrock-agentcore:*'],
        resources: [
          agentCoreRuntimeArn,
          `${agentCoreRuntimeArn}/*`,
          `arn:aws:bedrock-agentcore:${this.region}:${this.account}:code-interpreter/*`,
        ],
      })
    );

    const functionUrl = this.webhookFunction.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [lambda.HttpMethod.POST],
      },
    });

    this.webhookUrl = functionUrl.url;

    // Keepalive Lambda (from template): invoke runtime every 10 min so idleRuntimeSessionTimeout does not tear down the session.
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

    new cdk.CfnOutput(this, 'TelegramWebhookUrl', {
      value: this.webhookUrl,
      description: 'Telegram webhook Lambda Function URL',
      exportName: 'GlitchTelegramWebhookUrl',
    });

    // Grant runtime role permission to read webhook URL so agent can register webhook at startup
    const roleName = cdk.Arn.extractResourceName(defaultExecutionRoleArn, 'role');
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
        physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(`${roleName}-${lambdaWebhookPolicyName}`),
      },
      onUpdate: {
        service: 'IAM',
        action: 'putRolePolicy',
        parameters: {
          RoleName: roleName,
          PolicyName: lambdaWebhookPolicyName,
          PolicyDocument: lambdaWebhookPolicyDocument,
        },
        physicalResourceId: cdk.custom_resources.PhysicalResourceId.of(`${roleName}-${lambdaWebhookPolicyName}`),
      },
      onDelete: {
        service: 'IAM',
        action: 'deleteRolePolicy',
        parameters: { RoleName: roleName, PolicyName: lambdaWebhookPolicyName },
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


def get_bot_token():
    response = secrets_client.get_secret_value(SecretId=TELEGRAM_SECRET_NAME)
    return response['SecretString']


def get_webhook_secret():
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
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def get_config():
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
    return (chat or {}).get('type') in ('group', 'supergroup')


def is_private_chat(chat: dict) -> bool:
    return (chat or {}).get('type') == 'private'


def is_bot_mentioned(message: dict, bot_username: str, bot_id) -> bool:
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
    table.put_item(Item={'pk': 'CONFIG', 'sk': f"allowed_dm#{user_id}", 'user_id': user_id})
    logger.info(f"Allowed DM for user {user_id}")


def revoke_dm(user_id: int) -> None:
    table.delete_item(Key={'pk': 'CONFIG', 'sk': f"allowed_dm#{user_id}"})
    logger.info(f"Revoked DM for user {user_id}")


def list_allowed_dm_user_ids() -> list:
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
    table.put_item(Item={
        'pk': 'CONFIG',
        'sk': 'main',
        'owner_id': user_id,
        'claimed_at': datetime.utcnow().isoformat() + 'Z',
        'status': 'claimed',
    })
    logger.info(f"Owner set to {user_id}")


def get_pairing_code():
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
    logger.info("Generated new pairing code (expires in 1 hour)")
    return code


def validate_pairing_code(code: str, user_id: int) -> bool:
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
    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = json.dumps({'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


def invoke_agent(prompt: str, session_id: str):
    if not AGENTCORE_RUNTIME_ARN:
        logger.warning("AGENTCORE_RUNTIME_ARN not set")
        return "Agent runtime not configured."
    logger.info("Invoking agent: prompt_len=%d session_id=%s", len(prompt or ""), session_id)
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
        req = urllib.request.Request(url, data=body, headers=dict(aws_request.headers), method='POST')
        with urllib.request.urlopen(req, timeout=180) as response:
            result = json.loads(response.read().decode())
            logger.info("Invoke agent success: has_message=%s", bool(isinstance(result, dict) and result.get('message')))
            return result if isinstance(result, dict) else str(result)
    except Exception as e:
        logger.error(f"Failed to invoke agent: {e}", exc_info=True)
        return f"Error: {e}"


def handler(event, context):
    logger.info("Received event: %s", json.dumps(event)[:500])
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
    logger.info("Message from user %s in chat %s: %s", user_id, chat_id, text[:100])
    try:
        config = get_config()
    except Exception as e:
        logger.error(f"Failed to get config: {e}", exc_info=True)
        return {'statusCode': 200, 'body': 'OK'}
    is_claimed = config and config.get('status') in ('claimed', 'locked')
    if not is_claimed:
        if validate_pairing_code(text, user_id):
            send_telegram_message(chat_id, "✅ You are now the owner. Use /help for commands.", bot_token)
        else:
            send_telegram_message(chat_id, "❌ Bot not configured. Send the pairing code from startup logs.", bot_token)
        return {'statusCode': 200, 'body': 'OK'}
    if text.startswith('/'):
        cmd = text.split()[0].lower()
        owner_id = _int_or(config.get('owner_id'))
        is_owner = (user_id is not None and owner_id is not None and user_id == owner_id)
        if cmd == '/help' or cmd == '/start':
            help_text = "🤖 *Glitch Bot*\\n\\n/new - New conversation\\n/status - Status\\n/help - This message"
            if is_owner:
                help_text += "\\n/allow <user_id> - Allow DM\\n/revoke <user_id> - Revoke DM\\n/allowed - List allowed"
            send_telegram_message(chat_id, help_text, bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/status':
            send_telegram_message(chat_id, "📊 Owner: \`" + str(owner_id) + "\` Status: " + config.get('status', 'unknown'), bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/allow' and is_owner:
            parts = text.split()
            target_id = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            if message.get('reply_to_message', {}).get('from'):
                target_id = message['reply_to_message']['from'].get('id')
            if target_id is not None:
                allow_dm(target_id)
                send_telegram_message(chat_id, "✅ User \`" + str(target_id) + "\` can DM.", bot_token)
            else:
                send_telegram_message(chat_id, "Usage: /allow <user_id> or reply + /allow", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/revoke' and is_owner:
            parts = text.split()
            target_id = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            if message.get('reply_to_message', {}).get('from'):
                target_id = message['reply_to_message']['from'].get('id')
            if target_id is not None:
                revoke_dm(target_id)
                send_telegram_message(chat_id, "Revoked DM for \`" + str(target_id) + "\`.", bot_token)
            else:
                send_telegram_message(chat_id, "Usage: /revoke <user_id> or reply + /revoke", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/allowed' and is_owner:
            allowed = list_allowed_dm_user_ids()
            send_telegram_message(chat_id, "Allowed to DM: " + (", ".join(str(u) for u in allowed) if allowed else "Only owner"), bot_token)
            return {'statusCode': 200, 'body': 'OK'}
    chat = message.get('chat', {})
    if is_group_chat(chat):
        bot_info = get_bot_info(bot_token)
        if not is_bot_mentioned(message, bot_info.get('username'), bot_info.get('id')):
            return {'statusCode': 200, 'body': 'OK'}
        text = strip_bot_mention_from_text(message, bot_info.get('username'), bot_info.get('id'))
        if not text:
            return {'statusCode': 200, 'body': 'OK'}
    elif is_private_chat(chat):
        if not is_user_allowed_dm(user_id, config):
            send_telegram_message(chat_id, "You are not authorized to DM this bot.", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
    try:
        # AgentCore requires session_id >= 33 chars; pad with zeros if needed
        base_session = f"telegram:dm:{chat_id}" if is_private_chat(chat) else f"telegram:group:{chat_id}"
        session_id = base_session.ljust(33, '0')
        result = invoke_agent(text, session_id)
        if isinstance(result, dict):
            message_text = result.get('message') or result.get('response') or str(result)
            send_telegram_message(chat_id, message_text, bot_token)
        else:
            send_telegram_message(chat_id, str(result), bot_token)
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
    return "https://bedrock-agentcore." + region + ".amazonaws.com"

def parse_runtime_arn(arn):
    parts = arn.split(':')
    if len(parts) != 6 or not (parts[5] or '').startswith('runtime/'):
        raise ValueError("Invalid runtime ARN: " + str(arn))
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
        url = endpoint + "/runtimes/" + encoded_arn + "/invocations"
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
