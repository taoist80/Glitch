"""Telegram Processor Lambda — async agent invocation and Telegram reply.

Invoked asynchronously (InvocationType=Event) by the telegram-webhook Lambda
after update_id deduplication. Calling the agent here means the webhook can
return HTTP 200 to Telegram immediately, preventing Telegram's retry storm.

Event schema:
    {
        "chat_id": int,
        "text": str,
        "session_id": str,
        "update_id": int | str,
    }
"""
import json
import logging
import os

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from urllib.parse import quote

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets_client = boto3.client('secretsmanager')
_boto_session = boto3.Session()

TELEGRAM_SECRET_NAME = os.environ['TELEGRAM_SECRET_NAME']
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')


def _get_data_plane_endpoint(region: str) -> str:
    return f"https://bedrock-agentcore.{region}.amazonaws.com"


def _parse_runtime_arn(runtime_arn: str) -> dict:
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


def _get_bot_token() -> str:
    response = secrets_client.get_secret_value(SecretId=TELEGRAM_SECRET_NAME)
    return response['SecretString']


def _send_telegram_message(chat_id: int, text: str, bot_token: str) -> None:
    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = json.dumps({'chat_id': chat_id, 'text': text, 'parse_mode': 'Markdown'}).encode()
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logger.error("Failed to send Telegram message to chat_id=%s: %s", chat_id, e)


def _invoke_agent(prompt: str, session_id: str):
    if not AGENTCORE_RUNTIME_ARN:
        logger.warning("AGENTCORE_RUNTIME_ARN not set")
        return "Agent runtime not configured."
    logger.info("Invoking agent: prompt_len=%d session_id=%s runtime_arn=%s",
                len(prompt or ""), session_id, AGENTCORE_RUNTIME_ARN[:60])
    import urllib.request
    arn_parts = _parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
    region = arn_parts['region']
    endpoint = _get_data_plane_endpoint(region)
    encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
    url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
    payload = {"prompt": prompt, "session_id": session_id, "agent_id": "glitch"}
    body = json.dumps(payload).encode('utf-8')
    headers = {
        'Content-Type': 'application/json',
        'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
    }
    aws_request = AWSRequest(method='POST', url=url, data=body, headers=headers)
    credentials = _boto_session.get_credentials()
    if credentials:
        SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
    req = urllib.request.Request(url, data=body, headers=dict(aws_request.headers), method='POST')
    with urllib.request.urlopen(req, timeout=280) as response:
        result = json.loads(response.read().decode())
        logger.info("Invoke agent success: has_message=%s",
                    bool(isinstance(result, dict) and result.get('message')))
        return result if isinstance(result, dict) else str(result)


def handler(event, context):
    chat_id = event['chat_id']
    text = event['text']
    session_id = event['session_id']
    update_id = event.get('update_id', '?')

    logger.info("Processor: update_id=%s session_id=%s text_len=%s",
                update_id, session_id, len(text))

    try:
        bot_token = _get_bot_token()
    except Exception as e:
        logger.error("Processor: failed to get bot token update_id=%s: %s", update_id, e)
        return

    try:
        result = _invoke_agent(text, session_id)
        if isinstance(result, dict):
            if result.get('error'):
                logger.warning("Processor: agent error update_id=%s: %s", update_id, result['error'])
                _send_telegram_message(chat_id, "Sorry, I couldn't process that request. Please try again.", bot_token)
            else:
                message_text = result.get('message') or result.get('response') or str(result)
                _send_telegram_message(chat_id, message_text, bot_token)
                logger.info("Processor: replied to chat_id=%s update_id=%s", chat_id, update_id)
        else:
            _send_telegram_message(chat_id, str(result), bot_token)
    except Exception as e:
        logger.error("Processor: unhandled error update_id=%s: %s", update_id, e, exc_info=True)
        try:
            _send_telegram_message(chat_id, "Sorry, something went wrong. Please try again.", bot_token)
        except Exception:
            pass
