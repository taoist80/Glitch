"""SentinelAgent — the operational brain.

Wraps a Strands Agent with all tool groups and loads the system prompt from SOUL.md.
"""

import logging
import os
from pathlib import Path
from typing import List, Callable

from strands import Agent
from strands.models import BedrockModel
from strands.types.content import SystemContentBlock, CachePoint

logger = logging.getLogger(__name__)

# Soul file relative to repo root or container working directory
_SOUL_PATHS = [
    Path(__file__).parent.parent.parent / "SOUL.md",  # /app/SOUL.md in container
    Path("/app/SOUL.md"),
    Path("SOUL.md"),
]


def _load_soul() -> str:
    for path in _SOUL_PATHS:
        if path.exists():
            return path.read_text(encoding="utf-8")
    return (
        "You are Sentinel, an autonomous operations agent. "
        "Monitor logs, networks, and infrastructure. "
        "Alert via Telegram. Fix what you can. Escalate what you cannot."
    )


def _load_skills() -> str:
    """Load all Sentinel skill files and return them as a single appended section."""
    skills_dir = Path(__file__).parent.parent.parent / "src" / "sentinel" / "skills"
    if not skills_dir.exists():
        # Try relative to this file
        skills_dir = Path(__file__).parent / "skills"
    if not skills_dir.exists():
        return ""

    sections = []
    for skill_dir in sorted(skills_dir.iterdir()):
        skill_md = skill_dir / "skill.md"
        if skill_dir.is_dir() and skill_md.exists():
            content = skill_md.read_text(encoding="utf-8").strip()
            if content:
                sections.append(content)

    if not sections:
        return ""

    return "\n\n---\n\n## Active Skills\n\n" + "\n\n---\n\n".join(sections)


def _build_system_prompt() -> str:
    soul = _load_soul()
    skills = _load_skills()
    return f"""{soul}

## Available Tool Groups

- **CloudWatch**: scan_log_groups_for_errors, get_log_group_errors, list_monitored_log_groups, get_lambda_metrics, query_cloudwatch_insights
- **UniFi Protect (48 tools)**: cameras, events, snapshots, DB ops, alerts, monitoring controls, entity mgmt, video clips, heatmaps, patterns, hostile lists, GDPR, reports, tuning, and compound tools (security_correlation_scan, analyze_and_alert)
- **Pi-hole DNS**: pihole_list_dns_records, pihole_add_dns_record, pihole_delete_dns_record, pihole_update_dns_record
- **UniFi Network**: unifi_list_clients, unifi_get_device_status, unifi_get_ap_stats, unifi_get_switch_ports, unifi_get_firewall_rules, unifi_block_client, unifi_get_traffic_stats, unifi_get_network_health, unifi_get_vpn_status, unifi_get_wifi_networks, unifi_get_alerts_events, unifi_get_network_topology
- **DNS Intelligence**: dns_analyze_query_patterns, dns_detect_suspicious_domains, dns_get_top_blocked, dns_get_client_query_stats, dns_monitor_live_queries, dns_get_query_trends, dns_manage_blocklists
- **Infrastructure Ops**: list_cfn_stacks_status, check_cfn_drift, rollback_stack, cdk_synth_and_validate, cdk_diff, cdk_deploy_stack
- **GitHub**: github_get_file, github_create_branch, github_commit_file, github_create_pr
- **Telegram Alerts**: send_telegram_alert, send_telegram_resolved
- **Compound Tools**: security_correlation_scan (protect + network + DNS in one call), analyze_and_alert (full surveillance pipeline: fetch → analyze → decide → alert)
- **Glitch Agent**: invoke_glitch_agent (for SSH/SSM operations on on-prem hosts)

## Operating Guidelines

1. Always scan logs before forming hypotheses about errors.
2. Correlate across domains — single signals are often noise.
3. Require confirmed=True for cdk_deploy_stack. Always send Telegram alert and wait for confirmation before calling with confirmed=True.
4. Use invoke_glitch_agent for any task requiring SSM commands, SSH, or EC2 access.
5. When creating a GitHub PR for a code fix, include root cause, fix description, and testing notes in the PR body.
{skills}"""


