"""Telegram alerting tools for Sentinel.

Sends alerts and resolution notifications to the owner via the Telegram Bot API.
Uses the same bot token as Glitch (glitch/telegram-bot-token) and reads the
owner's chat ID from the Telegram config DynamoDB table.
"""

import json
import logging
import os
from typing import Optional

import httpx
from strands import tool

from sentinel.aws_utils import get_client

logger = logging.getLogger(__name__)

SECRET_NAME = "glitch/telegram-bot-token"
TELEGRAM_CONFIG_TABLE = os.environ.get("GLITCH_TELEGRAM_CONFIG_TABLE", "glitch-telegram-config")

_bot_token: Optional[str] = None
_owner_chat_id: Optional[str] = None


async def _get_bot_token() -> str:
    global _bot_token
    if _bot_token:
        return _bot_token
    client = get_client("secretsmanager")
    resp = client.get_secret_value(SecretId=SECRET_NAME)
    _bot_token = resp["SecretString"].strip()
    return _bot_token


async def _get_owner_chat_id() -> Optional[str]:
    """Retrieve owner chat ID from DynamoDB telegram config table."""
    global _owner_chat_id
    if _owner_chat_id:
        return _owner_chat_id
    try:
        ddb = get_client("dynamodb")
        resp = ddb.get_item(
            TableName=TELEGRAM_CONFIG_TABLE,
            Key={"pk": {"S": "CONFIG"}, "sk": {"S": "main"}},
        )
        item = resp.get("Item", {})
        owner_id = item.get("owner_id", {}).get("S")
        if owner_id:
            _owner_chat_id = owner_id
            return owner_id
    except Exception as e:
        logger.error(f"Failed to retrieve owner chat ID from DynamoDB: {e}")
    return None


async def _send_message(chat_id: str, text: str) -> bool:
    """Send a message via the Telegram Bot API."""
    token = await _get_bot_token()
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        })
        if resp.status_code == 200:
            return True
        logger.error(f"Telegram sendMessage failed: {resp.status_code} {resp.text}")
        return False


@tool
async def send_telegram_alert(
    message: str,
    severity: str = "medium",
    component: Optional[str] = None,
) -> str:
    """Send an alert notification to the owner via Telegram.

    Args:
        message: The alert message describing the issue. Include what happened,
                 what systems are affected, and what action (if any) is needed.
        severity: Alert severity — "low", "medium", or "high". Default "medium".
        component: Optional component name (e.g., "Lambda", "Protect", "DNS").

    Returns:
        "sent" on success, or error message.
    """
    severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(severity.lower(), "🟡")
    component_tag = f" [{component}]" if component else ""

    text = f"{severity_emoji} <b>Sentinel Alert{component_tag}</b>\n\n{message}"

    chat_id = await _get_owner_chat_id()
    if not chat_id:
        return "error: could not determine owner chat ID from DynamoDB"

    success = await _send_message(chat_id, text)
    return "sent" if success else "error: telegram API call failed"


@tool
async def send_telegram_resolved(
    summary: str,
    component: Optional[str] = None,
) -> str:
    """Send a resolution notification to the owner via Telegram.

    Args:
        summary: Description of what was resolved and how it was fixed.
        component: Optional component name (e.g., "Lambda", "Nginx", "DNS").

    Returns:
        "sent" on success, or error message.
    """
    component_tag = f" [{component}]" if component else ""
    text = f"✅ <b>Sentinel Resolved{component_tag}</b>\n\n{summary}"

    chat_id = await _get_owner_chat_id()
    if not chat_id:
        return "error: could not determine owner chat ID from DynamoDB"

    success = await _send_message(chat_id, text)
    return "sent" if success else "error: telegram API call failed"
