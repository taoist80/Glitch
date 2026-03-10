"""Real-time UniFi Protect WebSocket event consumer.

Connects to the UniFi Protect **integration** (public) WebSocket endpoints using
an API key — no username/password login required.

Two WebSocket streams are consumed concurrently:
  - **Events WS** (``/proxy/protect/integration/v1/subscribe/events``)
    Motion events, smart detections, doorbell rings, etc.
  - **Devices WS** (``/proxy/protect/integration/v1/subscribe/devices``)
    Camera state changes, NVR updates, sensor readings, etc.

Both endpoints authenticate via ``X-API-KEY`` header and emit JSON messages in
the format ``{"type": "add"|"update"|"remove", "item": {"modelKey": "...", ...}}``.

For legacy cookie-only mode (no API key), falls back to the private WS
(``/proxy/protect/ws/updates``) with session cookies.

Reconnects automatically with exponential backoff.  The poller is started as a
background ``asyncio.Task`` on Sentinel container startup and runs for the
container's lifetime (up to 8 hours per AgentCore ``max_lifetime``).
"""

import asyncio
import json
import logging
import random
import ssl
from datetime import datetime, timezone
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_MIN_BACKOFF = 1.0
_MAX_BACKOFF = 60.0
_MAX_BACKOFF_RATELIMIT = 300.0

_EVENTS_WS_PATH = "/proxy/protect/integration/v1/subscribe/events"
_DEVICES_WS_PATH = "/proxy/protect/integration/v1/subscribe/devices"
_PRIVATE_WS_PATH = "/proxy/protect/ws/updates"


