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
import os
import sys
from pathlib import Path
from typing import Any, AsyncIterator, Optional, Union

from bedrock_agentcore.runtime import BedrockAgentCoreApp, RequestContext
from starlette.responses import JSONResponse

from glitch.types import (
    InvocationRequest,
    InvocationResponse,
    ServerConfig,
    UiApiRequest,
    create_error_response,
    create_keepalive_response,
)

# Entrypoint return types:
# - InvocationResponse: Normal chat response
# - dict[str, Any]: UI API proxy response (from _ui_api_request)
# - AsyncIterator[dict]: Streaming response (when payload["stream"] is True)
InvocationEntrypointResult = Union[InvocationResponse, dict[str, Any], AsyncIterator[dict[str, Any]]]

logger = logging.getLogger(__name__)

# Type alias for the agent to avoid circular imports
# The actual type is GlitchAgent from glitch.agent
GlitchAgentType = "GlitchAgent"

# Global agent instance (primary Glitch; used when no registry or agent_id resolved)
_agent: Optional[GlitchAgentType] = None

# Create the AgentCore app
app = BedrockAgentCoreApp()


async def _handle_ui_api_request(api_request: UiApiRequest) -> dict:
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
        get_telemetry,
        get_mcp_servers,
        get_skills,
        toggle_skill,
        get_streaming_info,
        list_agents_api,
        get_session_agent,
        put_session_agent,
        get_session_mode,
        put_session_mode,
        list_modes,
    )

    path = api_request.get("path", "")
    method = api_request.get("method", "GET").upper()
    body = api_request.get("body")

    logger.info("UI API request: %s %s", method, path)

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

        elif path == "/telemetry" and method == "GET":
            result = await get_telemetry()
            return result.model_dump()

        elif path == "/streaming-info" and method == "GET":
            result = await get_streaming_info()
            return result.model_dump()

        elif path == "/mcp/servers" and method == "GET":
            result = await get_mcp_servers()
            return result.model_dump()

        elif path == "/skills" and method == "GET":
            result = await get_skills()
            return result.model_dump()
            
        elif path.startswith("/skills/") and path.endswith("/toggle") and method == "POST":
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "skills" and parts[-1] == "toggle":
                skill_id = parts[1]
                if not skill_id:
                    return {"error": "Missing skill_id in path"}
                from glitch.api.types import SkillToggleRequest
                toggle_req = SkillToggleRequest(**(body or {}))
                result = await toggle_skill(skill_id, toggle_req)
                return result.model_dump()
            return {"error": f"Invalid path: {path}"}

        elif path == "/agents" and method == "GET":
            result = await list_agents_api()
            return result.model_dump()

        elif path == "/modes" and method == "GET":
            result = await list_modes()
            return result.model_dump()

        elif path.startswith("/sessions/") and "/agent" in path and path.rstrip("/").endswith("/agent"):
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "sessions" and parts[-1] == "agent":
                session_id = parts[1]
                if method == "GET":
                    result = await get_session_agent(session_id)
                    return result.model_dump()
                if method == "PUT":
                    from glitch.api.types import SessionAgentUpdate
                    update = SessionAgentUpdate(**(body or {}))
                    result = await put_session_agent(session_id, update)
                    return result.model_dump()
            return {"error": f"Invalid path: {path}"}

        elif path.startswith("/sessions/") and "/mode" in path and path.rstrip("/").endswith("/mode"):
            parts = path.strip("/").split("/")
            if len(parts) >= 3 and parts[0] == "sessions" and parts[-1] == "mode":
                session_id = parts[1]
                if method == "GET":
                    result = await get_session_mode(session_id)
                    return result.model_dump()
                if method == "PUT":
                    from glitch.api.types import SessionModeUpdate
                    update = SessionModeUpdate(**(body or {}))
                    result = await put_session_mode(session_id, update)
                    return result.model_dump()
            return {"error": f"Invalid path: {path}"}

        else:
            return {"error": f"Unknown API endpoint: {method} {path}"}

    except Exception as e:
        logger.error("UI API request error: %s", e, exc_info=True)
        return {"error": str(e)}


