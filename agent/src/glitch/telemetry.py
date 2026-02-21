"""OpenTelemetry configuration and metrics for Glitch agent.

Thin wrapper around Strands built-in telemetry. Follows official patterns from:
- Metrics: https://strandsagents.com/latest/documentation/docs/user-guide/observability-evaluation/metrics/
- API: strands.telemetry.metrics (EventLoopMetrics.get_summary, metrics_to_string)
- Config: strands.telemetry.config (StrandsTelemetry, setup_meter)

Strands tracks: token usage (input/output/cache), cycle count/duration,
tool_metrics (call_count, success_count, error_count, total_time), latencyMs.

Telemetry export strategy (AgentCore-first approach):
1. AgentCore Runtime: Automatic OTEL traces/spans via AgentCore Observability (CloudWatch Transaction Search)
2. Local development: In-memory history for debugging
3. Strands telemetry: Built-in metrics via OpenTelemetry (when strands-agents[otel] is installed)

AgentCore Observability provides:
- Detailed visualizations of each step in the agent workflow
- Real-time visibility into operational performance through CloudWatch dashboards
- Telemetry for key metrics such as session count, latency, duration, token usage, and error rates
- Standardized OpenTelemetry (OTEL)-compatible format
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

# Timeout for CloudWatch Logs Insights queries (seconds)
_CLOUDWATCH_QUERY_TIMEOUT = int(os.environ.get("GLITCH_CLOUDWATCH_QUERY_TIMEOUT", "30"))

_DEFAULT_METRICS_NAMESPACE = "Glitch/Agent"
_cloudwatch_metrics_client: Optional[Any] = None

from glitch.types import (
    TelemetryConfig,
    TelemetryThreshold,
    TelemetryHistoryEntry,
    PeriodAggregates,
    InvocationMetrics,
    TokenUsage,
    ToolUsageStats,
    MetricType,
    create_empty_metrics,
    create_empty_token_usage,
)

logger = logging.getLogger(__name__)

_telemetry_instance: Optional[Any] = None
_last_agent_result: Optional[Any] = None
_telemetry_history: List[TelemetryHistoryEntry] = []
_MAX_TELEMETRY_HISTORY = 10_000
_MAX_HISTORY_AGE_SECONDS = 31 * 24 * 3600  # 31 days
_telemetry_thresholds: List[TelemetryThreshold] = []

# Period lengths in seconds (rolling windows). Mutable so add_aggregation_period can extend.
_PERIOD_SECONDS: Dict[str, int] = {"hour": 3600, "day": 86400, "week": 7 * 86400, "month": 30 * 86400}

# Custom metrics: registered names (with unit) and values for the current invocation.
_custom_metric_units: Dict[str, str] = {}
_current_custom_metrics: Dict[str, float] = {}


def set_last_agent_result(result: Any) -> None:
    """Store the last AgentResult for the telemetry tool (last invocation in this process)."""
    global _last_agent_result
    _last_agent_result = result


def get_last_agent_result() -> Optional[Any]:
    """Return the last stored AgentResult, or None."""
    return _last_agent_result


def append_telemetry(result: Any, skill_info: Optional[Dict[str, Any]] = None) -> None:
    """Append this invocation's metrics to the telemetry history (bounded by count and age).
    
    In-memory storage for local development and debugging. When deployed to AgentCore Runtime,
    telemetry is automatically exported via AgentCore Observability (OTEL -> CloudWatch).
    
    Merges any record_custom_telemetry_metric() values into the entry, then clears them.
    
    Args:
        result: AgentResult from Strands
        skill_info: Optional skill selection info (selected skills, scores, etc.)
    """
    global _telemetry_history, _current_custom_metrics
    now = time.time()
    metrics = extract_metrics_from_result(result)
    
    # Enrich with skill info if provided
    if skill_info:
        metrics["skill_info"] = skill_info
    
    entry: TelemetryHistoryEntry = {"timestamp": now, "metrics": metrics}
    if _current_custom_metrics:
        entry["custom_metrics"] = dict(_current_custom_metrics)
        _current_custom_metrics = {}
    _telemetry_history.append(entry)
    if len(_telemetry_history) > _MAX_TELEMETRY_HISTORY:
        _telemetry_history = _telemetry_history[-_MAX_TELEMETRY_HISTORY:]
    cutoff = now - _MAX_HISTORY_AGE_SECONDS
    _telemetry_history = [e for e in _telemetry_history if (e.get("timestamp") or 0) >= cutoff]


def get_telemetry_history(limit: int = 50) -> List[TelemetryHistoryEntry]:
    """Return the last `limit` telemetry entries (newest first).
    
    Returns in-memory history. When deployed to AgentCore Runtime, use CloudWatch
    Transaction Search for persistent telemetry across container restarts.
    """
    global _telemetry_history
    return list(reversed(_telemetry_history[-limit:]))


def _get_usage(metrics: Optional[InvocationMetrics], key: str) -> int:
    """Get a token-usage value from InvocationMetrics."""
    if not metrics or not isinstance(metrics, dict):
        return 0
    usage = metrics.get("token_usage") or {}
    return int(usage.get(key, 0) or 0)


def _get_logs_client():
    """Lazy-init boto3 CloudWatch Logs client."""
    try:
        import boto3
        return boto3.client("logs")
    except Exception as e:
        logger.debug("Failed to create CloudWatch Logs client: %s", e)
        return None


def query_cloudwatch_telemetry(
    period: str,
    log_group: Optional[str] = None,
) -> List[TelemetryHistoryEntry]:
    """Query CloudWatch Logs Insights for telemetry entries (invocation_metrics events).

    Uses structured JSON logs emitted by log_invocation_metrics. Falls back gracefully
    if CloudWatch is unavailable or log group is not set.

    Args:
        period: One of hour, day, week, month (rolling window).
        log_group: CloudWatch log group name; defaults to GLITCH_TELEMETRY_LOG_GROUP env.

    Returns:
        List of TelemetryHistoryEntry parsed from CloudWatch (may be empty).
    """
    client = _get_logs_client()
    log_group = log_group or os.environ.get("GLITCH_TELEMETRY_LOG_GROUP")
    if not client or not log_group:
        return []
    delta = _PERIOD_SECONDS.get(period)
    if not delta:
        return []
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - (delta * 1000)
    query = """
    fields @timestamp, @message
    | filter @message like /"event_type":\\s*"invocation_metrics"/
    | sort @timestamp desc
    | limit 1000
    """
    try:
        resp = client.start_query(
            logGroupName=log_group,
            startTime=start_ms,
            endTime=end_ms,
            queryString=query.strip(),
        )
        query_id = resp.get("queryId")
        if not query_id:
            return []
        deadline = time.time() + _CLOUDWATCH_QUERY_TIMEOUT
        while time.time() < deadline:
            result = client.get_query_results(queryId=query_id)
            status = result.get("status")
            if status == "Complete":
                entries: List[TelemetryHistoryEntry] = []
                for row in result.get("results", []):
                    msg = None
                    ts = None
                    for field in row:
                        if field.get("field") == "@message":
                            msg = field.get("value")
                        elif field.get("field") == "@timestamp":
                            ts = field.get("value")
                    if msg and ts:
                        try:
                            data = json.loads(msg)
                            ts_float = int(ts) / 1000.0 if len(ts) == 13 else float(ts)
                            token_usage = data.get("token_usage") or {}
                            metrics: InvocationMetrics = {
                                "duration_seconds": data.get("duration_seconds", 0),
                                "token_usage": {
                                    "input_tokens": token_usage.get("input_tokens", 0),
                                    "output_tokens": token_usage.get("output_tokens", 0),
                                    "total_tokens": token_usage.get("total_tokens", 0),
                                    "cache_read_tokens": token_usage.get("cache_read_tokens", 0),
                                    "cache_write_tokens": token_usage.get("cache_write_tokens", 0),
                                },
                                "cycle_count": data.get("cycle_count", 0),
                                "latency_ms": data.get("latency_ms", 0),
                                "stop_reason": "",
                                "tool_usage": {k: {"call_count": 1, "success_count": 1, "error_count": 0, "total_time": 0.0} for k in (data.get("tools_used") or [])},
                            }
                            entries.append({"timestamp": ts_float, "metrics": metrics})
                        except (json.JSONDecodeError, TypeError, KeyError) as e:
                            logger.debug("Skip CloudWatch log line: %s", e)
                return entries
            if status == "Failed" or status == "Cancelled":
                break
            time.sleep(0.5)
        logger.warning("CloudWatch Logs Insights query timed out or failed")
        return []
    except Exception as e:
        logger.warning("CloudWatch telemetry query failed: %s", e)
        return []


def get_cloudwatch_aggregates(
    period: str,
    log_group: Optional[str] = None,
) -> PeriodAggregates:
    """Query CloudWatch Logs Insights for aggregated metrics over the period.

    Returns PeriodAggregates (invocation_count, token totals, etc.) from
    structured invocation_metrics logs in the log group.
    """
    entries = query_cloudwatch_telemetry(period=period, log_group=log_group)
    return aggregate_metrics(entries)


def get_telemetry_for_period(
    period: str,
    now_ts: Optional[float] = None,
    include_cloudwatch: bool = False,
) -> List[TelemetryHistoryEntry]:
    """Return entries in the rolling window for period. period in ('hour','day','week','month').

    Uses in-memory history. When include_cloudwatch=True, supplements with
    CloudWatch Logs Insights query for persistent telemetry across restarts.
    """
    global _telemetry_history
    now = now_ts if now_ts is not None else time.time()
    delta = _PERIOD_SECONDS.get(period)
    if not delta:
        return []
    cutoff = now - delta
    entries = [e for e in _telemetry_history if (e.get("timestamp") or 0) >= cutoff]
    if include_cloudwatch:
        cw = query_cloudwatch_telemetry(period, None)
        seen_ts: Dict[float, bool] = {}
        for e in cw:
            ts = e.get("timestamp") or 0
            if ts not in seen_ts:
                seen_ts[ts] = True
                entries.append(e)
        entries.sort(key=lambda x: x.get("timestamp") or 0)
    return entries


def get_running_totals(
    now_ts: Optional[float] = None,
    include_cloudwatch: bool = False,
) -> Dict[str, PeriodAggregates]:
    """Return aggregates for calendar periods: this_hour, today, this_week, this_month (UTC).

    Uses in-memory history. When include_cloudwatch=True, merges in aggregates
    from CloudWatch Logs Insights for persistent telemetry across restarts.
    """
    global _telemetry_history
    now = now_ts if now_ts is not None else time.time()
    dt = datetime.fromtimestamp(now, tz=timezone.utc)
    start_of_hour = dt.replace(minute=0, second=0, microsecond=0).timestamp()
    start_of_day = dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    start_of_week = start_of_day - (dt.weekday() * 86400)
    start_of_month = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
    buckets: Dict[str, float] = {
        "this_hour": start_of_hour,
        "today": start_of_day,
        "this_week": start_of_week,
        "this_month": start_of_month,
    }

    out: Dict[str, PeriodAggregates] = {}
    for name, start in buckets.items():
        entries = [e for e in _telemetry_history if (e.get("timestamp") or 0) >= start]
        agg = aggregate_metrics(entries)
        if include_cloudwatch:
            period_map = {"this_hour": "hour", "today": "day", "this_week": "week", "this_month": "month"}
            cw_agg = get_cloudwatch_aggregates(period_map.get(name, "day"), None)
            agg = _merge_aggregates(agg, cw_agg)
        out[name] = agg
    return out


def _merge_aggregates(a: PeriodAggregates, b: PeriodAggregates) -> PeriodAggregates:
    """Merge two PeriodAggregates by summing numeric fields."""
    out: PeriodAggregates = {
        "invocation_count": a.get("invocation_count", 0) + b.get("invocation_count", 0),
        "input_tokens": a.get("input_tokens", 0) + b.get("input_tokens", 0),
        "output_tokens": a.get("output_tokens", 0) + b.get("output_tokens", 0),
        "total_tokens": a.get("total_tokens", 0) + b.get("total_tokens", 0),
        "cache_read_tokens": a.get("cache_read_tokens", 0) + b.get("cache_read_tokens", 0),
        "cache_write_tokens": a.get("cache_write_tokens", 0) + b.get("cache_write_tokens", 0),
        "duration_seconds": round((a.get("duration_seconds") or 0) + (b.get("duration_seconds") or 0), 2),
        "latency_ms_total": (a.get("latency_ms_total") or 0) + (b.get("latency_ms_total") or 0),
        "latency_ms_avg": 0,
    }
    total_inv = out["invocation_count"]
    out["latency_ms_avg"] = round(out["latency_ms_total"] / total_inv, 0) if total_inv else 0
    ac = (a.get("custom_metrics") or {}).copy()
    for k, v in (b.get("custom_metrics") or {}).items():
        ac[k] = ac.get(k, 0) + v
    if ac:
        out["custom_metrics"] = ac
    return out


def aggregate_metrics(entries: List[TelemetryHistoryEntry]) -> PeriodAggregates:
    """Aggregate a list of history entries into totals for the period. Includes custom metrics sum."""
    count = len(entries)
    input_tokens = output_tokens = total_tokens = cache_read = cache_write = 0
    duration_seconds = 0.0
    latency_ms = 0
    custom_totals: Dict[str, float] = {}
    for e in entries:
        m = e.get("metrics") or {}
        input_tokens += _get_usage(m, "input_tokens")
        output_tokens += _get_usage(m, "output_tokens")
        total_tokens += _get_usage(m, "total_tokens")
        cache_read += _get_usage(m, "cache_read_tokens")
        cache_write += _get_usage(m, "cache_write_tokens")
        duration_seconds += float(m.get("duration_seconds") or 0)
        latency_ms += int(m.get("latency_ms") or 0)
        for name, val in (e.get("custom_metrics") or {}).items():
            custom_totals[name] = custom_totals.get(name, 0) + float(val)
    out: PeriodAggregates = {
        "invocation_count": count,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cache_read_tokens": cache_read,
        "cache_write_tokens": cache_write,
        "duration_seconds": round(duration_seconds, 2),
        "latency_ms_total": latency_ms,
        "latency_ms_avg": round(latency_ms / count, 0) if count else 0,
    }
    if custom_totals:
        out["custom_metrics"] = custom_totals
    return out


def _allowed_threshold_metric(metric: str) -> bool:
    """True if metric is a built-in or registered custom metric."""
    allowed = ("input_tokens", "output_tokens", "total_tokens", "invocation_count", "duration_seconds")
    return metric.lower() in allowed or metric in _custom_metric_units


def set_telemetry_threshold(metric: str, period: str, limit: float) -> None:
    """Add a threshold: alert when metric over period exceeds limit. In-memory only."""
    global _telemetry_thresholds
    period = period.lower()
    if period not in _PERIOD_SECONDS and period not in ("this_hour", "today", "this_week", "this_month"):
        raise ValueError("period must be one of: hour, day, week, month, this_hour, today, this_week, this_month")
    metric = metric.lower()
    if not _allowed_threshold_metric(metric):
        raise ValueError("metric must be one of: input_tokens, output_tokens, total_tokens, invocation_count, duration_seconds, or a registered custom metric name")
    _telemetry_thresholds.append({"metric": metric, "period": period, "limit": float(limit)})


def set_telemetry_thresholds(thresholds: List[TelemetryThreshold]) -> None:
    """Replace all thresholds with the given list. Each item must have metric, period, limit."""
    global _telemetry_thresholds
    _telemetry_thresholds = []
    for th in thresholds or []:
        if not isinstance(th, dict):
            raise ValueError("Each threshold must be a dict with metric, period, limit")
        set_telemetry_threshold(
            th.get("metric", ""),
            th.get("period", ""),
            float(th.get("limit", 0)),
        )


def get_telemetry_thresholds() -> List[TelemetryThreshold]:
    """Return list of configured threshold dicts."""
    return list(_telemetry_thresholds)


def remove_telemetry_threshold(metric: str, period: str) -> bool:
    """Remove one threshold that matches the given metric and period.
    
    Returns True if a matching threshold was removed, False if none matched.
    """
    global _telemetry_thresholds
    metric = metric.lower()
    period = period.lower()
    for i, th in enumerate(_telemetry_thresholds):
        if (th.get("metric") or "").lower() == metric and (th.get("period") or "").lower() == period:
            _telemetry_thresholds.pop(i)
            return True
    return False


def update_telemetry_threshold(metric: str, period: str, new_limit: float) -> bool:
    """Update the limit of an existing threshold that matches metric and period. Returns True if updated."""
    global _telemetry_thresholds
    metric = metric.lower()
    period = period.lower()
    for th in _telemetry_thresholds:
        if (th.get("metric") or "").lower() == metric and (th.get("period") or "").lower() == period:
            th["limit"] = float(new_limit)
            return True
    return False


def clear_telemetry_thresholds() -> None:
    """Remove all configured thresholds."""
    global _telemetry_thresholds
    _telemetry_thresholds = []


def check_thresholds(period_aggregates: Dict[str, PeriodAggregates]) -> List[str]:
    """Given a dict of period_name -> aggregate_metrics, check configured thresholds and return list of alert strings."""
    global _telemetry_thresholds
    alerts = []
    for th in _telemetry_thresholds:
        period = th.get("period")
        metric = th.get("metric")
        limit = th.get("limit")
        agg = period_aggregates.get(period)
        if not agg:
            continue
        value = agg.get(metric)
        if value is None and agg.get("custom_metrics") is not None:
            value = agg["custom_metrics"].get(metric)
        if value is None:
            continue
        if value > limit:
            alerts.append("ALERT: %s for %s is %s (threshold: %s)" % (metric, period, value, limit))
    return alerts


# ---------------------------------------------------------------------------
# Custom metrics and aggregation periods
# ---------------------------------------------------------------------------

def register_custom_telemetry_metric(name: str, unit: str = "Count") -> None:
    """Register a custom metric name. Once registered, record_custom_telemetry_metric(name, value) can be used."""
    global _custom_metric_units
    name = name.strip().lower().replace(" ", "_")
    if not name:
        raise ValueError("metric name cannot be empty")
    _custom_metric_units[name] = unit


def get_registered_custom_metrics() -> Dict[str, str]:
    """Return dict of registered custom metric names to their units."""
    return dict(_custom_metric_units)


def record_custom_telemetry_metric(name: str, value: float) -> None:
    """Record a value for a custom metric for the current invocation. Name must be registered first."""
    global _current_custom_metrics, _custom_metric_units
    name = name.strip().lower().replace(" ", "_")
    if name not in _custom_metric_units:
        raise ValueError("unknown custom metric %r; use add_telemetry_metric(name, unit) first" % name)
    _current_custom_metrics[name] = float(value)


def add_aggregation_period(name: str, period_seconds: int) -> None:
    """Add or update a rolling aggregation period (e.g. 'quarter' = 90*86400). Enables get_telemetry_for_period(name)."""
    global _PERIOD_SECONDS
    name = name.lower().strip()
    if not name or period_seconds < 1:
        raise ValueError("name must be non-empty and period_seconds must be positive")
    _PERIOD_SECONDS[name] = int(period_seconds)


def get_aggregation_periods() -> Dict[str, int]:
    """Return current rolling period names and their lengths in seconds."""
    return dict(_PERIOD_SECONDS)


# ---------------------------------------------------------------------------
# CloudWatch Metrics Export (long-term aggregates, 1-hour resolution)
# ---------------------------------------------------------------------------


def _get_cloudwatch_metrics_client():
    """Lazy-init boto3 CloudWatch client for metrics."""
    global _cloudwatch_metrics_client
    if _cloudwatch_metrics_client is None:
        try:
            import boto3
            _cloudwatch_metrics_client = boto3.client("cloudwatch")
        except Exception as e:
            logger.debug("Failed to create CloudWatch Metrics client: %s", e)
    return _cloudwatch_metrics_client


def _get_metrics_namespace() -> str:
    """Return the CloudWatch Metrics namespace from env or default."""
    return os.environ.get("GLITCH_METRICS_NAMESPACE", _DEFAULT_METRICS_NAMESPACE)


def publish_hourly_metrics_to_cloudwatch(aggregates: PeriodAggregates) -> bool:
    """
    Publish hourly aggregate metrics to CloudWatch Metrics for long-term retention.
    
    CloudWatch retains 1-hour resolution metrics for 455 days (15 months).
    Call this once per hour with the aggregated metrics for that hour.
    
    Args:
        aggregates: dict from aggregate_metrics() with invocation_count, input_tokens, etc.
    
    Returns:
        True if published successfully
    """
    client = _get_cloudwatch_metrics_client()
    if not client:
        return False
    
    namespace = _get_metrics_namespace()
    now = datetime.now(timezone.utc)
    
    metric_data = []
    metric_mappings = [
        ("InvocationCount", aggregates.get("invocation_count", 0), "Count"),
        ("InputTokens", aggregates.get("input_tokens", 0), "Count"),
        ("OutputTokens", aggregates.get("output_tokens", 0), "Count"),
        ("TotalTokens", aggregates.get("total_tokens", 0), "Count"),
        ("CacheReadTokens", aggregates.get("cache_read_tokens", 0), "Count"),
        ("CacheWriteTokens", aggregates.get("cache_write_tokens", 0), "Count"),
        ("DurationSeconds", aggregates.get("duration_seconds", 0), "Seconds"),
        ("LatencyMsTotal", aggregates.get("latency_ms_total", 0), "Milliseconds"),
    ]
    
    for metric_name, value, unit in metric_mappings:
        if value > 0:
            metric_data.append({
                "MetricName": metric_name,
                "Timestamp": now,
                "Value": float(value),
                "Unit": unit,
                "StorageResolution": 3600,
            })
    
    if not metric_data:
        logger.debug("No metrics to publish (all zero)")
        return True
    
    try:
        client.put_metric_data(Namespace=namespace, MetricData=metric_data)
        logger.info("Published %d metrics to CloudWatch namespace %s", len(metric_data), namespace)
        return True
    except Exception as e:
        logger.warning("Failed to publish metrics to CloudWatch: %s", e)
        return False


def publish_custom_metric_to_cloudwatch(metric_name: str, value: float, unit: str = "Count") -> bool:
    """
    Publish a single custom metric to CloudWatch Metrics.
    Use when the user asks to "create a CloudWatch metric for X".
    """
    client = _get_cloudwatch_metrics_client()
    if not client:
        return False
    namespace = _get_metrics_namespace()
    # CloudWatch metric names: alphanumeric and underscore
    safe_name = "".join(c if c.isalnum() or c == "_" else "_" for c in metric_name.strip())[:255] or "CustomMetric"
    try:
        client.put_metric_data(
            Namespace=namespace,
            MetricData=[{
                "MetricName": safe_name,
                "Timestamp": datetime.now(timezone.utc),
                "Value": float(value),
                "Unit": unit,
                "StorageResolution": 60,
            }],
        )
        logger.info("Published custom metric %s=%s to CloudWatch namespace %s", safe_name, value, namespace)
        return True
    except Exception as e:
        logger.warning("Failed to publish custom metric to CloudWatch: %s", e)
        return False


def setup_telemetry(config: Optional[TelemetryConfig] = None) -> Optional[Any]:
    """
    Setup OpenTelemetry instrumentation for the agent using Strands SDK.
    
    Strands automatically emits these metrics via OpenTelemetry:
    - strands.event_loop.input.tokens
    - strands.event_loop.output.tokens
    - strands.event_loop.cache_read.input.tokens
    - strands.event_loop.cache_write.input.tokens
    - strands.event_loop.cycle_count
    - strands.event_loop.cycle_duration
    - strands.event_loop.latency
    - strands.tool.call_count
    - strands.tool.duration
    - strands.tool.success_count
    - strands.tool.error_count
    - strands.model.time_to_first_token
    
    Args:
        config: TelemetryConfig with service_name, otlp_endpoint, etc.
                If None, uses defaults from TelemetryConfig.
    
    Returns:
        StrandsTelemetry instance or None if not available
    """
    global _telemetry_instance
    
    if _telemetry_instance is not None:
        logger.info("Telemetry already initialized, returning existing instance")
        return _telemetry_instance
    
    if config is None:
        config = TelemetryConfig()
    
    try:
        from strands.telemetry import StrandsTelemetry
        
        os.environ["OTEL_SERVICE_NAME"] = config.service_name
        
        if config.otlp_endpoint:
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = config.otlp_endpoint
        elif "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ:
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
        
        # StrandsTelemetry: setup_* return self for chaining (strands.telemetry.config)
        telemetry = StrandsTelemetry()
        if config.enable_otlp:
            telemetry.setup_otlp_exporter()
            logger.info("OTLP exporter enabled: %s", os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"))
        if config.enable_console:
            telemetry.setup_console_exporter()
            logger.info("Console exporter enabled")
        telemetry.setup_meter(
            enable_otlp_exporter=config.enable_otlp,
            enable_console_exporter=config.enable_console,
        )
        
        logger.info(f"OpenTelemetry initialized for {config.service_name}")
        _telemetry_instance = telemetry
        return telemetry
        
    except ImportError as e:
        logger.warning(f"Strands telemetry not available (install with 'pip install strands-agents[otel]'): {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to setup telemetry: {e}")
        return None


def get_telemetry() -> Optional[Any]:
    """Get the current telemetry instance.
    
    Returns:
        StrandsTelemetry instance or None if not initialized
    """
    return _telemetry_instance


def _get_usage_value(usage: Any, key: str, default: int = 0) -> int:
    """Get a value from Strands Usage (TypedDict or dict). Handles both dict and object access."""
    if usage is None:
        return default
    if isinstance(usage, dict):
        return int(usage.get(key, default) or 0)
    return int(getattr(usage, key, default) or 0)


def extract_metrics_from_result(result: Any) -> InvocationMetrics:
    """
    Extract metrics from a Strands AgentResult using EventLoopMetrics.get_summary().

    Follows Strands API: result.metrics is EventLoopMetrics; get_summary() returns
    total_cycles, total_duration, tool_usage (execution_stats), accumulated_usage (Usage),
    accumulated_metrics (latencyMs). See strands.telemetry.metrics.EventLoopMetrics.
    """
    if result is None:
        return create_empty_metrics()

    try:
        if not hasattr(result, "metrics") or not result.metrics:
            return create_empty_metrics()
        summary = result.metrics.get_summary()
        usage = summary.get("accumulated_usage") or {}
        acc_metrics = summary.get("accumulated_metrics") or {}

        token_usage: TokenUsage = {
            "input_tokens": _get_usage_value(usage, "inputTokens"),
            "output_tokens": _get_usage_value(usage, "outputTokens"),
            "total_tokens": _get_usage_value(usage, "totalTokens"),
            "cache_read_tokens": _get_usage_value(usage, "cacheReadInputTokens"),
            "cache_write_tokens": _get_usage_value(usage, "cacheWriteInputTokens"),
        }

        tool_usage: Dict[str, ToolUsageStats] = {}
        for name, data in summary.get("tool_usage", {}).items():
            exec_stats = data.get("execution_stats", {}) if isinstance(data, dict) else {}
            tool_usage[name] = ToolUsageStats(
                call_count=exec_stats.get("call_count", 0),
                success_count=exec_stats.get("success_count", 0),
                error_count=exec_stats.get("error_count", 0),
                total_time=float(exec_stats.get("total_time", 0) or 0),
            )

        latency = acc_metrics.get("latencyMs", 0) if isinstance(acc_metrics, dict) else getattr(acc_metrics, "latencyMs", 0)
        return InvocationMetrics(
            duration_seconds=round(float(summary.get("total_duration", 0) or 0), 3),
            token_usage=token_usage,
            cycle_count=int(summary.get("total_cycles", 0) or 0),
            latency_ms=int(latency or 0),
            stop_reason=str(result.stop_reason) if hasattr(result, "stop_reason") else "",
            tool_usage=tool_usage,
        )
    except Exception as e:
        logger.warning("Failed to extract metrics from result: %s", e)
    return create_empty_metrics()


def log_invocation_metrics(
    metrics: InvocationMetrics,
    user_message: str = "",
    response_preview: str = "",
    session_id: str = "",
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log detailed metrics for an invocation to CloudWatch.
    
    Args:
        metrics: InvocationMetrics from extract_metrics_from_result()
        user_message: The user's input message (truncated for logging)
        response_preview: Preview of the response (truncated for logging)
        session_id: Session identifier for correlation
        extra: Optional extra data to include in logs (e.g., skill selection info)
    """
    token_usage = metrics.get("token_usage", create_empty_token_usage())
    
    logger.info(
        f"Invocation complete | "
        f"tokens: {token_usage.get('input_tokens', 0)}in/{token_usage.get('output_tokens', 0)}out "
        f"(cache: {token_usage.get('cache_read_tokens', 0)}r/{token_usage.get('cache_write_tokens', 0)}w) | "
        f"cycles: {metrics.get('cycle_count', 0)} | "
        f"duration: {metrics.get('duration_seconds', 0):.2f}s | "
        f"latency: {metrics.get('latency_ms', 0):.0f}ms"
    )

    structured_log: Dict[str, Any] = {
        "event_type": "invocation_metrics",
        "timestamp": time.time(),
        "session_id": session_id,
        "token_usage": {
            "input_tokens": token_usage.get("input_tokens", 0),
            "output_tokens": token_usage.get("output_tokens", 0),
            "total_tokens": token_usage.get("total_tokens", 0),
            "cache_read_tokens": token_usage.get("cache_read_tokens", 0),
            "cache_write_tokens": token_usage.get("cache_write_tokens", 0),
        },
        "duration_seconds": metrics.get("duration_seconds", 0),
        "cycle_count": metrics.get("cycle_count", 0),
        "latency_ms": metrics.get("latency_ms", 0),
        "tools_used": list((metrics.get("tool_usage") or {}).keys()),
    }
    if extra:
        structured_log["skill_info"] = extra
    logger.info(json.dumps(structured_log))

    tool_usage = metrics.get("tool_usage", {})
    if tool_usage:
        logger.info(f"Tools used: {list(tool_usage.keys())}")

    # Log skill selection info if provided
    if extra:
        skills_injected = extra.get("skills_injected", 0)
        if skills_injected > 0:
            skill_ids = extra.get("skill_ids", [])
            model_used = extra.get("model_used", "unknown")
            logger.info(
                f"Skills injected: {skills_injected} | "
                f"skill_ids: {skill_ids} | "
                f"model: {model_used}"
            )


