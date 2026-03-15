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


# Agents and session agent/mode (registry + DynamoDB)
class AgentInfo(BaseModel):
    """Single agent in list_agents response."""
    id: str
    name: str
    description: str = ""
    is_default: bool = False
    status: Optional[Dict[str, Any]] = None


class AgentsResponse(BaseModel):
    """Response from GET /api/agents."""
    agents: List[AgentInfo]


class SessionAgentResponse(BaseModel):
    """Response from GET /api/sessions/{session_id}/agent."""
    agent_id: str
    mode_id: str = "default"


class SessionAgentUpdate(BaseModel):
    """Request body for PUT /api/sessions/{session_id}/agent."""
    agent_id: str


class SessionModeResponse(BaseModel):
    """Response from GET /api/sessions/{session_id}/mode."""
    mode_id: str


class SessionModeUpdate(BaseModel):
    """Request body for PUT /api/sessions/{session_id}/mode."""
    mode_id: str


class ModeInfo(BaseModel):
    """Single mode in GET /api/modes."""
    id: str
    name: str
    description: str = ""


class ModesResponse(BaseModel):
    """Response from GET /api/modes."""
    modes: List[ModeInfo]


# --- UniFi Protect API (entities, events, alerts, patterns) ---


class ProtectEntityModel(BaseModel):
    """Single entity (person/vehicle) from Protect DB."""
    entity_id: str = ""
    type: str = ""
    label: Optional[str] = None
    trust_level: str = "unknown"
    role: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    sightings_count: int = 0
    plate_text: Optional[str] = None
    vehicle_color: Optional[str] = None
    vehicle_make_model: Optional[str] = None


class ProtectEventModel(BaseModel):
    """Single event from Protect DB."""
    event_id: str = ""
    camera_id: str = ""
    timestamp: str = ""
    entity_type: Optional[str] = None
    score: Optional[float] = None
    anomaly_score: float = 0.0
    snapshot_url: Optional[str] = None
    video_clip_url: Optional[str] = None
    processed: bool = False


class ProtectAlertModel(BaseModel):
    """Single alert from Protect DB."""
    alert_id: str = ""
    event_id: Optional[str] = None
    entity_id: Optional[str] = None
    camera_id: Optional[str] = None
    timestamp: str = ""
    priority: str = "medium"
    title: str = ""
    body: Optional[str] = None
    delivered: bool = False
    user_response: Optional[str] = None


class ProtectPatternModel(BaseModel):
    """Single pattern from Protect DB."""
    pattern_id: str = ""
    camera_id: str = ""
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    pattern_type: str = "entity_visit"
    frequency: float = 1.0
    last_seen: Optional[str] = None
    confidence: float = 0.1


class ProtectSummaryResponse(BaseModel):
    """Response from GET /api/protect/summary."""
    entities_total: int = 0
    events_24h: int = 0
    alerts_unack: int = 0
    cameras_online: int = 0
    cameras_total: int = 0


class ProtectEntitiesResponse(BaseModel):
    """Response from GET /api/protect/entities."""
    entities: List[ProtectEntityModel] = []
    total: int = 0


class ProtectEventsResponse(BaseModel):
    """Response from GET /api/protect/events."""
    events: List[ProtectEventModel] = []
    total: int = 0


class ProtectAlertsResponse(BaseModel):
    """Response from GET /api/protect/alerts."""
    alerts: List[ProtectAlertModel] = []
    total: int = 0


class ProtectPatternsResponse(BaseModel):
    """Response from GET /api/protect/patterns."""
    patterns: List[ProtectPatternModel] = []
    total: int = 0


class ProtectHealthResponse(BaseModel):
    """Response from GET /api/protect/health — agent component health from DB."""
    status: str = "unknown"
    protect_db: str = "no_data"
    protect_poller: str = "no_data"
    protect_processor: str = "no_data"
    protect_configured: bool = False
    uptime_seconds: Optional[int] = None
    updated_at: Optional[str] = None
    source: str = "db"


# Keep old name as alias for backward compat
SentinelHealthResponse = ProtectHealthResponse


class ProtectCameraModel(BaseModel):
    """Single camera from Protect DB."""
    camera_id: str = ""
    name: str = ""
    mac: Optional[str] = None
    model_key: Optional[str] = None
    state: Optional[str] = None
    type: Optional[str] = None
    zone: Optional[str] = None
    is_mic_enabled: Optional[bool] = None
    mic_volume: Optional[int] = None
    video_mode: Optional[str] = None
    hdr_type: Optional[str] = None
    has_hdr: Optional[bool] = None
    has_mic: Optional[bool] = None
    has_speaker: Optional[bool] = None
    has_led_status: Optional[bool] = None
    has_full_hd_snapshot: Optional[bool] = None
    video_modes: List[str] = []
    smart_detect_types: List[str] = []
    smart_detect_audio_types: List[str] = []
    smart_detect_object_types: List[str] = []
    smart_detect_audio_config: List[str] = []
    led_settings: Optional[Dict[str, Any]] = None
    osd_settings: Optional[Dict[str, Any]] = None
    lcd_message: Optional[Dict[str, Any]] = None
    updated_at: Optional[str] = None


class ProtectCamerasResponse(BaseModel):
    """Response from GET /api/protect/cameras."""
    cameras: List[ProtectCameraModel] = []
    total: int = 0


class PatrolResultModel(BaseModel):
    """Single patrol result from camera_patrols table."""
    patrol_id: str = ""
    camera_id: str = ""
    camera_name: Optional[str] = None
    timestamp: str = ""
    scene_description: Optional[str] = None
    detected_objects: List[str] = []
    anomaly_detected: bool = False
    anomaly_description: Optional[str] = None
    confidence: float = 0.0
    model_used: str = "llava"
    processing_ms: Optional[int] = None
    error: Optional[str] = None


class ProtectPatrolsResponse(BaseModel):
    """Response from GET /api/protect/patrols."""
    patrols: List[PatrolResultModel] = []
    total: int = 0

