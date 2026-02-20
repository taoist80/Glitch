"""Type definitions for channel adapters.

Defines configuration and message types used across different channel adapters.
"""

from dataclasses import dataclass, field
from typing import Optional, Literal, List, Union
from datetime import datetime


@dataclass
class BootstrapState:
    """Bot ownership bootstrap state.
    
    Manages the ownership claiming process via pairing code.
    
    Attributes:
        status: Current bootstrap status
        pairing_code: Generated pairing code (only when unclaimed)
        code_expires_at: When the pairing code expires
        owner_id: Telegram user ID of the owner (once claimed)
        claimed_at: When ownership was claimed
    """
    status: Literal["unclaimed", "claimed", "locked"]
    pairing_code: Optional[str] = None
    code_expires_at: Optional[datetime] = None
    owner_id: Optional[int] = None
    claimed_at: Optional[datetime] = None


@dataclass
class TelegramConfig:
    """Configuration for Telegram channel adapter.
    
    Attributes:
        bot_token: Bot token from BotFather (from environment)
        owner_id: Telegram user ID of the owner (set via pairing)
        mode: Connection mode (polling or webhook)
        webhook_url: URL for webhook mode
        webhook_secret: Secret for webhook validation
        dm_policy: Access policy for direct messages
        dm_allowlist: List of allowed Telegram user IDs for DMs
        group_policy: Access policy for groups
        group_allowlist: List of allowed group/chat IDs
        require_mention: Whether bot must be @mentioned in groups
        text_chunk_limit: Max message length before chunking
        media_max_mb: Max inbound media size in megabytes
        include_metrics: Whether to send Strands telemetry summary after each reply
    """
    bot_token: str
    owner_id: Optional[int] = None
    mode: Literal["polling", "webhook"] = "polling"
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    dm_policy: Literal["pairing", "allowlist", "open", "disabled"] = "pairing"
    dm_allowlist: List[int] = field(default_factory=list)
    group_policy: Literal["allowlist", "open", "disabled"] = "allowlist"
    group_allowlist: List[int] = field(default_factory=list)
    require_mention: bool = True
    text_chunk_limit: int = 4000
    media_max_mb: int = 5
    include_metrics: bool = True


@dataclass
class TelegramMediaMessage:
    """Message with attached media from Telegram.
    
    Represents a message containing an image, document, or video
    that needs to be processed by the agent.
    
    Attributes:
        text: User's caption or auto-generated prompt
        media_type: Type of media attached
        media_data: Base64-encoded media data or URL
        file_id: Telegram file_id for reference
        file_size_bytes: Size of the media file
    """
    text: str
    media_type: Literal["photo", "document", "video"]
    media_data: str
    file_id: str
    file_size_bytes: Optional[int] = None


# Union type for channel configurations
ChannelConfig = Union[TelegramConfig]
