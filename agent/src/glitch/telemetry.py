"""OpenTelemetry configuration and metrics for Glitch agent.

Thin wrapper around Strands built-in telemetry. Follows official patterns from:
- Metrics: https://strandsagents.com/latest/documentation/docs/user-guide/observability-evaluation/metrics/
- API: strands.telemetry.metrics (EventLoopMetrics.get_summary, metrics_to_string)
- Config: strands.telemetry.config (StrandsTelemetry, setup_meter)

Strands tracks: token usage (input/output/cache), cycle count/duration,
tool_metrics (call_count, success_count, error_count, total_time), latencyMs.

Telemetry export strategy (hybrid approach per AgentCore best practices):
1. OTEL/ADOT: Automatic traces/spans via opentelemetry-instrument (set env vars)
2. CloudWatch Logs: Per-invocation JSON events for detailed history (GLITCH_TELEMETRY_LOG_GROUP)
3. CloudWatch Metrics: Hourly aggregates for long-term retention (15 months)

CloudWatch Metrics retention:
- 1-minute resolution: 15 days
- 5-minute resolution: 63 days
- 1-hour resolution: 455 days (15 months)
"""

import json
import os
import time
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

_DEFAULT_TELEMETRY_LOG_GROUP = "/glitch/telemetry"
_DEFAULT_METRICS_NAMESPACE = "Glitch/Agent"
_cloudwatch_sequence_tokens: Dict[str, str] = {}
_cloudwatch_logs_client: Optional[Any] = None
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


def append_telemetry(result: Any) -> None:
    """Append this invocation's metrics to the telemetry history (bounded by count and age).
    
    Also writes to CloudWatch Logs if GLITCH_TELEMETRY_LOG_GROUP is set.
    Merges any record_custom_telemetry_metric() values into the entry, then clears them.
    """
    global _telemetry_history, _current_custom_metrics
    now = time.time()
    metrics = extract_metrics_from_result(result)
    entry: TelemetryHistoryEntry = {"timestamp": now, "metrics": metrics}
    if _current_custom_metrics:
        entry["custom_metrics"] = dict(_current_custom_metrics)
        _current_custom_metrics = {}
    _telemetry_history.append(entry)
    if len(_telemetry_history) > _MAX_TELEMETRY_HISTORY:
        _telemetry_history = _telemetry_history[-_MAX_TELEMETRY_HISTORY:]
    cutoff = now - _MAX_HISTORY_AGE_SECONDS
    _telemetry_history = [e for e in _telemetry_history if (e.get("timestamp") or 0) >= cutoff]
    
    if os.environ.get("GLITCH_TELEMETRY_LOG_GROUP"):
        _write_telemetry_to_cloudwatch(entry, event_type="invocation")


def get_telemetry_history(limit: int = 50) -> List[TelemetryHistoryEntry]:
    """Return the last `limit` telemetry entries (newest first)."""
    global _telemetry_history
    n = min(max(0, limit), len(_telemetry_history))
    if n == 0:
        return []
    return list(reversed(_telemetry_history[-n:]))


def _get_usage(metrics: Optional[InvocationMetrics], key: str) -> int:
    """Get a token-usage value from InvocationMetrics."""
    if not metrics or not isinstance(metrics, dict):
        return 0
    usage = metrics.get("token_usage") or {}
    return int(usage.get(key, 0) or 0)


def get_telemetry_for_period(period: str, now_ts: Optional[float] = None) -> List[TelemetryHistoryEntry]:
    """Return entries in the rolling window for period. period in ('hour','day','week','month')."""
    global _telemetry_history
    now = now_ts if now_ts is not None else time.time()
    delta = _PERIOD_SECONDS.get(period)
    if not delta:
        return []
    cutoff = now - delta
    return [e for e in _telemetry_history if (e.get("timestamp") or 0) >= cutoff]


def get_running_totals(now_ts: Optional[float] = None) -> Dict[str, PeriodAggregates]:
    """Return aggregates for calendar periods: this_hour, today, this_week, this_month (UTC)."""
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
        out[name] = aggregate_metrics(entries)
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
# CloudWatch Logs Export (detailed per-invocation history)
# ---------------------------------------------------------------------------


