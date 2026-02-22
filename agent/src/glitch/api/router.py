"""FastAPI router for Glitch Agent UI REST API.

Provides endpoints for the dashboard UI to query agent state and configuration.
"""

import logging
import os
from typing import Optional, TYPE_CHECKING

from fastapi import APIRouter, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from glitch.api.types import (
    StatusResponse,
    TelegramConfigResponse,
    TelegramConfigUpdate,
    OllamaHealthResponse,
    OllamaHostHealth,
    MemorySummaryResponse,
    MCPServersResponse,
    MCPServerInfo,
    SkillsResponse,
    SkillInfo,
    SkillToggleRequest,
    SkillToggleResponse,
    TelemetryResponse,
    StreamingInfoResponse,
    AgentsResponse,
    AgentInfo,
    SessionAgentResponse,
    SessionAgentUpdate,
    SessionModeResponse,
    SessionModeUpdate,
    ModesResponse,
    ModeInfo,
)

if TYPE_CHECKING:
    from glitch.agent import GlitchAgent

logger = logging.getLogger(__name__)

# No prefix here: when mounted at /api on Starlette, paths are relative (e.g. /status).
router = APIRouter(prefix="", tags=["ui"])

_agent: Optional["GlitchAgent"] = None
_disabled_skills: set[str] = set()
_dynamodb_table = None


def _get_dynamodb_region() -> str:
    """Region for DynamoDB (required in AgentCore where default may be unset)."""
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"


def _get_dynamodb_table():
    """Get DynamoDB table for skill persistence (lazy init)."""
    global _dynamodb_table
    if _dynamodb_table is not None:
        return _dynamodb_table

    table_name = os.getenv("GLITCH_CONFIG_TABLE", "glitch-telegram-config")
    if not table_name:
        return None

    try:
        import boto3
        region = _get_dynamodb_region()
        dynamodb = boto3.resource("dynamodb", region_name=region)
        _dynamodb_table = dynamodb.Table(table_name)
        return _dynamodb_table
    except Exception as e:
        logger.debug("Failed to connect to DynamoDB for skill persistence: %s", e)
        return None


def _load_disabled_skills_from_dynamodb() -> set[str]:
    """Load disabled skills from DynamoDB."""
    table = _get_dynamodb_table()
    if not table:
        return set()
    
    try:
        response = table.get_item(Key={"pk": "SKILL_CONFIG", "sk": "disabled_skills"})
        if "Item" in response:
            return set(response["Item"].get("skill_ids", []))
    except Exception as e:
        logger.debug("Failed to load disabled skills from DynamoDB: %s", e)
    return set()


def _save_disabled_skills_to_dynamodb(disabled_skills: set[str]) -> bool:
    """Save disabled skills to DynamoDB."""
    table = _get_dynamodb_table()
    if not table:
        return False

    try:
        table.put_item(Item={
            "pk": "SKILL_CONFIG",
            "sk": "disabled_skills",
            "skill_ids": list(disabled_skills),
        })
        return True
    except Exception as e:
        logger.warning("Failed to save disabled skills to DynamoDB: %s", e)
        return False


# Session agent/mode: pk=SESSION_AGENT, sk=session_id, attributes agent_id, mode_id
def _get_session_agent_mode(session_id: str) -> tuple[str, str]:
    """Load agent_id and mode_id for session from DynamoDB. Returns (agent_id, mode_id)."""
    from glitch.agent_registry import get_default_agent_id
    from glitch.modes import MODE_DEFAULT
    table = _get_dynamodb_table()
    if not table:
        return get_default_agent_id(), MODE_DEFAULT
    try:
        response = table.get_item(Key={"pk": "SESSION_AGENT", "sk": session_id})
        if "Item" not in response:
            return get_default_agent_id(), MODE_DEFAULT
        item = response["Item"]
        return (
            item.get("agent_id") or get_default_agent_id(),
            item.get("mode_id") or MODE_DEFAULT,
        )
    except Exception as e:
        logger.debug("Failed to load session agent/mode from DynamoDB: %s", e)
        return get_default_agent_id(), MODE_DEFAULT


