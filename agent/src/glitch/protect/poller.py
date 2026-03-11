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
import socket
import ssl
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import httpx

from glitch.protect.config import parse_host_port

logger = logging.getLogger(__name__)

_MIN_BACKOFF = 1.0
_MAX_BACKOFF = 60.0

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

        # Seed cameras in background so it doesn't block the health check
        asyncio.create_task(self._seed_cameras(), name="protect-camera-seed")

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

    async def _seed_cameras(self) -> None:
        """Fetch all cameras via REST and upsert into Postgres.

        Runs once at startup so the cameras table is fully populated before
        the WS streams begin delivering incremental updates.

        Delays 35s to ensure the container health check passes before issuing
        network calls that could be cancelled mid-flight if the container is
        not yet healthy.
        """
        try:
            await asyncio.sleep(35)
        except asyncio.CancelledError:
            return
        try:
            cameras = await self._client.get_cameras()
            logger.info("ProtectEventPoller: seeding %d cameras from REST", len(cameras))
            from glitch.protect import db as protect_db

            for cam in cameras:
                ff = cam.get("featureFlags", {})
                sds = cam.get("smartDetectSettings", {})
                await protect_db.upsert_camera(
                    camera_id=cam["id"],
                    name=cam.get("name", cam["id"]),
                    camera_type=cam.get("type"),
                    mac=cam.get("mac"),
                    model_key=cam.get("modelKey"),
                    state=cam.get("state"),
                    is_mic_enabled=cam.get("isMicEnabled"),
                    mic_volume=cam.get("micVolume"),
                    video_mode=cam.get("videoMode"),
                    hdr_type=cam.get("hdrType"),
                    has_hdr=ff.get("hasHdr"),
                    has_mic=ff.get("hasMic"),
                    has_speaker=ff.get("hasSpeaker"),
                    has_led_status=ff.get("hasLedStatus"),
                    has_full_hd_snapshot=ff.get("supportFullHdSnapshot"),
                    video_modes=ff.get("videoModes"),
                    smart_detect_types=ff.get("smartDetectTypes"),
                    smart_detect_audio_types=ff.get("smartDetectAudioTypes"),
                    smart_detect_object_types=sds.get("objectTypes"),
                    smart_detect_audio_config=sds.get("audioTypes"),
                    led_settings=cam.get("ledSettings"),
                    osd_settings=cam.get("osdSettings"),
                    lcd_message=cam.get("lcdMessage"),
                )
            logger.info("ProtectEventPoller: camera seed complete")
        except Exception as exc:
            logger.warning("ProtectEventPoller: camera seed failed (non-fatal): %s", exc, exc_info=True)

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
                    "ProtectEventPoller[%s] %s: %s — retrying in %.0fs",
                    stream_name, type(exc).__name__, exc, backoff,
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
        hostname, port = parse_host_port(self._config.host, self._config.port)
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
        import time as _time

        if not self._config.use_api_key:
            if not self._client._cookies:
                await self._client._authenticate()

        ws_url = self._build_ws_url(ws_path)
        ws_headers = self._build_ws_headers()
        hostname, port = parse_host_port(self._config.host, self._config.port)

        ssl_ctx: ssl.SSLContext | bool
        if self._config.verify_ssl:
            ssl_ctx = True
        else:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        # --- Phase 1: Async DNS resolution (non-blocking) ---
        t0 = _time.monotonic()
        try:
            loop = asyncio.get_event_loop()
            addrs = await loop.getaddrinfo(
                hostname, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM
            )
            ips = [a[4][0] for a in addrs]
            logger.info(
                "ProtectEventPoller[%s] DNS resolved %s → %s (%.1fms)",
                stream_name, hostname, ips, (_time.monotonic() - t0) * 1000,
            )
        except Exception as dns_exc:
            logger.error(
                "ProtectEventPoller[%s] DNS resolution failed for %s: %s",
                stream_name, hostname, dns_exc,
            )
            raise

        # --- Phase 2: REST probe with independent client ---
        # Uses its own httpx client so the shared singleton is never blocked.
        # 20s timeout: from AWS to home DDNS the path can be slow; fail fast but allow high latency.
        probe_timeout = 20.0
        t1 = _time.monotonic()
        host_authority = hostname if port == 443 else f"{hostname}:{port}"
        probe_url = f"https://{host_authority}/proxy/protect/integration/v1/cameras"
        try:
            async with httpx.AsyncClient(
                verify=self._config.verify_ssl, timeout=probe_timeout
            ) as probe_client:
                probe_resp = await probe_client.get(probe_url, headers=ws_headers)
            logger.info(
                "ProtectEventPoller[%s] REST probe → HTTP %d (%.0fms)",
                stream_name, probe_resp.status_code, (_time.monotonic() - t1) * 1000,
            )
        except Exception as probe_exc:
            logger.warning(
                "ProtectEventPoller[%s] REST probe failed (%.0fms): %s — proceeding to WS (check connectivity to %s)",
                stream_name, (_time.monotonic() - t1) * 1000, probe_exc, host_authority,
            )

        # --- Phase 3: WebSocket connect ---
        # total=None: no wall-clock limit on the long-lived stream.
        # sock_connect=90: from AWS to home DDNS the path can be slow; allow time for TCP+TLS+WS upgrade.
        ws_connect_timeout = 90
        client_timeout = aiohttp.ClientTimeout(
            total=None,
            sock_connect=ws_connect_timeout,
            sock_read=None,
        )
        connector = aiohttp.TCPConnector(ssl=ssl_ctx)

        logger.info(
            "ProtectEventPoller[%s] WS connecting to %s (sock_connect=%ss)",
            stream_name, ws_url, ws_connect_timeout,
        )
        t2 = _time.monotonic()

        async with aiohttp.ClientSession(connector=connector, timeout=client_timeout) as session:
            async with session.ws_connect(
                ws_url,
                headers=ws_headers,
                heartbeat=20,
                timeout=aiohttp.ClientWSTimeout(ws_close=10.0),
            ) as ws:
                logger.info(
                    "ProtectEventPoller[%s] WS connected in %.0fms — listening",
                    stream_name, (_time.monotonic() - t2) * 1000,
                )
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

        from glitch.protect import db as protect_db

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
        """Sync device state changes from the devices WS into Postgres.

        Camera updates are fully persisted to the cameras table;
        other model types (nvr, sensor, light, etc.) are logged for observability.
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
                from glitch.protect import db as protect_db
                ff = item.get("featureFlags", {})
                sds = item.get("smartDetectSettings", {})

                await protect_db.upsert_camera(
                    camera_id=device_id,
                    name=name or device_id,
                    camera_type=item.get("type"),
                    mac=item.get("mac"),
                    model_key=model_key,
                    state=state or None,
                    is_mic_enabled=item.get("isMicEnabled"),
                    mic_volume=item.get("micVolume"),
                    video_mode=item.get("videoMode"),
                    hdr_type=item.get("hdrType"),
                    has_hdr=ff.get("hasHdr"),
                    has_mic=ff.get("hasMic"),
                    has_speaker=ff.get("hasSpeaker"),
                    has_led_status=ff.get("hasLedStatus"),
                    has_full_hd_snapshot=ff.get("supportFullHdSnapshot"),
                    video_modes=ff.get("videoModes"),
                    smart_detect_types=ff.get("smartDetectTypes"),
                    smart_detect_audio_types=ff.get("smartDetectAudioTypes"),
                    smart_detect_object_types=sds.get("objectTypes"),
                    smart_detect_audio_config=sds.get("audioTypes"),
                    led_settings=item.get("ledSettings"),
                    osd_settings=item.get("osdSettings"),
                    lcd_message=item.get("lcdMessage"),
                )
            except Exception as exc:
                logger.debug("ProtectEventPoller: camera upsert failed: %s", exc)
        else:
            logger.debug(
                "ProtectEventPoller[devices]: %s %s (%s) action=%s",
                model_key, name, device_id, action_type,
            )
