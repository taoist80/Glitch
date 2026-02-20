"""API type definitions for Glitch UI endpoints."""

from typing import Dict, List, Optional, Any
from typing_extensions import TypedDict
from pydantic import BaseModel


class StatusResponse(BaseModel):
    """Response from GET /api/status."""
    session_id: str
    memory_id: str
    connected: bool
    skills_loaded: int
    mcp_servers_connected: int
    routing_stats: Dict[str, Any]
    structured_memory: Dict[str, Any]


class TelegramConfigResponse(BaseModel):
    """Response from GET /api/telegram/config."""
    enabled: bool
    bot_username: Optional[str] = None
    owner_id: Optional[int] = None
    dm_policy: str = "pairing"
    group_policy: str = "allowlist"
    require_mention: bool = True
    dm_allowlist: List[int] = []
    group_allowlist: List[int] = []
    webhook_url: Optional[str] = None
    mode: str = "polling"


class TelegramConfigUpdate(BaseModel):
    """Request body for POST /api/telegram/config."""
    dm_policy: Optional[str] = None
    group_policy: Optional[str] = None
    require_mention: Optional[bool] = None
    dm_allowlist: Optional[List[int]] = None
    group_allowlist: Optional[List[int]] = None


class OllamaHostHealth(BaseModel):
    """Health status for a single Ollama host."""
    name: str
    host: str
    healthy: bool
    models: List[str] = []
    error: Optional[str] = None


class OllamaHealthResponse(BaseModel):
    """Response from GET /api/ollama/health."""
    hosts: List[OllamaHostHealth]
    all_healthy: bool


class MemorySummaryResponse(BaseModel):
    """Response from GET /api/memory/summary."""
    session_id: str
    memory_id: str
    window_size: int
    structured_memory: Dict[str, Any]
    agentcore_connected: bool


class MCPServerInfo(BaseModel):
    """Information about a single MCP server."""
    name: str
    enabled: bool
    connected: bool
    transport: str
    tools: List[str] = []
    error: Optional[str] = None


class MCPServersResponse(BaseModel):
    """Response from GET /api/mcp/servers."""
    servers: List[MCPServerInfo]
    total_tools: int


class SkillInfo(BaseModel):
    """Information about a single skill."""
    id: str
    name: str
    description: str
    enabled: bool
    triggers: List[str] = []
    model_hints: List[str] = []
    usage_count: int = 0


class SkillsResponse(BaseModel):
    """Response from GET /api/skills."""
    skills: List[SkillInfo]
    total: int


class SkillToggleRequest(BaseModel):
    """Request body for POST /api/skills/{skill_id}/toggle."""
    enabled: bool


class SkillToggleResponse(BaseModel):
    """Response from POST /api/skills/{skill_id}/toggle."""
    skill_id: str
    enabled: bool
    message: str
