"""Poet — creative writing sub-agent.

Uses Sonnet 4.5 and poet-soul.md only. No SOUL.md, no skills, no MCP, no memory.
Exposes process_message(user_message) -> InvocationResponse for Telegram and HTTP.
"""

import logging
from typing import Optional

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from glitch.poet_soul import load_poet_soul
from glitch.routing.model_router import MODEL_REGISTRY
from glitch.telemetry import extract_metrics_from_result
from glitch.types import (
    InvocationResponse,
    InvocationMetrics,
    create_empty_metrics,
    create_error_response,
)

logger = logging.getLogger(__name__)

POET_TECHNICAL_CONTEXT = """
You are Poet, a creative writing agent. Respond only with your writing or a brief meta-comment. You do not perform Glitch's technical or orchestration role.
"""


def build_poet_system_prompt() -> str:
    """Build system prompt from poet-soul.md and technical context."""
    soul = load_poet_soul()
    if soul:
        return f"{soul}\n\n{POET_TECHNICAL_CONTEXT}"
    return f"# Poet\n\nCreative writing agent. Respond with your writing only.\n\n{POET_TECHNICAL_CONTEXT}"


class PoetAgent:
    """Creative writing sub-agent. Uses Sonnet 4.5 and poet-soul.md."""

    def __init__(
        self,
        session_id: str = "poet-default",
        memory_id: str = "poet-memory",
        window_size: int = 10,
    ):
        """Initialize Poet agent.

        Args:
            session_id: Session identifier for responses.
            memory_id: Memory identifier for response shape compatibility.
            window_size: Sliding window size for conversation history.
        """
        self.session_id = session_id
        self.memory_id = memory_id
        model_config = MODEL_REGISTRY["poet"]
        system_prompt = build_poet_system_prompt()
        self.agent = Agent(
            name="poet",
            system_prompt=system_prompt,
            model=model_config.model_id,
            tools=[],
            conversation_manager=SlidingWindowConversationManager(window_size=window_size),
            trace_attributes={
                "agent.role": "poet",
                "agent.model": "sonnet-4.5",
                "session.id": session_id,
            },
        )
        logger.info("Initialized Poet agent (model=%s)", model_config.name)

    async def process_message(self, user_message: str) -> InvocationResponse:
        """Process a user message and return a writing response.

        Args:
            user_message: The user's prompt or theme.

        Returns:
            InvocationResponse with message, session_id, memory_id, metrics.
        """
        try:
            result = self.agent(user_message)
            metrics: InvocationMetrics = extract_metrics_from_result(result)
            return InvocationResponse(
                message=str(result),
                session_id=self.session_id,
                memory_id=self.memory_id,
                metrics=metrics,
            )
        except Exception as e:
            logger.error("Poet process_message error: %s", e)
            return create_error_response(
                error=str(e),
                session_id=self.session_id,
                memory_id=self.memory_id,
            )

    def get_status(self) -> dict:
        """Return a minimal status for compatibility with TelegramCommandHandler."""
        return {
            "agent": "poet",
            "model": "sonnet-4.5",
            "session_id": self.session_id,
        }


def create_poet_agent(
    session_id: Optional[str] = None,
    memory_id: Optional[str] = None,
) -> PoetAgent:
    """Create a PoetAgent with default or given config.

    Args:
        session_id: Optional session ID (default: poet-default).
        memory_id: Optional memory ID (default: poet-memory).

    Returns:
        Configured PoetAgent instance.
    """
    import os
    import uuid
    sid = session_id or os.getenv("GLITCH_POET_SESSION_ID", "poet-default")
    mid = memory_id or os.getenv("GLITCH_POET_MEMORY_ID", "poet-memory")
    return PoetAgent(session_id=sid, memory_id=mid)
