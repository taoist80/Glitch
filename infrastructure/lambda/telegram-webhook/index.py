# v3 - diagnostic logging, case-insensitive header lookup, cold-start webhook registration via SSM
import json
import os
import logging
import random
import boto3
from datetime import datetime, timedelta

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
secrets_client = boto3.client('secretsmanager')
lambda_client = boto3.client('lambda')

CONFIG_TABLE_NAME = os.environ['CONFIG_TABLE_NAME']
TELEGRAM_SECRET_NAME = os.environ['TELEGRAM_SECRET_NAME']
PROCESSOR_FUNCTION_NAME = os.environ.get('PROCESSOR_FUNCTION_NAME', '')
MODE_DEFAULT = "default"
MODE_POET = "poet"
MODE_ROLEPLAY = "roleplay"

table = dynamodb.Table(CONFIG_TABLE_NAME)


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


def build_session_id(chat: dict) -> str:
    chat_id = (chat or {}).get('id')
    base_session = (
        f"telegram:dm:{chat_id}"
        if is_private_chat(chat)
        else f"telegram:group:{chat_id}"
    )
    return base_session.ljust(33, '0')


def get_session_mode(session_id: str) -> str:
    """Load persisted session mode from DynamoDB, defaulting to standard mode."""
    try:
        response = table.get_item(Key={'pk': 'SESSION_AGENT', 'sk': session_id})
        if 'Item' in response:
            return response['Item'].get('mode_id') or MODE_DEFAULT
    except Exception as e:
        logger.warning("Failed to read session mode for %s: %s", session_id, e)
    return MODE_DEFAULT


def set_session_mode(session_id: str, mode_id: str) -> bool:
    """Persist mode selection; preserve existing session agent if present."""
    try:
        response = table.get_item(Key={'pk': 'SESSION_AGENT', 'sk': session_id})
        current_item = response.get('Item', {})
        table.put_item(Item={
            'pk': 'SESSION_AGENT',
            'sk': session_id,
            'agent_id': current_item.get('agent_id') or 'glitch',
            'mode_id': mode_id,
        })
        logger.info("Persisted session mode: session_id=%s mode_id=%s", session_id, mode_id)
        return True
    except Exception as e:
        logger.error("Failed to persist session mode: session_id=%s mode_id=%s err=%s", session_id, mode_id, e)
        return False


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


def get_current_webhook_url(bot_token: str) -> str:
    """Return the URL currently registered with Telegram, or '' on error."""
    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            if data.get('ok'):
                return (data.get('result') or {}).get('url') or ''
    except Exception as e:
        logger.warning("getWebhookInfo failed: %s", e)
    return ''


def ensure_webhook_registered(bot_token: str, webhook_url: str, webhook_secret: str) -> bool:
    """Register webhook with Telegram if not already set to webhook_url.

    Called on Lambda cold start. The Lambda has internet egress; the AgentCore
    runtime does not (PRIVATE_ISOLATED subnets), so registration must happen here.
    """
    import urllib.request
    current = get_current_webhook_url(bot_token)
    if current.rstrip('/') == webhook_url.rstrip('/'):
        logger.info("Telegram webhook already registered: %s", webhook_url)
        return True
    logger.info("Registering Telegram webhook: current=%r target=%r", current, webhook_url)
    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        'url': webhook_url,
        'secret_token': webhook_secret,
        'allowed_updates': ['message', 'edited_message', 'callback_query'],
        'drop_pending_updates': True,
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            if result.get('ok'):
                logger.info("Telegram webhook registered successfully: %s", webhook_url)
                return True
            logger.error("setWebhook failed: %s", result)
            return False
    except Exception as e:
        logger.error("setWebhook error: %s", e)
        return False


def get_own_function_url() -> str:
    """Derive this Lambda's own Function URL from SSM (written by CDK at deploy time).

    Cannot be injected as a CFN env var (circular dependency: URL depends on the
    function, function env depends on URL). Instead we read the SSM parameter that
    CDK writes after the Function URL is created — no circular dependency because
    SSM is a separate resource that depends on FunctionUrl, not the other way around.
    """
    region = os.environ.get('AWS_REGION', 'us-west-2')
    ssm_param = '/glitch/telegram/webhook-url'
    try:
        ssm = boto3.client('ssm', region_name=region)
        resp = ssm.get_parameter(Name=ssm_param)
        return resp['Parameter']['Value'].rstrip('/')
    except Exception as e:
        logger.warning("get_own_function_url via SSM failed: %s", e)
    return ''


