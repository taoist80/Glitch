"""Telegram channel adapter implementation.

Provides Telegram integration for Glitch using python-telegram-bot.
Supports both polling and webhook modes, with session isolation,
access controls, and media handling.
"""

import base64
import logging
import io
import os
from typing import Optional

from telegram import Update, Bot
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

from glitch.channels.base import ChannelAdapter
from glitch.channels.types import TelegramConfig, TelegramMediaMessage
from glitch.channels.bootstrap import OwnerBootstrap
from glitch.channels.config_manager import ConfigManager
from glitch.channels.telegram_commands import TelegramCommandHandler

logger = logging.getLogger(__name__)


class TelegramChannel(ChannelAdapter):
    """Telegram channel adapter.
    
    Manages Telegram bot integration with:
    - Owner bootstrap via pairing code
    - Access control (DM/group policies)
    - Session isolation
    - Media handling (images, documents, video)
    - Command handling (/config, /status, /help, etc.)
    - Response chunking for long messages
    """
    
    def __init__(
        self,
        config_manager: ConfigManager,
        bootstrap: OwnerBootstrap,
        agent: Optional[any] = None,
    ):
        """Initialize Telegram channel.
        
        Args:
            config_manager: ConfigManager instance
            bootstrap: OwnerBootstrap instance
            agent: GlitchAgent instance (optional)
        """
        self.config_manager = config_manager
        self.bootstrap = bootstrap
        self.agent = agent
        self.config = config_manager.config.telegram
        
        if not self.config or not self.config.bot_token:
            raise ValueError("Telegram bot token not configured")
        
        # Initialize command handler
        self.command_handler = TelegramCommandHandler(
            config_manager=config_manager,
            bootstrap=bootstrap,
            agent=agent,
        )
        
        # Initialize application
        self.application = Application.builder().token(self.config.bot_token).build()
        
        # Register handlers
        self._register_handlers()
        
        logger.info(f"Telegram channel initialized (mode: {self.config.mode})")
    
    def _register_handlers(self) -> None:
        """Register message and command handlers."""
        # Command handlers
        self.application.add_handler(CommandHandler("config", self.command_handler.handle_config))
        self.application.add_handler(CommandHandler("status", self.command_handler.handle_status))
        self.application.add_handler(CommandHandler("help", self.command_handler.handle_help))
        self.application.add_handler(CommandHandler("start", self.command_handler.handle_help))
        self.application.add_handler(CommandHandler("new", self.command_handler.handle_new))
        
        # Message handlers
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_text_message)
        )
        self.application.add_handler(
            MessageHandler(filters.PHOTO, self._handle_photo_message)
        )
        self.application.add_handler(
            MessageHandler(filters.Document.IMAGE, self._handle_document_message)
        )
    
    async def start(self) -> None:
        """Start the Telegram bot.

        Initializes the bot and begins receiving messages via polling or webhook.
        Only one instance may poll getUpdates per bot token; use
        GLITCH_TELEGRAM_POLLING_ENABLED=false on extra replicas or catch Conflict.
        """
        try:
            await self.application.initialize()
            await self.application.start()

            if self.config.mode == "polling":
                polling_enabled = os.getenv("GLITCH_TELEGRAM_POLLING_ENABLED", "true").lower() in ("true", "1", "yes")
                if not polling_enabled:
                    logger.info(
                        "Telegram polling disabled by GLITCH_TELEGRAM_POLLING_ENABLED; "
                        "only one instance should poll in multi-instance deployments."
                    )
                    return
                logger.info("Starting Telegram bot in polling mode")
                try:
                    await self.application.updater.start_polling(
                        allowed_updates=Update.ALL_TYPES,
                        drop_pending_updates=True,
                    )
                except Conflict:
                    logger.warning(
                        "Telegram getUpdates conflict: another instance is already polling. "
                        "Skipping Telegram polling on this instance (only one bot instance should poll)."
                    )
                    await self.application.updater.stop()
                    return
            else:
                # Webhook mode: either this process serves the webhook, or an external endpoint (e.g. Lambda) does
                if not self.config.webhook_url:
                    logger.info(
                        "Telegram webhook mode but no webhook_url set; Lambda or external endpoint will receive updates. "
                        "Skipping local webhook server."
                    )
                    return

                logger.info(f"Starting Telegram bot in webhook mode: {self.config.webhook_url}")
                await self.application.updater.start_webhook(
                    listen="0.0.0.0",
                    port=8443,
                    url_path=self.config.bot_token,
                    webhook_url=self.config.webhook_url,
                    secret_token=self.config.webhook_secret,
                )

            logger.info("Telegram bot started successfully")
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}", exc_info=True)
            raise
    
    async def stop(self) -> None:
        """Stop the Telegram bot gracefully."""
        try:
            logger.info("Stopping Telegram bot")
            
            if self.config.mode == "polling":
                await self.application.updater.stop()
            else:
                await self.application.updater.stop()
            
            await self.application.stop()
            await self.application.shutdown()
            
            logger.info("Telegram bot stopped")
        except Exception as e:
            logger.error(f"Error stopping Telegram bot: {e}", exc_info=True)
    
    async def send_message(self, session_id: str, message: str) -> None:
        """Send a message to a Telegram chat.
        
        Args:
            session_id: Session ID (e.g., "telegram:dm:123456")
            message: Message content to send
        """
        # Parse session ID to get chat ID
        parts = session_id.split(":")
        if len(parts) < 3 or parts[0] != "telegram":
            raise ValueError(f"Invalid Telegram session ID: {session_id}")
        
        chat_id = int(parts[2])
        
        # Chunk message if needed
        chunks = self._chunk_message(message)
        
        for chunk in chunks:
            try:
                await self.application.bot.send_message(
                    chat_id=chat_id,
                    text=chunk,
                    parse_mode="Markdown",
                )
            except Exception as e:
                logger.error(f"Failed to send message to {chat_id}: {e}")
                # Try without markdown parsing as fallback
                try:
                    await self.application.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                    )
                except Exception as e2:
                    logger.error(f"Failed to send message (fallback): {e2}")
                    raise
    
    def get_session_id(self, update: Update) -> str:
        """Generate session ID from Telegram update.
        
        Args:
            update: Telegram update object
            
        Returns:
            Session ID string
        """
        chat = update.effective_chat
        message = update.effective_message
        
        # DM (private chat)
        if chat.type == "private":
            return f"telegram:dm:{chat.id}"
        
        # Group or supergroup
        if chat.type in ("group", "supergroup"):
            # Check for forum topic
            if message and message.message_thread_id:
                return f"telegram:group:{chat.id}:topic:{message.message_thread_id}"
            return f"telegram:group:{chat.id}"
        
        # Channel
        if chat.type == "channel":
            return f"telegram:channel:{chat.id}"
        
        return f"telegram:unknown:{chat.id}"
    
    def _chunk_message(self, message: str) -> list[str]:
        """Split long message into chunks.
        
        Args:
            message: Message to chunk
            
        Returns:
            List of message chunks
        """
        limit = self.config.text_chunk_limit
        
        if len(message) <= limit:
            return [message]
        
        chunks = []
        remaining = message
        
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break
            
            # Find a good split point (newline or space)
            split_pos = limit
            newline_pos = remaining.rfind("\n", 0, limit)
            space_pos = remaining.rfind(" ", 0, limit)
            
            if newline_pos > limit * 0.8:
                split_pos = newline_pos + 1
            elif space_pos > limit * 0.8:
                split_pos = space_pos + 1
            
            chunks.append(remaining[:split_pos])
            remaining = remaining[split_pos:]
        
        return chunks
    
    async def _handle_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming text messages."""
        # Check if bot is unclaimed and message is pairing code
        if not self.bootstrap.is_claimed():
            message_text = update.message.text.strip()
            user_id = update.effective_user.id
            logger.info(
                "Pairing: unclaimed bot received message",
                extra={"user_id": user_id, "message_len": len(message_text)},
            )
            valid = self.bootstrap.validate_code(message_text, user_id)
            logger.info(
                "Pairing: validate_code result",
                extra={"user_id": user_id, "valid": valid},
            )
            if valid:
                await update.message.reply_text(
                    f"✅ You are now the owner of this Glitch instance!\n\n"
                    f"Use /help to see available commands."
                )
                return
            else:
                pairing_code = self.bootstrap.get_pairing_code()
                logger.warning(
                    "Pairing: replying not configured",
                    extra={"user_id": user_id, "instance_has_code": pairing_code is not None},
                )
                await update.message.reply_text(
                    f"❌ Bot not configured. Owner must send the pairing code first.\n\n"
                    f"Check the startup logs for the code."
                )
                return
        
        # Check access
        if not await self._check_access(update):
            return
        
        # Get session ID
        session_id = self.get_session_id(update)
        message_text = update.message.text
        
        # Process message with agent
        if self.agent:
            try:
                response = await self.agent.process_message(
                    prompt=message_text,
                    session_id=session_id,
                )
                
                # Send response
                if isinstance(response, dict) and "response" in response:
                    await self.send_message(session_id, response["response"])
                elif isinstance(response, str):
                    await self.send_message(session_id, response)
                else:
                    logger.error(f"Unexpected response type: {type(response)}")
                    await update.message.reply_text("❌ Internal error processing message")
            except Exception as e:
                logger.error(f"Error processing message: {e}", exc_info=True)
                await update.message.reply_text(f"❌ Error: {e}")
        else:
            await update.message.reply_text("⚠️ Agent not configured")
    
    async def _handle_photo_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming photo messages."""
        if not await self._check_access(update):
            return
        
        # Get the largest photo
        photo = update.message.photo[-1]
        
        # Check file size
        if photo.file_size and photo.file_size > self.config.media_max_mb * 1024 * 1024:
            await update.message.reply_text(
                f"❌ Image too large. Max size: {self.config.media_max_mb}MB"
            )
            return
        
        try:
            # Download photo
            file = await photo.get_file()
            file_bytes = await file.download_as_bytearray()
            
            # Convert to base64
            media_data = base64.b64encode(bytes(file_bytes)).decode("utf-8")
            
            # Get caption or use default prompt
            caption = update.message.caption or ""
            
            # Create media message
            media_message = TelegramMediaMessage(
                text=caption,
                media_type="photo",
                media_data=media_data,
                file_id=photo.file_id,
                file_size_bytes=photo.file_size,
            )
            
            # Process with agent
            await self._process_media_message(update, media_message)
        except Exception as e:
            logger.error(f"Error handling photo: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error processing image: {e}")
    
    async def _handle_document_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle incoming document messages (images as documents)."""
        if not await self._check_access(update):
            return
        
        document = update.message.document
        
        # Check if it's an image
        if not document.mime_type or not document.mime_type.startswith("image/"):
            await update.message.reply_text("ℹ️ Only image documents are supported")
            return
        
        # Check file size
        if document.file_size > self.config.media_max_mb * 1024 * 1024:
            await update.message.reply_text(
                f"❌ File too large. Max size: {self.config.media_max_mb}MB"
            )
            return
        
        try:
            # Download document
            file = await document.get_file()
            file_bytes = await file.download_as_bytearray()
            
            # Convert to base64
            media_data = base64.b64encode(bytes(file_bytes)).decode("utf-8")
            
            # Get caption or use default prompt
            caption = update.message.caption or ""
            
            # Create media message
            media_message = TelegramMediaMessage(
                text=caption,
                media_type="document",
                media_data=media_data,
                file_id=document.file_id,
                file_size_bytes=document.file_size,
            )
            
            # Process with agent
            await self._process_media_message(update, media_message)
        except Exception as e:
            logger.error(f"Error handling document: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Error processing document: {e}")
    
    async def _process_media_message(self, update: Update, media: TelegramMediaMessage) -> None:
        """Process a media message with the agent.
        
        Args:
            update: Telegram update
            media: TelegramMediaMessage with image data
        """
        session_id = self.get_session_id(update)
        
        # Build prompt based on whether caption is present
        if media.text:
            prompt = f"[Image attached] {media.text}"
        else:
            prompt = "[Image attached] Please describe this image in detail."
        
        # Process with agent
        if self.agent:
            try:
                # Note: The agent should detect the [Image attached] prefix and
                # use the vision_agent tool automatically
                response = await self.agent.process_message(
                    prompt=prompt,
                    session_id=session_id,
                    image_data=media.media_data,  # Pass base64 image data
                )
                
                # Send response
                if isinstance(response, dict) and "response" in response:
                    await self.send_message(session_id, response["response"])
                elif isinstance(response, str):
                    await self.send_message(session_id, response)
                else:
                    logger.error(f"Unexpected response type: {type(response)}")
                    await update.message.reply_text("❌ Internal error processing image")
            except Exception as e:
                logger.error(f"Error processing media message: {e}", exc_info=True)
                await update.message.reply_text(f"❌ Error: {e}")
        else:
            await update.message.reply_text("⚠️ Agent not configured")
    
    async def _check_access(self, update: Update) -> bool:
        """Check if user/group has access to the bot.
        
        Args:
            update: Telegram update
            
        Returns:
            True if access granted, False otherwise
        """
        chat = update.effective_chat
        user = update.effective_user
        message = update.effective_message
        
        # Owner always has access
        if self.bootstrap.is_owner(user.id):
            return True
        
        # DM (private chat)
        if chat.type == "private":
            policy = self.config.dm_policy
            
            if policy == "disabled":
                await update.message.reply_text("❌ DMs are disabled")
                return False
            
            if policy == "open":
                return True
            
            if policy == "allowlist":
                if user.id in self.config.dm_allowlist:
                    return True
                await update.message.reply_text(
                    f"❌ Access denied. Your user ID: `{user.id}`",
                    parse_mode="Markdown",
                )
                return False
            
            if policy == "pairing":
                # Generate pairing code for new user
                await update.message.reply_text(
                    f"❌ Access denied. Contact the bot owner to get access.\n"
                    f"Your user ID: `{user.id}`",
                    parse_mode="Markdown",
                )
                return False
        
        # Group chat
        if chat.type in ("group", "supergroup"):
            policy = self.config.group_policy
            
            if policy == "disabled":
                return False
            
            # Check mention requirement
            if self.config.require_mention:
                bot_username = (await self.application.bot.get_me()).username
                if not message or not message.text or f"@{bot_username}" not in message.text:
                    return False
            
            if policy == "open":
                return True
            
            if policy == "allowlist":
                if chat.id in self.config.group_allowlist:
                    return True
                return False
        
        return False
