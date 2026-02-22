"""Type definitions for Glitch agent.

This module defines all data types used throughout the Glitch agent system.
Using explicit types enables:
- Clear function signatures
- IDE autocompletion and type checking
- Traceable dataflows
- Self-documenting code

Dataflow Overview:
    InvocationRequest -> GlitchAgent.process_message() -> InvocationResponse
                                    |
                                    v
                            AgentResult (Strands)
                                    |
                                    v
                            InvocationMetrics -> TelemetryHistoryEntry -> PeriodAggregates
    TelemetryThreshold (list) + PeriodAggregates -> check_thresholds() -> List[str] (alerts)

Session Management:
    Channel + Identity -> SessionKey -> SessionManager.get_or_create_session() -> session_id

Gateway Lambda:
    GatewayEvent -> route_request() -> GatewayResponse
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional, Any

# Pydantic requires typing_extensions.TypedDict on Python < 3.12 (runtime is 3.10).
from typing_extensions import TypedDict


class UiApiRequest(TypedDict, total=False):
    """Payload for UI API requests routed through invocations (proxy mode)."""
    path: str
    method: str
    body: Optional[Dict[str, Any]]


# =============================================================================
# Session Management Types
# =============================================================================


class SessionRecord(TypedDict, total=False):
    """DynamoDB record for a session.

    Stored in glitch-telegram-config table with pk=SESSION#{channel}:{identity}.
    """
    pk: str
    sk: str
    session_id: str
    channel: str
    identity: str
    created_at: int
    ttl: int


# =============================================================================
# Gateway Lambda Types
# =============================================================================


class GatewayEvent(TypedDict, total=False):
    """Lambda Function URL event structure.

    Normalized from API Gateway v2 or direct Lambda invocation.
    """
    rawPath: str
    requestContext: Dict[str, Any]
    headers: Dict[str, str]
    body: str
    isBase64Encoded: bool
    source: str
    detail_type: str


class GatewayResponse(TypedDict):
    """Lambda Function URL response structure."""
    statusCode: int
    body: str
    headers: Dict[str, str]


class GatewayRouteResult(TypedDict):
    """Result from a gateway route handler."""
    status: int
    body: str


# =============================================================================
# Token and Metrics Types
# =============================================================================


class TokenUsage(TypedDict):
    """Token usage statistics for a single invocation.
    
    Matches the format returned by Strands' EventLoopMetrics but with
    snake_case keys for API consistency.
    """
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int


class ToolUsageStats(TypedDict):
    """Statistics for a single tool's usage during an invocation."""
    call_count: int
    success_count: int
    error_count: int
    total_time: float


class InvocationMetrics(TypedDict):
    """Metrics collected during an agent invocation.
    
    This is the standardized format returned by extract_metrics_from_result()
    and included in InvocationResponse.
    """
    duration_seconds: float
    token_usage: TokenUsage
    cycle_count: int
    latency_ms: int
    stop_reason: str
    tool_usage: Dict[str, ToolUsageStats]


class TelemetryThreshold(TypedDict):
    """A single telemetry alert threshold: alert when metric over period exceeds limit.
    
    Used by telemetry module and telemetry_tools; makes threshold dataflow explicit.
    """
    metric: str   # input_tokens, output_tokens, total_tokens, invocation_count, duration_seconds
    period: str   # hour, day, week, month, this_hour, today, this_week, this_month
    limit: float


class _TelemetryHistoryEntryRequired(TypedDict):
    timestamp: float
    metrics: InvocationMetrics


class TelemetryHistoryEntry(_TelemetryHistoryEntryRequired, total=False):
    """A single entry in the in-memory telemetry history.
    Optional: custom_metrics (Dict[str, float]).
    """
    custom_metrics: Dict[str, float]


class _PeriodAggregatesRequired(TypedDict):
    invocation_count: int
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    duration_seconds: float
    latency_ms_total: int
    latency_ms_avg: float


class PeriodAggregates(_PeriodAggregatesRequired, total=False):
    """Aggregated metrics over a time period. Optional: custom_metrics (Dict[str, float])."""
    custom_metrics: Dict[str, float]


class CloudWatchQueryResult(TypedDict, total=False):
    """Result from a CloudWatch Logs Insights query.

    Used by query_cloudwatch_telemetry() for persistent telemetry retrieval.
    """
    status: str
    results: List[Dict[str, str]]
    statistics: Dict[str, Any]


class CloudWatchAggregates(TypedDict, total=False):
    """Aggregated metrics from CloudWatch Logs Insights.

    Returned by get_cloudwatch_aggregates() for merging with in-memory telemetry.
    """
    invocation_count: int
    total_input_tokens: int
    total_output_tokens: int
    total_tokens: int
    avg_duration_seconds: float
    query_time_range: str


# =============================================================================
# Invocation Request/Response Types
# =============================================================================


class InvocationRequest(TypedDict, total=False):
    """Request payload for agent invocation.

    Sent to POST /invocations endpoint.
    Either prompt (normal chat) or _ui_api_request (proxy API) is present.
    """
    prompt: str  # Required for chat invocations
    session_id: Optional[str]  # Optional: Override session ID
    agent_id: Optional[str]  # Optional: glitch | mistral | llava (else default from registry)
    mode_id: Optional[str]  # Optional: default | poet
    context: Optional[Dict[str, Any]]  # Optional: Additional context
    stream: bool  # Optional: Stream events instead of single response
    _ui_api_request: UiApiRequest  # Optional: UI API proxy request


