"""Unified session management across channels (Telegram, Web UI, API).

Session keys follow the pattern SESSION#{channel}:{identity} in DynamoDB,
allowing a single view per channel/identity and future cross-channel linking.

Key structure:
    pk: SESSION#telegram#dm:{user_id}   (Telegram DM)
    pk: SESSION#telegram#group:{chat_id} (Telegram group)
    pk: SESSION#ui#client:{client_id}    (Web UI)
    pk: SESSION#api#key:{key_id}         (API key)
    sk: session
    session_id: string passed to AgentCore Runtime
"""

import logging
import os
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class Channel(str, Enum):
    """Channel identifier for session keys."""

    TELEGRAM_DM = "telegram#dm"
    TELEGRAM_GROUP = "telegram#group"
    UI = "ui#client"
    API = "api#key"


@dataclass
class SessionKey:
    """Identifies a session by channel and identity."""

    channel: Channel
    identity: str

    @property
    def pk(self) -> str:
        """DynamoDB partition key: SESSION#{channel}:{identity}."""
        return f"SESSION#{self.channel.value}:{self.identity}"

    @staticmethod
    def sk() -> str:
        """DynamoDB sort key for the session record."""
        return "session"

    @classmethod
    def from_telegram_dm(cls, user_id: int) -> "SessionKey":
        return cls(Channel.TELEGRAM_DM, str(user_id))

    @classmethod
    def from_telegram_group(cls, chat_id: int) -> "SessionKey":
        return cls(Channel.TELEGRAM_GROUP, str(chat_id))

    @classmethod
    def from_ui_client(cls, client_id: str) -> "SessionKey":
        return cls(Channel.UI, client_id or "")

    @classmethod
    def from_api_key(cls, key_id: str) -> "SessionKey":
        return cls(Channel.API, key_id or "")


class SessionManager:
    """Get or create a runtime session_id for a channel/identity."""

    def __init__(self, table_name: Optional[str] = None):
        self._table_name = table_name or os.environ.get("GLITCH_CONFIG_TABLE", "glitch-telegram-config")
        self._table = None

    @property
    def table(self):
        if self._table is None:
            import boto3

            region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
            self._table = boto3.resource("dynamodb", region_name=region).Table(self._table_name)
        return self._table

    def get_or_create_session(self, key: SessionKey) -> str:
        """Return existing session_id or create a new one for this channel/identity."""
        try:
            response = self.table.get_item(
                Key={"pk": key.pk, "sk": key.sk()}
            )
            if "Item" in response:
                return response["Item"]["session_id"]
        except Exception as e:
            logger.warning("SessionManager get_item failed: %s", e)

        session_id = f"{key.channel.value}-{key.identity}-{uuid.uuid4().hex[:8]}"
        try:
            self.table.put_item(
                Item={
                    "pk": key.pk,
                    "sk": key.sk(),
                    "session_id": session_id,
                    "channel": key.channel.value,
                    "identity": key.identity,
                    "created_at": int(time.time()),
                }
            )
        except Exception as e:
            logger.warning("SessionManager put_item failed: %s", e)
        return session_id
