"""HTTP server for AgentCore Runtime integration.

Uses BedrockAgentCoreApp from bedrock_agentcore.runtime which provides:
- Built-in /ping and /invocations endpoints
- Automatic request context handling (session ID, request ID)
- WebSocket support
- Async task tracking for health status
- Proper error handling and JSON serialization

Additional REST API endpoints are provided via FastAPI router for the UI:
- /api/status - Agent status
- /api/telegram/config - Telegram configuration
- /api/ollama/health - Ollama health
- /api/memory/summary - Memory state
- /api/mcp/servers - MCP servers
- /api/skills - Skills management

Dataflow:
    HTTP Request -> BedrockAgentCoreApp -> invoke() -> GlitchAgent.process_message()
                                                              |
                                                              v
                                                    InvocationResponse -> HTTP Response
"""

import logging
from typing import Optional, AsyncIterator

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext

from glitch.types import (
    InvocationRequest,
    InvocationResponse,
    ServerConfig,
    create_error_response,
    create_keepalive_response,
)

logger = logging.getLogger(__name__)

# Type alias for the agent to avoid circular imports
# The actual type is GlitchAgent from glitch.agent
GlitchAgentType = "GlitchAgent"

# Global agent instance
_agent: Optional[GlitchAgentType] = None

# Create the AgentCore app
app = BedrockAgentCoreApp()


async def _handle_ui_api_request(api_request: dict) -> dict:
    """Handle UI API requests routed through invocations.

    This allows the UI to access API endpoints when connecting via agentcore invoke
    (proxy mode) instead of direct HTTP to the container.

    Args:
        api_request: Dict with path, method, and optional body

    Returns:
        API response as a dict
    """
    # Import the handler functions directly from the router module
    from glitch.api.router import (
        get_status,
        get_telegram_config,
        update_telegram_config,
        get_ollama_health,
        get_memory_summary,
        get_mcp_servers,
        get_skills,
        toggle_skill,
    )

    path = api_request.get("path", "")
    method = api_request.get("method", "GET").upper()
    body = api_request.get("body")

    logger.info(f"UI API request: {method} {path}")

    try:
        # Route to the appropriate handler
        if path == "/status" and method == "GET":
            result = await get_status()
            return result.model_dump()

        elif path == "/telegram/config" and method == "GET":
            result = await get_telegram_config()
            return result.model_dump()

        elif path == "/telegram/config" and method == "POST":
            from glitch.api.types import TelegramConfigUpdate
            update = TelegramConfigUpdate(**(body or {}))
            result = await update_telegram_config(update)
            return result.model_dump()

        elif path == "/ollama/health" and method == "GET":
            result = await get_ollama_health()
            return result.model_dump()

        elif path == "/memory/summary" and method == "GET":
            result = await get_memory_summary()
            return result.model_dump()

        elif path == "/mcp/servers" and method == "GET":
            result = await get_mcp_servers()
            return result.model_dump()

        elif path == "/skills" and method == "GET":
            result = await get_skills()
            return result.model_dump()
            
        elif path.startswith("/skills/") and path.endswith("/toggle") and method == "POST":
            skill_id = path.split("/")[2]
            from glitch.api.types import SkillToggleRequest
            toggle_req = SkillToggleRequest(**(body or {}))
            result = await toggle_skill(skill_id, toggle_req)
            return result.model_dump()
            
        else:
            return {"error": f"Unknown API endpoint: {method} {path}"}
            
    except Exception as e:
        logger.error(f"UI API request error: {e}", exc_info=True)
        return {"error": str(e)}


def _setup_api_routes() -> None:
    """Mount the API router for UI endpoints.
    BedrockAgentCoreApp is Starlette-based (no include_router); we mount a FastAPI sub-app at /api.
    """
    from fastapi import FastAPI
    from glitch.api.router import router, setup_api, add_cors_middleware

    if _agent is not None:
        setup_api(_agent)

    api_app = FastAPI(title="Glitch API", openapi_url=None)
    add_cors_middleware(api_app)
    api_app.include_router(router)
    app.mount("/api", api_app)
    logger.info("API routes mounted at /api")


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
    
    Special payloads:
        - {"_ui_api_request": {"path": "/status", "method": "GET"}} - Handle UI API requests
    """
    global _agent
    
    # Handle UI API requests (for proxy mode)
    if "_ui_api_request" in payload:
        return await _handle_ui_api_request(payload["_ui_api_request"])
    
    prompt_preview = (payload.get("prompt") or "")[:80]
    logger.info("Received invocation: prompt=%s session_id=%s", repr(prompt_preview), payload.get("session_id"))

    # Keepalive from scheduled Lambda to avoid idleRuntimeSessionTimeout (default 15 min).
    session_id = payload.get("session_id") or ""
    if session_id == "system:keepalive":
        prompt = (payload.get("prompt") or "").strip().lower()
        if prompt in ("", "ping", "keepalive"):
            logger.debug("Keepalive received, skipping agent")
            sid = _agent.session_id if _agent else ""
            mid = _agent.memory_id if _agent else ""
            return create_keepalive_response(session_id=sid, memory_id=mid)

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
    
    # Optional streaming: when payload has "stream": true, yield events (AgentCore best practice).
    if payload.get("stream"):
        async def stream_events() -> AsyncIterator[dict]:
            try:
                async for event in _agent.process_message_stream(prompt):
                    yield event
            except Exception as e:
                logger.error("Error in streaming invocation: %s", e, exc_info=True)
                yield {"error": str(e)}
        return stream_events()

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
    try:
        from glitch.api.router import setup_api
        setup_api(agent)
    except ModuleNotFoundError as e:
        if "fastapi" in str(e).lower():
            raise ModuleNotFoundError(
                "fastapi is required for server mode (/api routes). "
                "Add 'fastapi>=0.115.0' to agent/requirements.txt and rebuild the container."
            ) from e
        raise


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
    
    Additional UI API endpoints at /api/*
    
    Args:
        agent: GlitchAgent instance
        config: ServerConfig with host, port, debug settings.
                If None, uses defaults (0.0.0.0:8080).
    """
    if config is None:
        config = ServerConfig()
    
    set_agent(agent)
    _setup_api_routes()
    
    logger.info(f"Starting AgentCore HTTP server on {config.host}:{config.port}")
    logger.info(f"Session ID: {agent.session_id}")
    logger.info(f"Memory ID: {agent.memory_id}")
    logger.info(f"UI API available at http://{config.host}:{config.port}/api")
    
    app.run(port=config.port, host=config.host)


def _disable_uvicorn_access_log() -> None:
    """Disable Uvicorn request (access) logs so GET /ping etc. are not printed."""
    import logging
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.setLevel(logging.WARNING)
    uvicorn_access.disabled = True


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

    _disable_uvicorn_access_log()
    
    if config is None:
        config = ServerConfig()
    
    set_agent(agent)
    _setup_api_routes()
    
    logger.info(f"Starting AgentCore HTTP server on {config.host}:{config.port}")
    logger.info(f"Session ID: {agent.session_id}")
    logger.info(f"Memory ID: {agent.memory_id}")
    logger.info(f"UI API available at http://{config.host}:{config.port}/api")
    
    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_level="debug" if config.debug else "info",
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()
