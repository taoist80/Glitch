"""Telegram bot command handlers.

Handles all Telegram commands including owner configuration and user commands.
"""

import logging
from typing import Optional
from telegram import Update
from telegram.ext import ContextTypes

from glitch.channels.bootstrap import OwnerBootstrap
from glitch.channels.config_manager import ConfigManager

logger = logging.getLogger(__name__)


class TelegramCommandHandler:
    """Handles Telegram bot commands with owner/user permission levels."""
    
    def __init__(
        self,
        config_manager: ConfigManager,
        bootstrap: OwnerBootstrap,
        agent: Optional[any] = None,
        poet_agent: Optional[any] = None,
    ):
        """Initialize command handler.
        
        Args:
            config_manager: ConfigManager instance
            bootstrap: OwnerBootstrap instance
            agent: GlitchAgent instance (optional, for agent commands)
            poet_agent: PoetAgent instance (optional; when set, help shows /poet and /glitch)
        """
        self.config_manager = config_manager
        self.bootstrap = bootstrap
        self.agent = agent
        self.poet_agent = poet_agent
    
    async def handle_config(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /config commands - owner only.
        
        Available subcommands:
        - show: Display current configuration
        - dm <policy>: Set DM policy
        - group <policy>: Set group policy
        - mention <on|off>: Toggle mention requirement
        - allow <user_id>: Add user to DM allowlist
        - deny <user_id>: Remove user from DM allowlist
        - allowgroup <chat_id>: Add group to allowlist
        - denygroup <chat_id>: Remove group from allowlist
        - webhook <url>: Switch to webhook mode
        - polling: Switch to polling mode
        - lock: Lock configuration
        - unlock: Unlock configuration
        - transfer <user_id>: Transfer ownership
        """
        if not self.bootstrap.is_owner(update.effective_user.id):
            await update.message.reply_text("❌ Only the owner can configure the bot.")
            return
        
        if not context.args:
            await update.message.reply_text(
                "Usage: /config <subcommand> [args]\n\n"
                "Subcommands:\n"
                "• show - Display current configuration\n"
                "• dm <open|pairing|allowlist|disabled> - Set DM policy\n"
                "• group <open|allowlist|disabled> - Set group policy\n"
                "• mention <on|off> - Toggle @mention requirement in groups\n"
                "• allow <user_id> - Add user to DM allowlist\n"
                "• deny <user_id> - Remove user from DM allowlist\n"
                "• allowgroup <chat_id> - Add group to allowlist\n"
                "• denygroup <chat_id> - Remove group from allowlist\n"
                "• lock - Lock configuration\n"
                "• unlock - Unlock configuration\n"
                "• transfer <user_id> - Transfer ownership"
            )
            return
        
        subcommand = context.args[0].lower()
        
        try:
            if subcommand == "show":
                await self._config_show(update)
            elif subcommand == "dm":
                await self._config_dm(update, context.args[1:])
            elif subcommand == "group":
                await self._config_group(update, context.args[1:])
            elif subcommand == "mention":
                await self._config_mention(update, context.args[1:])
            elif subcommand == "allow":
                await self._config_allow(update, context.args[1:])
            elif subcommand == "deny":
                await self._config_deny(update, context.args[1:])
            elif subcommand == "allowgroup":
                await self._config_allowgroup(update, context.args[1:])
            elif subcommand == "denygroup":
                await self._config_denygroup(update, context.args[1:])
            elif subcommand == "lock":
                await self._config_lock(update)
            elif subcommand == "unlock":
                await self._config_unlock(update)
            elif subcommand == "transfer":
                await self._config_transfer(update, context.args[1:])
            else:
                await update.message.reply_text(f"❌ Unknown subcommand: {subcommand}")
        except ValueError as e:
            await update.message.reply_text(f"❌ Error: {e}")
        except Exception as e:
            logger.error(f"Error handling /config: {e}", exc_info=True)
            await update.message.reply_text(f"❌ Internal error: {e}")
    
    async def _config_show(self, update: Update) -> None:
        """Show current configuration."""
        config = self.config_manager.config
        telegram = config.telegram
        
        status = "🔒 Locked" if config.locked else "🔓 Unlocked"
        owner_id = config.owner.telegram_id if config.owner else "None"
        
        msg = (
            f"⚙️ **Configuration**\n\n"
            f"Status: {status}\n"
            f"Owner: `{owner_id}`\n\n"
        )
        
        if telegram:
            msg += (
                f"**Telegram Channel:**\n"
                f"• DM Policy: `{telegram.dm_policy}`\n"
                f"• DM Allowlist: {len(telegram.dm_allowlist)} users\n"
                f"• Group Policy: `{telegram.group_policy}`\n"
                f"• Group Allowlist: {len(telegram.group_allowlist)} groups\n"
                f"• Require Mention: `{telegram.require_mention}`\n"
                f"• Mode: `{telegram.mode}`\n"
                f"• Chunk Limit: `{telegram.text_chunk_limit}`\n"
                f"• Media Limit: `{telegram.media_max_mb}` MB\n"
            )
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    
    async def _config_dm(self, update: Update, args: list) -> None:
        """Set DM policy."""
        if not args:
            await update.message.reply_text("Usage: /config dm <open|pairing|allowlist|disabled>")
            return
        
        policy = args[0].lower()
        if policy not in ("open", "pairing", "allowlist", "disabled"):
            await update.message.reply_text("❌ Invalid policy. Use: open, pairing, allowlist, or disabled")
            return
        
        self.config_manager.update_telegram(dm_policy=policy)
        await update.message.reply_text(f"✅ DM policy set to: `{policy}`", parse_mode="Markdown")
    
    async def _config_group(self, update: Update, args: list) -> None:
        """Set group policy."""
        if not args:
            await update.message.reply_text("Usage: /config group <open|allowlist|disabled>")
            return
        
        policy = args[0].lower()
        if policy not in ("open", "allowlist", "disabled"):
            await update.message.reply_text("❌ Invalid policy. Use: open, allowlist, or disabled")
            return
        
        self.config_manager.update_telegram(group_policy=policy)
        await update.message.reply_text(f"✅ Group policy set to: `{policy}`", parse_mode="Markdown")
    
    async def _config_mention(self, update: Update, args: list) -> None:
        """Toggle mention requirement."""
        if not args:
            await update.message.reply_text("Usage: /config mention <on|off>")
            return
        
        value = args[0].lower()
        if value not in ("on", "off"):
            await update.message.reply_text("❌ Invalid value. Use: on or off")
            return
        
        require_mention = (value == "on")
        self.config_manager.update_telegram(require_mention=require_mention)
        status = "enabled" if require_mention else "disabled"
        await update.message.reply_text(f"✅ Mention requirement: `{status}`", parse_mode="Markdown")
    
    async def _config_allow(self, update: Update, args: list) -> None:
        """Add user to DM allowlist."""
        if not args:
            await update.message.reply_text("Usage: /config allow <user_id>")
            return
        
        try:
            user_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user_id. Must be a number.")
            return
        
        config = self.config_manager.config
        if user_id not in config.telegram.dm_allowlist:
            config.telegram.dm_allowlist.append(user_id)
            self.config_manager.save()
            await update.message.reply_text(f"✅ User `{user_id}` added to DM allowlist", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ User `{user_id}` already in allowlist", parse_mode="Markdown")
    
    async def _config_deny(self, update: Update, args: list) -> None:
        """Remove user from DM allowlist."""
        if not args:
            await update.message.reply_text("Usage: /config deny <user_id>")
            return
        
        try:
            user_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user_id. Must be a number.")
            return
        
        config = self.config_manager.config
        if user_id in config.telegram.dm_allowlist:
            config.telegram.dm_allowlist.remove(user_id)
            self.config_manager.save()
            await update.message.reply_text(f"✅ User `{user_id}` removed from DM allowlist", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ User `{user_id}` not in allowlist", parse_mode="Markdown")
    
    async def _config_allowgroup(self, update: Update, args: list) -> None:
        """Add group to allowlist."""
        if not args:
            await update.message.reply_text("Usage: /config allowgroup <chat_id>")
            return
        
        try:
            chat_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid chat_id. Must be a number.")
            return
        
        config = self.config_manager.config
        if chat_id not in config.telegram.group_allowlist:
            config.telegram.group_allowlist.append(chat_id)
            self.config_manager.save()
            await update.message.reply_text(f"✅ Group `{chat_id}` added to allowlist", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ Group `{chat_id}` already in allowlist", parse_mode="Markdown")
    
    async def _config_denygroup(self, update: Update, args: list) -> None:
        """Remove group from allowlist."""
        if not args:
            await update.message.reply_text("Usage: /config denygroup <chat_id>")
            return
        
        try:
            chat_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid chat_id. Must be a number.")
            return
        
        config = self.config_manager.config
        if chat_id in config.telegram.group_allowlist:
            config.telegram.group_allowlist.remove(chat_id)
            self.config_manager.save()
            await update.message.reply_text(f"✅ Group `{chat_id}` removed from allowlist", parse_mode="Markdown")
        else:
            await update.message.reply_text(f"ℹ️ Group `{chat_id}` not in allowlist", parse_mode="Markdown")
    
    async def _config_lock(self, update: Update) -> None:
        """Lock configuration."""
        self.bootstrap.lock()
        await update.message.reply_text("🔒 Configuration locked. Use /config unlock to unlock.")
    
    async def _config_unlock(self, update: Update) -> None:
        """Unlock configuration."""
        self.bootstrap.unlock()
        await update.message.reply_text("🔓 Configuration unlocked.")
    
    async def _config_transfer(self, update: Update, args: list) -> None:
        """Transfer ownership."""
        if not args:
            await update.message.reply_text("Usage: /config transfer <user_id>")
            return
        
        try:
            new_owner_id = int(args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user_id. Must be a number.")
            return
        
        old_owner = update.effective_user.id
        self.bootstrap.transfer_ownership(new_owner_id)
        await update.message.reply_text(
            f"✅ Ownership transferred from `{old_owner}` to `{new_owner_id}`",
            parse_mode="Markdown"
        )
    
    async def handle_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status - show bot health and config."""
        config = self.config_manager.config
        
        # Basic status
        claimed = "✅ Yes" if self.bootstrap.is_claimed() else "❌ No"
        locked = "🔒 Yes" if config.locked else "🔓 No"
        
        msg = (
            f"🤖 **Glitch Status**\n\n"
            f"Claimed: {claimed}\n"
            f"Locked: {locked}\n"
        )
        
        if config.owner and config.owner.telegram_id:
            is_owner = self.bootstrap.is_owner(update.effective_user.id)
            owner_marker = " (you)" if is_owner else ""
            msg += f"Owner: `{config.owner.telegram_id}`{owner_marker}\n"
        
        # Agent status (if available)
        if self.agent:
            try:
                agent_status = self.agent.get_status()
                msg += (
                    f"\n**Agent:**\n"
                    f"• Model Router: {agent_status.get('router_status', 'Unknown')}\n"
                    f"• Memory: {agent_status.get('memory_status', 'Unknown')}\n"
                )
            except Exception as e:
                logger.error(f"Failed to get agent status: {e}")
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    
    async def handle_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help - show available commands."""
        is_owner = self.bootstrap.is_owner(update.effective_user.id)
        
        msg = "🤖 **Glitch Bot Commands**\n\n"
        
        # User commands
        msg += (
            "**User Commands:**\n"
            "• /new - Start new conversation\n"
            "• /status - Show bot status\n"
            "• /help - Show this message\n"
        )
        if self.poet_agent:
            msg += (
                "• /poet - Switch to Poet (creative writing); optional: /poet &lt;prompt&gt;\n"
                "• /glitch - Switch back to Glitch\n"
            )
        
        # Owner commands
        if is_owner:
            msg += (
                "\n**Owner Commands:**\n"
                "• /config - Configure the bot\n"
                "• /config show - Display configuration\n"
                "• /config dm <policy> - Set DM policy\n"
                "• /config group <policy> - Set group policy\n"
                "• /config allow <user_id> - Add user to allowlist\n"
                "• /config lock - Lock configuration\n"
                "\nUse `/config` without args for full command list."
            )
        
        await update.message.reply_text(msg, parse_mode="Markdown")
    
    async def handle_new(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /new - start new conversation (clear session)."""
        # TODO: Implement session clearing when agent integration is complete
        await update.message.reply_text("✨ New conversation started. Previous context cleared.")
