"""Group moderation tools for Auri.

Provides warn, mute, kick, ban, delete_message, and query tools for
Telegram group moderation. All tools read chat_id/from_user_id from
invocation_context (set by server.py), never from LLM parameters.

DynamoDB key patterns (glitch-telegram-config table):
    MOD_RULES#{chat_id} / rules        — group moderation rules
    MOD_WARN#{chat_id}#{user_id} / {ts} — per-user warnings (30-day TTL)
    MOD_ACTION#{chat_id} / {ts}#{user_id} — action audit log (90-day TTL)
"""

import json
import logging
import os
import time
from typing import Optional

import httpx
from strands import tool

from glitch.aws_utils import get_client
from glitch.invocation_context import get_context

logger = logging.getLogger(__name__)

SECRET_NAME = "glitch/telegram-bot-token"
CONFIG_TABLE = os.environ.get("GLITCH_CONFIG_TABLE", "glitch-telegram-config")

_bot_token: Optional[str] = None

# Default rules applied when no custom rules exist for a group.
DEFAULT_RULES = [
    {"id": 1, "text": "Be respectful", "severity": "medium"},
    {"id": 2, "text": "No racism", "severity": "high"},
    {"id": 3, "text": "No threats of violence", "severity": "high"},
    {"id": 4, "text": "No spamming the channel", "severity": "medium"},
    {"id": 5, "text": "Suspected AI bots will be banned immediately", "severity": "high"},
]

# TTLs in seconds
WARN_TTL = 30 * 24 * 3600   # 30 days
ACTION_TTL = 90 * 24 * 3600  # 90 days


async def _get_bot_token() -> str:
    """Retrieve bot token from Secrets Manager (cached in-process)."""
    global _bot_token
    if _bot_token:
        return _bot_token
    client = get_client("secretsmanager")
    resp = client.get_secret_value(SecretId=SECRET_NAME)
    _bot_token = resp["SecretString"].strip()
    return _bot_token


async def _telegram_api(method: str, **params: object) -> dict:
    """Call a Telegram Bot API method. Returns the parsed JSON response."""
    token = await _get_bot_token()
    url = f"https://api.telegram.org/bot{token}/{method}"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=params)
        data = resp.json()
        if not data.get("ok"):
            logger.error("Telegram API %s failed: %s", method, data)
        return data


def _record_action(chat_id: int, user_id: int, action: str, reason: str) -> None:
    """Write an audit log entry to DynamoDB."""
    ts = str(int(time.time()))
    ddb = get_client("dynamodb")
    ddb.put_item(
        TableName=CONFIG_TABLE,
        Item={
            "pk": {"S": f"MOD_ACTION#{chat_id}"},
            "sk": {"S": f"{ts}#{user_id}"},
            "action": {"S": action},
            "reason": {"S": reason},
            "user_id": {"N": str(user_id)},
            "timestamp": {"N": ts},
            "ttl": {"N": str(int(time.time()) + ACTION_TTL)},
        },
    )


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@tool
async def warn_user(reason: str) -> str:
    """Warn a user in the current group chat for a rule violation.

    Records the warning in DynamoDB and sends a reply in the group.
    The warning count is tracked per user per group (30-day rolling window).

    Args:
        reason: Why the user is being warned. Keep it short and clear.

    Returns:
        Warning result including current warning count, or error message.
    """
    ctx = get_context()
    if not ctx.chat_id or not ctx.from_user_id:
        return "error: no group chat context available"

    # Record warning in DynamoDB
    ts = str(int(time.time()))
    ddb = get_client("dynamodb")
    ddb.put_item(
        TableName=CONFIG_TABLE,
        Item={
            "pk": {"S": f"MOD_WARN#{ctx.chat_id}#{ctx.from_user_id}"},
            "sk": {"S": ts},
            "reason": {"S": reason},
            "timestamp": {"N": ts},
            "ttl": {"N": str(int(time.time()) + WARN_TTL)},
        },
    )

    # Count active warnings
    resp = ddb.query(
        TableName=CONFIG_TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": f"MOD_WARN#{ctx.chat_id}#{ctx.from_user_id}"}},
        Select="COUNT",
    )
    count = resp.get("Count", 1)

    # Send warning reply in group
    result = await _telegram_api(
        "sendMessage",
        chat_id=ctx.chat_id,
        reply_to_message_id=ctx.message_id if ctx.message_id else None,
        text=f"⚠️ Warning ({count}): {reason}",
        parse_mode="HTML",
    )

    _record_action(ctx.chat_id, ctx.from_user_id, "warn", reason)

    if result.get("ok"):
        return f"warned: warning #{count} for user {ctx.from_user_id}"
    return f"warning recorded (count={count}) but reply failed: {result.get('description', 'unknown error')}"


