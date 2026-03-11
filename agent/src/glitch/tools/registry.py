"""Tool registry for organizing and managing agent tools by group."""

from typing import Callable, Dict, List, Set

from glitch.tools.ollama_tools import vision_agent, local_chat, check_ollama_health, test_ollama_model
from glitch.tools.network_tools import run_packet_capture, ping_host, traceroute_host, curl_request, dig_host
from glitch.tools.local_network_tools import net_tcp_check, net_resolve, net_curl, net_ping, net_traceroute
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
from glitch.tools.secrets_tools import store_secret, list_secrets
from glitch.tools.deploy_tools import (
    get_deployed_arns,
    update_glitch_arn_in_ssm,
    check_codebuild_deploy_status,
)
# Ops tools absorbed from Sentinel
from glitch.tools.cloudwatch_tools import (
    scan_log_groups_for_errors,
    get_log_group_errors,
    list_monitored_log_groups,
    list_all_log_groups,
    get_lambda_metrics,
    query_cloudwatch_insights,
    tail_log_stream,
    get_my_recent_logs,
)
from glitch.tools.ops_telegram_tools import send_telegram_alert, send_telegram_resolved
from glitch.tools.github_tools import (
    github_get_file,
    github_create_branch,
    github_commit_file,
    github_create_pr,
)
from glitch.tools.protect_tools import CORE_PROTECT_TOOLS
from glitch.tools.pihole_tools import (
    pihole_list_dns_records,
    pihole_add_dns_record,
    pihole_delete_dns_record,
    pihole_update_dns_record,
)
from glitch.tools.unifi_network_tools import (
    unifi_list_clients,
    unifi_get_device_status,
    unifi_get_ap_stats,
    unifi_get_switch_ports,
    unifi_get_firewall_rules,
    unifi_block_client,
    unifi_get_traffic_stats,
    unifi_get_network_health,
    unifi_get_vpn_status,
    unifi_get_wifi_networks,
    unifi_get_alerts_events,
    unifi_get_network_topology,
)
from glitch.tools.dns_intelligence_tools import (
    dns_analyze_query_patterns,
    dns_detect_suspicious_domains,
    dns_get_top_blocked,
    dns_get_client_query_stats,
    dns_monitor_live_queries,
    dns_get_query_trends,
    dns_manage_blocklists,
)
from glitch.tools.infra_ops_tools import (
    list_cfn_stacks_status,
    check_cfn_drift,
    rollback_stack,
    cdk_synth_and_validate,
    cdk_diff,
    cdk_deploy_stack,
)
from glitch.tools.compound_tools import security_correlation_scan, analyze_and_alert


class ToolRegistry:
    """Registry for organizing and managing agent tools by group."""

    def __init__(self) -> None:
        self._groups: Dict[str, List[Callable]] = {}
        self._disabled_groups: Set[str] = set()
        self._register_default_groups()

    def _register_default_groups(self) -> None:
        self._groups["ollama"] = [vision_agent, local_chat, check_ollama_health, test_ollama_model]
        self._groups["network"] = [run_packet_capture, ping_host, traceroute_host, curl_request, dig_host]
        self._groups["local_network"] = [net_tcp_check, net_resolve, net_curl, net_ping, net_traceroute]
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
        self._groups["soul"] = [update_soul]
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
        self._groups["secrets"] = [store_secret, list_secrets]
        self._groups["deploy"] = [
            get_deployed_arns,
            update_glitch_arn_in_ssm,
            check_codebuild_deploy_status,
        ]
        # Ops groups absorbed from Sentinel
        self._groups["cloudwatch"] = [
            scan_log_groups_for_errors,
            get_log_group_errors,
            list_monitored_log_groups,
            list_all_log_groups,
            get_lambda_metrics,
            query_cloudwatch_insights,
            tail_log_stream,
            get_my_recent_logs,
        ]
        self._groups["ops_telegram"] = [send_telegram_alert, send_telegram_resolved]
        self._groups["github"] = [
            github_get_file,
            github_create_branch,
            github_commit_file,
            github_create_pr,
        ]
        self._groups["protect"] = list(CORE_PROTECT_TOOLS)
        self._groups["pihole"] = [
            pihole_list_dns_records,
            pihole_add_dns_record,
            pihole_delete_dns_record,
            pihole_update_dns_record,
        ]
        self._groups["unifi_network"] = [
            unifi_list_clients,
            unifi_get_device_status,
            unifi_get_ap_stats,
            unifi_get_switch_ports,
            unifi_get_firewall_rules,
            unifi_block_client,
            unifi_get_traffic_stats,
            unifi_get_network_health,
            unifi_get_vpn_status,
            unifi_get_wifi_networks,
            unifi_get_alerts_events,
            unifi_get_network_topology,
        ]
        self._groups["dns"] = [
            dns_analyze_query_patterns,
            dns_detect_suspicious_domains,
            dns_get_top_blocked,
            dns_get_client_query_stats,
            dns_monitor_live_queries,
            dns_get_query_trends,
            dns_manage_blocklists,
        ]
        self._groups["infra_ops"] = [
            list_cfn_stacks_status,
            check_cfn_drift,
            rollback_stack,
            cdk_synth_and_validate,
            cdk_diff,
            cdk_deploy_stack,
        ]
        self._groups["compound"] = [security_correlation_scan, analyze_and_alert]

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
