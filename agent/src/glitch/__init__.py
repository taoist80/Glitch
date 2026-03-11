"""Glitch Agent - Main orchestrator for AgentCore hybrid system.

This package provides the Glitch agent, a hybrid AI orchestrator that:
- Routes tasks between cloud (Bedrock) and local (Ollama) models
- Manages conversation memory via AgentCore Memory API
- Selects and injects skills based on task analysis
- Tracks metrics via OpenTelemetry
- Integrates with on-premises services via Site-to-Site VPN

Dataflow Overview:
    InvocationRequest -> TaskPlanner -> TaskSpec
                                           |
                                           v
                                   SkillSelector(TaskSpec, model)
                                           |
                                           v
                                   build_prompt_with_skills()
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
    TelemetryThreshold,
    TelemetryHistoryEntry,
    PeriodAggregates,
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

from glitch.skills import select_skills_for_message

from glitch.mcp import (
    MCPServerConfig,
    MCPConfig,
    MCPServerManager,
    load_mcp_config,
    get_default_mcp_config_path,
)


def __getattr__(name):
    """Lazy import for modules with heavy dependencies."""
    if name in ("GlitchAgent", "create_glitch_agent"):
        from glitch.agent import GlitchAgent, create_glitch_agent
        return GlitchAgent if name == "GlitchAgent" else create_glitch_agent
    
    if name in ("PoetAgent", "create_poet_agent"):
        from glitch.poet_agent import PoetAgent, create_poet_agent
        return PoetAgent if name == "PoetAgent" else create_poet_agent
    
    if name == "load_poet_soul":
        from glitch.poet_soul import load_poet_soul
        return load_poet_soul
    
    if name in (
        "setup_telemetry", "get_telemetry", "get_metrics_collector",
        "extract_metrics_from_result", "log_invocation_metrics",
        "get_metrics_to_string", "invocation_metrics_to_telegram_string",
        "add_span_attributes", "record_metric", "create_span",
    ):
        from glitch import telemetry
        return getattr(telemetry, name)
    
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # Types
    "TokenUsage",
    "ToolUsageStats",
    "InvocationMetrics",
    "InvocationRequest",
    "InvocationResponse",
    "TelemetryThreshold",
    "TelemetryHistoryEntry",
    "PeriodAggregates",
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
    # Telemetry (lazy)
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
    # Agent (lazy)
    "GlitchAgent",
    "create_glitch_agent",
    # Poet sub-agent (lazy)
    "PoetAgent",
    "create_poet_agent",
    "load_poet_soul",
    # Skills
    "select_skills_for_message",
    # MCP
    "MCPServerConfig",
    "MCPConfig",
    "MCPServerManager",
    "load_mcp_config",
    "get_default_mcp_config_path",
]