def _set_session_agent_mode(session_id: str, agent_id: Optional[str] = None, mode_id: Optional[str] = None) -> bool:
    """Save agent_id and/or mode_id for session to DynamoDB. Merges with existing."""
    table = _get_dynamodb_table()
    if not table:
        return False
    try:
        current_agent, current_mode = _get_session_agent_mode(session_id)
        new_agent = agent_id if agent_id is not None else current_agent
        new_mode = mode_id if mode_id is not None else current_mode
        table.put_item(Item={
            "pk": "SESSION_AGENT",
            "sk": session_id,
            "agent_id": new_agent,
            "mode_id": new_mode,
        })
        return True
    except Exception as e:
        logger.warning("Failed to save session agent/mode to DynamoDB: %s", e)
        return False


def setup_api(agent: "GlitchAgent") -> None:
    """Initialize the API with the agent instance.
    
    Args:
        agent: GlitchAgent instance to expose via API
    """
    global _agent, _disabled_skills
    _agent = agent
    
    # Load disabled skills from DynamoDB if available
    _disabled_skills = _load_disabled_skills_from_dynamodb()
    if _disabled_skills:
        logger.info("Loaded %d disabled skills from DynamoDB", len(_disabled_skills))
    
    logger.info("API router initialized with agent")


def _get_agent() -> "GlitchAgent":
    """Get the agent instance or raise 503."""
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return _agent


def _normalize_recent_events(events: list) -> list:
    """Flatten AgentCore get_last_k_turns output to List[Dict] for MemorySummaryResponse.

    get_last_k_turns() returns a list of turns; each turn can be a list of message dicts
    (or a single message dict). We flatten to one dict per message so recent_events is List[Dict[str, Any]].
    """
    out: list = []
    for item in events:
        if isinstance(item, list):
            for msg in item:
                if isinstance(msg, dict):
                    normalized = dict(msg)
                    # content may be {"text": "..."}; UI expects content as string
                    content = normalized.get("content")
                    if isinstance(content, dict) and "text" in content:
                        normalized["content"] = content["text"]
                    out.append(normalized)
        elif isinstance(item, dict):
            normalized = dict(item)
            content = normalized.get("content")
            if isinstance(content, dict) and "text" in content:
                normalized["content"] = content["text"]
            out.append(normalized)
    return out


def _ensure_recent_events_list_of_dicts(events: list) -> list:
    """Ensure recent_events is List[Dict]; flatten any nested lists (defensive)."""
    if not events:
        return []
    # If already flat list of dicts, only normalize content
    result: list = []
    for item in events:
        if isinstance(item, dict):
            result.append(_normalize_content_in_message(dict(item)))
        elif isinstance(item, list):
            for msg in item:
                if isinstance(msg, dict):
                    result.append(_normalize_content_in_message(dict(msg)))
    return result


def _normalize_content_in_message(msg: dict) -> dict:
    """Normalize message dict: content {"text": "..."} -> content as string."""
    out = dict(msg)
    content = out.get("content")
    if isinstance(content, dict) and "text" in content:
        out["content"] = content["text"]
    return out


def _sanitize_for_json(obj: object) -> object:
    """Convert to JSON-serializable types (avoid 500 from Pydantic/Starlette)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(x) for x in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        if obj != obj or abs(obj) == float("inf"):
            return 0
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, str):
        return obj
    return str(obj)


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Get overall agent status."""
    try:
        agent = _get_agent()
    except HTTPException:
        raise
    try:
        status = agent.get_status()
        mcp_status = agent.mcp_manager.get_status()
    except Exception as e:
        logger.exception("get_status failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Agent status error: {e}")
    
    routing = status.get("routing_stats") or {}
    memory = status.get("structured_memory") or {}
    
    return StatusResponse(
        session_id=str(status.get("session_id", "")),
        memory_id=str(status.get("memory_id", "")),
        connected=True,
        skills_loaded=int(status.get("skills_loaded", len(agent.skill_registry))),
        mcp_servers_connected=int(mcp_status.get("connected_clients", 0)),
        routing_stats=_sanitize_for_json(routing) if isinstance(routing, dict) else {},
        structured_memory=_sanitize_for_json(memory) if isinstance(memory, dict) else {},
    )


