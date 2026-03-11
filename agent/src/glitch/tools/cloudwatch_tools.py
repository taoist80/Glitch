"""CloudWatch log scanning and metrics tools for Glitch.

Provides tools for querying CloudWatch Logs Insights, scanning log groups for
errors, retrieving Lambda function metrics, and tailing recent log events.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import boto3
from strands import tool

from glitch.aws_utils import REGION, CLIENT_CONFIG_LONG, get_client

logger = logging.getLogger(__name__)

SSM_PARAM_LOG_GROUPS = "/glitch/sentinel/monitored-log-groups"

# The AgentCore runtime log group — stream names contain the container ID.
# Glitch can self-diagnose by querying this group.
_AGENTCORE_LOG_GROUP = os.environ.get(
    "AGENTCORE_LOG_GROUP",
    "/aws/bedrock-agentcore/runtimes",
)

_DEFAULT_LOG_GROUPS = [
    _AGENTCORE_LOG_GROUP,
    "/aws/lambda/glitch-telegram-webhook",
    "/aws/lambda/glitch-gateway",
    "/aws/lambda/glitch-agentcore-keepalive",
    "/glitch/telemetry",
    "RDSOSMetrics",
]

# Prefixes to enumerate when discovering all infra log groups.
_INFRA_LOG_GROUP_PREFIXES = [
    "/aws/bedrock-agentcore/",
    "/aws/lambda/glitch-",
    "/aws/lambda/GlitchFoundation",
    "/aws/lambda/GlitchProtect",
    "/aws/vpc/flowlogs",
    "/glitch/",
    "RDSOSMetrics",
]

# CloudWatch Insights queries can take 30s+; use the long timeout config.
_logs_client = None
_cw_client = None
_cached_log_groups: Optional[List[str]] = None


def _get_logs_client():
    global _logs_client
    if _logs_client is None:
        _logs_client = boto3.client("logs", region_name=REGION, config=CLIENT_CONFIG_LONG)
    return _logs_client


def _get_cw_client():
    global _cw_client
    if _cw_client is None:
        _cw_client = boto3.client("cloudwatch", region_name=REGION, config=CLIENT_CONFIG_LONG)
    return _cw_client


def _get_monitored_log_groups() -> List[str]:
    global _cached_log_groups
    if _cached_log_groups is not None:
        return _cached_log_groups
    try:
        ssm = get_client("ssm")
        resp = ssm.get_parameter(Name=SSM_PARAM_LOG_GROUPS)
        groups = json.loads(resp["Parameter"]["Value"])
        _cached_log_groups = groups
        return groups
    except Exception as e:
        logger.warning(f"Could not load log groups from SSM, using defaults: {e}")
        return _DEFAULT_LOG_GROUPS


def _resolve_log_groups(log_group_prefix: str) -> List[str]:
    """Resolve a prefix (potentially with wildcard) to actual log group names."""
    client = _get_logs_client()
    prefix = log_group_prefix.rstrip("/*")
    try:
        paginator = client.get_paginator("describe_log_groups")
        groups = []
        for page in paginator.paginate(logGroupNamePrefix=prefix):
            for g in page.get("logGroups", []):
                groups.append(g["logGroupName"])
        return groups if groups else [prefix]
    except Exception:
        return [prefix]


def _run_insights_query(log_group: str, query_str: str, hours: int = 3) -> List[dict]:
    """Run a CloudWatch Insights query and return results."""
    client = _get_logs_client()
    end_time = int(time.time())
    start_time = end_time - (hours * 3600)

    log_groups = _resolve_log_groups(log_group)
    if not log_groups:
        return []

    try:
        resp = client.start_query(
            logGroupNames=log_groups[:20],
            startTime=start_time,
            endTime=end_time,
            queryString=query_str,
            limit=50,
        )
        query_id = resp["queryId"]

        for _ in range(30):
            time.sleep(2)
            result = client.get_query_results(queryId=query_id)
            status = result["status"]
            if status in ("Complete", "Failed", "Cancelled", "Timeout"):
                if status == "Complete":
                    return result.get("results", [])
                return []
        return []
    except Exception as e:
        logger.error(f"Insights query failed for {log_group}: {e}")
        return []


def _row_to_dict(row: List[dict]) -> dict:
    return {field["field"]: field["value"] for field in row}


@tool
def scan_log_groups_for_errors(hours: int = 3) -> str:
    """Scan all monitored log groups for errors and return a structured summary.

    Args:
        hours: How many hours back to scan (default 3).

    Returns:
        JSON summary with error counts, sample messages, and affected log groups.
    """
    groups = _get_monitored_log_groups()
    query = (
        "fields @timestamp, @logStream, @message "
        "| filter @message like /(?i)(error|exception|traceback|failed|timeout|critical)/ "
        "| sort @timestamp desc "
        "| limit 20"
    )

    results = []
    for group in groups:
        rows = _run_insights_query(group, query, hours=hours)
        if rows:
            samples = [_row_to_dict(r).get("@message", "")[:200] for r in rows[:5]]
            results.append({
                "log_group": group,
                "error_count": len(rows),
                "samples": samples,
            })

    if not results:
        return json.dumps({"status": "clean", "hours_scanned": hours, "groups_scanned": len(groups)})

    return json.dumps({
        "status": "errors_found",
        "hours_scanned": hours,
        "groups_with_errors": len(results),
        "groups_scanned": len(groups),
        "details": results,
    }, indent=2)


@tool
def get_log_group_errors(log_group: str, hours: int = 6, limit: int = 50) -> str:
    """Deep-dive into a specific log group's recent errors with full context.

    Args:
        log_group: The CloudWatch log group name (e.g., "/aws/lambda/glitch-gateway").
        hours: How many hours back to look (default 6).
        limit: Maximum number of log events to return (default 50).

    Returns:
        JSON list of error log events with timestamps, streams, and messages.
    """
    query = (
        f"fields @timestamp, @logStream, @message "
        f"| filter @message like /(?i)(error|exception|traceback|failed|timeout|critical)/ "
        f"| sort @timestamp desc "
        f"| limit {min(limit, 100)}"
    )
    rows = _run_insights_query(log_group, query, hours=hours)
    events = [_row_to_dict(r) for r in rows]
    return json.dumps({
        "log_group": log_group,
        "hours": hours,
        "event_count": len(events),
        "events": events,
    }, indent=2)


@tool
def list_monitored_log_groups() -> str:
    """Return all log groups being monitored by Glitch with last check timestamp.

    Returns:
        JSON list of log group names currently configured for monitoring.
    """
    groups = _get_monitored_log_groups()
    return json.dumps({
        "log_groups": groups,
        "count": len(groups),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2)


@tool
def get_lambda_metrics(function_name: str, hours: int = 6) -> str:
    """Fetch error rate, throttle count, and P99 duration for a Lambda function.

    Args:
        function_name: The Lambda function name (e.g., "glitch-gateway").
        hours: How many hours back to retrieve metrics (default 6).

    Returns:
        JSON with Errors, Throttles, Duration P99, and Invocations counts.
    """
    client = _get_cw_client()
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)
    period = max(300, hours * 60)

    metrics_to_fetch = [
        ("Errors", "Sum"),
        ("Throttles", "Sum"),
        ("Invocations", "Sum"),
        ("Duration", "p99"),
    ]

    results = {}
    for metric_name, stat in metrics_to_fetch:
        try:
            resp = client.get_metric_statistics(
                Namespace="AWS/Lambda",
                MetricName=metric_name,
                Dimensions=[{"Name": "FunctionName", "Value": function_name}],
                StartTime=start_time,
                EndTime=end_time,
                Period=period,
                Statistics=[stat] if stat != "p99" else [],
                ExtendedStatistics=["p99"] if stat == "p99" else [],
            )
            datapoints = resp.get("Datapoints", [])
            if datapoints:
                value = sum(
                    d.get(stat, d.get("ExtendedStatistics", {}).get("p99", 0))
                    for d in datapoints
                )
                results[metric_name] = round(value, 2)
            else:
                results[metric_name] = 0
        except Exception as e:
            results[metric_name] = f"error: {e}"

    return json.dumps({
        "function": function_name,
        "hours": hours,
        "metrics": results,
    }, indent=2)


@tool
def query_cloudwatch_insights(log_group: str, query_string: str, hours: int = 3) -> str:
    """Run an arbitrary CloudWatch Logs Insights query against a log group.

    Args:
        log_group: The log group name or prefix to query.
        query_string: A valid CloudWatch Logs Insights query string.
        hours: How many hours back to query (default 3).

    Returns:
        JSON list of query result rows.
    """
    rows = _run_insights_query(log_group, query_string, hours=hours)
    results = [_row_to_dict(r) for r in rows]
    return json.dumps({
        "log_group": log_group,
        "query": query_string,
        "hours": hours,
        "row_count": len(results),
        "results": results,
    }, indent=2)


@tool
def tail_log_stream(log_group: str, minutes: int = 10, filter_pattern: str = "", limit: int = 100) -> str:
    """Fetch recent raw log events from a log group using filter_log_events (low latency).

    Unlike Insights queries this returns results immediately without a 30s wait,
    making it ideal for checking what just happened.

    Args:
        log_group: The CloudWatch log group name. Use "/aws/bedrock-agentcore/runtimes"
            to see Glitch's own runtime logs.
        minutes: How many minutes back to fetch (default 10, max 60).
        filter_pattern: Optional CloudWatch filter pattern (e.g. "ERROR" or "protect").
            Leave empty to return all events.
        limit: Maximum number of events to return (default 100, max 200).

    Returns:
        JSON with recent log events including timestamp, stream name, and message.
    """
    client = _get_logs_client()
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (min(minutes, 60) * 60 * 1000)

    log_groups = _resolve_log_groups(log_group)
    all_events = []

    for group in log_groups[:5]:
        try:
            kwargs = dict(
                logGroupName=group,
                startTime=start_ms,
                endTime=end_ms,
                limit=min(limit, 200),
            )
            if filter_pattern:
                kwargs["filterPattern"] = filter_pattern

            resp = client.filter_log_events(**kwargs)
            for ev in resp.get("events", []):
                all_events.append({
                    "timestamp": datetime.fromtimestamp(ev["timestamp"] / 1000, tz=timezone.utc).isoformat(),
                    "stream": ev.get("logStreamName", ""),
                    "message": ev.get("message", "").rstrip("\n"),
                })
        except Exception as e:
            logger.warning("tail_log_stream failed for %s: %s", group, e)

    all_events.sort(key=lambda x: x["timestamp"])
    return json.dumps({
        "log_group": log_group,
        "minutes": minutes,
        "filter_pattern": filter_pattern,
        "event_count": len(all_events),
        "events": all_events[-limit:],
    }, indent=2)


@tool
def list_all_log_groups(prefix: str = "") -> str:
    """Discover all CloudWatch log groups in the deployed AWS infrastructure.

    Lists every log group Glitch has access to, grouped by service. Use this
    to find the right log group name before calling tail_log_stream or
    query_cloudwatch_insights.

    Args:
        prefix: Optional prefix to filter results (e.g. "/aws/lambda/glitch-").
            Leave empty to list all known infra log groups.

    Returns:
        JSON with log groups organized by service prefix, including size and
        last event timestamp.
    """
    client = _get_logs_client()
    prefixes = [prefix] if prefix else _INFRA_LOG_GROUP_PREFIXES

    groups_by_prefix: dict = {}
    for pfx in prefixes:
        try:
            paginator = client.get_paginator("describe_log_groups")
            found = []
            for page in paginator.paginate(logGroupNamePrefix=pfx):
                for g in page.get("logGroups", []):
                    last_event = g.get("lastEventTimestamp")
                    found.append({
                        "name": g["logGroupName"],
                        "stored_bytes": g.get("storedBytes", 0),
                        "last_event": (
                            datetime.fromtimestamp(last_event / 1000, tz=timezone.utc).isoformat()
                            if last_event else None
                        ),
                        "retention_days": g.get("retentionInDays"),
                    })
            if found:
                groups_by_prefix[pfx] = found
        except Exception as e:
            groups_by_prefix[pfx] = f"error: {e}"

    total = sum(len(v) for v in groups_by_prefix.values() if isinstance(v, list))
    return json.dumps({
        "total_groups": total,
        "groups_by_prefix": groups_by_prefix,
    }, indent=2)


@tool
def get_my_recent_logs(minutes: int = 15, filter_pattern: str = "") -> str:
    """Fetch Glitch's own AgentCore runtime logs from the last N minutes.

    Use this to self-diagnose errors, check subsystem startup, or verify that
    a recent deploy is behaving correctly. Returns raw log lines from all
    running containers.

    Args:
        minutes: How many minutes back to fetch (default 15, max 60).
        filter_pattern: Optional filter (e.g. "ERROR", "protect", "DB connection").
            Leave empty to return all recent logs.

    Returns:
        JSON with recent log events from this agent's runtime log group.
    """
    return tail_log_stream.__wrapped__(
        log_group=_AGENTCORE_LOG_GROUP,
        minutes=minutes,
        filter_pattern=filter_pattern,
        limit=150,
    )