# Register webhook on cold start (Lambda has internet; runtime does not).
def _cold_start_register_webhook():
    try:
        webhook_url = get_own_function_url()
        if not webhook_url:
            logger.warning("Could not resolve own Function URL from SSM; skipping cold-start webhook registration")
            return
        bot_token = get_bot_token()
        webhook_secret = get_webhook_secret()
        ensure_webhook_registered(bot_token, webhook_url, webhook_secret)
    except Exception as e:
        logger.warning("Cold-start webhook registration failed: %s", e)

_cold_start_register_webhook()


def claim_update(update_id) -> bool:
    """Atomically mark an update_id as processing. Returns True if this invocation owns it.

    Telegram retries the webhook if no 200 is received within 60s, but invoke_agent()
    can take up to 280s. Without deduplication the same message gets processed 5+ times.
    Uses a conditional DynamoDB put: if the item already exists the put fails and we
    drop the duplicate silently.
    """
    import time
    ttl = int(time.time()) + 86400  # 24h TTL
    try:
        table.put_item(
            Item={'pk': 'UPDATE', 'sk': str(update_id), 'ttl': ttl},
            ConditionExpression='attribute_not_exists(pk)',
        )
        return True
    except dynamodb.meta.client.exceptions.ConditionalCheckFailedException:
        logger.info("Telegram webhook: duplicate update_id=%s — skipping", update_id)
        return False
    except Exception as e:
        # On any other DynamoDB error, allow processing (fail open)
        logger.warning("Telegram webhook: claim_update error update_id=%s: %s", update_id, e)
        return True


def _headers_get(headers: dict, key: str, default=None):
    """Get header value case-insensitively (Lambda Function URL may normalize casing)."""
    if not headers:
        return default
    key_lower = key.lower()
    for k, v in headers.items():
        if (k or '').lower() == key_lower:
            return v
    return default


