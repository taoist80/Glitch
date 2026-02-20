"""DynamoDB-backed configuration management for multi-instance deployments.

Provides shared configuration storage using DynamoDB so all AgentCore instances
see the same owner, pairing code, and settings. Falls back to local file storage
if DynamoDB is not configured.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from dataclasses import dataclass, asdict, field

import boto3
from botocore.exceptions import ClientError

from glitch.channels.types import TelegramConfig

logger = logging.getLogger(__name__)


@dataclass
class OwnerConfig:
    """Owner information.
    
    Attributes:
        telegram_id: Telegram user ID of the owner
        claimed_at: When ownership was claimed
    """
    telegram_id: Optional[int] = None
    claimed_at: Optional[str] = None


@dataclass
class GlitchConfig:
    """Main Glitch configuration.
    
    Attributes:
        version: Config file format version
        owner: Owner information
        telegram: Telegram channel configuration
        locked: Whether configuration is locked (prevents changes)
    """
    version: int = 1
    owner: OwnerConfig = field(default_factory=OwnerConfig)
    telegram: Optional[TelegramConfig] = None
    locked: bool = False
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert config to dictionary for JSON serialization."""
        result = {
            "version": self.version,
            "owner": asdict(self.owner) if self.owner else None,
            "locked": self.locked,
        }
        
        if self.telegram:
            telegram_dict = asdict(self.telegram)
            telegram_dict.pop("bot_token", None)
            result["channels"] = {"telegram": telegram_dict}
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], bot_token: Optional[str] = None) -> "GlitchConfig":
        """Create config from dictionary."""
        owner_data = data.get("owner", {})
        owner = OwnerConfig(
            telegram_id=owner_data.get("telegram_id"),
            claimed_at=owner_data.get("claimed_at"),
        )
        
        telegram = None
        channels = data.get("channels", {})
        if "telegram" in channels and bot_token:
            telegram_data = channels["telegram"]
            telegram = TelegramConfig(
                bot_token=bot_token,
                owner_id=telegram_data.get("owner_id"),
                mode=telegram_data.get("mode", "polling"),
                webhook_url=telegram_data.get("webhook_url"),
                webhook_secret=telegram_data.get("webhook_secret"),
                dm_policy=telegram_data.get("dm_policy", "pairing"),
                dm_allowlist=telegram_data.get("dm_allowlist", []),
                group_policy=telegram_data.get("group_policy", "allowlist"),
                group_allowlist=telegram_data.get("group_allowlist", []),
                require_mention=telegram_data.get("require_mention", True),
                text_chunk_limit=telegram_data.get("text_chunk_limit", 4000),
                media_max_mb=telegram_data.get("media_max_mb", 5),
            )
        
        return cls(
            version=data.get("version", 1),
            owner=owner,
            telegram=telegram,
            locked=data.get("locked", False),
        )