def _get_cloudwatch_logs_client():
    """Lazy-init boto3 CloudWatch Logs client."""
    global _cloudwatch_logs_client
    if _cloudwatch_logs_client is None:
        try:
            import boto3
            _cloudwatch_logs_client = boto3.client("logs")
        except Exception as e:
            logger.debug("Failed to create CloudWatch Logs client: %s", e)
    return _cloudwatch_logs_client


def _get_telemetry_log_group() -> str:
    """Return the CloudWatch Logs log group name from env or default."""
    return os.environ.get("GLITCH_TELEMETRY_LOG_GROUP", _DEFAULT_TELEMETRY_LOG_GROUP)


def _telemetry_log_stream_for_timestamp(ts: float) -> str:
    """Return a daily log stream name for the given timestamp (UTC date)."""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y/%m/%d")


def _ensure_log_stream(log_group: str, log_stream: str) -> bool:
    """Ensure the log stream exists, creating it if necessary. Returns True on success."""
    client = _get_cloudwatch_logs_client()
    if not client:
        return False
    try:
        client.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
        logger.debug("Created log stream %s/%s", log_group, log_stream)
    except client.exceptions.ResourceAlreadyExistsException:
        pass
    except Exception as e:
        logger.warning("Failed to create log stream %s/%s: %s", log_group, log_stream, e)
        return False
    return True


def _write_telemetry_to_cloudwatch(entry: TelemetryHistoryEntry, event_type: str = "invocation") -> bool:
    """
    Write a telemetry entry to CloudWatch Logs.
    
    Args:
        entry: dict with "timestamp" (float epoch) and "metrics" (InvocationMetrics)
        event_type: "invocation" or "alert"
    
    Returns:
        True if written successfully, False otherwise
    """
    global _cloudwatch_sequence_tokens
    client = _get_cloudwatch_logs_client()
    if not client:
        return False
    
    log_group = _get_telemetry_log_group()
    ts = entry.get("timestamp") or time.time()
    log_stream = _telemetry_log_stream_for_timestamp(ts)
    stream_key = f"{log_group}:{log_stream}"
    
    log_event = {
        "timestamp": int(ts * 1000),
        "message": json.dumps({
            "event_type": event_type,
            "timestamp_iso": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "metrics": entry.get("metrics"),
        }, default=str),
    }
    
    try:
        kwargs = {
            "logGroupName": log_group,
            "logStreamName": log_stream,
            "logEvents": [log_event],
        }
        if stream_key in _cloudwatch_sequence_tokens:
            kwargs["sequenceToken"] = _cloudwatch_sequence_tokens[stream_key]
        
        response = client.put_log_events(**kwargs)
        _cloudwatch_sequence_tokens[stream_key] = response.get("nextSequenceToken", "")
        return True
        
    except client.exceptions.ResourceNotFoundException:
        if _ensure_log_stream(log_group, log_stream):
            try:
                response = client.put_log_events(
                    logGroupName=log_group,
                    logStreamName=log_stream,
                    logEvents=[log_event],
                )
                _cloudwatch_sequence_tokens[stream_key] = response.get("nextSequenceToken", "")
                return True
            except Exception as e:
                logger.warning("Failed to write telemetry after creating stream: %s", e)
        return False
        
    except client.exceptions.InvalidSequenceTokenException as e:
        expected = getattr(e, "expectedSequenceToken", None)
        if expected:
            _cloudwatch_sequence_tokens[stream_key] = expected
            try:
                response = client.put_log_events(
                    logGroupName=log_group,
                    logStreamName=log_stream,
                    logEvents=[log_event],
                    sequenceToken=expected,
                )
                _cloudwatch_sequence_tokens[stream_key] = response.get("nextSequenceToken", "")
                return True
            except Exception as e2:
                logger.warning("Failed to write telemetry after token refresh: %s", e2)
        return False
        
    except Exception as e:
        logger.warning("Failed to write telemetry to CloudWatch Logs: %s", e)
        return False


def write_telemetry_alert_to_cloudwatch(alert_message: str, period: str, metric: str, value: float, limit: float) -> bool:
    """Write a threshold alert event to CloudWatch Logs."""
    entry = {
        "timestamp": time.time(),
        "metrics": {
            "alert_message": alert_message,
            "period": period,
            "metric": metric,
            "value": value,
            "limit": limit,
        },
    }
    return _write_telemetry_to_cloudwatch(entry, event_type="alert")


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
