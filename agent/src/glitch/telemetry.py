"""OpenTelemetry configuration for Glitch agent."""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def setup_telemetry(
    service_name: str = "glitch-agent",
    otlp_endpoint: Optional[str] = None,
    enable_console: bool = False,
) -> Optional[object]:
    """
    Setup OpenTelemetry instrumentation for the agent.
    
    Args:
        service_name: Service name for traces
        otlp_endpoint: OTLP endpoint URL (defaults to CloudWatch)
        enable_console: Enable console exporter for debugging
    
    Returns:
        StrandsTelemetry instance or None if not available
    """
    try:
        from strands.telemetry import StrandsTelemetry
        
        otlp_endpoint = otlp_endpoint or os.getenv(
            "OTEL_EXPORTER_OTLP_ENDPOINT",
            "http://localhost:4318"
        )
        
        telemetry = StrandsTelemetry()
        
        os.environ["OTEL_SERVICE_NAME"] = service_name
        os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = otlp_endpoint
        
        telemetry.setup_otlp_exporter()
        
        if enable_console:
            telemetry.setup_console_exporter()
        
        telemetry.setup_meter(
            enable_otlp_exporter=True,
            enable_console_exporter=enable_console,
        )
        
        logger.info(f"OpenTelemetry initialized for {service_name}")
        logger.info(f"OTLP endpoint: {otlp_endpoint}")
        
        return telemetry
        
    except ImportError:
        logger.warning("Strands telemetry not available, continuing without instrumentation")
        return None
    except Exception as e:
        logger.error(f"Failed to setup telemetry: {e}")
        return None


def add_span_attributes(attributes: dict):
    """
    Add custom attributes to the current span.
    
    Args:
        attributes: Dictionary of attributes to add
    """
    try:
        from opentelemetry import trace
        
        span = trace.get_current_span()
        if span:
            for key, value in attributes.items():
                span.set_attribute(key, value)
    except Exception as e:
        logger.debug(f"Failed to add span attributes: {e}")


def record_metric(name: str, value: float, unit: str = "", attributes: Optional[dict] = None):
    """
    Record a custom metric.
    
    Args:
        name: Metric name
        value: Metric value
        unit: Unit of measurement
        attributes: Optional attributes
    """
    try:
        from opentelemetry import metrics
        
        meter = metrics.get_meter(__name__)
        counter = meter.create_counter(name, unit=unit)
        counter.add(value, attributes=attributes or {})
    except Exception as e:
        logger.debug(f"Failed to record metric: {e}")
