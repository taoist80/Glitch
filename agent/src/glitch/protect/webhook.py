"""Protect webhook handler.

Handles incoming POST requests from UniFi Protect on event triggers.
Enqueues events to the ProtectEventProcessor for async processing.
"""

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

_processor = None


def set_processor(processor: Any) -> None:
    """Set the event processor instance for webhook routing."""
    global _processor
    _processor = processor


async def handle_webhook(body: bytes, headers: Dict[str, str]) -> Dict[str, Any]:
    """Handle an incoming Protect webhook POST request.

    Args:
        body: Raw request body bytes
        headers: Request headers dict

    Returns:
        Response dict with status
    """
    try:
        event_data = json.loads(body)
    except json.JSONDecodeError as e:
        logger.warning(f"Invalid JSON in webhook body: {e}")
        return {"status": "error", "message": "Invalid JSON"}

    event_type = event_data.get("type") or event_data.get("event_type", "unknown")
    event_id = event_data.get("id") or event_data.get("event_id", "unknown")

    logger.info(f"Protect webhook received: type={event_type}, id={event_id}")

    if _processor is not None and _processor._running:
        queued = await _processor.enqueue(event_data)
        if queued:
            return {"status": "queued", "event_id": event_id}
        else:
            return {"status": "dropped", "reason": "queue_full", "event_id": event_id}
    else:
        logger.warning("Protect event processor not running, webhook event dropped")
        return {"status": "dropped", "reason": "processor_not_running", "event_id": event_id}
