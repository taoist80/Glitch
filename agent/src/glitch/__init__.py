"""Glitch Agent - Main orchestrator for AgentCore hybrid system.

This package provides the Glitch agent, a hybrid AI orchestrator that:
- Routes tasks between cloud (Bedrock) and local (Ollama) models
- Manages conversation memory via AgentCore Memory API
- Tracks metrics via OpenTelemetry
- Integrates with on-premises services via Tailscale

Dataflow Overview:
    InvocationRequest -> GlitchAgent.process_message() -> InvocationResponse
                                    |
                                    v
                            Strands Agent (with tools)
                                    |
                                    v
                            AgentResult -> InvocationMetrics
"""

__version__ = "1.0.0"

from glitch.types import (
    TokenUsage,
    ToolUsageStats,
    InvocationMetrics,
    InvocationRequest,
    InvocationResponse,
    AgentStatus,
    ConnectivityStatus,
    EventType,
    MetricType,
    TelemetryConfig,
    AgentConfig,
    ServerConfig,
    create_empty_token_usage,
    create_empty_metrics,
    create_error_response,
)

from glitch.telemetry import (
    setup_telemetry,
    get_telemetry,
    get_metrics_collector,
    extract_metrics_from_result,
    log_invocation_metrics,
    get_metrics_to_string,
    invocation_metrics_to_telegram_string,
    add_span_attributes,
    record_metric,
    create_span,
)

from glitch.agent import (
    GlitchAgent,
    create_glitch_agent,
)

__all__ = [
    # Types
    "TokenUsage",
    "ToolUsageStats",
    "InvocationMetrics",
    "InvocationRequest",
    "InvocationResponse",
    "AgentStatus",
    "ConnectivityStatus",
    "EventType",
    "MetricType",
    "TelemetryConfig",
    "AgentConfig",
    "ServerConfig",
    # Type factories
    "create_empty_token_usage",
    "create_empty_metrics",
    "create_error_response",
    # Telemetry
    "setup_telemetry",
    "get_telemetry",
    "get_metrics_collector",
    "extract_metrics_from_result",
    "log_invocation_metrics",
    "get_metrics_to_string",
    "invocation_metrics_to_telegram_string",
    "add_span_attributes",
    "record_metric",
    "create_span",
    # Agent
    "GlitchAgent",
    "create_glitch_agent",
]