def _load_telegram_config_for_api():
    """Load Telegram config using same backend as main (DynamoDB in AWS, file locally).
    
    In webhook mode (AgentCore deployment), the agent container may not have DynamoDB
    permissions or the GLITCH_CONFIG_TABLE env var. We detect AgentCore deployment
    and return enabled=True since the webhook Lambda handles Telegram integration.
    """
    import os
    import boto3
    from botocore.exceptions import ClientError

    config_table = os.getenv("GLITCH_CONFIG_TABLE", "").strip()
    webhook_url_env = os.getenv("GLITCH_TELEGRAM_WEBHOOK_URL", "").strip()
    
    # Detect if we're running in AgentCore (container deployment)
    # AgentCore sets AWS_EXECUTION_ENV or we can check for /app directory
    is_agentcore = (
        os.path.exists("/app") or 
        "agentcore" in os.getenv("AWS_EXECUTION_ENV", "").lower() or
        os.getenv("BEDROCK_AGENTCORE_RUNTIME", "")
    )
    
    # Default table name for webhook deployments
    default_table = "glitch-telegram-config"
    table_name = config_table or default_table
    
    # Try to read from DynamoDB if we have a table name
    if config_table or webhook_url_env or is_agentcore:
        try:
            region = _get_dynamodb_region()
            dynamodb = boto3.resource("dynamodb", region_name=region)
            table = dynamodb.Table(table_name)
            response = table.get_item(Key={"pk": "CONFIG", "sk": "telegram"})
            if "Item" in response:
                item = response["Item"]
                return {
                    "owner_id": item.get("owner_id"),
                    "dm_policy": item.get("dm_policy", "pairing"),
                    "group_policy": item.get("group_policy", "allowlist"),
                    "require_mention": item.get("require_mention", True),
                    "dm_allowlist": item.get("dm_allowlist", []) or [],
                    "group_allowlist": item.get("group_allowlist", []) or [],
                    "webhook_url": item.get("webhook_url"),
                    "mode": item.get("mode", "webhook"),
                }, True
        except (ClientError, Exception) as e:
            logger.warning("DynamoDB Telegram config load failed (expected if no DynamoDB permissions): %s", e)
        
        # Fallback: we're in AgentCore/webhook mode but can't read DynamoDB
        # Return enabled=True with default config since the webhook Lambda handles Telegram
        if is_agentcore or config_table or webhook_url_env:
            return {
                "mode": "webhook",
                "dm_policy": "pairing",
                "group_policy": "allowlist",
                "require_mention": True,
            }, True

    # Local/polling mode - check for token env vars
    has_token = bool(
        os.environ.get("GLITCH_TELEGRAM_BOT_TOKEN") or
        os.environ.get("GLITCH_TELEGRAM_SECRET_NAME")
    )
    if not has_token:
        return None, False
    try:
        from glitch.channels.config_manager import ConfigManager
        cm = ConfigManager()
        config = cm.load()
        if config.telegram:
            t = config.telegram
            return {
                "bot_username": getattr(t, "bot_username", None),
                "owner_id": getattr(t, "owner_id", None),
                "dm_policy": getattr(t, "dm_policy", "pairing"),
                "group_policy": getattr(t, "group_policy", "allowlist"),
                "require_mention": getattr(t, "require_mention", True),
                "dm_allowlist": getattr(t, "dm_allowlist", []) or [],
                "group_allowlist": getattr(t, "group_allowlist", []) or [],
                "webhook_url": getattr(t, "webhook_url", None),
                "mode": getattr(t, "mode", "polling"),
            }, True
    except Exception as e:
        logger.warning("File Telegram config load failed: %s", e)
    return None, has_token


@router.get("/telegram/config", response_model=TelegramConfigResponse)
async def get_telegram_config() -> TelegramConfigResponse:
    """Get Telegram bot configuration."""
    data, has_token = _load_telegram_config_for_api()
    if not has_token:
        return TelegramConfigResponse(
            enabled=False,
            dm_policy="pairing",
            group_policy="allowlist",
            require_mention=True,
        )
    if not data:
        return TelegramConfigResponse(
            enabled=True,
            dm_policy="pairing",
            group_policy="allowlist",
            require_mention=True,
        )
    return TelegramConfigResponse(
        enabled=True,
        bot_username=data.get("bot_username"),
        owner_id=data.get("owner_id"),
        dm_policy=data.get("dm_policy", "pairing"),
        group_policy=data.get("group_policy", "allowlist"),
        require_mention=data.get("require_mention", True),
        dm_allowlist=data.get("dm_allowlist") or [],
        group_allowlist=data.get("group_allowlist") or [],
        webhook_url=data.get("webhook_url"),
        mode=data.get("mode", "polling"),
    )


