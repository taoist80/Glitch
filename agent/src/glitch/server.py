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
        get_protect_summary,
        get_protect_entities,
        get_protect_events,
        get_protect_alerts,
        get_protect_patterns,
        get_auri_channels,
        get_auri_dm_users,
        get_auri_profiles,
        get_auri_persona_core,
        put_auri_persona_core,
        get_auri_persona_rules,
        put_auri_persona_rules,
        get_auri_memory_stats,
        get_auri_character_card,
    )

    path = (api_request.get("path") or "").rstrip("/")
    if path.startswith("/api/") and len(path) > 5:
        path = "/" + path[5:]
    method = api_request.get("method", "GET").upper()
    body = api_request.get("body")
    query_params = api_request.get("query_params") or {}

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

        # --- Auri endpoints ---
        elif path == "/auri/channels" and method == "GET":
            result = await get_auri_channels()
            return result.model_dump()

        elif path == "/auri/dm-users" and method == "GET":
            result = await get_auri_dm_users()
            return result.model_dump()

        elif path == "/auri/profiles" and method == "GET":
            result = await get_auri_profiles()
            return result.model_dump()

        elif path == "/auri/persona/core" and method == "GET":
            result = await get_auri_persona_core()
            return result.model_dump()

        elif path == "/auri/persona/core" and method == "PUT":
            from glitch.api.auri_types import AuriPersonaUpdate
            update = AuriPersonaUpdate(**(body or {}))
            result = await put_auri_persona_core(update)
            return result.model_dump()

        elif path == "/auri/persona/rules" and method == "GET":
            result = await get_auri_persona_rules()
            return result.model_dump()

        elif path == "/auri/persona/rules" and method == "PUT":
            from glitch.api.auri_types import AuriPersonaUpdate
            update = AuriPersonaUpdate(**(body or {}))
            result = await put_auri_persona_rules(update)
            return result.model_dump()

        elif path == "/auri/memory-stats" and method == "GET":
            result = await get_auri_memory_stats()
            return result.model_dump()

        elif path == "/auri/export/character-card" and method == "GET":
            return await get_auri_character_card()

        elif path.startswith("/protect/") and method == "GET":
            def _int(name: str, default: int) -> int:
                v = query_params.get(name)
                if v is None:
                    return default
                try:
                    return int(v) if isinstance(v, str) else int(v)
                except (TypeError, ValueError):
                    return default

            def _bool(name: str, default: bool) -> bool:
                v = query_params.get(name)
                if v is None:
                    return default
                if isinstance(v, bool):
                    return v
                if isinstance(v, str):
                    return v.lower() in ("1", "true", "yes")
                return bool(v)

            if path == "/protect/summary":
                result = await get_protect_summary()
            elif path == "/protect/entities":
                result = await get_protect_entities(limit=_int("limit", 50))
            elif path == "/protect/events":
                result = await get_protect_events(hours=_int("hours", 24), limit=_int("limit", 30))
            elif path == "/protect/alerts":
                result = await get_protect_alerts(limit=_int("limit", 20), unack_only=_bool("unack_only", False))
            elif path == "/protect/patterns":
                result = await get_protect_patterns(limit=_int("limit", 20))
            else:
                return {"error": f"Unknown protect endpoint: {path}"}
            return result.model_dump()

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

    logger.info("_setup_ui_routes: getting UI paths")
    sys.stdout.flush()
    
    ui_mode = os.getenv("GLITCH_UI_MODE", "local")
    ui_dir, ui_dist = get_ui_paths()
    
    logger.info("_setup_ui_routes: ui_mode=%s ui_dir=%s ui_dist_exists=%s", ui_mode, ui_dir, ui_dist.is_dir())
    sys.stdout.flush()

    # Skip auto-build in AgentCore container - UI is hosted separately via CloudFront
    is_agentcore = os.path.exists("/app") or "agentcore" in os.getenv("AWS_EXECUTION_ENV", "").lower()
    
    # Auto-build UI if dist doesn't exist and we're not in dev mode and not in AgentCore
    if ui_mode != "dev" and not ui_dist.is_dir() and not is_agentcore:
        logger.info("_setup_ui_routes: auto-building UI")
        sys.stdout.flush()
        auto_build_ui(ui_dir, verbose=False)

    if ui_mode != "dev" and ui_dist.is_dir():
        logger.info("_setup_ui_routes: mounting UI at /ui")
        sys.stdout.flush()
        app.mount("/ui", StaticFiles(directory=str(ui_dist), html=True), name="ui")
        logger.info("UI dashboard mounted at /ui")
        
        # Add root redirect to /ui for convenience
        async def redirect_to_ui(request):
            return RedirectResponse(url="/ui", status_code=302)
        app.add_route("/", redirect_to_ui, methods=["GET"])
        logger.info("Root redirect to /ui enabled")
    elif ui_mode != "dev":
        logger.info("_setup_ui_routes: UI dist not found, skipping mount")
        sys.stdout.flush()

    logger.info("_setup_ui_routes: adding debug routes")
    sys.stdout.flush()
    
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
    
    logger.info("_setup_ui_routes: complete")
    sys.stdout.flush()


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
        session_id = payload.get("session_id") or ""
        _mode_hint = (payload.get("mode_id") or "").strip().lower()
        if _mode_hint == "roleplay":
            logger.info("Received invocation: prompt=[roleplay] session_id=%s", session_id)
        else:
            prompt_preview = (payload.get("prompt") or "")[:80]
            logger.info("Received invocation: prompt=%s session_id=%s", repr(prompt_preview), session_id)
        sys.stdout.flush()

        invoke_step = "check_keepalive"
        # Keepalive from scheduled Lambda to avoid idleRuntimeSessionTimeout (default 15 min).
        if session_id.startswith("system:keepalive"):
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

        # System command interception — handle before mode/agent routing so the
        # AI model never sees these. Matches both the raw Telegram command text
        # ("/haltprotect") and the clean sentinel dispatched by the webhook Lambda.
        invoke_step = "system_commands"
        _cmd = prompt.strip().lower().split()[0] if prompt.strip() else ""
        if _cmd in ("/haltprotect", "__system:halt_protect"):
            try:
                import main as _main
                stopped = await _main.halt_protect()
                lines = ["🛑 Protect subsystem halted."]
                if stopped.get("pollers"):
                    lines.append(f"Pollers stopped: {', '.join(stopped['pollers'])}")
                if stopped.get("processors"):
                    lines.append(f"Processors stopped: {', '.join(stopped['processors'])}")
                if stopped.get("patrols"):
                    lines.append(f"Patrols stopped: {', '.join(stopped['patrols'])}")
                if stopped.get("tasks"):
                    lines.append(f"Tasks cancelled: {', '.join(stopped['tasks'])}")
                if not any(stopped.get(k) for k in ("pollers", "processors", "patrols", "tasks")):
                    lines.append("(Nothing was running.)")
                from glitch.types import InvocationResponse
                from glitch.types import create_empty_metrics
                return InvocationResponse(
                    message="\n".join(lines),
                    session_id=session_id,
                    memory_id="",
                    metrics=create_empty_metrics(),
                )
            except Exception as exc:
                logger.error("system_command halt_protect failed: %s", exc, exc_info=True)
                return create_error_response(
                    error=f"halt_protect failed: {exc}", session_id=session_id, memory_id=""
                )

        if _cmd in ("/stop", "__system:shutdown"):
            import signal
            from glitch.types import InvocationResponse, create_empty_metrics
            logger.warning("system_command: shutdown requested — sending SIGTERM in 1.5s")
            # Schedule SIGTERM after response is returned and transmitted.
            loop = asyncio.get_event_loop()
            loop.call_later(1.5, lambda: os.kill(os.getpid(), signal.SIGTERM))
            return InvocationResponse(
                message="🔴 Glitch shutting down. AgentCore will restart the runtime automatically.",
                session_id=session_id,
                memory_id="",
                metrics=create_empty_metrics(),
            )

        invoke_step = "resolve_agent_and_mode"
        from glitch.agent_registry import get_agent as registry_get_agent, get_default_agent_id
        from glitch.modes import apply_mode_with_memories, MODE_DEFAULT
        agent_id = (payload.get("agent_id") or "").strip().lower() or get_default_agent_id()
        mode_id = (payload.get("mode_id") or "").strip().lower() or MODE_DEFAULT
        # Optional: caller can specify who's in the session for profile retrieval.
        # Accepts "participant_id" (string) or "active_members" (list of strings).
        participant_id = (payload.get("participant_id") or "").strip().lower()
        active_members_raw = payload.get("active_members")
        if participant_id:
            active_members = [participant_id]
        elif isinstance(active_members_raw, list):
            active_members = [p.strip().lower() for p in active_members_raw if p]
        else:
            active_members = None

        # Telegram moderation context: set per-invocation context for moderation tools
        chat_id_raw = int(payload.get("chat_id") or 0)
        from_user_id = int(payload.get("from_user_id") or 0)
        message_id_raw = int(payload.get("message_id") or 0)
        is_group = ":group:" in session_id if session_id else False

        from glitch.invocation_context import set_context, clear_context
        set_context(
            chat_id=chat_id_raw,
            from_user_id=from_user_id,
            message_id=message_id_raw,
            session_id=session_id,
            participant_id=participant_id,
            is_group=is_group,
        )

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

        prompt_out, system_prompt_out, mode_context = await apply_mode_with_memories(
            mode_id, prompt, system_prompt=None, session_id=session_id,
            active_members=active_members,
        )
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
                from glitch.modes import MODE_ROLEPLAY as _MR
                _stream_model_override = "haiku" if mode_id == _MR else None
                async def stream_events() -> AsyncIterator[dict]:
                    try:
                        async for event in agent.process_message_stream(prompt_out, mode_context=mode_context, model_override=_stream_model_override):
                            yield event
                    except Exception as e:
                        logger.error("Error in streaming invocation: %s", e, exc_info=True)
                        yield {"error": f"invoke_step=streaming: {e}"}
                return stream_events()
            # No streaming for this agent; fall through to non-stream

        invoke_step = "call_process_message"
        from glitch.modes import MODE_ROLEPLAY
        _model_override = "haiku" if mode_id == MODE_ROLEPLAY else None
        _max_turns = 5 if mode_id == MODE_ROLEPLAY else None
        response = await agent.process_message(
            prompt_out,
            session_id=session_id,
            system_prompt=system_prompt_out,
            mode_context=mode_context,
            model_override=_model_override,
            max_turns=_max_turns,
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
    finally:
        # Always clear invocation context after request completes
        from glitch.invocation_context import clear_context
        clear_context()


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

    logger.info("run_server_async: disabling uvicorn access log")
    sys.stdout.flush()
    _disable_uvicorn_access_log()
    
    if config is None:
        config = ServerConfig()
    
    logger.info("run_server_async: calling set_agent")
    sys.stdout.flush()
    set_agent(agent)
    
    logger.info("run_server_async: calling _setup_api_routes")
    sys.stdout.flush()
    _setup_api_routes()
    
    logger.info("run_server_async: calling _setup_ui_routes")
    sys.stdout.flush()
    _setup_ui_routes()
    
    logger.info("run_server_async: setup complete, starting uvicorn")
    sys.stdout.flush()
    
    logger.info("Starting AgentCore HTTP server on %s:%s", config.host, config.port)
    logger.info("Session ID: %s", agent.session_id)
    logger.info("Memory ID: %s", agent.memory_id)
    logger.info("UI API available at http://%s:%s/api", config.host, config.port)
    sys.stdout.flush()

    uvicorn_config = uvicorn.Config(
        app,
        host=config.host,
        port=config.port,
        log_level="debug" if config.debug else "info",
        access_log=False,
    )
    server = uvicorn.Server(uvicorn_config)
    await server.serve()
