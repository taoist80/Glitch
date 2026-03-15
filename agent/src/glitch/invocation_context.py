"""Per-invocation context for Glitch.

Set by server.py before each agent invocation, read by moderation tools.
Safe because AgentCore processes one invocation at a time per container.

Usage:
    # In server.py invoke():
    set_context(chat_id=12345, from_user_id=67890, message_id=111, ...)
    try:
        result = await agent.process_message(...)
    finally:
        clear_context()

    # In moderation tools:
    ctx = get_context()
    if not ctx.chat_id:
        return "error: no chat context"
"""

from dataclasses import dataclass


@dataclass
class InvocationContext:
    """Per-invocation metadata set by server.py, read by tools."""

    chat_id: int = 0
    from_user_id: int = 0
    message_id: int = 0
    session_id: str = ""
    participant_id: str = ""
    is_group: bool = False


_ctx: InvocationContext = InvocationContext()


def set_context(**kwargs: object) -> None:
    """Replace the current invocation context."""
    global _ctx
    _ctx = InvocationContext(**kwargs)  # type: ignore[arg-type]


def get_context() -> InvocationContext:
    """Read the current invocation context."""
    return _ctx


def clear_context() -> None:
    """Reset to empty context after invocation completes."""
    global _ctx
    _ctx = InvocationContext()
