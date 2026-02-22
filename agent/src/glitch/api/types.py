"""API type definitions for Glitch UI endpoints."""

from typing import Dict, List, Optional, Any
from typing_extensions import TypedDict
from pydantic import BaseModel, model_validator
import logging

logger = logging.getLogger(__name__)


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
    recent_events: List[Dict[str, Any]] = []
    
    @model_validator(mode="before")
    @classmethod
    def flatten_recent_events(cls, data: Any) -> Any:
        """Flatten recent_events to List[Dict] before field validation. Return new dict so Pydantic uses it."""
        if not isinstance(data, dict):
            return data
        recent_events = data.get("recent_events", [])
        if not isinstance(recent_events, list):
            return {**data, "recent_events": []}
        flattened: List[Dict[str, Any]] = []
        for item in recent_events:
            if isinstance(item, dict):
                normalized = dict(item)
                content = normalized.get("content")
                if isinstance(content, dict) and "text" in content:
                    normalized["content"] = content["text"]
                flattened.append(normalized)
            elif isinstance(item, list):
                for msg in item:
                    if isinstance(msg, dict):
                        normalized = dict(msg)
                        content = normalized.get("content")
                        if isinstance(content, dict) and "text" in content:
                            normalized["content"] = content["text"]
                        flattened.append(normalized)
        return {**data, "recent_events": flattened}


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


class TelemetryResponse(BaseModel):
    """Response from GET /api/telemetry."""
    history: List[Dict[str, Any]] = []
    running_totals: Dict[str, Dict[str, Any]] = {}
    thresholds: List[Dict[str, Any]] = []
    alerts: List[str] = []


class StreamingInfoResponse(BaseModel):
    """Response from GET /api/streaming-info.
    
    Provides information about streaming capabilities for the UI.
    Phase 2 will add presigned WebSocket URL support.
    """
    streaming_enabled: bool = False
    http_streaming_supported: bool = True
    websocket_url: Optional[str] = None
    session_id: Optional[str] = None
    expires_in_seconds: Optional[int] = None
    message: str = "HTTP streaming available. WebSocket streaming coming in Phase 2."
