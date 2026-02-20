"""Bot access policy: who can DM, when to respond in groups.

Centralizes all access and policy logic so dataflows are explicit and testable.
Inputs: TelegramConfig + AccessContext (or primitives).
Outputs: AccessResult (allowed + optional denial message).

Used by: TelegramChannel (_check_access), TelegramCommandHandler (owner checks).
"""

from typing import Optional

from glitch.channels.types import (
    AccessContext,
    AccessResult,
    TelegramConfig,
)


def is_owner(user_id: int, owner_id: Optional[int]) -> bool:
    """True if user_id is the bot owner."""
    return owner_id is not None and user_id == owner_id


def check_dm_access(
    user_id: int,
    config: TelegramConfig,
    owner_id: Optional[int],
) -> AccessResult:
    """Determine if a user may send DMs to the bot.

    Policy order: owner always allowed; then dm_policy (disabled, open, allowlist, pairing).
    """
    if is_owner(user_id, owner_id):
        return AccessResult(allowed=True)

    policy = config.dm_policy
    if policy == "disabled":
        return AccessResult(allowed=False, denial_message="❌ DMs are disabled")
    if policy == "open":
        return AccessResult(allowed=True)
    if policy == "allowlist":
        if user_id in config.dm_allowlist:
            return AccessResult(allowed=True)
        return AccessResult(
            allowed=False,
            denial_message=f"❌ Access denied. Your user ID: `{user_id}`",
        )
    # pairing: only owner can DM until they add others via allowlist
    return AccessResult(
        allowed=False,
        denial_message=(
            f"❌ Access denied. Contact the bot owner to get access.\n"
            f"Your user ID: `{user_id}`"
        ),
    )


def check_group_access(
    chat_id: int,
    config: TelegramConfig,
    message_mentions_bot: bool,
) -> AccessResult:
    """Determine if the bot should respond in a group/supergroup.

    When require_mention is True, message_mentions_bot must be True.
    group_policy: disabled (never), open (always if mention satisfied), allowlist (chat_id in list).
    Returns silent deny (no message) when we simply ignore the message.
    """
    policy = config.group_policy
    if policy == "disabled":
        return AccessResult(allowed=False)

    if config.require_mention and not message_mentions_bot:
        return AccessResult(allowed=False)  # silent: don't reply

    if policy == "open":
        return AccessResult(allowed=True)
    if policy == "allowlist":
        return AccessResult(allowed=chat_id in config.group_allowlist)

    return AccessResult(allowed=False)


def check_access(ctx: AccessContext, config: TelegramConfig) -> AccessResult:
    """Single entry point: check access for private or group from AccessContext."""
    if ctx.chat_type == "private":
        return check_dm_access(ctx.user_id, config, ctx.owner_id)
    if ctx.chat_type in ("group", "supergroup"):
        return check_group_access(ctx.chat_id, config, ctx.message_mentions_bot)
    # channel or other
    return AccessResult(allowed=False)
