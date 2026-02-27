"""Tools package for Glitch agent.

Exports:
    Ollama tools:
        vision_agent: Process images with local LLaVA
        local_chat: Chat with local Ollama models
        check_ollama_health: Check Ollama endpoint health
        OllamaConfig: Configuration for Ollama endpoints
        HealthCheckResult: Result of health check
    
    Network tools (placeholders):
        query_pihole_stats: Query Pi-hole DNS stats
        check_unifi_network: Check Unifi network status
        query_protect_cameras: Query Protect camera status
        IntegrationStatus: Status enum for integrations
        NetworkToolResponse: Standard response type
"""

from glitch.tools.ollama_tools import (
    vision_agent,
    local_chat,
    check_ollama_health,
    OllamaConfig,
    HealthCheckResult,
    OllamaGeneratePayload,
    OllamaGenerateResponse,
    OllamaTagsResponse,
    OllamaModelInfo,
)

from glitch.tools.network_tools import (
    query_pihole_stats,
    check_unifi_network,
    query_protect_cameras,
    IntegrationStatus,
    NetworkToolResponse,
    PiholeStats,
    UnifiDevice,
    ProtectCamera,
)

from glitch.tools.memory_tools import (
    set_memory_manager,
    get_memory_manager,
    set_session_goal,
    add_fact,
    add_constraint,
    record_decision,
    add_open_question,
    resolve_question,
    update_tool_results_summary,
    get_memory_state,
)

from glitch.tools.pihole_tools import (
    pihole_list_dns_records,
    pihole_add_dns_record,
    pihole_delete_dns_record,
    pihole_update_dns_record,
    PiholeConfig,
)

from glitch.tools.protect_tools import ALL_PROTECT_TOOLS

__all__ = [
    # Ollama tools
    "vision_agent",
    "local_chat",
    "check_ollama_health",
    "OllamaConfig",
    "HealthCheckResult",
    "OllamaGeneratePayload",
    "OllamaGenerateResponse",
    "OllamaTagsResponse",
    "OllamaModelInfo",
    # Network tools
    "query_pihole_stats",
    "check_unifi_network",
    "query_protect_cameras",
    "IntegrationStatus",
    "NetworkToolResponse",
    "PiholeStats",
    "UnifiDevice",
    "ProtectCamera",
    # Memory tools
    "set_memory_manager",
    "get_memory_manager",
    "set_session_goal",
    "add_fact",
    "add_constraint",
    "record_decision",
    "add_open_question",
    "resolve_question",
    "update_tool_results_summary",
    "get_memory_state",
    # Pi-hole DNS tools
    "pihole_list_dns_records",
    "pihole_add_dns_record",
    "pihole_delete_dns_record",
    "pihole_update_dns_record",
    "PiholeConfig",
    # Protect tools
    "ALL_PROTECT_TOOLS",
]
