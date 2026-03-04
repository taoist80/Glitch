"""Real-time UniFi Protect WebSocket event consumer.

Maintains a persistent WebSocket connection to the NVR's update feed and writes
incoming events directly to Postgres via the existing db module singletons.

Reconnects automatically with exponential backoff (1 → 2 → 4 → … → 60s cap).
The poller is started as a background asyncio.Task on Sentinel container startup
and runs for the container's lifetime (up to 8 hours per AgentCore max_lifetime).

Protocol notes:
  - Endpoint: wss://<host>/proxy/protect/ws/updates
  - Auth: the same session cookies established by ProtectClient._authenticate()
  - Messages: JSON with {"action": {...}, "data": {...}} structure
    - action.modelKey == "event" and action.action in ("add", "update")
    - data fields: id, type, start (ms epoch), end, score, camera, thumbnail, heatmap,
      smartDetectTypes (list of "person"/"vehicle"/etc.)
"""

import asyncio
import json
import logging
import ssl
import time
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_MIN_BACKOFF = 1.0
_MAX_BACKOFF = 60.0


class ProtectEventPoller:
    """WebSocket consumer for UniFi Protect real-time events."""

    def __init__(self, protect_client, config) -> None:
        """
        Args:
            protect_client: singleton ProtectClient instance (for auth cookies)
            config: ProtectConfig instance (host, port, verify_ssl)
        """
        self._client = protect_client
        self._config = config
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> asyncio.Task:
        """Launch background reconnect loop. Returns the asyncio.Task."""
        self._running = True
        self._task = asyncio.create_task(self._reconnect_loop(), name="protect-ws-poller")
        logger.info("ProtectEventPoller started (host=%s)", self._config.host)
        return self._task

    def stop(self) -> None:
        """Signal the poller to stop and cancel the background task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            logger.info("ProtectEventPoller stop requested")

    async def _reconnect_loop(self) -> None:
        """Reconnect with exponential backoff until stop() is called."""
        backoff = _MIN_BACKOFF
        while self._running:
            try:
                await self._consume_websocket()
                backoff = _MIN_BACKOFF  # successful session — reset backoff
            except asyncio.CancelledError:
                logger.info("ProtectEventPoller cancelled")
                return
            except Exception as exc:
                logger.warning(
                    "ProtectEventPoller connection error: %s — retrying in %.0fs",
                    exc, backoff,
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    return
                backoff = min(backoff * 2, _MAX_BACKOFF)

    async def _consume_websocket(self) -> None:
        """Establish WebSocket connection and ingest events until disconnected."""
        import websockets

        # Ensure the HTTP client has valid session cookies.
        if not self._client._cookies:
            await self._client._authenticate()

        # Build cookie header from the current session.
        cookie_header = "; ".join(f"{k}={v}" for k, v in self._client._cookies.items())

        ws_url = (
            f"wss://{self._config.host}:{self._config.port}"
            "/proxy/protect/ws/updates"
        )

        ssl_ctx: ssl.SSLContext | bool
        if self._config.verify_ssl:
            ssl_ctx = True  # default CA verification
        else:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        logger.info("ProtectEventPoller connecting to %s", ws_url)
        async with websockets.connect(
            ws_url,
            ssl=ssl_ctx,
            additional_headers={"Cookie": cookie_header},
            ping_interval=30,
            ping_timeout=10,
            close_timeout=5,
        ) as ws:
            logger.info("ProtectEventPoller connected — listening for events")
            async for raw_message in ws:
                if not self._running:
                    break
                try:
                    await self._ingest(json.loads(raw_message))
                except Exception as exc:
                    logger.debug("ProtectEventPoller ingest error: %s", exc)

    async def _ingest(self, msg: dict) -> None:
        """Parse a Protect WS message and write to Postgres."""
        action = msg.get("action", {})
        data = msg.get("data", {})

        # Only process event model add/update messages
        if action.get("modelKey") != "event":
            return
        action_type = action.get("action")
        if action_type not in ("add", "update"):
            return

        event_id = data.get("id")
        camera_id = data.get("camera")
        if not event_id or not camera_id:
            return

        # start/end are millisecond timestamps
        start_ms = data.get("start")
        timestamp = (
            datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
            if start_ms
            else datetime.now(tz=timezone.utc)
        )

        entity_type = data.get("type")  # "motion", "smartDetectZone", "ring", etc.
        score = data.get("score")
        score_float = (score / 100.0) if score is not None else None

        # Smart detect types → classifications list
        smart_types = data.get("smartDetectTypes") or []
        classifications = {"smart_detect": smart_types} if smart_types else None

        snapshot_url = data.get("thumbnail")
        heatmap_url = data.get("heatmap")
        metadata = {}
        if heatmap_url:
            metadata["heatmap_url"] = heatmap_url
        end_ms = data.get("end")
        if end_ms:
            metadata["end_ms"] = end_ms

        # Import here to avoid circular imports at module level
        from sentinel.protect import db as protect_db

        if action_type == "add":
            await protect_db.insert_event(
                event_id=event_id,
                camera_id=camera_id,
                timestamp=timestamp,
                entity_type=entity_type,
                score=score_float,
                snapshot_url=snapshot_url,
                metadata=metadata if metadata else None,
            )
            logger.debug(
                "ProtectEventPoller: inserted event %s type=%s camera=%s",
                event_id, entity_type, camera_id,
            )
        elif action_type == "update" and score_float is not None:
            # Score updates arrive as partial objects — update anomaly score
            await protect_db.update_event_anomaly(
                event_id=event_id,
                anomaly_score=score_float,
                anomaly_factors={"raw_score": score},
                classifications=classifications,
            )
            logger.debug(
                "ProtectEventPoller: updated event %s score=%.2f", event_id, score_float
            )