class InvocationResponse(TypedDict, total=False):
    """Response from agent invocation.
    
    Returned from POST /invocations endpoint.
    """
    message: str  # The agent's response
    session_id: str  # Session identifier
    memory_id: str  # Memory identifier
    metrics: InvocationMetrics  # Invocation metrics
    error: Optional[str]  # Error message if failed


class AgentStatus(TypedDict, total=False):
    """Agent status information.
    
    Returned by GlitchAgent.get_status().
    """
    session_id: str
    memory_id: str
    routing_stats: Dict[str, Any]
    structured_memory: Dict[str, Any]
    skills_loaded: int
    mcp_servers: Dict[str, Any]
    code_interpreter_available: bool


class ConnectivityStatus(TypedDict):
    """Connectivity check results.
    
    Returned by GlitchAgent.check_connectivity().
    """
    ollama_health: bool
    agentcore_memory: bool


class StreamingInfo(TypedDict, total=False):
    """Streaming capabilities information.

    Internal type matching StreamingInfoResponse API model.
    """
    streaming_enabled: bool
    http_streaming_supported: bool
    websocket_url: Optional[str]
    session_id: Optional[str]
    expires_in_seconds: Optional[int]
    message: str


# =============================================================================
# Tool Registry Types
# =============================================================================


class ToolGroupInfo(TypedDict):
    """Information about a tool group in the registry."""
    name: str
    tool_count: int
    enabled: bool


class ToolRegistryStatus(TypedDict):
    """Status of the tool registry."""
    total_tools: int
    enabled_tools: int
    groups: List[ToolGroupInfo]
    disabled_groups: List[str]


# =============================================================================
# Enums
# =============================================================================


class EventType(str, Enum):
    """Types of events stored in memory."""
    USER_MESSAGE = "user_message"
    AGENT_RESPONSE = "agent_response"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    SYSTEM = "system"


class MetricType(str, Enum):
    """Types of OpenTelemetry metrics."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


class IntegrationStatus(str, Enum):
    """Status of an external integration."""
    NOT_IMPLEMENTED = "not_implemented"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    ERROR = "error"


# =============================================================================
# Configuration Dataclasses
# =============================================================================


@dataclass
class TelemetryConfig:
    """Configuration for OpenTelemetry setup.
    
    Attributes:
        service_name: Service name for traces (default: "glitch-agent")
        otlp_endpoint: OTLP endpoint URL (default: from env or localhost:4318)
        enable_console: Enable console exporter for debugging
        enable_otlp: Enable OTLP exporter for production
    """
    service_name: str = "glitch-agent"
    otlp_endpoint: Optional[str] = None
    enable_console: bool = False
    enable_otlp: bool = True


@dataclass
class AgentConfig:
    """Configuration for GlitchAgent initialization.
    
    Attributes:
        session_id: Unique session identifier
        memory_id: Memory store identifier
        region: AWS region for AgentCore services
        window_size: Sliding window size for conversation history
        mcp_config_path: Optional path to MCP servers configuration file
    """
    session_id: str
    memory_id: str
    region: str = "us-west-2"
    window_size: int = 20
    mcp_config_path: Optional[Path] = None


@dataclass
class ServerConfig:
    """Configuration for HTTP server.
    
    Attributes:
        host: Host to bind to (default: 0.0.0.0 for containers)
        port: Port to bind to (default: 8080 for AgentCore)
        debug: Enable debug mode
    """
    host: str = "0.0.0.0"
    port: int = 8080
    debug: bool = False


def create_empty_token_usage() -> TokenUsage:
    """Create an empty TokenUsage with zero values."""
    return TokenUsage(
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        cache_read_tokens=0,
        cache_write_tokens=0,
    )


def create_empty_metrics() -> InvocationMetrics:
    """Create an empty InvocationMetrics with default values."""
    return InvocationMetrics(
        duration_seconds=0.0,
        token_usage=create_empty_token_usage(),
        cycle_count=0,
        latency_ms=0,
        stop_reason="",
        tool_usage={},
    )


def create_error_response(error: str, session_id: str = "", memory_id: str = "") -> InvocationResponse:
    """Create an error InvocationResponse."""
    return InvocationResponse(
        message=f"I encountered an error processing your request: {error}",
        session_id=session_id,
        memory_id=memory_id,
        metrics=create_empty_metrics(),
        error=error,
    )


def create_keepalive_response(session_id: str = "", memory_id: str = "") -> InvocationResponse:
    """Minimal success response for keepalive pings (avoids session termination)."""
    return InvocationResponse(
        message="ok",
        session_id=session_id,
        memory_id=memory_id,
        metrics=create_empty_metrics(),
    )


def create_gateway_response(status: int, body: Any) -> GatewayResponse:
    """Create a Lambda Function URL response."""
    import json
    return GatewayResponse(
        statusCode=status,
        body=body if isinstance(body, str) else json.dumps(body),
        headers={"Content-Type": "application/json"},
    )