def _setup_api_routes() -> None:
    """Mount the API router for UI endpoints.
    BedrockAgentCoreApp is Starlette-based (no include_router); we mount a FastAPI sub-app at /api.
    """
    from fastapi import FastAPI
    from glitch.api.router import router, setup_api, add_cors_middleware

    logger.info("Setting up API routes")

    if _agent is not None:
        setup_api(_agent)

    api_app = FastAPI(title="Glitch API", openapi_url=None)
    add_cors_middleware(api_app)
    api_app.include_router(router)
    app.mount("/api", api_app)
    logger.info("API routes mounted at /api")


def _setup_ui_routes() -> None:
    """Mount static UI routes when applicable.
    
    If ui/dist doesn't exist and pnpm is available, builds the UI automatically.
    """
    from starlette.staticfiles import StaticFiles
    from starlette.responses import RedirectResponse, JSONResponse
    from glitch.ui_build import get_ui_paths, auto_build_ui

    ui_mode = os.getenv("GLITCH_UI_MODE", "local")
    ui_dir, ui_dist = get_ui_paths()

    # Auto-build UI if dist doesn't exist and we're not in dev mode
    if ui_mode != "dev" and not ui_dist.is_dir():
        auto_build_ui(ui_dir, verbose=False)

    if ui_mode != "dev" and ui_dist.is_dir():
        app.mount("/ui", StaticFiles(directory=str(ui_dist), html=True), name="ui")
        logger.info("UI dashboard mounted at /ui")
        
        # Add root redirect to /ui for convenience
        async def redirect_to_ui(request):
            return RedirectResponse(url="/ui", status_code=302)
        app.add_route("/", redirect_to_ui, methods=["GET"])
        logger.info("Root redirect to /ui enabled")
    elif ui_mode != "dev":
        logger.warning("UI dist not found at %s; /ui will not be available", ui_dist)

    # Debug endpoint to list all routes
    async def debug_routes(request):
        routes_info = []
        for route in app.routes:
            route_info = {"path": getattr(route, "path", str(route)), "name": getattr(route, "name", None)}
            if hasattr(route, "methods"):
                route_info["methods"] = list(route.methods)
            routes_info.append(route_info)
        return JSONResponse({"routes": routes_info, "ui_mode": ui_mode})
    app.add_route("/debug/routes", debug_routes, methods=["GET"])


