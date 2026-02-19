"""HTTP server for AgentCore Runtime integration (placeholder)."""

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def run_server(agent: Any):
    """
    Run Glitch agent as an HTTP server for AgentCore Runtime.
    
    This is a placeholder for future AgentCore HTTP protocol implementation.
    The actual implementation will follow AgentCore Runtime HTTP contract.
    
    Args:
        agent: GlitchAgent instance
    """
    logger.info("HTTP server mode not yet implemented")
    logger.info("This will be implemented following AgentCore Runtime HTTP protocol")
    logger.info("For now, use interactive mode or deploy to AgentCore Runtime directly")
    
    raise NotImplementedError(
        "HTTP server for AgentCore Runtime not yet implemented. "
        "Use GLITCH_MODE=interactive for testing."
    )
