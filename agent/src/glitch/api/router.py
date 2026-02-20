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


@router.get("/status", response_model=StatusResponse)
async def get_status() -> StatusResponse:
    """Get overall agent status."""
    agent = _get_agent()
    status = agent.get_status()
    mcp_status = agent.mcp_manager.get_status()
    
    return StatusResponse(
        session_id=status["session_id"],
        memory_id=status["memory_id"],
        connected=True,
        skills_loaded=status.get("skills_loaded", len(agent.skill_registry)),
        mcp_servers_connected=mcp_status.get("connected_clients", 0),
        routing_stats=status.get("routing_stats", {}),
        structured_memory=status.get("structured_memory", {}),
    )


@router.get("/telegram/config", response_model=TelegramConfigResponse)
async def get_telegram_config() -> TelegramConfigResponse:
    """Get Telegram bot configuration."""
    import os
    
    has_token = bool(
        os.environ.get("GLITCH_TELEGRAM_BOT_TOKEN") or
        os.environ.get("GLITCH_TELEGRAM_SECRET_NAME")
    )
    
    if not has_token:
        return TelegramConfigResponse(
            enabled=False,
            dm_policy="pairing",
            group_policy="allowlist",
            require_mention=True,
        )
    
    try:
        from glitch.channels.config_manager import ConfigManager
        config_manager = ConfigManager()
        config = config_manager.load()
        
        telegram_config = config.get("channels", {}).get("telegram", {})
        
        return TelegramConfigResponse(
            enabled=True,
            bot_username=telegram_config.get("bot_username"),
            owner_id=telegram_config.get("owner_id"),
            dm_policy=telegram_config.get("dm_policy", "pairing"),
            group_policy=telegram_config.get("group_policy", "allowlist"),
            require_mention=telegram_config.get("require_mention", True),
            dm_allowlist=telegram_config.get("dm_allowlist", []),
            group_allowlist=telegram_config.get("group_allowlist", []),
            webhook_url=telegram_config.get("webhook_url"),
            mode=telegram_config.get("mode", "polling"),
        )
    except Exception as e:
        logger.warning(f"Failed to load Telegram config: {e}")
        return TelegramConfigResponse(
            enabled=has_token,
            dm_policy="pairing",
            group_policy="allowlist",
            require_mention=True,
        )


@router.post("/telegram/config", response_model=TelegramConfigResponse)
async def update_telegram_config(update: TelegramConfigUpdate) -> TelegramConfigResponse:
    """Update Telegram bot configuration."""
    try:
        from glitch.channels.config_manager import ConfigManager
        config_manager = ConfigManager()
        config = config_manager.load()
        
        if "channels" not in config:
            config["channels"] = {}
        if "telegram" not in config["channels"]:
            config["channels"]["telegram"] = {}
        
        telegram_config = config["channels"]["telegram"]
        
        if update.dm_policy is not None:
            telegram_config["dm_policy"] = update.dm_policy
        if update.group_policy is not None:
            telegram_config["group_policy"] = update.group_policy
        if update.require_mention is not None:
            telegram_config["require_mention"] = update.require_mention
        if update.dm_allowlist is not None:
            telegram_config["dm_allowlist"] = update.dm_allowlist
        if update.group_allowlist is not None:
            telegram_config["group_allowlist"] = update.group_allowlist
        
        config_manager.save(config)
        
        return await get_telegram_config()
    except Exception as e:
        logger.error(f"Failed to update Telegram config: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/ollama/health", response_model=OllamaHealthResponse)
async def get_ollama_health() -> OllamaHealthResponse:
    """Get Ollama hosts health status."""
    from glitch.tools.ollama_tools import _check_single_host, DEFAULT_CONFIG
    
    config = DEFAULT_CONFIG
    hosts = []
    
    for name, host in [("Chat", config.chat_host), ("Vision", config.vision_host)]:
        result = await _check_single_host(name, host, config)
        hosts.append(OllamaHostHealth(
            name=result.name,
            host=result.host,
            healthy=result.healthy,
            models=result.models,
            error=result.error,
        ))
    
    return OllamaHealthResponse(
        hosts=hosts,
        all_healthy=all(h.healthy for h in hosts),
    )


@router.get("/memory/summary", response_model=MemorySummaryResponse)
async def get_memory_summary() -> MemorySummaryResponse:
    """Get memory state summary."""
    agent = _get_agent()
    
    return MemorySummaryResponse(
        session_id=agent.session_id,
        memory_id=agent.memory_id,
        window_size=agent.memory_manager.window_size,
        structured_memory=agent.memory_manager.structured_memory.to_dict(),
        agentcore_connected=agent.memory_manager.agentcore_client is not None,
    )


@router.get("/mcp/servers", response_model=MCPServersResponse)
async def get_mcp_servers() -> MCPServersResponse:
    """Get MCP servers status."""
    agent = _get_agent()
    mcp_status = agent.mcp_manager.get_status()
    
    servers = []
    total_tools = 0
    
    for server_name in mcp_status.get("server_names", []):
        server_config = agent.mcp_manager.config.servers.get(server_name)
        client = agent.mcp_manager.clients.get(server_name)
        
        tools = []
        if client:
            try:
                tool_providers = agent.mcp_manager.get_tool_providers()
                for provider in tool_providers:
                    if hasattr(provider, 'tools'):
                        tools.extend([t.name for t in provider.tools if hasattr(t, 'name')])
            except Exception:
                pass
        
        servers.append(MCPServerInfo(
            name=server_name,
            enabled=server_config.enabled if server_config else False,
            connected=client is not None,
            transport=server_config.transport if server_config else "unknown",
            tools=tools,
        ))
        total_tools += len(tools)
    
    return MCPServersResponse(
        servers=servers,
        total_tools=total_tools,
    )


@router.get("/skills", response_model=SkillsResponse)
async def get_skills() -> SkillsResponse:
    """Get all registered skills."""
    agent = _get_agent()
    
    skills = []
    for skill_id, skill in agent.skill_registry._skills.items():
        metadata = skill.metadata
        skills.append(SkillInfo(
            id=skill_id,
            name=metadata.name,
            description=metadata.description,
            enabled=skill_id not in _disabled_skills,
            triggers=metadata.triggers,
            model_hints=metadata.model_hints,
            usage_count=0,
        ))
    
    return SkillsResponse(
        skills=skills,
        total=len(skills),
    )


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
