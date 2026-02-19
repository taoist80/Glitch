"""OpenTelemetry configuration for Glitch agent.

Uses the official Strands Agents SDK telemetry API.
Reference: https://strandsagents.com/latest/documentation/docs/user-guide/observability-evaluation/traces/
"""

import os
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)

_telemetry_instance: Optional[Any] = None


def setup_telemetry(
    service_name: str = "glitch-agent",
    otlp_endpoint: Optional[str] = None,
    enable_console: bool = False,
    enable_otlp: bool = True,
) -> Optional[Any]:
    """
    Setup OpenTelemetry instrumentation for the agent using Strands SDK.
    
    Args:
        service_name: Service name for traces
        otlp_endpoint: OTLP endpoint URL (defaults to env var or localhost)
        enable_console: Enable console exporter for debugging
        enable_otlp: Enable OTLP exporter for production
    
    Returns:
        StrandsTelemetry instance or None if not available
    """
    global _telemetry_instance
    
    if _telemetry_instance is not None:
        logger.info("Telemetry already initialized, returning existing instance")
        return _telemetry_instance
    
    try:
        from strands.telemetry import StrandsTelemetry
        
        os.environ["OTEL_SERVICE_NAME"] = service_name
        
        if otlp_endpoint:
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = otlp_endpoint
        elif "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ:
            os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4318"
        
        telemetry = StrandsTelemetry()
        
        if enable_otlp:
            telemetry.setup_otlp_exporter()
            logger.info(f"OTLP exporter enabled: {os.environ.get('OTEL_EXPORTER_OTLP_ENDPOINT')}")
        
        if enable_console:
            telemetry.setup_console_exporter()
            logger.info("Console exporter enabled")
        
        telemetry.setup_meter(
            enable_otlp_exporter=enable_otlp,
            enable_console_exporter=enable_console,
        )
        
        logger.info(f"OpenTelemetry initialized for {service_name}")
        _telemetry_instance = telemetry
        return telemetry
        
    except ImportError as e:
        logger.warning(f"Strands telemetry not available (install with 'pip install strands-agents[otel]'): {e}")
        return None
    except Exception as e:
        logger.error(f"Failed to setup telemetry: {e}")
        return None


def get_telemetry() -> Optional[Any]:
    """Get the current telemetry instance."""
    return _telemetry_instance


def add_span_attributes(attributes: dict):
    """
    Add custom attributes to the current span.
    
    Args:
        attributes: Dictionary of attributes to add
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
    attributes: Optional[dict] = None,
    metric_type: str = "counter",
):
    """
    Record a custom metric.
    
    Args:
        name: Metric name
        value: Metric value
        unit: Unit of measurement
        attributes: Optional attributes
        metric_type: Type of metric ("counter", "gauge", "histogram")
    """
    try:
        from opentelemetry import metrics
        
        meter = metrics.get_meter("glitch-agent")
        
        if metric_type == "counter":
            counter = meter.create_counter(name, unit=unit, description=f"Counter for {name}")
            counter.add(int(value), attributes=attributes or {})
        elif metric_type == "gauge":
            gauge = meter.create_up_down_counter(name, unit=unit, description=f"Gauge for {name}")
            gauge.add(value, attributes=attributes or {})
        elif metric_type == "histogram":
            histogram = meter.create_histogram(name, unit=unit, description=f"Histogram for {name}")
            histogram.record(value, attributes=attributes or {})
            
    except ImportError:
        logger.debug("OpenTelemetry metrics module not available")
    except Exception as e:
        logger.debug(f"Failed to record metric: {e}")


def create_span(name: str, attributes: Optional[dict] = None):
    """
    Create a new span context manager.
    
    Args:
        name: Span name
        attributes: Optional span attributes
    
    Returns:
        Span context manager or None
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
