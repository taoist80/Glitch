"""Tool registry for organizing and managing agent tools by group."""

from typing import Callable, Dict, List, Set

from glitch.tools.ollama_tools import vision_agent, local_chat, check_ollama_health
from glitch.tools.memory_tools import (
    set_session_goal,
    add_fact,
    add_constraint,
    record_decision,
    add_open_question,
    resolve_question,
    update_tool_results_summary,
    get_memory_state,
)
from glitch.tools.telemetry_tools import (
    telemetry,
    set_telemetry_threshold,
    set_telemetry_thresholds,
    update_telemetry_threshold,
    list_telemetry_thresholds,
    remove_telemetry_threshold,
    clear_telemetry_thresholds,
    add_telemetry_metric,
    record_telemetry_metric,
    list_telemetry_metrics,
    update_telemetry_aggregation,
    list_aggregation_periods,
    create_cloudwatch_metric,
    query_persistent_telemetry,
)
from glitch.tools.network_tools import (
    query_pihole_stats,
    check_unifi_network,
    query_protect_cameras,
)
from glitch.tools.pihole_tools import (
    pihole_list_dns_records,
    pihole_add_dns_record,
    pihole_delete_dns_record,
    pihole_update_dns_record,
)
from glitch.tools.soul_tools import update_soul
from glitch.tools.ssh_tools import (
    ssh_list_hosts,
    ssh_install_key,
    ssh_run_command,
    ssh_read_file,
    ssh_write_file,
    ssh_mkdir,
    ssh_file_exists,
    ssh_list_dir,
)
from glitch.tools.protect_tools import ALL_PROTECT_TOOLS
from glitch.tools.tailscale_tools import run_tailscale_ensure_tls, run_tailscale_ssm_command, run_tailscale_renew_tls


class ToolRegistry:
    """Registry for organizing and managing agent tools by group."""

    def __init__(self) -> None:
        self._groups: Dict[str, List[Callable]] = {}
        self._disabled_groups: Set[str] = set()
        self._register_default_groups()

    def _register_default_groups(self) -> None:
        self._groups["ollama"] = [vision_agent, local_chat, check_ollama_health]
        self._groups["memory"] = [
            set_session_goal,
            add_fact,
            add_constraint,
            record_decision,
            add_open_question,
            resolve_question,
            update_tool_results_summary,
            get_memory_state,
        ]
        self._groups["telemetry"] = [
            telemetry,
            set_telemetry_threshold,
            set_telemetry_thresholds,
            update_telemetry_threshold,
            list_telemetry_thresholds,
            remove_telemetry_threshold,
            clear_telemetry_thresholds,
            add_telemetry_metric,
            record_telemetry_metric,
            list_telemetry_metrics,
            update_telemetry_aggregation,
            list_aggregation_periods,
            create_cloudwatch_metric,
            query_persistent_telemetry,
        ]
        self._groups["network"] = [
            query_pihole_stats,
            check_unifi_network,
            query_protect_cameras,
        ]
        self._groups["pihole_dns"] = [
            pihole_list_dns_records,
            pihole_add_dns_record,
            pihole_delete_dns_record,
            pihole_update_dns_record,
        ]
        self._groups["soul"] = [update_soul]
        self._groups["protect"] = ALL_PROTECT_TOOLS
        self._groups["tailscale"] = [run_tailscale_ensure_tls, run_tailscale_ssm_command, run_tailscale_renew_tls]
        self._groups["ssh"] = [
            ssh_list_hosts,
            ssh_install_key,
            ssh_run_command,
            ssh_read_file,
            ssh_write_file,
            ssh_mkdir,
            ssh_file_exists,
            ssh_list_dir,
        ]

    def register_group(self, name: str, tools: List[Callable]) -> None:
        """Register a group of tools (replaces existing group with same name)."""
        self._groups[name] = list(tools)

    def disable_group(self, name: str) -> None:
        """Disable a tool group (excluded from get_all_tools)."""
        self._disabled_groups.add(name)

    def enable_group(self, name: str) -> None:
        """Re-enable a disabled tool group."""
        self._disabled_groups.discard(name)

    def get_all_tools(self) -> List[Callable]:
        """Return all enabled tools as a flat list."""
        tools: List[Callable] = []
        for name, group_tools in self._groups.items():
            if name not in self._disabled_groups:
                tools.extend(group_tools)
        return tools

    def get_group(self, name: str) -> List[Callable]:
        """Return tools for a specific group."""
        return list(self._groups.get(name, []))

    def list_groups(self) -> Dict[str, int]:
        """Return all group names and their tool counts."""
        return {name: len(tools) for name, tools in self._groups.items()}


# Singleton registry used by the agent
registry = ToolRegistry()


def get_all_tools() -> List[Callable]:
    """Return all enabled tools from the default registry."""
    return registry.get_all_tools()
