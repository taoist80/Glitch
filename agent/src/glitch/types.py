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
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Literal, Optional, Any

# Pydantic requires typing_extensions.TypedDict on Python < 3.12 (runtime is 3.10).
from typing_extensions import TypedDict


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


class InvocationRequest(TypedDict, total=False):
    """Request payload for agent invocation.
    
    Sent to POST /invocations endpoint.
    """
    prompt: str  # Required: The user's message
    session_id: Optional[str]  # Optional: Override session ID
    context: Optional[Dict[str, Any]]  # Optional: Additional context


class InvocationResponse(TypedDict, total=False):
    """Response from agent invocation.
    
    Returned from POST /invocations endpoint.
    """
    message: str  # The agent's response
    session_id: str  # Session identifier
    memory_id: str  # Memory identifier
    metrics: InvocationMetrics  # Invocation metrics
    error: Optional[str]  # Error message if failed


class AgentStatus(TypedDict):
    """Agent status information.
    
    Returned by GlitchAgent.get_status().
    """
    session_id: str
    memory_id: str
    routing_stats: Dict[str, Any]
    structured_memory: Dict[str, Any]


class ConnectivityStatus(TypedDict):
    """Connectivity check results.
    
    Returned by GlitchAgent.check_connectivity().
    """
    ollama_health: bool
    agentcore_memory: bool


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
