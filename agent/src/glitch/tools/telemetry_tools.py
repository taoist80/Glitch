"""Telemetry tools: full metrics, history, period aggregates, running totals, and thresholds.
"""

import json
import logging
import time
from datetime import datetime, timezone

from strands import tool

from glitch.telemetry import (
    aggregate_metrics,
    check_thresholds,
    get_last_agent_result,
    get_metrics_to_string,
    get_telemetry_history,
    get_telemetry_for_period,
    get_telemetry_thresholds,
    get_running_totals,
    invocation_metrics_to_telegram_string,
)

logger = logging.getLogger(__name__)


def _format_timestamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _format_aggregate(agg: dict, label: str) -> str:
    lines = [
        "  invocations: %s" % agg.get("invocation_count", 0),
        "  input_tokens: %s" % agg.get("input_tokens", 0),
        "  output_tokens: %s" % agg.get("output_tokens", 0),
        "  total_tokens: %s" % agg.get("total_tokens", 0),
        "  duration_seconds: %s" % agg.get("duration_seconds", 0),
    ]
    return "%s:\n%s" % (label, "\n".join(lines))


@tool
def telemetry(
    last_n: int = 0,
    period: str = "",
    running_totals: bool = False,
) -> str:
    """Return Strands telemetry: latest invocation, optional history, and optional aggregates by time period.

    Use when the user asks for metrics, usage by hour/day/week/month, running totals, or alerts.
    - Most recent: full EventLoopMetrics for the last reply.
    - last_n > 0: append last N invocations (newest first) with one-line summaries.
    - period: one of 'hour','day','week','month' to add rolling aggregates for that window (e.g. total tokens in last 24h).
    - running_totals: if True, add aggregates for this hour, today, this week, this month (UTC calendar).

    After any period or running totals, configured thresholds are checked and ALERT lines are appended if exceeded.

    Args:
        last_n: Number of past invocations to list (0 = skip). Max 50.
        period: Optional. One of hour, day, week, month for rolling-window totals.
        running_totals: If True, include this_hour, today, this_week, this_month running totals.

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
        entries = get_telemetry_for_period(p, now_ts)
        agg = aggregate_metrics(entries)
        period_aggregates[p] = agg
        parts.append("\n=== Rolling total (last %s) ===" % p)
        parts.append(_format_aggregate(agg, p))

    if running_totals:
        totals = get_running_totals(now_ts)
        parts.append("\n=== Running totals (UTC calendar) ===")
        for name in ("this_hour", "today", "this_week", "this_month"):
            period_aggregates[name] = totals[name]
            parts.append(_format_aggregate(totals[name], name))

    thresholds = get_telemetry_thresholds()
    if thresholds:
        for p in ("hour", "day", "week", "month"):
            if p not in period_aggregates:
                entries = get_telemetry_for_period(p, now_ts)
                period_aggregates[p] = aggregate_metrics(entries)
        for name in ("this_hour", "today", "this_week", "this_month"):
            if name not in period_aggregates:
                totals = get_running_totals(now_ts)
                period_aggregates[name] = totals[name]
        alerts = check_thresholds(period_aggregates)
        if alerts:
            parts.append("\n=== Threshold alerts ===")
            for a in alerts:
                parts.append(a)

    return "\n".join(parts)


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
