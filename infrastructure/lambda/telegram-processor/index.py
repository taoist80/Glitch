"""Telegram Processor Lambda -- async agent invocation and Telegram reply.

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
import random
import threading
import time
from typing import List

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from urllib.parse import quote

from agentcore_utils import get_data_plane_endpoint as _get_data_plane_endpoint, parse_runtime_arn as _parse_runtime_arn

logger = logging.getLogger()
logger.setLevel(logging.INFO)

secrets_client = boto3.client('secretsmanager')
_boto_session = boto3.Session()

TELEGRAM_SECRET_NAME = os.environ['TELEGRAM_SECRET_NAME']
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')


def _get_bot_token() -> str:
    response = secrets_client.get_secret_value(SecretId=TELEGRAM_SECRET_NAME)
    return response['SecretString']


def _chunk_text(text: str, max_len: int = 3500) -> List[str]:
    """Split large responses into Telegram-safe chunks."""
    normalized = (text or "").strip()
    if not normalized:
        return ["(no content)"]
    if len(normalized) <= max_len:
        return [normalized]

    chunks: List[str] = []
    remaining = normalized
    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, max_len)
        if split_at < 200:
            split_at = remaining.rfind("\n", 0, max_len)
        if split_at < 200:
            split_at = remaining.rfind(" ", 0, max_len)
        if split_at < 1:
            split_at = max_len
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return chunks


def _send_telegram_message(chat_id: int, text: str, bot_token: str) -> None:
    import urllib.request
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    chunks = _chunk_text(text)
    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        payload_text = chunk if total == 1 else f"[{idx}/{total}]\n{chunk}"
        data = json.dumps({'chat_id': chat_id, 'text': payload_text}).encode()
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
        try:
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logger.error(
                "Failed to send Telegram message to chat_id=%s chunk=%s/%s: %s",
                chat_id,
                idx,
                total,
                e,
            )


# All progress phrases are nursery/toddler/AB-DL themed regardless of mode
_PHRASES_ALL = [
    "Shh, shh... still thinking, little one.",
    "Hang tight -- someone's still in their thinking corner.",
    "One moment... Auri's checking the nursery.",
    "Still here. Just getting the wipes ready.",
    "Patience, cub -- good things take time.",
    "Mmm, still working... someone stay on the mat.",
    "Hold still -- still sorting through the diaper bag.",
    "Almost there, sweetheart. Don't fuss.",
    "Still thinking... the crinkles can wait.",
    "Shh... nearly done. Someone sit tight.",
    "Just a little longer -- no sneaking off the changing table.",
    "Still on it... someone's getting their blankie?",
    "Working on it... crib side manner takes patience.",
    "Auri's not done yet. Don't go anywhere.",
    "One second -- counting the pacis.",
    "Still thinking... someone's waddling impatiently over there.",
    "Auri hears the crinkles. Just a little longer.",
    "Mmm, that waddle says someone needs a check. One moment.",
    "Still here... did someone spring a leak? Auri will be right there.",
    "Working on it... that diaper's not gonna hold forever, is it.",
    "Someone smells like they've been busy. Auri's almost done.",
    "Still going... little one staying put or waddling around?",
    "One more moment -- and then Auri's checking for soggy bottoms.",
    "Almost there... someone's padding doing okay over there?",
    "Patience... puddles happen when you don't wait properly.",
]


def _working_phrases_for_mode(mode_id: str) -> List[str]:
    return _PHRASES_ALL


def _send_progress_ping(chat_id: int, bot_token: str, tick: int, mode_id: str = "") -> None:
    phrases = _working_phrases_for_mode(mode_id)
    phrase = random.choice(phrases)
    _send_telegram_message(chat_id, f"{phrase} ({tick * 30}s)", bot_token)


def _invoke_agent(prompt: str, session_id: str, agent_id: str = "glitch", mode_id: str = "", participant_id: str = ""):
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
    payload = {"prompt": prompt, "session_id": session_id, "agent_id": agent_id}
    if mode_id:
        payload["mode_id"] = mode_id
    if participant_id:
        payload["participant_id"] = participant_id
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
    mode_id = (event.get('mode_id') or '').strip().lower() or 'default'
    agent_id = (event.get('agent_id') or 'glitch').strip().lower()
    participant_id = (event.get('participant_id') or '').strip().lower()
    update_id = event.get('update_id', '?')

    logger.info("Processor: update_id=%s session_id=%s mode_id=%s text_len=%s",
                update_id, session_id, mode_id, len(text))

    try:
        bot_token = _get_bot_token()
    except Exception as e:
        logger.error("Processor: failed to get bot token update_id=%s: %s", update_id, e)
        return

    try:
        result_holder = {'result': None, 'error': None}

        def _invoke_worker():
            try:
                result_holder['result'] = _invoke_agent(
                    text,
                    session_id,
                    agent_id=agent_id,
                    mode_id=mode_id,
                    participant_id=participant_id,
                )
            except Exception as exc:  # captured and handled in main thread
                result_holder['error'] = exc

        worker = threading.Thread(target=_invoke_worker, daemon=True)
        worker.start()

        tick = 0
        next_ping = time.monotonic() + 30.0
        while worker.is_alive():
            worker.join(timeout=1.0)
            now = time.monotonic()
            if worker.is_alive() and now >= next_ping:
                tick += 1
                _send_progress_ping(chat_id, bot_token, tick, mode_id)
                next_ping = now + 30.0

        if result_holder['error'] is not None:
            raise result_holder['error']

        result = result_holder['result']
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