@app.entrypoint
async def invoke(payload: InvocationRequest, context: RequestContext) -> InvocationEntrypointResult:
    """Main invocation entrypoint for AgentCore Runtime.

    Dataflow:
        InvocationRequest -> GlitchAgent.process_message() -> InvocationResponse
        or _ui_api_request -> _handle_ui_api_request() -> dict (API response)

    Args:
        payload: InvocationRequest (prompt for chat, or _ui_api_request for API proxy).
        context: RequestContext with session_id, request_headers, etc.

    Returns:
        InvocationResponse for chat, or dict for _ui_api_request API responses.
    """
    global _agent
    invoke_step = "entry"
    agent_id = ""
    mode_id = ""
    session_id = ""

    try:
        invoke_step = "get_session_id"
        # Distinctive log for CloudWatch: confirms this container is handling invocations (search for GLITCH_INVOKE_ENTRY)
        session_id_val = payload.get("session_id") or ""
        logger.info("GLITCH_INVOKE_ENTRY session_id=%s has_ui_api=%s", session_id_val[:36] if session_id_val else "", "_ui_api_request" in payload)
        sys.stdout.flush()
        sys.stderr.flush()

        invoke_step = "check_ui_api"
        # Handle UI API requests (for Lambda UI backend)
        if "_ui_api_request" in payload:
            return await _handle_ui_api_request(payload["_ui_api_request"])
        
        invoke_step = "log_prompt"
        prompt_preview = (payload.get("prompt") or "")[:80]
        session_id = payload.get("session_id") or ""
        logger.info("Received invocation: prompt=%s session_id=%s", repr(prompt_preview), session_id)
        sys.stdout.flush()

        invoke_step = "check_keepalive"
        # Keepalive from scheduled Lambda to avoid idleRuntimeSessionTimeout (default 15 min).
        if session_id == "system:keepalive":
            prompt = (payload.get("prompt") or "").strip().lower()
            if prompt in ("", "ping", "keepalive"):
                logger.debug("Keepalive received, skipping agent")
                sid = _agent.session_id if _agent else ""
                mid = _agent.memory_id if _agent else ""
                return create_keepalive_response(session_id=sid, memory_id=mid)

        invoke_step = "check_agent"
        if _agent is None:
            return create_error_response(
                error="invoke_step=check_agent: Agent not initialized",
                session_id="",
                memory_id="",
            )

        invoke_step = "get_prompt"
        prompt = payload.get("prompt", "")
        if not prompt:
            fallback_agent = _agent
            return create_error_response(
                error="invoke_step=get_prompt: No prompt provided",
                session_id=getattr(fallback_agent, "session_id", "") if fallback_agent else "",
                memory_id=getattr(fallback_agent, "memory_id", "") if fallback_agent else "",
            )

        invoke_step = "resolve_agent_and_mode"
        from glitch.agent_registry import get_agent as registry_get_agent, get_default_agent_id
        from glitch.modes import apply_mode_to_prompt, MODE_DEFAULT
        agent_id = (payload.get("agent_id") or "").strip().lower() or get_default_agent_id()
        mode_id = (payload.get("mode_id") or "").strip().lower() or MODE_DEFAULT
        agent = registry_get_agent(agent_id)
        if agent is None:
            agent = _agent
        if agent is None:
            logger.error(
                "Agent not found",
                extra={"agent_id": agent_id, "session_id": session_id[:36] if session_id else ""},
            )
            return create_error_response(
                error=f"invoke_step=resolve_agent: agent_id={agent_id!r} not found",
                session_id=session_id,
                memory_id="",
            )

        prompt_out, system_prompt_out = apply_mode_to_prompt(mode_id, prompt, system_prompt=None)
        logger.info(
            "Invocation routed to agent",
            extra={
                "session_id": session_id[:36] if session_id else "",
                "agent_id": agent_id,
                "mode_id": mode_id,
                "prompt_len": len(prompt_out),
            },
        )

        invoke_step = "check_streaming"
        if payload.get("stream"):
            if hasattr(agent, "process_message_stream"):
                async def stream_events() -> AsyncIterator[dict]:
                    try:
                        async for event in agent.process_message_stream(prompt_out):
                            yield event
                    except Exception as e:
                        logger.error("Error in streaming invocation: %s", e, exc_info=True)
                        yield {"error": f"invoke_step=streaming: {e}"}
                return stream_events()
            # No streaming for this agent; fall through to non-stream

        invoke_step = "call_process_message"
        response = await agent.process_message(
            prompt_out,
            session_id=session_id,
            system_prompt=system_prompt_out,
        )

        invoke_step = "log_done"
        logger.info(
            "GLITCH_INVOKE_DONE session_id=%s agent_id=%s",
            session_id_val[:36] if session_id_val else "",
            agent_id,
            extra={"agent_id": agent_id, "mode_id": mode_id},
        )
        sys.stdout.flush()
        
        invoke_step = "return_response"
        return response

    except Exception as e:
        logger.error(
            "Error in invoke at invoke_step=%s: %s",
            invoke_step,
            e,
            exc_info=True,
            extra={"session_id": session_id[:36] if session_id else "", "agent_id": agent_id or None},
        )
        return create_error_response(
            error=f"invoke_step={invoke_step}: {e}",
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
    logger.info("Agent set for session: %s", agent.session_id)
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
    _setup_ui_routes()
    
    logger.info("Starting AgentCore HTTP server on %s:%s", config.host, config.port)
    logger.info("Session ID: %s", agent.session_id)
    logger.info("Memory ID: %s", agent.memory_id)
    logger.info("UI API available at http://%s:%s/api", config.host, config.port)

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
    _setup_ui_routes()
    
    logger.info("Starting AgentCore HTTP server on %s:%s", config.host, config.port)
    logger.info("Session ID: %s", agent.session_id)
    logger.info("Memory ID: %s", agent.memory_id)
    logger.info("UI API available at http://%s:%s/api", config.host, config.port)

    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_level="debug" if config.debug else "info",
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()