@tool
async def mute_user(duration_minutes: int, reason: str) -> str:
    """Mute (restrict) a user in the current group chat.

    Uses Telegram restrictChatMember to remove send_messages permission
    for the specified duration.

    Args:
        duration_minutes: How long to mute (1-1440 minutes).
        reason: Why the user is being muted.

    Returns:
        "muted" on success, or error message.
    """
    ctx = get_context()
    if not ctx.chat_id or not ctx.from_user_id:
        return "error: no group chat context available"

    duration_minutes = max(1, min(duration_minutes, 1440))
    until_date = int(time.time()) + (duration_minutes * 60)

    result = await _telegram_api(
        "restrictChatMember",
        chat_id=ctx.chat_id,
        user_id=ctx.from_user_id,
        permissions={"can_send_messages": False},
        until_date=until_date,
    )

    _record_action(ctx.chat_id, ctx.from_user_id, "mute", f"{duration_minutes}min: {reason}")

    if result.get("ok"):
        return f"muted: user {ctx.from_user_id} for {duration_minutes} minutes"
    return f"mute failed: {result.get('description', 'unknown error')}"


@tool
async def kick_user(reason: str) -> str:
    """Kick a user from the current group chat (they can rejoin).

    Uses banChatMember followed by unbanChatMember to remove the user
    without a permanent ban.

    Args:
        reason: Why the user is being kicked.

    Returns:
        "kicked" on success, or error message.
    """
    ctx = get_context()
    if not ctx.chat_id or not ctx.from_user_id:
        return "error: no group chat context available"

    ban_result = await _telegram_api(
        "banChatMember",
        chat_id=ctx.chat_id,
        user_id=ctx.from_user_id,
    )

    if not ban_result.get("ok"):
        return f"kick failed (ban step): {ban_result.get('description', 'unknown error')}"

    # Immediately unban so user can rejoin
    await _telegram_api(
        "unbanChatMember",
        chat_id=ctx.chat_id,
        user_id=ctx.from_user_id,
        only_if_banned=True,
    )

    _record_action(ctx.chat_id, ctx.from_user_id, "kick", reason)
    return f"kicked: user {ctx.from_user_id}"


@tool
async def ban_user(reason: str) -> str:
    """Permanently ban a user from the current group chat.

    Args:
        reason: Why the user is being banned.

    Returns:
        "banned" on success, or error message.
    """
    ctx = get_context()
    if not ctx.chat_id or not ctx.from_user_id:
        return "error: no group chat context available"

    result = await _telegram_api(
        "banChatMember",
        chat_id=ctx.chat_id,
        user_id=ctx.from_user_id,
    )

    _record_action(ctx.chat_id, ctx.from_user_id, "ban", reason)

    if result.get("ok"):
        return f"banned: user {ctx.from_user_id}"
    return f"ban failed: {result.get('description', 'unknown error')}"


@tool
async def delete_message(reason: str) -> str:
    """Delete the offending message from the current group chat.

    Args:
        reason: Why the message is being deleted.

    Returns:
        "deleted" on success, or error message.
    """
    ctx = get_context()
    if not ctx.chat_id or not ctx.message_id:
        return "error: no message context available"

    result = await _telegram_api(
        "deleteMessage",
        chat_id=ctx.chat_id,
        message_id=ctx.message_id,
    )

    _record_action(ctx.chat_id, ctx.from_user_id, "delete_message", reason)

    if result.get("ok"):
        return "deleted"
    return f"delete failed: {result.get('description', 'unknown error')}"


@tool
async def get_warnings() -> str:
    """Get the warning history for the current user in this group.

    Returns:
        JSON list of warnings with timestamps and reasons.
    """
    ctx = get_context()
    if not ctx.chat_id or not ctx.from_user_id:
        return "error: no group chat context available"

    ddb = get_client("dynamodb")
    resp = ddb.query(
        TableName=CONFIG_TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": f"MOD_WARN#{ctx.chat_id}#{ctx.from_user_id}"}},
        ScanIndexForward=False,
        Limit=20,
    )

    warnings = []
    for item in resp.get("Items", []):
        warnings.append({
            "timestamp": int(item.get("timestamp", {}).get("N", "0")),
            "reason": item.get("reason", {}).get("S", ""),
        })

    return json.dumps({"user_id": ctx.from_user_id, "count": len(warnings), "warnings": warnings})


@tool
async def get_group_rules() -> str:
    """Get the moderation rules for the current group chat.

    Returns custom rules if configured, otherwise the default rules.

    Returns:
        JSON list of rules with id, text, and severity.
    """
    ctx = get_context()
    if not ctx.chat_id:
        return json.dumps({"rules": DEFAULT_RULES, "source": "default"})

    ddb = get_client("dynamodb")
    try:
        resp = ddb.get_item(
            TableName=CONFIG_TABLE,
            Key={
                "pk": {"S": f"MOD_RULES#{ctx.chat_id}"},
                "sk": {"S": "rules"},
            },
        )
        item = resp.get("Item")
        if item and "rules_json" in item:
            rules = json.loads(item["rules_json"]["S"])
            return json.dumps({"rules": rules, "source": "custom"})
    except Exception as e:
        logger.error("Failed to load moderation rules for chat %s: %s", ctx.chat_id, e)

    return json.dumps({"rules": DEFAULT_RULES, "source": "default"})