def _get_all_tools() -> List[Callable]:
    """Import and return all Sentinel tools."""
    from sentinel.tools.cloudwatch_tools import (
        scan_log_groups_for_errors,
        get_log_group_errors,
        list_monitored_log_groups,
        get_lambda_metrics,
        query_cloudwatch_insights,
    )
    from sentinel.tools.telegram_tools import send_telegram_alert, send_telegram_resolved
    from sentinel.tools.github_tools import (
        github_get_file,
        github_create_branch,
        github_commit_file,
        github_create_pr,
    )
    from sentinel.tools.protect_tools import ALL_PROTECT_TOOLS
    from sentinel.tools.pihole_tools import (
        pihole_list_dns_records,
        pihole_add_dns_record,
        pihole_delete_dns_record,
        pihole_update_dns_record,
    )
    from sentinel.tools.unifi_network_tools import (
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
    from sentinel.tools.dns_intelligence_tools import (
        dns_analyze_query_patterns,
        dns_detect_suspicious_domains,
        dns_get_top_blocked,
        dns_get_client_query_stats,
        dns_monitor_live_queries,
        dns_get_query_trends,
        dns_manage_blocklists,
    )
    from sentinel.tools.infra_ops_tools import (
        list_cfn_stacks_status,
        check_cfn_drift,
        rollback_stack,
        cdk_synth_and_validate,
        cdk_diff,
        cdk_deploy_stack,
    )
    from sentinel.tools.glitch_invoke_tools import invoke_glitch_agent
    from sentinel.tools.compound_tools import security_correlation_scan, analyze_and_alert

    return [
        # CloudWatch
        scan_log_groups_for_errors,
        get_log_group_errors,
        list_monitored_log_groups,
        get_lambda_metrics,
        query_cloudwatch_insights,
        # Telegram
        send_telegram_alert,
        send_telegram_resolved,
        # GitHub
        github_get_file,
        github_create_branch,
        github_commit_file,
        github_create_pr,
        # Protect (all 48 tools)
        *ALL_PROTECT_TOOLS,
        # Pi-hole
        pihole_list_dns_records,
        pihole_add_dns_record,
        pihole_delete_dns_record,
        pihole_update_dns_record,
        # UniFi Network
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
        # DNS Intelligence
        dns_analyze_query_patterns,
        dns_detect_suspicious_domains,
        dns_get_top_blocked,
        dns_get_client_query_stats,
        dns_monitor_live_queries,
        dns_get_query_trends,
        dns_manage_blocklists,
        # Infra Ops
        list_cfn_stacks_status,
        check_cfn_drift,
        rollback_stack,
        cdk_synth_and_validate,
        cdk_diff,
        cdk_deploy_stack,
        # Compound tools (multi-source, fewer round-trips)
        security_correlation_scan,
        analyze_and_alert,
        # A2A
        invoke_glitch_agent,
    ]


class SentinelAgent:
    """Sentinel operational agent wrapping a Strands Agent with all tool groups."""

    def __init__(self) -> None:
        model_id = os.environ.get(
            "SENTINEL_MODEL_ID",
            "anthropic.claude-sonnet-4-6",
        )
        # cache_tools caches the 91 tool schemas on every request — the largest
        # cacheable token block (~2000 tokens at $0.30/M vs $3.00/M = 90% savings).
        model = BedrockModel(
            model_id=model_id,
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
            cache_tools="default",
        )
        system_prompt_str = _build_system_prompt()
        # Sentinel's system prompt is entirely static — wrap it with a cache point
        # so the full prompt (soul + tool descriptions + guidelines + skills) is
        # cached and reused across every invocation.
        system_blocks: list[SystemContentBlock] = [
            SystemContentBlock(text=system_prompt_str),
            SystemContentBlock(cachePoint=CachePoint(type="default")),
        ]
        tools = _get_all_tools()

        self._agent = Agent(
            name="Sentinel",
            description=(
                "Autonomous operations agent for the Glitch system. "
                "Monitors CloudWatch logs, UniFi Protect cameras, UniFi Network, "
                "Pi-hole DNS, CloudFormation infrastructure, and GitHub. "
                "Detects errors, correlates incidents, remediates automatically where possible, "
                "and alerts via Telegram when human attention is needed."
            ),
            model=model,
            system_prompt=system_blocks,
            tools=tools,
            callback_handler=None,
        )
        logger.info(f"SentinelAgent initialized with {len(tools)} tools (48 protect, 2 compound) and model {model_id}")

    def get_agent(self) -> Agent:
        return self._agent


_sentinel_agent: SentinelAgent | None = None


def get_sentinel_agent() -> SentinelAgent:
    global _sentinel_agent
    if _sentinel_agent is None:
        _sentinel_agent = SentinelAgent()
    return _sentinel_agent