def get_metrics_to_string(result: Any, allowed_names: Optional[set] = None) -> str:
    """
    Human-readable metrics string from Strands EventLoopMetrics.

    Uses strands.telemetry.metrics.metrics_to_string(event_loop_metrics, allowed_names).
    """
    try:
        from strands.telemetry.metrics import metrics_to_string

        if hasattr(result, "metrics") and result.metrics:
            return metrics_to_string(result.metrics, allowed_names=allowed_names or set())
    except ImportError:
        pass
    except Exception as e:
        logger.warning("Failed to format metrics: %s", e)
    return ""


def invocation_metrics_to_telegram_string(metrics: Optional[InvocationMetrics]) -> str:
    """
    Format InvocationMetrics as a short Telegram-friendly line (Strands telemetry summary).
    
    Args:
        metrics: InvocationMetrics from InvocationResponse (or None)
    
    Returns:
        One-line summary e.g. "📊 120 in / 80 out · 1.2s · 2 tools" or empty string
    """
    if not metrics:
        return ""
    token = metrics.get("token_usage") or {}
    in_t = token.get("input_tokens", 0)
    out_t = token.get("output_tokens", 0)
    cache_r = token.get("cache_read_tokens", 0)
    cache_w = token.get("cache_write_tokens", 0)
    duration = metrics.get("duration_seconds", 0)
    cycles = metrics.get("cycle_count", 0)
    latency_ms = metrics.get("latency_ms", 0)
    tool_usage = metrics.get("tool_usage") or {}
    tool_names = list(tool_usage.keys()) if tool_usage else []
    parts = [f"📊 {in_t} in / {out_t} out"]
    if cache_r or cache_w:
        parts.append(f"cache {cache_r}r/{cache_w}w")
    parts.append(f"{duration:.1f}s")
    if latency_ms:
        parts.append(f"{latency_ms}ms")
    if cycles and cycles > 1:
        parts.append(f"{cycles} cycles")
    if tool_names:
        parts.append(f"tools: {', '.join(tool_names)}")
    return " · ".join(parts)


