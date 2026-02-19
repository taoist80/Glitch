"""OpenTelemetry configuration and metrics for Glitch agent.

This module provides a thin wrapper around Strands' built-in telemetry.
Strands automatically tracks:
- Token usage (input, output, cache read/write)
- Event loop cycles and durations
- Tool call counts, success rates, and durations
- Model latency

Dataflow:
    TelemetryConfig -> setup_telemetry() -> StrandsTelemetry
    AgentResult -> extract_metrics_from_result() -> InvocationMetrics
    InvocationMetrics -> log_invocation_metrics() -> CloudWatch logs

Reference: https://strandsagents.com/latest/documentation/docs/user-guide/observability-evaluation/metrics/
"""

import os
import logging
from typing import Optional, Any, Dict

from glitch.types import (
    TelemetryConfig,
    InvocationMetrics,
    TokenUsage,
    ToolUsageStats,
    MetricType,
    create_empty_metrics,
    create_empty_token_usage,
)

logger = logging.getLogger(__name__)

_telemetry_instance: Optional[Any] = None


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
        
        telemetry = StrandsTelemetry()
        
        if config.enable_otlp:
            telemetry.setup_otlp_exporter()
            logger.info(f"OTLP exporter enabled: {os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')}")
        
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


def extract_metrics_from_result(result: Any) -> InvocationMetrics:
    """
    Extract metrics from a Strands AgentResult using the built-in get_summary().
    
    Strands' EventLoopMetrics.get_summary() returns:
    {
        "total_cycles": int,
        "total_duration": float,
        "average_cycle_time": float,
        "tool_usage": {...},
        "traces": [...],
        "accumulated_usage": {
            "inputTokens": int,
            "outputTokens": int,
            "totalTokens": int,
            "cacheReadInputTokens": int (optional),
            "cacheWriteInputTokens": int (optional)
        },
        "accumulated_metrics": {"latencyMs": int},
        "agent_invocations": [...]
    }
    
    Args:
        result: AgentResult from Strands agent invocation.
                Can be None for error cases.
    
    Returns:
        InvocationMetrics with extracted data, or empty metrics if extraction fails
    """
    if result is None:
        return create_empty_metrics()
    
    try:
        if hasattr(result, 'metrics') and result.metrics:
            summary = result.metrics.get_summary()
            
            usage = summary.get('accumulated_usage', {})
            acc_metrics = summary.get('accumulated_metrics', {})
            
            token_usage: TokenUsage = {
                "input_tokens": usage.get('inputTokens', 0),
                "output_tokens": usage.get('outputTokens', 0),
                "total_tokens": usage.get('totalTokens', 0),
                "cache_read_tokens": usage.get('cacheReadInputTokens', 0),
                "cache_write_tokens": usage.get('cacheWriteInputTokens', 0),
            }
            
            tool_usage: Dict[str, ToolUsageStats] = {}
            for name, data in summary.get('tool_usage', {}).items():
                exec_stats = data.get('execution_stats', {})
                tool_usage[name] = ToolUsageStats(
                    call_count=exec_stats.get('call_count', 0),
                    success_count=exec_stats.get('success_count', 0),
                    error_count=exec_stats.get('error_count', 0),
                    total_time=exec_stats.get('total_time', 0.0),
                )
            
            return InvocationMetrics(
                duration_seconds=round(summary.get('total_duration', 0), 3),
                token_usage=token_usage,
                cycle_count=summary.get('total_cycles', 0),
                latency_ms=acc_metrics.get('latencyMs', 0),
                stop_reason=str(result.stop_reason) if hasattr(result, 'stop_reason') else "",
                tool_usage=tool_usage,
            )
    except Exception as e:
        logger.warning(f"Failed to extract metrics from result: {e}")
    
    return create_empty_metrics()


def log_invocation_metrics(
    metrics: InvocationMetrics,
    user_message: str = "",
    response_preview: str = "",
    session_id: str = "",
) -> None:
    """
    Log detailed metrics for an invocation to CloudWatch.
    
    Args:
        metrics: InvocationMetrics from extract_metrics_from_result()
        user_message: The user's input message (truncated for logging)
        response_preview: Preview of the response (truncated for logging)
        session_id: Session identifier for correlation
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


def get_metrics_to_string(result: Any) -> str:
    """
    Get a human-readable string of metrics using Strands' built-in formatter.
    
    Args:
        result: AgentResult from Strands agent invocation
    
    Returns:
        Formatted string representation of metrics, or empty string if unavailable
    """
    try:
        from strands.telemetry.metrics import metrics_to_string
        
        if hasattr(result, 'metrics') and result.metrics:
            return metrics_to_string(result.metrics)
    except ImportError:
        pass
    except Exception as e:
        logger.warning(f"Failed to format metrics: {e}")
    
    return ""


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
