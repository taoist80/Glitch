"""Configuration management with auto-save functionality.

Manages persistent configuration for Glitch, including channel settings
and ownership information. All configuration changes are automatically
saved to disk.
"""

import json
import logging
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass, asdict, field

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
            # Don't save bot_token to config file (comes from env)
            telegram_dict.pop("bot_token", None)
            result["channels"] = {"telegram": telegram_dict}
        
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any], bot_token: Optional[str] = None) -> "GlitchConfig":
        """Create config from dictionary.
        
        Args:
            data: Configuration dictionary
            bot_token: Bot token from environment (not stored in config)
            
        Returns:
            GlitchConfig instance
        """
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


class ConfigManager:
    """Manages persistent configuration with auto-save.
    
    Configuration is stored in ~/.glitch/config.json by default.
    All updates automatically save to disk.
    """
    
    def __init__(self, config_dir: Optional[Path] = None):
        """Initialize ConfigManager.
        
        Args:
            config_dir: Override config directory (default: ~/.glitch)
        """
        if config_dir is None:
            config_dir = Path.home() / ".glitch"
        
        self.config_dir = config_dir
        self.config_path = config_dir / "config.json"
        self.config: Optional[GlitchConfig] = None
        
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Set restrictive permissions on config directory
        try:
            self.config_dir.chmod(0o700)
        except Exception as e:
            logger.warning(f"Failed to set config directory permissions: {e}")
    
    def load(self, bot_token: Optional[str] = None) -> GlitchConfig:
        """Load config from disk, create defaults if missing.
        
        Args:
            bot_token: Telegram bot token from environment
            
        Returns:
            GlitchConfig instance
        """
        if self.config_path.exists():
            try:
                with open(self.config_path, "r") as f:
                    data = json.load(f)
                self.config = GlitchConfig.from_dict(data, bot_token)
                logger.info(f"Loaded configuration from {self.config_path}")
            except Exception as e:
                logger.error(f"Failed to load config: {e}, using defaults")
                self.config = self._create_default_config(bot_token)
        else:
            logger.info("No config file found, creating defaults")
            self.config = self._create_default_config(bot_token)
            self.save()
        
        return self.config
    
    def _create_default_config(self, bot_token: Optional[str] = None) -> GlitchConfig:
        """Create default configuration.
        
        Args:
            bot_token: Telegram bot token from environment
            
        Returns:
            Default GlitchConfig
        """
        telegram = None
        if bot_token:
            telegram = TelegramConfig(bot_token=bot_token)
        
        return GlitchConfig(telegram=telegram)
    
    def save(self) -> None:
        """Save current config to disk.
        
        Raises:
            Exception: If save fails
        """
        if self.config is None:
            logger.warning("No config to save")
            return
        
        try:
            config_dict = self.config.to_dict()
            
            # Write to temp file first, then rename (atomic operation)
            temp_path = self.config_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(config_dict, f, indent=2)
            
            # Set restrictive permissions
            temp_path.chmod(0o600)
            
            # Atomic rename
            temp_path.rename(self.config_path)
            
            logger.debug(f"Saved configuration to {self.config_path}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            raise
    
    def update(self, **kwargs) -> None:
        """Update config values and auto-save.
        
        Args:
            **kwargs: Configuration fields to update
            
        Raises:
            ValueError: If trying to update while locked
        """
        if self.config is None:
            raise ValueError("Config not loaded")
        
        if self.config.locked:
            raise ValueError("Configuration is locked")
        
        # Update fields
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
            else:
                logger.warning(f"Unknown config field: {key}")
        
        # Auto-save
        self.save()
    
    def update_telegram(self, **kwargs) -> None:
        """Update Telegram configuration and auto-save.
        
        Args:
            **kwargs: Telegram configuration fields to update
            
        Raises:
            ValueError: If trying to update while locked or no Telegram config
        """
        if self.config is None:
            raise ValueError("Config not loaded")
        
        if self.config.locked:
            raise ValueError("Configuration is locked")
        
        if self.config.telegram is None:
            raise ValueError("Telegram not configured")
        
        # Update Telegram fields
        for key, value in kwargs.items():
            if hasattr(self.config.telegram, key):
                setattr(self.config.telegram, key, value)
            else:
                logger.warning(f"Unknown Telegram config field: {key}")
        
        # Auto-save
        self.save()
    
    def set_owner(self, telegram_id: int) -> None:
        """Set the owner and auto-save.
        
        Args:
            telegram_id: Telegram user ID
        """
        if self.config is None:
            raise ValueError("Config not loaded")
        
        self.config.owner = OwnerConfig(
            telegram_id=telegram_id,
            claimed_at=datetime.utcnow().isoformat() + "Z",
        )
        
        # Also set owner_id in Telegram config
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