@router.post("/telegram/config", response_model=TelegramConfigResponse)
async def update_telegram_config(update: TelegramConfigUpdate) -> TelegramConfigResponse:
    """Update Telegram bot configuration (file backend only; DynamoDB not updated via API)."""
    import os
    try:
        from glitch.channels.config_manager import ConfigManager
        if os.environ.get("GLITCH_CONFIG_TABLE") or os.environ.get("GLITCH_TELEGRAM_WEBHOOK_URL"):
            raise HTTPException(
                status_code=501,
                detail="Telegram config updates are not supported when using DynamoDB backend",
            )
        config_manager = ConfigManager()
        config = config_manager.load()
        if not config.telegram:
            raise HTTPException(status_code=400, detail="Telegram not configured")
        kwargs = {}
        if update.dm_policy is not None:
            kwargs["dm_policy"] = update.dm_policy
        if update.group_policy is not None:
            kwargs["group_policy"] = update.group_policy
        if update.require_mention is not None:
            kwargs["require_mention"] = update.require_mention
        if update.dm_allowlist is not None:
            kwargs["dm_allowlist"] = update.dm_allowlist
        if update.group_allowlist is not None:
            kwargs["group_allowlist"] = update.group_allowlist
        if kwargs:
            config_manager.update_telegram(**kwargs)
        return await get_telegram_config()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to update Telegram config: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ollama/health", response_model=OllamaHealthResponse)
async def get_ollama_health() -> OllamaHealthResponse:
    """Get Ollama hosts health status."""
    try:
        from glitch.tools.ollama_tools import _check_single_host, DEFAULT_CONFIG
        config = DEFAULT_CONFIG
        hosts = []
        # Chat: Ollama 11434 /api/tags. Vision: OpenAI-compatible 8080 /v1/models.
        for name, host, port_override, use_openai in [
            ("Chat", config.chat_host, None, False),
            ("Vision", config.vision_host, config.vision_port, True),
        ]:
            result = await _check_single_host(name, host, config, port_override=port_override, use_openai_format=use_openai)
            hosts.append(OllamaHostHealth(
                name=result.name,
                host=result.host,
                healthy=result.healthy,
                models=getattr(result, "models", []) or [],
                error=result.error,
            ))
        return OllamaHealthResponse(
            hosts=hosts,
            all_healthy=all(h.healthy for h in hosts),
        )
    except Exception as e:
        logger.exception("get_ollama_health failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/summary", response_model=MemorySummaryResponse)
