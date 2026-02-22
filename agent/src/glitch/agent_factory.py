"""Factory for creating chat agents (Glitch, Mistral, LLaVA) and registering with the registry."""

import logging
import os
from typing import Optional

from glitch.agent_registry import register_agent, get_default_agent_id, get_allowed_agent_ids
from glitch.agent import create_glitch_agent as _create_glitch_agent
from glitch.agent import GlitchAgent
from glitch.mistral_agent import MistralAgent
from glitch.llava_agent import LLaVAAgent
from glitch.local_model_types import MISTRAL_HOST, LLAVA_HOST

logger = logging.getLogger(__name__)

ENV_DEFAULT_AGENT = "GLITCH_DEFAULT_CHAT_AGENT"


def create_glitch_agent(
    session_id: Optional[str] = None,
    memory_id: Optional[str] = None,
    region: Optional[str] = None,
    window_size: int = 20,
) -> GlitchAgent:
    """Create a Glitch orchestrator agent and log creation."""
    agent = _create_glitch_agent(
        session_id=session_id,
        memory_id=memory_id,
        region=region,
        window_size=window_size,
    )
    sid = getattr(agent, "session_id", None) or session_id or "unknown"
    logger.info(
        "Created agent",
        extra={"agent_id": "glitch", "session_id": sid},
    )
    return agent


def create_mistral_agent(
    host: str = MISTRAL_HOST,
    port: Optional[int] = None,
    model: Optional[str] = None,
) -> MistralAgent:
    """Create a Mistral chat agent (one per process)."""
    agent = MistralAgent(host=host, port=port, model=model)
    logger.info(
        "Created agent",
        extra={"agent_id": "mistral", "model": agent.model, "host": host},
    )
    return agent


def create_llava_agent(
    host: str = LLAVA_HOST,
    port: Optional[int] = None,
    model: Optional[str] = None,
) -> LLaVAAgent:
    """Create a LLaVA vision agent (one per process)."""
    agent = LLaVAAgent(host=host, port=port, model=model)
    logger.info(
        "Created agent",
        extra={"agent_id": "llava", "model": agent.model, "host": host},
    )
    return agent


def bootstrap_agents_and_register() -> GlitchAgent:
    """Create Glitch, Mistral, and LLaVA; register all three; set default from env. Returns Glitch agent."""
    from glitch.agent_registry import set_default_agent_id

    glitch = create_glitch_agent()
    mistral = create_mistral_agent()
    llava = create_llava_agent()

    register_agent("glitch", glitch, {"name": "Glitch", "description": "Primary orchestrator (Strands + Bedrock)"})
    register_agent("mistral", mistral, {"name": "Mistral", "description": "Local chat (mistral-nemo-12b)"})
    register_agent("llava", llava, {"name": "LLaVA", "description": "Vision (image processing)"})

    default_id = os.getenv(ENV_DEFAULT_AGENT, "mistral").strip().lower()
    if default_id not in get_allowed_agent_ids():
        default_id = "mistral"
    set_default_agent_id(default_id)
    logger.info(
        "Registered agents: glitch, mistral, llava; default=%s",
        default_id,
        extra={"default_agent_id": default_id},
    )
    return glitch
