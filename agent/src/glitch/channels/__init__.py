"""Communication channels for Glitch agent.

This package provides adapters for different communication channels
(Telegram, HTTP, etc.) that allow users to interact with the Glitch agent.
"""

from glitch.channels.base import ChannelAdapter
from glitch.channels.types import (
    ChannelConfig,
    TelegramConfig,
    BootstrapState,
    TelegramMediaMessage,
)
from glitch.channels.config_manager import ConfigManager, OwnerConfig, GlitchConfig
from glitch.channels.dynamodb_config import DynamoDBConfigManager
from glitch.channels.bootstrap import OwnerBootstrap
from glitch.channels.telegram_commands import TelegramCommandHandler
from glitch.channels.telegram import TelegramChannel

__all__ = [
    "ChannelAdapter",
    "ChannelConfig",
    "TelegramConfig",
    "BootstrapState",
    "TelegramMediaMessage",
    "OwnerConfig",
    "GlitchConfig",
    "ConfigManager",
    "DynamoDBConfigManager",
    "OwnerBootstrap",
    "TelegramCommandHandler",
    "TelegramChannel",
]