def add_span_attributes(attributes: Dict[str, Any]) -> None:
    """
    Add custom attributes to the current OpenTelemetry span.
    
    Args:
        attributes: Dictionary of attribute key-value pairs to add
    """
    try:
        from opentelemetry import trace
        
        span = trace.get_current_span()
        if span and span.is_recording():
            for key, value in attributes.items():
                span.set_attribute(key, value)
    except ImportError:
        logger.debug("OpenTelemetry trace module not available")
    except Exception as e:
        logger.debug(f"Failed to add span attributes: {e}")


def record_metric(
    name: str,
    value: float,
    unit: str = "",
    attributes: Optional[Dict[str, Any]] = None,
    metric_type: MetricType = MetricType.COUNTER,
) -> None:
    """
    Record a custom metric using OpenTelemetry.
    
    Note: Strands already emits standard metrics automatically.
    Use this for custom application-specific metrics.
    
    Args:
        name: Metric name (e.g., "glitch.custom.my_metric")
        value: Metric value
        unit: Unit of measurement (e.g., "ms", "bytes", "1")
        attributes: Optional attributes/labels for the metric
        metric_type: Type of metric (COUNTER, GAUGE, or HISTOGRAM)
    """
    try:
        from opentelemetry import metrics
        
        meter = metrics.get_meter("glitch-agent")
        attrs = attributes or {}
        
        if metric_type == MetricType.COUNTER:
            counter = meter.create_counter(name, unit=unit, description=f"Counter for {name}")
            counter.add(int(value), attributes=attrs)
        elif metric_type == MetricType.GAUGE:
            gauge = meter.create_up_down_counter(name, unit=unit, description=f"Gauge for {name}")
            gauge.add(value, attributes=attrs)
        elif metric_type == MetricType.HISTOGRAM:
            histogram = meter.create_histogram(name, unit=unit, description=f"Histogram for {name}")
            histogram.record(value, attributes=attrs)
            
    except ImportError:
        logger.debug("OpenTelemetry metrics module not available")
    except Exception as e:
        logger.debug(f"Failed to record metric: {e}")


def create_span(name: str, attributes: Optional[Dict[str, Any]] = None):
    """
    Create a new OpenTelemetry span context manager.
    
    Usage:
        with create_span("my_operation", {"key": "value"}):
            # code to trace
    
    Args:
        name: Span name
        attributes: Optional span attributes
    
    Returns:
        Span context manager, or None if OpenTelemetry unavailable
    """
    try:
        from opentelemetry import trace
        
        tracer = trace.get_tracer("glitch-agent")
        return tracer.start_as_current_span(name, attributes=attributes)
    except ImportError:
        logger.debug("OpenTelemetry trace module not available")
        return None
    except Exception as e:
        logger.debug(f"Failed to create span: {e}")
        return None


def get_metrics_collector() -> Optional[Any]:
    """
    Get the Strands MetricsClient singleton.
    
    Returns:
        Strands MetricsClient which manages all OpenTelemetry metric instruments,
        or None if not available
    """
    try:
        from strands.telemetry.metrics import MetricsClient
        return MetricsClient()
    except ImportError:
        return None
    except Exception:
        return None