def handler(event, context):
    try:
        if isinstance(event.get('body'), str):
            body = json.loads(event['body'])
        else:
            body = event.get('body', {}) or {}
    except Exception as e:
        logger.error("Telegram webhook: Failed to parse body: %s", e)
        return {'statusCode': 400, 'body': 'Invalid JSON'}
    update_id = body.get('update_id', '?')
    logger.info("Telegram webhook received update_id=%s keys=%s", update_id, list(body.keys()))
    headers = event.get('headers', {}) or {}
    secret_token = _headers_get(headers, 'x-telegram-bot-api-secret-token')
    expected_secret = get_webhook_secret()
    if secret_token and secret_token != expected_secret:
        logger.warning("Telegram webhook: Invalid secret token, rejecting update_id=%s", update_id)
        return {'statusCode': 403, 'body': 'Forbidden'}
    try:
        bot_token = get_bot_token()
    except Exception as e:
        logger.error("Telegram webhook: Failed to get bot token: %s", e, exc_info=True)
        return {'statusCode': 200, 'body': 'OK'}
    message = body.get('message', {})
    if not message:
        logger.info("Telegram webhook: update_id=%s has no message (e.g. channel_post), ack", update_id)
        return {'statusCode': 200, 'body': 'OK'}
    chat_id = message.get('chat', {}).get('id')
    user_id = _int_or(message.get('from', {}).get('id'))
    text = (message.get('text') or '').strip()
    if not chat_id or not text:
        logger.info("Telegram webhook: update_id=%s chat_id=%s empty text, ack", update_id, chat_id)
        return {'statusCode': 200, 'body': 'OK'}
    chat = message.get('chat', {})
    # In group chats, strip the bot @mention early so commands like "@Bot /auri" are recognized.
    if is_group_chat(chat):
        bot_info_early = get_bot_info(bot_token)
        text = strip_bot_mention_from_text(message, bot_info_early.get('username'), bot_info_early.get('id')) or text
    logger.info("Telegram webhook: message from user_id=%s chat_id=%s text=%s", user_id, chat_id, text[:80])
    try:
        config = get_config()
    except Exception as e:
        logger.error("Telegram webhook: failed to get config: %s", e, exc_info=True)
        return {'statusCode': 200, 'body': 'OK'}
    is_claimed = config and config.get('status') in ('claimed', 'locked')
    if not is_claimed:
        logger.info("Telegram webhook: bot not claimed (update_id=%s user_id=%s); user must /pair with code", update_id, user_id)
        if validate_pairing_code(text, user_id):
            send_telegram_message(chat_id, "\u2705 You are now the owner. Use /help for commands.", bot_token)
        else:
            send_telegram_message(chat_id, "\u274c Bot not configured. Send the pairing code from startup logs.", bot_token)
        return {'statusCode': 200, 'body': 'OK'}
    if text.startswith('/'):
        first_token = text.split()[0].lower()
        cmd = first_token.split('@', 1)[0]
        owner_id = _int_or(config.get('owner_id'))
        is_owner = (user_id is not None and owner_id is not None and user_id == owner_id)
        session_id = build_session_id(chat)
        if cmd == '/help' or cmd == '/start':
            help_text = (
                "\U0001f916 *Glitch Bot*\n\n"
                "/new - New conversation\n"
                "/status - Status\n"
                "/auri - Switch to Auri roleplay mode\n"
                "/default - Switch to default mode\n"
                "/help - This message"
            )
            if is_owner:
                help_text += "\n/allow <user_id> - Allow DM\n/revoke <user_id> - Revoke DM\n/allowed - List allowed"
            send_telegram_message(chat_id, help_text, bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/status':
            send_telegram_message(chat_id, "\U0001f4ca Owner: `" + str(owner_id) + "` Status: " + config.get('status', 'unknown'), bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/allow' and is_owner:
            parts = text.split()
            target_id = int(parts[1]) if len(parts) >= 2 and parts[1].isdigit() else None
            if message.get('reply_to_message', {}).get('from'):
                target_id = message['reply_to_message']['from'].get('id')
            if target_id is not None:
                allow_dm(target_id)
                send_telegram_message(chat_id, "\u2705 User `" + str(target_id) + "` can DM.", bot_token)
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
                send_telegram_message(chat_id, "Revoked DM for `" + str(target_id) + "`.", bot_token)
            else:
                send_telegram_message(chat_id, "Usage: /revoke <user_id> or reply + /revoke", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/allowed' and is_owner:
            allowed = list_allowed_dm_user_ids()
            send_telegram_message(chat_id, "Allowed to DM: " + (", ".join(str(u) for u in allowed) if allowed else "Only owner"), bot_token)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/haltprotect' and is_owner:
            if not claim_update(update_id):
                return {'statusCode': 200, 'body': 'OK'}
            if not PROCESSOR_FUNCTION_NAME:
                send_telegram_message(chat_id, "⚠️ Processor not configured.", bot_token)
                return {'statusCode': 200, 'body': 'OK'}
            lambda_client.invoke(
                FunctionName=PROCESSOR_FUNCTION_NAME,
                InvocationType='Event',
                Payload=json.dumps({
                    'chat_id': chat_id,
                    'text': '__system:halt_protect',
                    'session_id': session_id,
                    'mode_id': 'default',
                    'update_id': update_id,
                }).encode(),
            )
            logger.info("haltprotect: dispatched to processor session_id=%s", session_id)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd == '/stop' and is_owner:
            if not claim_update(update_id):
                return {'statusCode': 200, 'body': 'OK'}
            if not PROCESSOR_FUNCTION_NAME:
                send_telegram_message(chat_id, "⚠️ Processor not configured.", bot_token)
                return {'statusCode': 200, 'body': 'OK'}
            lambda_client.invoke(
                FunctionName=PROCESSOR_FUNCTION_NAME,
                InvocationType='Event',
                Payload=json.dumps({
                    'chat_id': chat_id,
                    'text': '__system:shutdown',
                    'session_id': session_id,
                    'mode_id': 'default',
                    'update_id': update_id,
                }).encode(),
            )
            logger.info("stop: dispatched shutdown to processor session_id=%s", session_id)
            return {'statusCode': 200, 'body': 'OK'}
        elif cmd in ('/auri', '/default', '/normal', '/poet'):
            mode_map = {
                '/auri': MODE_ROLEPLAY,
                '/poet': MODE_POET,
                '/default': MODE_DEFAULT,
                '/normal': MODE_DEFAULT,
            }
            mode_id = mode_map[cmd]
            if not set_session_mode(session_id, mode_id):
                send_telegram_message(chat_id, "⚠️ Failed to switch mode right now. Try again.", bot_token)
                return {'statusCode': 200, 'body': 'OK'}

            # Support one-shot command prompts, e.g. "/auri hello there".
            parts = text.split(maxsplit=1)
            if len(parts) >= 2 and parts[1].strip():
                text = parts[1].strip()
            else:
                # In-character reply so it feels like Auri/Poet took over, not Glitch announcing a switch
                if mode_id == MODE_ROLEPLAY:
                    auri_ack = random.choice([
                        "Hey. Auri's here — whenever you're ready.",
                        "Mm, I'm here. What do you need?",
                        "Auri's got you. Say when.",
                    ])
                    send_telegram_message(chat_id, auri_ack, bot_token)
                elif mode_id == MODE_POET:
                    send_telegram_message(chat_id, "Poet mode. Words at the ready.", bot_token)
                else:
                    send_telegram_message(chat_id, "✅ Switched to default mode.", bot_token)
                return {'statusCode': 200, 'body': 'OK'}
    session_id = build_session_id(chat)
    if is_group_chat(chat):
        bot_info = get_bot_info(bot_token)
        mode_id = get_session_mode(session_id)
        # In Auri (roleplay) mode, respond to all group messages without requiring @mention
        if mode_id != MODE_ROLEPLAY and not is_bot_mentioned(message, bot_info.get('username'), bot_info.get('id')):
            logger.info("Telegram webhook: group chat but bot not mentioned, ack update_id=%s", update_id)
            return {'statusCode': 200, 'body': 'OK'}
        text = strip_bot_mention_from_text(message, bot_info.get('username'), bot_info.get('id'))
        if not text:
            logger.info("Telegram webhook: group mention only, no text, ack update_id=%s", update_id)
            return {'statusCode': 200, 'body': 'OK'}
        # Prepend sender name so Auri can tell speakers apart in group conversation history
        from_user = message.get('from', {}) or {}
        sender_first = (from_user.get('first_name') or from_user.get('username') or '').strip().split()[0]
        if sender_first:
            text = f"[{sender_first}]: {text}"
    elif is_private_chat(chat):
        if not is_user_allowed_dm(user_id, config):
            logger.info("Telegram webhook: user_id=%s not allowed to DM, ack update_id=%s", user_id, update_id)
            send_telegram_message(chat_id, "You are not authorized to DM this bot.", bot_token)
            return {'statusCode': 200, 'body': 'OK'}
    if not claim_update(update_id):
        return {'statusCode': 200, 'body': 'OK'}
    mode_id = get_session_mode(session_id)
    if not PROCESSOR_FUNCTION_NAME:
        logger.error("Telegram webhook: PROCESSOR_FUNCTION_NAME not set update_id=%s", update_id)
        return {'statusCode': 200, 'body': 'OK'}
    # Extract sender name for participant profile loading (Auri memory)
    from_user = message.get('from', {}) or {}
    sender_first = (from_user.get('first_name') or from_user.get('username') or '').strip().split()[0]
    participant_id = sender_first.lower() if sender_first else ''

    try:
        lambda_client.invoke(
            FunctionName=PROCESSOR_FUNCTION_NAME,
            InvocationType='Event',  # async — returns immediately, processor runs independently
            Payload=json.dumps({
                'chat_id': chat_id,
                'text': text,
                'session_id': session_id,
                'mode_id': mode_id,
                'update_id': update_id,
                'participant_id': participant_id,
            }).encode(),
        )
        logger.info(
            "Telegram webhook: dispatched to processor update_id=%s session_id=%s mode_id=%s",
            update_id,
            session_id,
            mode_id,
        )
    except Exception as e:
        logger.error("Telegram webhook: failed to dispatch to processor update_id=%s: %s", update_id, e)
    return {'statusCode': 200, 'body': 'OK'}
