"""Telegram channel adapter implementation.

Provides Telegram integration for Glitch using python-telegram-bot.
Supports both polling and webhook modes, with session isolation,
access controls, and media handling.
"""

import base64
import logging
import io
import os
from typing import Any, Dict, Optional

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
from glitch.channels.types import AccessContext, TelegramConfig, TelegramMediaMessage
from glitch.channels.bot_policy import check_access
from glitch.channels.bootstrap import OwnerBootstrap
from glitch.channels.config_manager import ConfigManager
from glitch.channels.telegram_commands import TelegramCommandHandler
from glitch.agent_registry import get_agent as registry_get_agent, get_default_agent_id
from glitch.modes import apply_mode_to_prompt, apply_mode_with_memories, MODE_DEFAULT, MODE_POET, MODE_ROLEPLAY

logger = logging.getLogger(__name__)

# Minimum chunk size before sending a Telegram message when streaming (AgentCore best practice).
_STREAM_CHUNK_MIN_CHARS = 400


async def _consume_stream_and_send(
    send_message_fn,
    session_id: str,
    stream,
    update,
    reply_error_fn,
) -> None:
    """Consume process_message_stream events; send chunks to Telegram; handle errors."""
    buffer = ""
    try:
        async for event in stream:
            if isinstance(event, dict) and "error" in event:
                await reply_error_fn(f"❌ Error: {event['error']}")
                return
            if isinstance(event, dict) and "data" in event:
                buffer += event.get("data") or ""
                while len(buffer) >= _STREAM_CHUNK_MIN_CHARS or (
                    "\n" in buffer and buffer.strip()
                ):
                    idx = buffer.find("\n", 0, _STREAM_CHUNK_MIN_CHARS + 1)
                    if idx < 0:
                        idx = min(_STREAM_CHUNK_MIN_CHARS, len(buffer))
                    else:
                        idx += 1
                    chunk = buffer[:idx].rstrip() if idx < len(buffer) else buffer[:idx]
                    buffer = buffer[idx:]
                    if chunk:
                        await send_message_fn(session_id, chunk)
        if buffer.strip():
            await send_message_fn(session_id, buffer.strip())
    except Exception as e:
        logger.error("Error consuming stream: %s", e, exc_info=True)
        await reply_error_fn(f"❌ Error: {e}")


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
        agent: Optional[Any] = None,
        poet_agent: Optional[Any] = None,
    ):
        """Initialize Telegram channel.
        
        Args:
            config_manager: ConfigManager instance
            bootstrap: OwnerBootstrap instance
            agent: GlitchAgent instance (optional)
            poet_agent: PoetAgent instance (optional); when set, /poet and /glitch enable routing
        """
        self.config_manager = config_manager
        self.bootstrap = bootstrap
        self.agent = agent
        self.poet_agent = poet_agent  # kept for optional one-shot /poet <prompt>; routing uses registry + mode
        self._session_agent: Dict[str, str] = {}  # session_id -> agent_id (glitch | mistral | llava)
        self._session_mode: Dict[str, str] = {}   # session_id -> mode_id (default | poet | roleplay)
        self.config = config_manager.config.telegram

        if not self.config or not self.config.bot_token:
            raise ValueError("Telegram bot token not configured")

        self.command_handler = TelegramCommandHandler(
            config_manager=config_manager,
            bootstrap=bootstrap,
            agent=agent,
            poet_agent=poet_agent,
        )
        
        # Initialize application
        self.application = Application.builder().token(self.config.bot_token).build()
        
        # Register handlers
        self._register_handlers()
        
        logger.info(f"Telegram channel initialized (mode: {self.config.mode})")
    
    def _get_agent_id(self, session_id: str) -> str:
        """Return agent_id for this session (default from registry)."""
        return self._session_agent.get(session_id) or get_default_agent_id()

    def _get_mode_id(self, session_id: str) -> str:
        """Return mode_id for this session."""
        return self._session_mode.get(session_id) or MODE_DEFAULT

    def _get_agent(self, session_id: str) -> Optional[Any]:
        """Return the agent instance for this session (from registry)."""
        agent_id = self._get_agent_id(session_id)
        a = registry_get_agent(agent_id)
        return a if a is not None else self.agent

    async def _handle_poet_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /poet — set mode to Poet; optionally run one message in poet mode."""
        if not await self._check_access(update):
            return
        session_id = self.get_session_id(update)
        self._session_mode[session_id] = MODE_POET
        logger.info("Session mode selected", extra={"session_id": session_id, "mode_id": MODE_POET, "channel": "telegram"})
        if context.args:
            prompt = " ".join(context.args)
            prompt_out, system_prompt_out = apply_mode_to_prompt(MODE_POET, prompt, system_prompt=None)
            agent = self._get_agent(session_id)
            if agent:
                try:
                    response = await agent.process_message(
                        prompt_out, session_id=session_id, system_prompt=system_prompt_out
                    )
                    text = response.get("message") if isinstance(response, dict) else str(response)
                    if text:
                        await self.send_message(session_id, text)
                    else:
                        await update.message.reply_text("❌ No response.")
                except Exception as e:
                    logger.error("Poet mode command error: %s", e, exc_info=True)
                    await update.message.reply_text(f"❌ Error: {e}")
            else:
                await update.message.reply_text("❌ No agent available.")
        else:
            await update.message.reply_text(
                "Poet mode on. Send me a theme, a line, or a mood and I'll write for you. Use /default to switch back."
            )

    async def _handle_glitch_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /glitch — set session agent to Glitch."""
        if not await self._check_access(update):
            return
        session_id = self.get_session_id(update)
        self._session_agent[session_id] = "glitch"
        logger.info("Session agent selected", extra={"session_id": session_id, "agent_id": "glitch", "channel": "telegram"})
        await update.message.reply_text("Switched to Glitch.")

    async def _handle_mistral_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /mistral — set session agent to Mistral."""
        if not await self._check_access(update):
            return
        session_id = self.get_session_id(update)
        self._session_agent[session_id] = "mistral"
        logger.info("Session agent selected", extra={"session_id": session_id, "agent_id": "mistral", "channel": "telegram"})
        await update.message.reply_text("Switched to Mistral.")

    async def _handle_llava_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /llava — set session agent to LLaVA (vision)."""
        if not await self._check_access(update):
            return
        session_id = self.get_session_id(update)
        self._session_agent[session_id] = "llava"
        logger.info("Session agent selected", extra={"session_id": session_id, "agent_id": "llava", "channel": "telegram"})
        await update.message.reply_text("Switched to LLaVA (vision).")

    async def _handle_auri_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /auri — set mode to Roleplay (Auri persona)."""
        if not await self._check_access(update):
            return
        session_id = self.get_session_id(update)
        self._session_mode[session_id] = MODE_ROLEPLAY
        logger.info("Session mode selected", extra={"session_id": session_id, "mode_id": MODE_ROLEPLAY, "channel": "telegram"})
        if context.args:
            prompt = " ".join(context.args)
            active_members = self._get_participant_ids(update)
            prompt_out, system_prompt_out, mode_context = await apply_mode_with_memories(
                MODE_ROLEPLAY, prompt, system_prompt=None, session_id=session_id,
                active_members=active_members,
            )
            agent = self._get_agent(session_id)
            if agent:
                try:
                    response = await agent.process_message(
                        prompt_out, session_id=session_id, system_prompt=system_prompt_out,
                        mode_context=mode_context,
                    )
                    text = response.get("message") if isinstance(response, dict) else str(response)
                    if text:
                        await self.send_message(session_id, text)
                    else:
                        await update.message.reply_text("No response.")
                except Exception as e:
                    logger.error("Auri mode command error: %s", e, exc_info=True)
                    await update.message.reply_text(f"Error: {e}")
            else:
                await update.message.reply_text("No agent available.")
        else:
            await update.message.reply_text(
                "Auri mode on. Aurelion is here. Use /default to switch back."
            )

    async def _handle_default_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /default or /normal — set mode to default."""
        if not await self._check_access(update):
            return
        session_id = self.get_session_id(update)
        self._session_mode[session_id] = MODE_DEFAULT
        logger.info("Session mode selected", extra={"session_id": session_id, "mode_id": MODE_DEFAULT, "channel": "telegram"})
        await update.message.reply_text("Switched to default mode.")

    async def _handle_haltprotect_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /haltprotect — immediately stop all Protect subsystem components."""
        if not await self._check_access(update):
            return
        try:
            import main as _main
            stopped = await _main.halt_protect()
            lines = ["🛑 Protect subsystem halted."]
            if stopped["pollers"]:
                lines.append(f"Pollers stopped: {', '.join(stopped['pollers'])}")
            if stopped["processors"]:
                lines.append(f"Processors stopped: {', '.join(stopped['processors'])}")
            if stopped["patrols"]:
                lines.append(f"Patrols stopped: {', '.join(stopped['patrols'])}")
            if stopped["tasks"]:
                lines.append(f"Tasks cancelled: {', '.join(stopped['tasks'])}")
            if not any([stopped["pollers"], stopped["processors"], stopped["patrols"], stopped["tasks"]]):
                lines.append("(Nothing was running.)")
            await update.message.reply_text("\n".join(lines))
        except Exception as e:
            logger.error("haltprotect command error: %s", e, exc_info=True)
            await update.message.reply_text(f"❌ Error halting Protect: {e}")

    def _register_handlers(self) -> None:
        """Register message and command handlers."""
        # Command handlers
        self.application.add_handler(CommandHandler("config", self.command_handler.handle_config))
        self.application.add_handler(CommandHandler("status", self.command_handler.handle_status))
        self.application.add_handler(CommandHandler("help", self.command_handler.handle_help))
        self.application.add_handler(CommandHandler("start", self.command_handler.handle_help))
        self.application.add_handler(CommandHandler("new", self.command_handler.handle_new))
        self.application.add_handler(CommandHandler("poet", self._handle_poet_command))
        self.application.add_handler(CommandHandler("auri", self._handle_auri_command))
        self.application.add_handler(CommandHandler("glitch", self._handle_glitch_command))
        self.application.add_handler(CommandHandler("mistral", self._handle_mistral_command))
        self.application.add_handler(CommandHandler("llava", self._handle_llava_command))
        self.application.add_handler(CommandHandler("default", self._handle_default_command))
        self.application.add_handler(CommandHandler("normal", self._handle_default_command))
        self.application.add_handler(CommandHandler("haltprotect", self._handle_haltprotect_command))

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
                # Webhook mode: we always use an external webhook (e.g. Lambda). This process does not
                # run a local webhook server; Telegram sends updates to the configured URL.
                if not self.config.webhook_url:
                    logger.info(
                        "Telegram webhook mode but no webhook_url set; external endpoint will receive updates."
                    )
                else:
                    logger.info(
                        "Webhook mode: updates will be received by external endpoint: %s",
                        self.config.webhook_url,
                    )
                return

            logger.info("Telegram bot started successfully")
        except Exception as e:
            logger.error(f"Failed to start Telegram bot: {e}", exc_info=True)
            raise
    
    async def stop(self) -> None:
        """Stop the Telegram bot gracefully.
        In webhook mode the updater is never started; only polling mode starts it.
        We never call updater.stop() in webhook mode and swallow 'not running' so
        shutdown does not mask the real error (e.g. missing fastapi).
        """
        try:
            logger.info("Stopping Telegram bot")
            if self.config.mode == "polling":
                try:
                    await self.application.updater.stop()
                except RuntimeError as e:
                    if "not running" not in str(e).lower():
                        raise
                    logger.debug("Updater was not running, skipping updater.stop()")
            else:
                # Webhook mode: updater was never started; do not call updater.stop().
                pass
            try:
                await self.application.stop()
                await self.application.shutdown()
            except Exception as e:
                logger.warning("Error during application stop/shutdown: %s", e)
            logger.info("Telegram bot stopped")
        except Exception as e:
            logger.error("Error stopping Telegram bot: %s", e, exc_info=True)
    
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

    def _get_participant_ids(self, update: Update) -> list[str]:
        """Derive participant_id list from the Telegram sender.

        Uses first_name (lowercased, spaces stripped) as the participant_id, falling
        back to username. This matches how profiles are stored via store_session_moment /
        update_participant_profile (e.g. "rusty", "arc").
        """
        user = update.effective_user
        if not user:
            return []
        # Prefer first_name (e.g. "Rusty") over username (e.g. "rusty_pup").
        # Take only the first word so "Rusty Puppy" → "rusty" (matches stored profile key).
        raw = (user.first_name or user.username or "").strip()
        name = raw.split()[0].lower() if raw else ""
        if not name:
            return []
        return [name]

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
        
        # Get session ID and resolve agent + mode
        session_id = self.get_session_id(update)
        message_text = update.message.text
        mode_id = self._get_mode_id(session_id)
        active_members = self._get_participant_ids(update)
        prompt_out, system_prompt_out, mode_context = await apply_mode_with_memories(
            mode_id, message_text, system_prompt=None, session_id=session_id,
            active_members=active_members,
        )

        agent = self._get_agent(session_id)
        if agent:
            try:
                if hasattr(agent, "process_message_stream"):
                    stream = agent.process_message_stream(prompt_out, mode_context=mode_context)
                    await _consume_stream_and_send(
                        self.send_message,
                        session_id,
                        stream,
                        update,
                        lambda msg: update.message.reply_text(msg),
                    )
                    return
                response = await agent.process_message(
                    prompt_out, session_id=session_id, system_prompt=system_prompt_out,
                    mode_context=mode_context,
                )
                # Send response (InvocationResponse uses "message" key)
                if isinstance(response, dict):
                    text = response.get("message") or response.get("response")
                    if text is not None:
                        await self.send_message(session_id, text)
                    else:
                        logger.error("Response dict missing message/key")
                        await update.message.reply_text("❌ Internal error processing message")
                elif isinstance(response, str):
                    await self.send_message(session_id, response)
                else:
                    logger.error("Unexpected response type: %s", type(response))
                    await update.message.reply_text("❌ Internal error processing message")
            except Exception as e:
                logger.error("Error processing message: %s", e, exc_info=True)
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
        if media.text:
            prompt = f"[Image attached] {media.text}"
        else:
            prompt = "[Image attached] Please describe this image in detail."
        mode_id = self._get_mode_id(session_id)
        active_members = self._get_participant_ids(update)
        prompt_out, system_prompt_out, mode_context = await apply_mode_with_memories(
            mode_id, prompt, system_prompt=None, session_id=session_id,
            active_members=active_members,
        )
        image_urls = None
        if media.media_data:
            image_urls = [f"data:image/jpeg;base64,{media.media_data}"]

        agent = self._get_agent(session_id)
        if agent:
            try:
                if hasattr(agent, "process_message_stream"):
                    stream = agent.process_message_stream(prompt_out, mode_context=mode_context)
                    await _consume_stream_and_send(
                        self.send_message,
                        session_id,
                        stream,
                        update,
                        lambda msg: update.message.reply_text(msg),
                    )
                    return
                kwargs = {"session_id": session_id, "system_prompt": system_prompt_out, "mode_context": mode_context}
                if image_urls is not None and hasattr(agent, "process_message"):
                    import inspect
                    sig = inspect.signature(agent.process_message)
                    if "image_urls" in sig.parameters:
                        kwargs["image_urls"] = image_urls
                response = await agent.process_message(prompt_out, **kwargs)
                if isinstance(response, dict):
                    text = response.get("message") or response.get("response")
                    if text is not None:
                        await self.send_message(session_id, text)
                    else:
                        logger.error("Response dict missing message/key")
                        await update.message.reply_text("❌ Internal error processing image")
                elif isinstance(response, str):
                    await self.send_message(session_id, response)
                else:
                    logger.error("Unexpected response type: %s", type(response))
                    await update.message.reply_text("❌ Internal error processing image")
            except Exception as e:
                logger.error("Error processing media message: %s", e, exc_info=True)
                await update.message.reply_text(f"❌ Error: {e}")
        else:
            await update.message.reply_text("⚠️ Agent not configured")
    
    async def _check_access(self, update: Update) -> bool:
        """Check if user/group has access to the bot via bot_policy.
        
        Builds AccessContext from the update, calls check_access(), then sends
        any denial message and returns the result.
        """
        chat = update.effective_chat
        user = update.effective_user
        message = update.effective_message
        owner_id = self.config.owner_id if self.config else None

        message_mentions_bot = False
        if chat and chat.type in ("group", "supergroup") and message and message.text:
            me = await self.application.bot.get_me()
            bot_username = (me.username or "").lower()
            message_mentions_bot = bot_username and f"@{bot_username}" in (message.text or "").lower()

        ctx = AccessContext(
            chat_type=chat.type if chat else "unknown",
            user_id=user.id if user else 0,
            chat_id=chat.id if chat else 0,
            owner_id=owner_id,
            message_mentions_bot=message_mentions_bot,
        )
        result = check_access(ctx, self.config)

        if result.allowed:
            return True
        if result.denial_message:
            await update.message.reply_text(
                result.denial_message,
                parse_mode="Markdown",
            )
        return False