class ProtectEventPoller:
    """WebSocket consumer for UniFi Protect real-time events and device updates."""

    def __init__(self, protect_client, config) -> None:
        """
        Args:
            protect_client: singleton ProtectClient instance
            config: ProtectConfig instance (host, port, verify_ssl, api_key)
        """
        self._client = protect_client
        self._config = config
        self._tasks: list[asyncio.Task] = []
        self._running = False

    async def start(self) -> list[asyncio.Task]:
        """Launch background reconnect loops.  Returns the asyncio Tasks."""
        self._running = True

        if self._config.use_api_key:
            events_task = asyncio.create_task(
                self._reconnect_loop("events", _EVENTS_WS_PATH),
                name="protect-ws-events",
            )
            devices_task = asyncio.create_task(
                self._reconnect_loop("devices", _DEVICES_WS_PATH),
                name="protect-ws-devices",
            )
            self._tasks = [events_task, devices_task]
            logger.info(
                "ProtectEventPoller started (host=%s, auth=API key, streams=events+devices)",
                self._config.host,
            )
        else:
            task = asyncio.create_task(
                self._reconnect_loop("private", _PRIVATE_WS_PATH),
                name="protect-ws-private",
            )
            self._tasks = [task]
            logger.info(
                "ProtectEventPoller started (host=%s, auth=cookie, stream=private)",
                self._config.host,
            )

        return self._tasks

    def stop(self) -> None:
        """Signal all poller tasks to stop."""
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        logger.info("ProtectEventPoller stop requested")

    # ------------------------------------------------------------------
    # Reconnect loop (shared by events / devices / private streams)
    # ------------------------------------------------------------------

    async def _reconnect_loop(self, stream_name: str, ws_path: str) -> None:
        """Reconnect with exponential backoff until stop() is called.

        Waits 5-30s on first run so the container health check passes before
        we issue the (potentially slow) WS connect.
        """
        startup_delay = random.uniform(5, 30)
        logger.info("ProtectEventPoller[%s] startup delay: %.1fs", stream_name, startup_delay)
        try:
            await asyncio.sleep(startup_delay)
        except asyncio.CancelledError:
            return

        backoff = _MIN_BACKOFF
        while self._running:
            try:
                await self._consume_websocket(stream_name, ws_path)
                backoff = _MIN_BACKOFF
            except asyncio.CancelledError:
                logger.info("ProtectEventPoller[%s] cancelled", stream_name)
                return
            except Exception as exc:
                logger.warning(
                    "ProtectEventPoller[%s] connection error: %s — retrying in %.0fs",
                    stream_name, exc, backoff,
                )
                try:
                    await asyncio.sleep(backoff)
                except asyncio.CancelledError:
                    return
                backoff = min(backoff * 2, _MAX_BACKOFF)

    # ------------------------------------------------------------------
    # WebSocket consumer (aiohttp)
    # ------------------------------------------------------------------

    def _build_ws_url(self, ws_path: str) -> str:
        """Build ``https://`` URL using the configured host and port."""
        raw_host = self._config.host
        if ":" in raw_host:
            hostname, port_str = raw_host.rsplit(":", 1)
            port = int(port_str)
        else:
            hostname = raw_host
            port = self._config.port

        if port == 443:
            return f"https://{hostname}{ws_path}"
        return f"https://{hostname}:{port}{ws_path}"

    def _build_ws_headers(self) -> dict:
        """Build auth headers for the WebSocket connection."""
        if self._config.use_api_key:
            return {"X-API-KEY": self._config.api_key}
        cookie_header = "; ".join(f"{k}={v}" for k, v in self._client._cookies.items())
        return {"Cookie": cookie_header}

    async def _consume_websocket(self, stream_name: str, ws_path: str) -> None:
        """Connect via aiohttp and ingest messages until disconnected."""
        if not self._config.use_api_key:
            if not self._client._cookies:
                await self._client._authenticate()

        ws_url = self._build_ws_url(ws_path)
        ws_headers = self._build_ws_headers()

        ssl_ctx: ssl.SSLContext | bool
        if self._config.verify_ssl:
            ssl_ctx = True
        else:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        connector = aiohttp.TCPConnector(ssl=ssl_ctx)

        logger.info("ProtectEventPoller[%s] connecting to %s", stream_name, ws_url)

        async with aiohttp.ClientSession(connector=connector) as session:
            async with session.ws_connect(
                ws_url,
                headers=ws_headers,
                heartbeat=30,
                timeout=aiohttp.ClientWSTimeout(ws_close=10),
            ) as ws:
                logger.info("ProtectEventPoller[%s] connected — listening", stream_name)
                async for msg in ws:
                    if not self._running:
                        break
                    if msg.type == aiohttp.WSMsgType.TEXT:
                        try:
                            await self._ingest(json.loads(msg.data), stream_name)
                        except Exception as exc:
                            logger.debug(
                                "ProtectEventPoller[%s] ingest error: %s", stream_name, exc
                            )
                    elif msg.type == aiohttp.WSMsgType.ERROR:
                        logger.warning(
                            "ProtectEventPoller[%s] WS error: %s", stream_name, ws.exception()
                        )
                        break
                    elif msg.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSED,
                    ):
                        logger.info("ProtectEventPoller[%s] WS closed by server", stream_name)
                        break

    # ------------------------------------------------------------------
    # Message ingestion
    # ------------------------------------------------------------------

    async def _ingest(self, msg: dict, stream_name: str) -> None:
        """Parse a Protect WS message and write to Postgres.

        Integration WS format (events + devices streams):
            {"type": "add"|"update"|"remove", "item": {"modelKey": "event"|"camera"|..., ...}}

        Private WS format (legacy cookie mode):
            {"action": {"modelKey": "event", "action": "add"|"update"}, "data": {...}}
        """
        if "item" in msg:
            await self._ingest_integration(msg, stream_name)
        elif "action" in msg:
            await self._ingest_private(msg)

    async def _ingest_integration(self, msg: dict, stream_name: str) -> None:
        """Ingest a message from the integration (public API) WebSocket."""
        action_type = msg.get("type")  # "add", "update", "remove"
        item = msg.get("item", {})
        model_key = item.get("modelKey")

        if not action_type or not model_key:
            return

        if model_key == "event":
            await self._ingest_event(item, action_type)
        elif model_key == "camera" and stream_name == "devices":
            await self._ingest_device_update(item, model_key, action_type)
        elif stream_name == "devices":
            await self._ingest_device_update(item, model_key, action_type)

    async def _ingest_private(self, msg: dict) -> None:
        """Ingest a message from the private WS (legacy cookie mode)."""
        action = msg["action"]
        data = msg.get("data", {})
        if action.get("modelKey") != "event":
            return
        action_type = action.get("action")
        if action_type not in ("add", "update"):
            return
        await self._ingest_event(data, action_type)

    async def _ingest_event(self, data: dict, action_type: str) -> None:
        """Write an event add/update to Postgres."""
        event_id = data.get("id")
        camera_id = data.get("camera")
        if not event_id or not camera_id:
            return

        start_ms = data.get("start")
        timestamp = (
            datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)
            if start_ms
            else datetime.now(tz=timezone.utc)
        )

        entity_type = data.get("type")
        score = data.get("score")
        score_float = (score / 100.0) if score is not None else None

        smart_types = data.get("smartDetectTypes") or []
        classifications = {"smart_detect": smart_types} if smart_types else None

        snapshot_url = data.get("thumbnail")
        heatmap_url = data.get("heatmap")
        metadata: dict = {}
        if heatmap_url:
            metadata["heatmap_url"] = heatmap_url
        end_ms = data.get("end")
        if end_ms:
            metadata["end_ms"] = end_ms

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
            await protect_db.update_event_anomaly(
                event_id=event_id,
                anomaly_score=score_float,
                anomaly_factors={"raw_score": score},
                classifications=classifications,
            )
            logger.debug(
                "ProtectEventPoller: updated event %s score=%.2f", event_id, score_float
            )

    async def _ingest_device_update(
        self, item: dict, model_key: str, action_type: str,
    ) -> None:
        """Log device state changes from the devices WS.

        Camera updates are synced to the cameras table; other model types
        (nvr, sensor, light, etc.) are logged for observability.
        """
        device_id = item.get("id", "unknown")
        name = item.get("name", "")

        if model_key == "camera" and action_type in ("add", "update"):
            state = item.get("state", "")
            logger.info(
                "ProtectEventPoller[devices]: camera %s (%s) state=%s action=%s",
                name, device_id, state, action_type,
            )
            try:
                from sentinel.protect import db as protect_db
                camera_meta = {}
                if "featureFlags" in item:
                    camera_meta["featureFlags"] = item["featureFlags"]
                if "state" in item:
                    camera_meta["state"] = item["state"]
                if "mac" in item:
                    camera_meta["mac"] = item["mac"]
                await protect_db.upsert_camera(
                    camera_id=device_id,
                    name=name or device_id,
                    camera_type=item.get("type"),
                    metadata=camera_meta if camera_meta else None,
                )
            except Exception as exc:
                logger.debug("ProtectEventPoller: camera upsert failed: %s", exc)
        else:
            logger.debug(
                "ProtectEventPoller[devices]: %s %s (%s) action=%s",
                model_key, name, device_id, action_type,
            )
