"""FastAPI router for Glitch Agent UI REST API.

Provides endpoints for the dashboard UI to query agent state and configuration.
"""

import logging
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
)

if TYPE_CHECKING:
    from glitch.agent import GlitchAgent

logger = logging.getLogger(__name__)

# No prefix here: when mounted at /api on Starlette, paths are relative (e.g. /status).
router = APIRouter(prefix="", tags=["ui"])

_agent: Optional["GlitchAgent"] = None
_disabled_skills: set[str] = set()


def setup_api(agent: "GlitchAgent") -> None:
    """Initialize the API with the agent instance.
    
    Args:
        agent: GlitchAgent instance to expose via API
    """
    global _agent
    _agent = agent
    logger.info("API router initialized with agent")


def _get_agent() -> "GlitchAgent":
    """Get the agent instance or raise 503."""
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent not initialized")
    return _agent


def _sanitize_for_json(obj: object) -> object:
    """Convert to JSON-serializable types (avoid 500 from Pydantic/Starlette)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {str(k): _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sanitize_for_json(x) for x in obj]
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (int, float)) and (obj != obj or abs(obj) == float("inf")):
        return 0
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
    """Load Telegram config using same backend as main (DynamoDB in AWS, file locally)."""
    import os
    import boto3
    from botocore.exceptions import ClientError

    has_token = bool(
        os.environ.get("GLITCH_TELEGRAM_BOT_TOKEN") or
        os.environ.get("GLITCH_TELEGRAM_SECRET_NAME")
    )
    if not has_token:
        return None, has_token

    config_table = os.getenv("GLITCH_CONFIG_TABLE", "").strip()
    webhook_url_env = os.getenv("GLITCH_TELEGRAM_WEBHOOK_URL", "").strip()
    if config_table or webhook_url_env:
        try:
            table_name = config_table or "glitch-telegram-config"
            dynamodb = boto3.resource("dynamodb")
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
        except ClientError as e:
            logger.warning("DynamoDB Telegram config load failed: %s", e)
        except Exception as e:
            logger.warning("DynamoDB Telegram config load failed: %s", e)
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
        for name, host in [("Chat", config.chat_host), ("Vision", config.vision_host)]:
            result = await _check_single_host(name, host, config)
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
        return MemorySummaryResponse(
            session_id=agent.session_id,
            memory_id=agent.memory_id,
            window_size=getattr(agent.memory_manager, "window_size", 20),
            structured_memory=_sanitize_for_json(raw) if isinstance(raw, dict) else {},
            agentcore_connected=agent.memory_manager.agentcore_client is not None,
            recent_events=_sanitize_for_json(recent_events) if isinstance(recent_events, list) else [],
        )
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
    """Enable or disable a skill."""
    agent = _get_agent()
    
    if skill_id not in agent.skill_registry._skills:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")
    
    if request.enabled:
        _disabled_skills.discard(skill_id)
        message = f"Skill '{skill_id}' enabled"
    else:
        _disabled_skills.add(skill_id)
        message = f"Skill '{skill_id}' disabled"
    
    logger.info(message)
    
    return SkillToggleResponse(
        skill_id=skill_id,
        enabled=request.enabled,
        message=message,
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