class DynamoDBConfigManager:
    """Manages shared configuration in DynamoDB for multi-instance deployments.
    
    Uses DynamoDB table with pk/sk pattern:
    - CONFIG#main: Main config (owner, locked status)
    - CONFIG#pairing: Pairing code with TTL
    - CONFIG#telegram: Telegram-specific settings
    """
    
    def __init__(
        self,
        table_name: Optional[str] = None,
        region: Optional[str] = None,
    ):
        """Initialize DynamoDB config manager.
        
        Args:
            table_name: DynamoDB table name (default: GLITCH_CONFIG_TABLE env var)
            region: AWS region (default: AWS_REGION env var)
        """
        self.table_name = table_name or os.getenv("GLITCH_CONFIG_TABLE", "glitch-telegram-config")
        self.region = region or os.getenv("AWS_REGION", "us-west-2")
        
        self._dynamodb = None
        self._table = None
        self.config: Optional[GlitchConfig] = None
        self._bot_token: Optional[str] = None
    
    @property
    def dynamodb(self):
        """Lazy-load DynamoDB resource."""
        if self._dynamodb is None:
            self._dynamodb = boto3.resource("dynamodb", region_name=self.region)
        return self._dynamodb
    
    @property
    def table(self):
        """Lazy-load DynamoDB table."""
        if self._table is None:
            self._table = self.dynamodb.Table(self.table_name)
        return self._table
    
    def load(self, bot_token: Optional[str] = None) -> GlitchConfig:
        """Load config from DynamoDB.
        
        Args:
            bot_token: Telegram bot token from environment
            
        Returns:
            GlitchConfig instance
        """
        self._bot_token = bot_token
        
        try:
            response = self.table.get_item(Key={"pk": "CONFIG", "sk": "main"})
            if "Item" in response:
                item = response["Item"]
                owner = OwnerConfig(
                    telegram_id=item.get("owner_id"),
                    claimed_at=item.get("claimed_at"),
                )
                
                telegram = None
                if bot_token:
                    telegram = self._load_telegram_config(bot_token)
                
                self.config = GlitchConfig(
                    version=item.get("version", 1),
                    owner=owner,
                    telegram=telegram,
                    locked=item.get("locked", False),
                )
                logger.info(f"Loaded config from DynamoDB table {self.table_name}")
            else:
                logger.info("No config in DynamoDB, creating defaults")
                self.config = self._create_default_config(bot_token)
                self.save()
        except ClientError as e:
            logger.error(f"Failed to load config from DynamoDB: {e}")
            self.config = self._create_default_config(bot_token)
        
        return self.config
    
    def _load_telegram_config(self, bot_token: str) -> TelegramConfig:
        """Load Telegram-specific config from DynamoDB."""
        try:
            response = self.table.get_item(Key={"pk": "CONFIG", "sk": "telegram"})
            if "Item" in response:
                item = response["Item"]
                return TelegramConfig(
                    bot_token=bot_token,
                    owner_id=item.get("owner_id"),
                    mode=item.get("mode", "webhook"),
                    webhook_url=item.get("webhook_url"),
                    webhook_secret=item.get("webhook_secret"),
                    dm_policy=item.get("dm_policy", "pairing"),
                    dm_allowlist=item.get("dm_allowlist", []),
                    group_policy=item.get("group_policy", "allowlist"),
                    group_allowlist=item.get("group_allowlist", []),
                    require_mention=item.get("require_mention", True),
                    text_chunk_limit=item.get("text_chunk_limit", 4000),
                    media_max_mb=item.get("media_max_mb", 5),
                )
        except ClientError as e:
            logger.warning(f"Failed to load Telegram config: {e}")
        
        return TelegramConfig(bot_token=bot_token, mode="webhook")
    
    def _create_default_config(self, bot_token: Optional[str] = None) -> GlitchConfig:
        """Create default configuration."""
        telegram = None
        if bot_token:
            telegram = TelegramConfig(bot_token=bot_token, mode="webhook")
        return GlitchConfig(telegram=telegram)
    
    def save(self) -> None:
        """Save current config to DynamoDB."""
        if self.config is None:
            logger.warning("No config to save")
            return
        
        try:
            self.table.put_item(Item={
                "pk": "CONFIG",
                "sk": "main",
                "version": self.config.version,
                "owner_id": self.config.owner.telegram_id if self.config.owner else None,
                "claimed_at": self.config.owner.claimed_at if self.config.owner else None,
                "status": "claimed" if self.config.owner and self.config.owner.telegram_id else "unclaimed",
                "locked": self.config.locked,
            })
            
            if self.config.telegram:
                self._save_telegram_config()
            
            logger.debug(f"Saved config to DynamoDB table {self.table_name}")
        except ClientError as e:
            logger.error(f"Failed to save config to DynamoDB: {e}")
            raise
    
    def _save_telegram_config(self) -> None:
        """Save Telegram-specific config to DynamoDB."""
        if not self.config or not self.config.telegram:
            return
        
        t = self.config.telegram
        self.table.put_item(Item={
            "pk": "CONFIG",
            "sk": "telegram",
            "owner_id": t.owner_id,
            "mode": t.mode,
            "webhook_url": t.webhook_url,
            "webhook_secret": t.webhook_secret,
            "dm_policy": t.dm_policy,
            "dm_allowlist": t.dm_allowlist,
            "group_policy": t.group_policy,
            "group_allowlist": t.group_allowlist,
            "require_mention": t.require_mention,
            "text_chunk_limit": t.text_chunk_limit,
            "media_max_mb": t.media_max_mb,
        })
    
    def update(self, **kwargs) -> None:
        """Update config values and auto-save."""
        if self.config is None:
            raise ValueError("Config not loaded")
        
        if self.config.locked:
            raise ValueError("Configuration is locked")
        
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
        
        self.save()
    
    def update_telegram(self, **kwargs) -> None:
        """Update Telegram configuration and auto-save."""
        if self.config is None:
            raise ValueError("Config not loaded")
        
        if self.config.locked:
            raise ValueError("Configuration is locked")
        
        if self.config.telegram is None:
            raise ValueError("Telegram not configured")
        
        for key, value in kwargs.items():
            if hasattr(self.config.telegram, key):
                setattr(self.config.telegram, key, value)
        
        self.save()
    
    def set_owner(self, telegram_id: int) -> None:
        """Set the owner and auto-save."""
        if self.config is None:
            raise ValueError("Config not loaded")
        
        self.config.owner = OwnerConfig(
            telegram_id=telegram_id,
            claimed_at=datetime.utcnow().isoformat() + "Z",
        )
        
        if self.config.telegram:
            self.config.telegram.owner_id = telegram_id
        
        self.save()
        logger.info(f"Owner set to Telegram user {telegram_id}")
    
    def lock(self) -> None:
        """Lock configuration to prevent changes."""
        if self.config:
            self.config.locked = True
            self.save()
            logger.info("Configuration locked")
    
    def unlock(self) -> None:
        """Unlock configuration to allow changes."""
        if self.config:
            self.config.locked = False
            self.save()
            logger.info("Configuration unlocked")
    
    def get_pairing_code(self) -> Optional[str]:
        """Get or generate pairing code from DynamoDB."""
        try:
            response = self.table.get_item(Key={"pk": "CONFIG", "sk": "pairing"})
            if "Item" in response:
                item = response["Item"]
                expires_at = datetime.fromisoformat(item["expires_at"].rstrip("Z"))
                if datetime.utcnow() < expires_at:
                    return item["code"]
        except (ClientError, KeyError, ValueError) as e:
            logger.warning(f"Failed to get pairing code: {e}")
        
        return self._generate_pairing_code()
    
    def _generate_pairing_code(self) -> str:
        """Generate and store a new pairing code."""
        import secrets
        import string
        
        alphabet = string.ascii_uppercase + string.digits
        code = "".join(secrets.choice(alphabet) for _ in range(8))
        expires_at = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z"
        ttl = int((datetime.utcnow() + timedelta(hours=2)).timestamp())
        
        try:
            self.table.put_item(Item={
                "pk": "CONFIG",
                "sk": "pairing",
                "code": code,
                "expires_at": expires_at,
                "ttl": ttl,
            })
            logger.info("Generated new pairing code (expires in 1 hour)")
        except ClientError as e:
            logger.error(f"Failed to store pairing code: {e}")
        
        return code
    
    def validate_pairing_code(self, code: str, user_id: int) -> bool:
        """Validate pairing code and claim ownership if correct."""
        if self.config and self.config.owner and self.config.owner.telegram_id:
            logger.warning("Pairing rejected: already claimed")
            return False
        
        stored_code = self.get_pairing_code()
        if code.upper() == stored_code:
            self.set_owner(user_id)
            try:
                self.table.delete_item(Key={"pk": "CONFIG", "sk": "pairing"})
            except ClientError:
                pass
            return True
        
        logger.warning(f"Invalid pairing code from user {user_id}")
        return False
    
    def is_claimed(self) -> bool:
        """Check if bot has been claimed."""
        if self.config and self.config.owner and self.config.owner.telegram_id:
            return True
        return False
    
    def get_webhook_secret(self) -> str:
        """Get or generate webhook secret for Telegram validation."""
        try:
            response = self.table.get_item(Key={"pk": "CONFIG", "sk": "webhook_secret"})
            if "Item" in response:
                return response["Item"]["value"]
        except ClientError:
            pass
        
        import secrets
        new_secret = secrets.token_hex(32)
        try:
            self.table.put_item(Item={
                "pk": "CONFIG",
                "sk": "webhook_secret",
                "value": new_secret,
            })
        except ClientError as e:
            logger.error(f"Failed to store webhook secret: {e}")
        
        return new_secret
    
    def set_webhook_url(self, url: str) -> None:
        """Set the webhook URL in config."""
        if self.config and self.config.telegram:
            self.config.telegram.webhook_url = url
            self.config.telegram.mode = "webhook"
            self.save()
            logger.info(f"Webhook URL set to {url}")
