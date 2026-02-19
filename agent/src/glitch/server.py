"""HTTP server for AgentCore Runtime integration.

Uses BedrockAgentCoreApp from bedrock_agentcore.runtime which provides:
- Built-in /ping and /invocations endpoints
- Automatic request context handling (session ID, request ID)
- WebSocket support
- Async task tracking for health status
- Proper error handling and JSON serialization

Dataflow:
    HTTP Request -> BedrockAgentCoreApp -> invoke() -> GlitchAgent.process_message()
                                                              |
                                                              v
                                                    InvocationResponse -> HTTP Response
"""

import logging
from typing import Optional

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext

from glitch.types import (
    InvocationRequest,
    InvocationResponse,
    ServerConfig,
    create_error_response,
)

logger = logging.getLogger(__name__)

# Type alias for the agent to avoid circular imports
# The actual type is GlitchAgent from glitch.agent
GlitchAgentType = "GlitchAgent"

# Global agent instance
_agent: Optional[GlitchAgentType] = None

# Create the AgentCore app
app = BedrockAgentCoreApp()


@app.entrypoint
async def invoke(payload: InvocationRequest, context: RequestContext) -> InvocationResponse:
    """Main invocation entrypoint for AgentCore Runtime.
    
    Dataflow:
        InvocationRequest -> GlitchAgent.process_message() -> InvocationResponse
    
    Args:
        payload: InvocationRequest containing {"prompt": "user message", ...}
        context: RequestContext with session_id, request_headers, etc.
    
    Returns:
        InvocationResponse with message, metrics, and session info
    """
    global _agent
    
    if _agent is None:
        return create_error_response(
            error="Agent not initialized",
            session_id="",
            memory_id="",
        )
    
    prompt = payload.get("prompt", "")
    
    if not prompt:
        return create_error_response(
            error="No prompt provided",
            session_id=_agent.session_id,
            memory_id=_agent.memory_id,
        )
    
    try:
        response: InvocationResponse = await _agent.process_message(prompt)
        return response
        
    except Exception as e:
        logger.error(f"Error processing invocation: {e}", exc_info=True)
        return create_error_response(
            error=str(e),
            session_id=_agent.session_id if _agent else "",
            memory_id=_agent.memory_id if _agent else "",
        )


def set_agent(agent: GlitchAgentType) -> None:
    """Set the global agent instance.
    
    Args:
        agent: GlitchAgent instance to use for invocations
    """
    global _agent
    _agent = agent
    logger.info(f"Agent set for session: {agent.session_id}")


def get_agent() -> Optional[GlitchAgentType]:
    """Get the current global agent instance.
    
    Returns:
        GlitchAgent instance or None if not set
    """
    return _agent


def run_server(agent: GlitchAgentType, config: Optional[ServerConfig] = None) -> None:
    """Run Glitch agent as an HTTP server for AgentCore Runtime.
    
    Uses BedrockAgentCoreApp which automatically handles:
    - /ping health checks
    - /invocations endpoint
    - /ws WebSocket endpoint
    - Request context propagation
    
    Args:
        agent: GlitchAgent instance
        config: ServerConfig with host, port, debug settings.
                If None, uses defaults (0.0.0.0:8080).
    """
    if config is None:
        config = ServerConfig()
    
    set_agent(agent)
    
    logger.info(f"Starting AgentCore HTTP server on {config.host}:{config.port}")
    logger.info(f"Session ID: {agent.session_id}")
    logger.info(f"Memory ID: {agent.memory_id}")
    
    app.run(port=config.port, host=config.host)


async def run_server_async(
    agent: GlitchAgentType,
    config: Optional[ServerConfig] = None,
) -> None:
    """Async version of run_server for use with asyncio.run().
    
    Args:
        agent: GlitchAgent instance
        config: ServerConfig with host, port, debug settings.
                If None, uses defaults (0.0.0.0:8080).
    """
    import uvicorn
    
    if config is None:
        config = ServerConfig()
    
    set_agent(agent)
    
    logger.info(f"Starting AgentCore HTTP server on {config.host}:{config.port}")
    logger.info(f"Session ID: {agent.session_id}")
    logger.info(f"Memory ID: {agent.memory_id}")
    
    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_level="debug" if config.debug else "info",
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()