async def get_memory_summary() -> MemorySummaryResponse:
    """Get memory state summary including structured memory and recent AgentCore events."""
    try:
        agent = _get_agent()
        sm = agent.memory_manager.structured_memory
        raw = sm.to_dict() if hasattr(sm, "to_dict") and callable(sm.to_dict) else {}
        recent_events: list = []
        if getattr(agent.memory_manager, "retrieve_recent_events", None):
            try:
                recent_events = await agent.memory_manager.retrieve_recent_events(max_results=15)
            except Exception as e:
                logger.debug("retrieve_recent_events failed: %s", e)
        normalized_events = _normalize_recent_events(recent_events) if isinstance(recent_events, list) else []
        normalized_events = _ensure_recent_events_list_of_dicts(normalized_events)
        logger.debug(f"Memory summary - normalized_events count: {len(normalized_events)}")
        if normalized_events:
            logger.debug(f"Memory summary - first normalized event type: {type(normalized_events[0])}, value: {normalized_events[0]}")
        
        # Build the response dict manually to inspect it before Pydantic validation
        response_data = {
            "session_id": agent.session_id,
            "memory_id": agent.memory_id,
            "window_size": getattr(agent.memory_manager, "window_size", 20),
            "structured_memory": _sanitize_for_json(raw) if isinstance(raw, dict) else {},
            "agentcore_connected": agent.memory_manager.agentcore_client is not None,
            "recent_events": normalized_events,
        }
        logger.debug(f"Memory summary - recent_events in response_data type: {type(response_data['recent_events'])}")
        if response_data['recent_events']:
            logger.debug(f"Memory summary - first item in response_data recent_events: {type(response_data['recent_events'][0])}")
        
        return MemorySummaryResponse(**response_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_memory_summary failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/telemetry", response_model=TelemetryResponse)
async def get_telemetry() -> TelemetryResponse:
    """Get collected telemetry: recent history, running totals by period, thresholds, and current alerts."""
    try:
        from glitch.telemetry import (
            get_telemetry_history,
            get_running_totals,
            get_telemetry_thresholds,
            check_thresholds,
        )
        history = get_telemetry_history(limit=100)
        running_totals = get_running_totals()
        thresholds = get_telemetry_thresholds()
        alerts = check_thresholds(running_totals)
        logger.info("Telemetry: history=%d entries, running_totals=%s, thresholds=%d",
                    len(history), list(running_totals.keys()), len(thresholds))
        return TelemetryResponse(
            history=_sanitize_for_json(history) if isinstance(history, list) else [],
            running_totals=_sanitize_for_json(running_totals) if isinstance(running_totals, dict) else {},
            thresholds=_sanitize_for_json(thresholds) if isinstance(thresholds, list) else [],
            alerts=alerts if isinstance(alerts, list) else [],
        )
    except Exception as e:
        logger.exception("get_telemetry failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/streaming-info", response_model=StreamingInfoResponse)
async def get_streaming_info() -> StreamingInfoResponse:
    """Get streaming capabilities and WebSocket URL info.
    
    Phase 2 implementation: Returns information about streaming support.
    HTTP streaming is available via the /invocations endpoint with async generators.
    WebSocket presigned URL support will be added when AgentCore Runtime supports it.
    """
    try:
        agent = _get_agent()
        session_id = agent.session_id
        
        return StreamingInfoResponse(
            streaming_enabled=True,
            http_streaming_supported=True,
            websocket_url=None,
            session_id=session_id,
            expires_in_seconds=None,
            message="HTTP streaming available via /invocations. WebSocket presigned URLs pending AgentCore Runtime support.",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_streaming_info failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mcp/servers", response_model=MCPServersResponse)
async def get_mcp_servers() -> MCPServersResponse:
    """Get MCP servers status."""
    try:
        agent = _get_agent()
        mcp_status = agent.mcp_manager.get_status() or {}
        server_names = mcp_status.get("server_names") or []
        servers = []
        total_tools = 0
        config_servers = getattr(agent.mcp_manager, "config", None)
        config_servers = config_servers.servers if config_servers else {}
        clients = getattr(agent.mcp_manager, "clients", {}) or {}
        for server_name in server_names:
            server_config = config_servers.get(server_name)
            client = clients.get(server_name)
            tools = []
            if client:
                try:
                    for provider in agent.mcp_manager.get_tool_providers():
                        if hasattr(provider, "tools"):
                            tools.extend([getattr(t, "name", str(t)) for t in provider.tools])
                except Exception:
                    pass
            servers.append(MCPServerInfo(
                name=server_name,
                enabled=getattr(server_config, "enabled", False) if server_config else False,
                connected=client is not None,
                transport=getattr(server_config, "transport", "unknown") if server_config else "unknown",
                tools=tools,
            ))
            total_tools += len(tools)
        return MCPServersResponse(servers=servers, total_tools=total_tools)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_mcp_servers failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/skills", response_model=SkillsResponse)
async def get_skills() -> SkillsResponse:
    """Get all registered skills."""
    try:
        agent = _get_agent()
        skills_list = []
        reg = getattr(agent, "skill_registry", None)
        if reg is None:
            return SkillsResponse(skills=[], total=0)
        items = getattr(reg, "_skills", {}) or {}
        for skill_id, skill in items.items():
            metadata = getattr(skill, "metadata", None)
            if not metadata:
                continue
            skills_list.append(SkillInfo(
                id=skill_id,
                name=getattr(metadata, "name", skill_id),
                description=getattr(metadata, "description", ""),
                enabled=skill_id not in _disabled_skills,
                triggers=getattr(metadata, "triggers", []) or [],
                model_hints=getattr(metadata, "model_hints", []) or [],
                usage_count=0,
            ))
        return SkillsResponse(skills=skills_list, total=len(skills_list))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("get_skills failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/skills/{skill_id}/toggle", response_model=SkillToggleResponse)
async def toggle_skill(skill_id: str, request: SkillToggleRequest) -> SkillToggleResponse:
    """Enable or disable a skill. Persists to DynamoDB if available."""
    global _disabled_skills
    agent = _get_agent()
    
    if skill_id not in agent.skill_registry._skills:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    
    if request.enabled:
        _disabled_skills.discard(skill_id)
        message = f"Skill '{skill_id}' enabled"
    else:
        _disabled_skills.add(skill_id)
        message = f"Skill '{skill_id}' disabled"
    
    # Persist to DynamoDB
    if _save_disabled_skills_to_dynamodb(_disabled_skills):
        message += " (persisted)"
    
    logger.info(message)
    
    return SkillToggleResponse(
        skill_id=skill_id,
        enabled=request.enabled,
        message=message,
    )


# ---------------------------------------------------------------------------
# Agents and session agent/mode (registry + DynamoDB)
# ---------------------------------------------------------------------------

@router.get("/agents", response_model=AgentsResponse)
async def list_agents_api() -> AgentsResponse:
    """List registered chat agents (glitch, mistral, llava)."""
    try:
        from glitch.agent_registry import list_agents as registry_list_agents
        agents_data = registry_list_agents()
        agents = [
            AgentInfo(
                id=a.get("id", ""),
                name=a.get("name", ""),
                description=a.get("description", ""),
                is_default=a.get("is_default", False),
                status=a.get("status"),
            )
            for a in agents_data
        ]
        logger.info("List agents requested", extra={"count": len(agents)})
        return AgentsResponse(agents=agents)
    except Exception as e:
        logger.exception("list_agents failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/sessions/{session_id}/agent", response_model=SessionAgentResponse)
async def get_session_agent(session_id: str) -> SessionAgentResponse:
    """Get current agent_id and mode_id for a session."""
    agent_id, mode_id = _get_session_agent_mode(session_id)
    return SessionAgentResponse(agent_id=agent_id, mode_id=mode_id)


@router.put("/sessions/{session_id}/agent", response_model=SessionAgentResponse)
async def put_session_agent(session_id: str, body: SessionAgentUpdate) -> SessionAgentResponse:
    """Set agent_id for a session. Validates against registry."""
    from glitch.agent_registry import get_allowed_agent_ids
    aid = (body.agent_id or "").strip().lower()
    if aid not in get_allowed_agent_ids():
        raise HTTPException(status_code=400, detail=f"Invalid agent_id: {aid}")
    _set_session_agent_mode(session_id, agent_id=aid)
    _, mode_id = _get_session_agent_mode(session_id)
    logger.info("Session agent selected", extra={"session_id": session_id, "agent_id": aid, "channel": "api"})
    return SessionAgentResponse(agent_id=aid, mode_id=mode_id)


@router.get("/sessions/{session_id}/mode", response_model=SessionModeResponse)
async def get_session_mode(session_id: str) -> SessionModeResponse:
    """Get current mode_id for a session."""
    _, mode_id = _get_session_agent_mode(session_id)
    return SessionModeResponse(mode_id=mode_id)


@router.put("/sessions/{session_id}/mode", response_model=SessionModeResponse)
async def put_session_mode(session_id: str, body: SessionModeUpdate) -> SessionModeResponse:
    """Set mode_id for a session (default | poet)."""
    from glitch.modes import MODE_DEFAULT, MODE_POET
    mid = (body.mode_id or "").strip().lower()
    if mid not in (MODE_DEFAULT, MODE_POET):
        raise HTTPException(status_code=400, detail=f"Invalid mode_id: {mid}")
    _set_session_agent_mode(session_id, mode_id=mid)
    logger.info("Session mode selected", extra={"session_id": session_id, "mode_id": mid, "channel": "api"})
    return SessionModeResponse(mode_id=mid)


@router.get("/modes", response_model=ModesResponse)
async def list_modes() -> ModesResponse:
    """List available modes (default, poet)."""
    from glitch.modes import MODE_DEFAULT, MODE_POET
    return ModesResponse(
        modes=[
            ModeInfo(id=MODE_DEFAULT, name="Default"),
            ModeInfo(id=MODE_POET, name="Poet"),
        ]
    )


def add_cors_middleware(app) -> None:
    """Add CORS middleware for UI development."""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
