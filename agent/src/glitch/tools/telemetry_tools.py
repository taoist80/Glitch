"""Telemetry tools: full metrics, history, period aggregates, running totals, and thresholds.
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import List

from pydantic import BaseModel
from strands import tool

from glitch.types import PeriodAggregates, TelemetryThreshold

from glitch.telemetry import (
    add_aggregation_period,
    aggregate_metrics,
    check_thresholds,
    clear_telemetry_thresholds as clear_thresholds_impl,
    get_aggregation_periods,
    get_cloudwatch_aggregates,
    get_last_agent_result,
    get_metrics_to_string,
    get_registered_custom_metrics,
    get_telemetry_history,
    get_telemetry_for_period,
    get_telemetry_thresholds,
    get_running_totals,
    invocation_metrics_to_telegram_string,
    publish_custom_metric_to_cloudwatch,
    query_cloudwatch_telemetry,
    record_custom_telemetry_metric,
    register_custom_telemetry_metric,
    remove_telemetry_threshold as remove_threshold_impl,
    set_telemetry_thresholds as set_thresholds_impl,
    update_telemetry_threshold as update_threshold_impl,
)

logger = logging.getLogger(__name__)


def _format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_aggregate(agg: PeriodAggregates, label: str) -> str:
    input_t = agg.get("input_tokens", 0)
    output_t = agg.get("output_tokens", 0)
    cache_read = agg.get("cache_read_tokens", 0)
    cache_write = agg.get("cache_write_tokens", 0)
    # total_tokens from Strands = input + output only (no cache).
    # AWS bills cache read at ~10% and cache write at ~125% of input token rate.
    # billing_equivalent = all tokens that appear on the AWS invoice.
    billing_equivalent = input_t + output_t + cache_read + cache_write
    lines = [
        "  invocations: %s" % agg.get("invocation_count", 0),
        "  input_tokens: %s" % input_t,
        "  output_tokens: %s" % output_t,
        "  cache_read_tokens: %s" % cache_read,
        "  cache_write_tokens: %s" % cache_write,
        "  billing_equivalent_tokens: %s  (input+output+cache, matches AWS)" % billing_equivalent,
        "  duration_seconds: %s" % agg.get("duration_seconds", 0),
    ]
    custom = agg.get("custom_metrics")
    if custom:
        for k, v in sorted(custom.items()):
            lines.append("  %s: %s" % (k, v))
    return "%s:\n%s" % (label, "\n".join(lines))


@tool
def telemetry(
    last_n: int = 0,
    period: str = "",
    running_totals: bool = False,
    include_cloudwatch: bool = False,
) -> str:
    """Return Strands telemetry: latest invocation, optional history, and optional aggregates by time period.

    Use when the user asks for metrics, usage by hour/day/week/month, running totals, or alerts.
    - Most recent: full EventLoopMetrics for the last reply.
    - last_n > 0: append last N invocations (newest first) with one-line summaries.
    - period: one of 'hour','day','week','month' to add rolling aggregates for that window (e.g. total tokens in last 24h).
    - running_totals: if True, add aggregates for this hour, today, this week, this month (UTC calendar).
    - include_cloudwatch: if True, also query CloudWatch Logs Insights for persistent telemetry across restarts.

    After any period or running totals, configured thresholds are checked and ALERT lines are appended if exceeded.

    Args:
        last_n: Number of past invocations to list (0 = skip). Max 50.
        period: Optional. One of hour, day, week, month for rolling-window totals.
        running_totals: If True, include this_hour, today, this_week, this_month running totals.
        include_cloudwatch: If True, supplement with CloudWatch for persistent data.

    Returns:
        Formatted telemetry and, if thresholds are set, any alerts.
    """
    result = get_last_agent_result()
    parts = []

    if result is not None and hasattr(result, "metrics") and result.metrics:
        full_text = get_metrics_to_string(result, allowed_names=None)
        if full_text:
            summary = result.metrics.get_summary()

            def _to_json(obj):
                if obj is None:
                    return "null"
                if isinstance(obj, dict):
                    return json.dumps(obj, indent=2)
                if hasattr(obj, "__dict__"):
                    return json.dumps(obj.__dict__, indent=2)
                return json.dumps(dict(obj) if hasattr(obj, "items") else str(obj))

            parts.append("=== Most recent invocation ===")
            parts.append(full_text)
            if summary.get("accumulated_usage"):
                parts.append("\n--- Structured usage ---")
                parts.append(_to_json(summary["accumulated_usage"]))
            if summary.get("accumulated_metrics"):
                parts.append("\n--- Accumulated metrics ---")
                parts.append(_to_json(summary["accumulated_metrics"]))
            if summary.get("tool_usage"):
                parts.append("\n--- Tool usage (summary) ---")
                tool_summary = {
                    name: data.get("execution_stats", data) if isinstance(data, dict) else data
                    for name, data in summary["tool_usage"].items()
                }
                parts.append(_to_json(tool_summary))
    else:
        parts.append(
            "No telemetry for the most recent invocation yet. "
            "Telemetry is recorded after each reply; ask something first, then ask for telemetry."
        )

    last_n = min(max(0, last_n), 50)
    if last_n > 0:
        history = get_telemetry_history(limit=last_n)
        if history:
            parts.append("\n=== History (last {} invocations, newest first) ===".format(len(history)))
            for entry in history:
                ts = entry.get("timestamp")
                metrics = entry.get("metrics")
                ts_str = _format_timestamp(ts) if ts else "?"
                line = invocation_metrics_to_telegram_string(metrics) if metrics else "no metrics"
                parts.append("{}  {}".format(ts_str, line))
        else:
            parts.append("\nNo history yet (invocations are recorded as you chat).")

    now_ts = time.time()
    period_aggregates = {}

    if period and period.lower() in ("hour", "day", "week", "month"):
        p = period.lower()
        entries = get_telemetry_for_period(p, now_ts, include_cloudwatch=include_cloudwatch)
        agg = aggregate_metrics(entries)
        period_aggregates[p] = agg
        parts.append("\n=== Rolling total (last %s) ===" % p)
        parts.append(_format_aggregate(agg, p))

    if running_totals:
        totals = get_running_totals(now_ts, include_cloudwatch=include_cloudwatch)
        parts.append("\n=== Running totals (UTC calendar) ===")
        for name in ("this_hour", "today", "this_week", "this_month"):
            period_aggregates[name] = totals[name]
            parts.append(_format_aggregate(totals[name], name))

    thresholds = get_telemetry_thresholds()
    if thresholds:
        for p in ("hour", "day", "week", "month"):
            if p not in period_aggregates:
                entries = get_telemetry_for_period(p, now_ts, include_cloudwatch=include_cloudwatch)
                period_aggregates[p] = aggregate_metrics(entries)
        for name in ("this_hour", "today", "this_week", "this_month"):
            if name not in period_aggregates:
                totals = get_running_totals(now_ts, include_cloudwatch=include_cloudwatch)
                period_aggregates[name] = totals[name]
        alerts = check_thresholds(period_aggregates)
        if alerts:
            parts.append("\n=== Threshold alerts ===")
            for a in alerts:
                parts.append(a)

    return "\n".join(parts)


@tool
def query_persistent_telemetry(
    period: str = "day",
    include_in_memory: bool = True,
) -> str:
    """Query persistent telemetry from CloudWatch Logs Insights.

    Use when the user asks for historical telemetry across sessions, or when
    the container has restarted and in-memory history is empty. Set
    GLITCH_TELEMETRY_LOG_GROUP to the log group name for CloudWatch queries.

    Args:
        period: One of hour, day, week, month - time range to query.
        include_in_memory: If True, merge with in-memory history for the period.

    Returns:
        Aggregated telemetry from CloudWatch and optionally in-memory.
    """
    p = period.lower() if period else "day"
    if p not in ("hour", "day", "week", "month"):
        return "Invalid period. Use one of: hour, day, week, month."
    if include_in_memory:
        entries = get_telemetry_for_period(p, time.time(), include_cloudwatch=True)
        agg = aggregate_metrics(entries)
    else:
        agg = get_cloudwatch_aggregates(p, None)
    return _format_aggregate(agg, "Persistent telemetry (last %s)" % p)


@tool
def set_telemetry_threshold(metric: str, period: str, limit: float) -> str:
    """Set a telemetry threshold to alert when a metric over a time period exceeds a limit.

    Use when the user wants to be alerted on usage (e.g. alert if tokens per day > 100000).
    Metrics are checked when telemetry(period=...) or telemetry(running_totals=True) is called.

    Args:
        metric: One of input_tokens, output_tokens, total_tokens, invocation_count, duration_seconds.
        period: One of hour, day, week, month (rolling), or this_hour, today, this_week, this_month (calendar).
        limit: Alert when the metric for that period exceeds this value.

    Returns:
        Confirmation message or error.
    """
    from glitch.telemetry import set_telemetry_threshold as set_threshold_impl

    try:
        set_threshold_impl(metric, period, limit)
        return "Threshold set: alert when %s for %s exceeds %s." % (metric, period, limit)
    except ValueError as e:
        return "Invalid threshold: %s" % e


class _TelemetryThresholdInput(BaseModel):
    """Input model for set_telemetry_thresholds to avoid Pydantic TypedDict introspection on Python < 3.12."""

    metric: str
    period: str
    limit: float


@tool
def set_telemetry_thresholds(thresholds: List[_TelemetryThresholdInput]) -> str:
    """Set multiple telemetry thresholds at once, replacing any existing thresholds.

    Use when the user wants to define several alerts in one go (e.g. tokens per day and per week).

    Args:
        thresholds: List of dicts, each with keys: metric, period, limit.
            metric: one of input_tokens, output_tokens, total_tokens, invocation_count, duration_seconds
            period: one of hour, day, week, month, this_hour, today, this_week, this_month
            limit: number; alert when the metric for that period exceeds this value.

    Returns:
        Confirmation message or error.
    """
    try:
        # Convert Pydantic models to TelemetryThreshold dicts for the implementation
        as_dicts: List[TelemetryThreshold] = [
            {"metric": t.metric, "period": t.period, "limit": t.limit} for t in (thresholds or [])
        ]
        set_thresholds_impl(as_dicts)
        n = len(as_dicts)
        return "Set %d threshold(s). Use list_telemetry_thresholds() to see them." % n
    except ValueError as e:
        return "Invalid thresholds: %s" % e


@tool
def list_telemetry_thresholds() -> str:
    """List all configured telemetry thresholds (alert when metric for period exceeds limit)."""
    ths = get_telemetry_thresholds()
    if not ths:
        return "No thresholds configured. Use set_telemetry_threshold(metric, period, limit) to add one."
    lines = ["Configured thresholds:"]
    for t in ths:
        lines.append("  %s for %s > %s" % (t.get("metric"), t.get("period"), t.get("limit")))
    return "\n".join(lines)


@tool
def remove_telemetry_threshold(metric: str, period: str) -> str:
    """Remove one telemetry threshold that matches the given metric and period.

    Use when the user wants to stop alerting on a specific metric/period.
    To remove all thresholds, use clear_telemetry_thresholds().

    Args:
        metric: Same as set_telemetry_threshold (e.g. total_tokens, invocation_count).
        period: Same as set_telemetry_threshold (e.g. day, today).

    Returns:
        Confirmation that the threshold was removed, or that no matching threshold was found.
    """
    if remove_threshold_impl(metric, period):
        return "Removed threshold for %s / %s." % (metric, period)
    return "No threshold found for metric=%s, period=%s. Use list_telemetry_thresholds() to see current ones." % (
        metric,
        period,
    )


@tool
def clear_telemetry_thresholds() -> str:
    """Remove all configured telemetry thresholds. Use when the user wants to clear all alerts."""
    clear_thresholds_impl()
    return "All telemetry thresholds have been cleared."


@tool
def update_telemetry_threshold(metric: str, period: str, new_limit: float) -> str:
    """Update an existing telemetry threshold's limit (e.g. change the alert level).

    Use when the user wants to change a threshold without removing and re-adding it.

    Args:
        metric: Same as set_telemetry_threshold (e.g. total_tokens, invocation_count).
        period: Same as set_telemetry_threshold (e.g. day, today).
        new_limit: New limit; alert when the metric for that period exceeds this value.

    Returns:
        Confirmation that the threshold was updated, or that no matching threshold was found.
    """
    if update_threshold_impl(metric, period, new_limit):
        return "Updated threshold: %s for %s now alerts when > %s." % (metric, period, new_limit)
    return "No threshold found for metric=%s, period=%s. Use list_telemetry_thresholds() to see current ones." % (
        metric,
        period,
    )


# ---------------------------------------------------------------------------
# Add new telemetry metric / update aggregation / CloudWatch metric
# ---------------------------------------------------------------------------


@tool
def add_telemetry_metric(name: str, unit: str = "Count") -> str:
    """Register a new custom telemetry metric. After registering, use record_telemetry_metric(name, value) to record values per invocation.

    Use when the user asks to "add a new telemetry metric". Custom metrics are stored in history and aggregated by period; you can also set thresholds on them.

    Args:
        name: Short name for the metric (e.g. widgets_sold, api_calls).
        unit: Unit string (e.g. Count, Seconds, None). Default Count.

    Returns:
        Confirmation or error.
    """
    try:
        register_custom_telemetry_metric(name, unit)
        return "Registered custom telemetry metric %r (unit=%s). Use record_telemetry_metric(%r, value) to record values for the current invocation." % (
            name,
            unit,
            name,
        )
    except ValueError as e:
        return "Invalid: %s" % e


@tool
def record_telemetry_metric(name: str, value: float) -> str:
    """Record a value for a custom telemetry metric for the current invocation. The metric must have been registered with add_telemetry_metric first.

    Use when the user or a tool produces a value to track (e.g. number of API calls, latency). The value is attached to the current turn and included in history and aggregates.

    Args:
        name: Name registered with add_telemetry_metric.
        value: Numeric value to record.

    Returns:
        Confirmation or error.
    """
    try:
        record_custom_telemetry_metric(name, float(value))
        return "Recorded %s=%s for this invocation." % (name, value)
    except ValueError as e:
        return "Error: %s" % e


@tool
def list_telemetry_metrics() -> str:
    """List registered custom telemetry metrics (name -> unit). Use add_telemetry_metric to register new ones."""
    metrics = get_registered_custom_metrics()
    if not metrics:
        return "No custom metrics registered. Use add_telemetry_metric(name, unit) to add one."
    lines = ["Custom telemetry metrics:"]
    for name, unit in sorted(metrics.items()):
        lines.append("  %s (unit=%s)" % (name, unit))
    return "\n".join(lines)


@tool
def update_telemetry_aggregation(period_name: str, period_seconds: int) -> str:
    """Add or update a rolling telemetry aggregation period. Enables querying aggregates for that period (e.g. telemetry(period='quarter')).

    Use when the user asks to "update telemetry aggregation" or add a new time window (e.g. quarter = 90 days).

    Args:
        period_name: Name for the period (e.g. quarter, fortnight).
        period_seconds: Length of the period in seconds (e.g. 90*86400 for 90 days).

    Returns:
        Confirmation or error.
    """
    try:
        add_aggregation_period(period_name, period_seconds)
        return "Aggregation period %r set to %s seconds. You can now use telemetry(period=%r) for rolling totals." % (
            period_name,
            period_seconds,
            period_name,
        )
    except ValueError as e:
        return "Invalid: %s" % e


@tool
def list_aggregation_periods() -> str:
    """List current telemetry aggregation periods (rolling windows) and their lengths in seconds."""
    periods = get_aggregation_periods()
    lines = ["Aggregation periods (rolling windows):"]
    for name, secs in sorted(periods.items(), key=lambda x: -x[1]):
        lines.append("  %s: %s seconds" % (name, secs))
    return "\n".join(lines)


@tool
def create_cloudwatch_metric(metric_name: str, value: float, unit: str = "Count") -> str:
    """Publish a single metric to CloudWatch Metrics. Use when the user asks to "create a CloudWatch metric for X".

    The metric appears in the Glitch/Agent namespace (or GLITCH_METRICS_NAMESPACE). Good for one-off or periodic custom metrics.

    Args:
        metric_name: Name for the metric (alphanumeric and underscore; will be sanitized).
        value: Numeric value to publish.
        unit: Unit (e.g. Count, Seconds, Milliseconds). Default Count.

    Returns:
        Confirmation or error.
    """
    if publish_custom_metric_to_cloudwatch(metric_name, value, unit):
        return "Published CloudWatch metric %s=%s (unit=%s). Check GLITCH_METRICS_NAMESPACE (default Glitch/Agent) in CloudWatch." % (
            metric_name,
            value,
            unit,
        )
    return "Failed to publish metric to CloudWatch (check logs and IAM permissions)."
