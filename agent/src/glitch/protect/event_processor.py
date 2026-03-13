"""Async event processor for UniFi Protect events.

Manages an asyncio.Queue + worker pool for real-time event processing.
Each worker runs: snapshot -> LLaVA -> recognition -> DB match -> anomaly -> alert -> store.
"""

import asyncio
import hashlib
import json
import logging
import os
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Set

logger = logging.getLogger(__name__)

_SEEN_DEQUE_SIZE = 20  # per-camera dedup window


def _vision_camera_ids() -> Set[str]:
    """Optional camera allowlist for vision analysis.

    Reuses GLITCH_PROTECT_VISION_CAMERAS (comma-separated camera IDs).
    Empty/unset means all cameras are eligible.
    """
    raw = os.environ.get("GLITCH_PROTECT_VISION_CAMERAS", "").strip()
    if not raw:
        return set()
    return {c.strip() for c in raw.split(",") if c.strip()}


def _vision_event_types() -> Set[str]:
    """Event types that trigger vision analysis.

    Default is motion-only. Override with GLITCH_PROTECT_VISION_EVENT_TYPES
    (comma-separated, e.g. "motion,person,vehicle") for gradual rollout.
    """
    raw = os.environ.get("GLITCH_PROTECT_VISION_EVENT_TYPES", "").strip().lower()
    if not raw:
        return {"motion"}
    return {t.strip() for t in raw.split(",") if t.strip()}


class ProtectEventProcessor:
    """Async event processor with bounded queue and worker pool."""

    def __init__(self, max_workers: int = 3, queue_size: int = 100):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._camera_ids: List[str] = []
        self._check_interval: float = 2.0
        self._alert_profile: str = "balanced"
        self._seen_event_ids: Dict[str, Deque[str]] = {}
        self._vision_event_types: Set[str] = _vision_event_types()
        self._vision_camera_ids: Set[str] = _vision_camera_ids()
        self._stats = {
            "processed": 0,
            "errors": 0,
            "alerts_sent": 0,
            "last_processed": None,
            "started_at": None,
        }
        self._max_workers = max_workers
        # Avoid flooding logs with identical ingest tracebacks while DB is down.
        self._last_ingest_error_sig: str = ""
        self._last_ingest_error_ts: float = 0.0

    async def start(
        self,
        camera_ids: List[str],
        check_interval: float = 2.0,
        alert_profile: str = "balanced",
    ) -> None:
        """Start ingestion loop and worker pool."""
        if self._running:
            logger.warning("Event processor already running")
            return

        self._camera_ids = camera_ids
        self._check_interval = check_interval
        self._alert_profile = alert_profile
        self._running = True
        self._stats["started_at"] = datetime.now().isoformat()

        # Start workers
        for i in range(self._max_workers):
            task = asyncio.create_task(self._worker(i), name=f"protect-worker-{i}")
            self._workers.append(task)

        # Start ingestion loop
        asyncio.create_task(self._ingest_loop(), name="protect-ingest")
        logger.info(
            f"Protect event processor started: {len(camera_ids)} cameras, "
            f"{self._max_workers} workers, {check_interval}s interval"
        )
        logger.info(
            "Protect event processor vision trigger: event_types=%s camera_filter=%s",
            sorted(list(self._vision_event_types)),
            sorted(list(self._vision_camera_ids)) if self._vision_camera_ids else "ALL",
        )

    async def stop(self) -> None:
        """Graceful shutdown: stop ingestion, drain queue, cancel workers."""
        self._running = False

        # Wait for queue to drain (up to 30s)
        try:
            await asyncio.wait_for(self._queue.join(), timeout=30.0)
        except asyncio.TimeoutError:
            logger.warning("Queue drain timed out, cancelling workers")

        for task in self._workers:
            task.cancel()

        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("Protect event processor stopped")

    async def enqueue(self, event_data: Dict[str, Any]) -> bool:
        """Enqueue an event for processing. Returns False if queue is full."""
        try:
            self._queue.put_nowait(event_data)
            return True
        except asyncio.QueueFull:
            logger.warning(f"Event queue full (size={self._queue.maxsize}), dropping event")
            return False

    def get_status(self) -> Dict[str, Any]:
        """Return processor status."""
        return {
            "running": self._running,
            "cameras": self._camera_ids,
            "queue_depth": self._queue.qsize(),
            "queue_max": self._queue.maxsize,
            "worker_count": len(self._workers),
            "active_workers": sum(1 for t in self._workers if not t.done()),
            "stats": self._stats.copy(),
        }

    async def _ingest_loop(self) -> None:
        """Poll the DB for unprocessed events and enqueue them.

        The UniFi Protect integration API has no REST events endpoint \u2014 events
        arrive via WebSocket and are persisted by the poller.  This loop picks
        up unprocessed rows and feeds them to the worker pool for enrichment.
        """
        from glitch.protect import db as protect_db

        while self._running:
            try:
                if not protect_db.is_pool_available():
                    await asyncio.sleep(self._check_interval)
                    continue

                events = await protect_db.run_in_pool_loop(
                    protect_db.get_unprocessed_events,
                    50,
                )
                for event in events:
                    event_id = event.get("event_id")
                    if not event_id:
                        continue

                    camera_id = event.get("camera_id", "unknown")
                    seen = self._seen_event_ids.setdefault(
                        camera_id, deque(maxlen=_SEEN_DEQUE_SIZE)
                    )
                    if event_id in seen:
                        continue

                    seen.append(event_id)
                    await self.enqueue(event)

            except Exception as e:
                now = time.monotonic()
                error_sig = f"{type(e).__name__}:{e}"
                # Emit full traceback at most once per 5 minutes per unique error.
                if (
                    error_sig != self._last_ingest_error_sig
                    or (now - self._last_ingest_error_ts) >= 300
                ):
                    logger.error("Ingest loop error: %s", e, exc_info=True)
                    self._last_ingest_error_sig = error_sig
                    self._last_ingest_error_ts = now
                else:
                    logger.warning("Ingest loop error (suppressed traceback): %s", e)

            await asyncio.sleep(self._check_interval)

    async def _worker(self, worker_id: int) -> None:
        """Process events from the queue."""
        logger.info(f"Worker {worker_id} started")

        while self._running:
            try:
                event_data = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            try:
                await self._process_event(event_data, worker_id)
                self._stats["processed"] += 1
                self._stats["last_processed"] = datetime.now().isoformat()
            except Exception as e:
                self._stats["errors"] += 1
                logger.error(f"Worker {worker_id} error processing event: {e}", exc_info=True)
            finally:
                self._queue.task_done()

        logger.info(f"Worker {worker_id} stopped")

    async def _process_event(self, event_data: Dict[str, Any], worker_id: int) -> None:
        """Full processing pipeline for a single event."""
        from glitch.protect import db as protect_db
        from glitch.protect.client import get_client

        event_id = event_data.get("id") or event_data.get("event_id", "unknown")
        camera_id = event_data.get("camera") or event_data.get("camera_id", "unknown")
        entity_type = event_data.get("type") or event_data.get("entity_type", "motion")

        # Parse timestamp
        ts_raw = event_data.get("start") or event_data.get("timestamp")
        if isinstance(ts_raw, (int, float)):
            timestamp = datetime.fromtimestamp(ts_raw / 1000 if ts_raw > 1e10 else ts_raw)
        elif isinstance(ts_raw, str):
            timestamp = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        else:
            timestamp = datetime.now()

        logger.debug(f"Worker {worker_id} processing event {event_id} ({entity_type}) on {camera_id}")

        # Store raw event (best-effort — DB may be unreachable)
        try:
            await protect_db.run_in_pool_loop(
                protect_db.insert_event,
                event_id,
                camera_id,
                timestamp,
                entity_type,
                event_data.get("score"),
            )
        except Exception as e:
            logger.warning("DB insert skipped for event %s: %s", event_id, e)

        # Fetch snapshot for vision analysis
        snapshot_bytes = None
        try:
            client = get_client()
            snapshot_bytes = await client.get_snapshot(camera_id, timestamp)
        except Exception as e:
            logger.warning(f"Could not fetch snapshot for event {event_id}: {e}")

        # Vision analysis (LLaVA) — optional: fall back to heuristic if Ollama unreachable
        classifications: Dict[str, Any] = {}
        vision_attempted = False
        normalized_event_type = str(entity_type or "").strip().lower()
        should_run_vision = (
            snapshot_bytes is not None
            and (
                normalized_event_type in self._vision_event_types
                or any(
                    token in normalized_event_type
                    for token in self._vision_event_types
                    if token
                )
            )
            and (
                not self._vision_camera_ids
                or camera_id in self._vision_camera_ids
            )
        )
        if should_run_vision:
            vision_attempted = True
            try:
                classifications = await self._run_vision_analysis(
                    snapshot_bytes, camera_id, timestamp, entity_type
                )
            except Exception as e:
                logger.warning(f"Vision analysis failed for event {event_id} (heuristic fallback): {e}")

        anomaly_score = _compute_anomaly_score(entity_type, classifications)
        anomaly_factors = {
            "entity_type": entity_type,
            "has_classifications": bool(classifications),
            "vision_attempted": vision_attempted,
            "vision_available": bool(classifications),
        }

        # Persist classifications + score + timing metadata (best-effort)
        try:
            await protect_db.run_in_pool_loop(
                protect_db.update_event_anomaly,
                event_id,
                anomaly_score,
                anomaly_factors,
                classifications if classifications else None,
            )
        except Exception as e:
            logger.warning("DB update skipped for event %s: %s", event_id, e)

        # Persist entities + sightings so Protect UI can show tracked entities.
        try:
            if classifications:
                await self._persist_entities_from_classifications(
                    event_id=event_id,
                    camera_id=camera_id,
                    timestamp=timestamp,
                    classifications=classifications,
                )
        except Exception as e:
            logger.warning("Entity persistence skipped for event %s: %s", event_id, e)

        # Send Telegram alert for substantial events
        from glitch.protect.config import PROTECT_ALERT_THRESHOLD
        if anomaly_score >= PROTECT_ALERT_THRESHOLD and classifications:
            try:
                from glitch.tools.ops_telegram_tools import send_telegram_alert
                camera_name = event_data.get("camera_name", camera_id)
                summary = (
                    classifications.get("summary")
                    or (f"{len(classifications.get('persons', []))} person(s)" if classifications.get("persons") else None)
                    or (f"{len(classifications.get('people', []))} person(s)" if classifications.get("people") else None)
                    or (f"{len(classifications.get('vehicles', []))} vehicle(s)" if classifications.get("vehicles") else None)
                    or entity_type
                )
                msg = (
                    f"📷 <b>{camera_name}</b>\n"
                    f"Detected: {summary}\n"
                    f"Score: {anomaly_score:.2f} | {timestamp.strftime('%H:%M:%S UTC')}"
                )
                severity = "high" if anomaly_score >= 0.8 else "medium"
                await send_telegram_alert.__wrapped__(message=msg, severity=severity, component="Protect")
                self._stats["alerts_sent"] += 1
            except Exception as e:
                logger.warning(f"Telegram alert failed for event {event_id}: {e}")

    @staticmethod
    def _normalize_plate(plate_text: str) -> str:
        return "".join(ch for ch in (plate_text or "").upper() if ch.isalnum())

    @staticmethod
    def _signature_id(prefix: str, payload: Dict[str, Any]) -> str:
        canonical = json.dumps(payload, sort_keys=True, default=str)
        digest = hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]
        return f"{prefix}_{digest}"

    async def _persist_entities_from_classifications(
        self,
        event_id: str,
        camera_id: str,
        timestamp: datetime,
        classifications: Dict[str, Any],
    ) -> None:
        """Create/update entities and sightings from vision classifications."""
        from glitch.protect import db as protect_db

        people = classifications.get("persons") or classifications.get("people") or []
        vehicles = classifications.get("vehicles") or []

        # 1) Vehicles (plate-first matching; fallback to feature signature)
        for vehicle in vehicles:
            if not isinstance(vehicle, dict):
                continue

            plate_obj = vehicle.get("plate") if isinstance(vehicle.get("plate"), dict) else {}
            plate_text = self._normalize_plate(str(plate_obj.get("text") or vehicle.get("plate") or ""))
            plate_state = str(plate_obj.get("state") or "").strip() or None

            make_model = vehicle.get("make_model") if isinstance(vehicle.get("make_model"), dict) else {}
            color_obj = vehicle.get("color") if isinstance(vehicle.get("color"), dict) else {}
            primary_color = str(color_obj.get("primary") or vehicle.get("color") or "").strip() or None
            vehicle_type = str(vehicle.get("vehicle_type") or vehicle.get("type") or "vehicle").strip()
            make = str(make_model.get("make") or "").strip() or None
            model = str(make_model.get("model") or "").strip() or None

            if plate_text:
                entity_id = f"veh_plate_{plate_text[:24].lower()}"
                label = f"Plate {plate_text}"
            else:
                signature_payload = {
                    "type": vehicle_type.lower(),
                    "color": (primary_color or "").lower(),
                    "make": (make or "").lower(),
                    "model": (model or "").lower(),
                }
                entity_id = self._signature_id("veh_sig", signature_payload)
                label = " ".join(part for part in [primary_color, make, model, vehicle_type] if part) or None

            existing = await protect_db.run_in_pool_loop(protect_db.get_entity, entity_id)
            if not existing:
                await protect_db.run_in_pool_loop(
                    protect_db.insert_entity,
                    entity_id,
                    "vehicle",
                    "unknown",
                    label,
                    plate_text or None,
                    plate_state,
                    primary_color,
                    " ".join(part for part in [make, model] if part) or None,
                    None,
                    None,
                    {"source": "event_processor", "vehicle_features": vehicle},
                )

            await protect_db.run_in_pool_loop(
                protect_db.insert_sighting,
                entity_id,
                event_id,
                camera_id,
                timestamp,
                vehicle,
            )
            await protect_db.run_in_pool_loop(protect_db.update_entity_sighting, entity_id, timestamp)
            await self._auto_mark_frequent(entity_id)

        # 2) People (stable signature from visible attributes)
        for person in people:
            if not isinstance(person, dict):
                continue

            build = person.get("build") if isinstance(person.get("build"), dict) else {}
            clothing = person.get("clothing") if isinstance(person.get("clothing"), dict) else {}
            upper = clothing.get("upper") if isinstance(clothing.get("upper"), dict) else {}
            lower = clothing.get("lower") if isinstance(clothing.get("lower"), dict) else {}
            headwear = clothing.get("headwear") if isinstance(clothing.get("headwear"), dict) else {}
            accessories = person.get("accessories") if isinstance(person.get("accessories"), dict) else {}

            signature_payload = {
                "gender": (build.get("gender") or "").lower(),
                "age": (build.get("age_range") or "").lower(),
                "upper_type": (upper.get("type") or "").lower(),
                "upper_color": (upper.get("color") or "").lower(),
                "lower_type": (lower.get("type") or "").lower(),
                "lower_color": (lower.get("color") or "").lower(),
                "headwear_type": (headwear.get("type") or "").lower(),
                "headwear_color": (headwear.get("color") or "").lower(),
                "bag": (accessories.get("bag") or "").lower(),
                "glasses": (accessories.get("glasses") or "").lower(),
            }
            entity_id = self._signature_id("prs_sig", signature_payload)
            label_bits = [build.get("gender"), build.get("age_range"), upper.get("color"), upper.get("type")]
            label = " ".join(str(bit).strip() for bit in label_bits if bit).strip() or "Unknown person"

            existing = await protect_db.run_in_pool_loop(protect_db.get_entity, entity_id)
            if not existing:
                await protect_db.run_in_pool_loop(
                    protect_db.insert_entity,
                    entity_id,
                    "person",
                    "unknown",
                    label,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    {"source": "event_processor", "person_features": person},
                )

            await protect_db.run_in_pool_loop(
                protect_db.insert_sighting,
                entity_id,
                event_id,
                camera_id,
                timestamp,
                person,
            )
            await protect_db.run_in_pool_loop(protect_db.update_entity_sighting, entity_id, timestamp)
            await self._auto_mark_frequent(entity_id)

    async def _auto_mark_frequent(self, entity_id: str) -> None:
        """Mark repeat entities as regular/known once enough sightings accumulate."""
        from glitch.protect import db as protect_db

        entity = await protect_db.run_in_pool_loop(protect_db.get_entity, entity_id)
        if not entity:
            return

        sightings = int(entity.get("sightings_count") or 0)
        current_role = str(entity.get("role") or "").strip().lower()
        current_trust = str(entity.get("trust_level") or "unknown").strip().lower()

        if sightings >= 5 and current_role in ("", "unknown"):
            await protect_db.run_in_pool_loop(
                protect_db.update_entity_role,
                entity_id,
                "regular_visitor",
            )

        if sightings >= 5 and current_trust == "unknown":
            await protect_db.run_in_pool_loop(
                protect_db.update_entity_trust,
                entity_id,
                "neutral",
                "system",
                "Auto-marked as known regular after repeated sightings",
            )

    async def _run_vision_analysis(
        self,
        snapshot_bytes: bytes,
        camera_id: str,
        timestamp: datetime,
        entity_type: str,
    ) -> Dict[str, Any]:
        """Run LLaVA vision analysis on a snapshot."""
        from glitch.protect.recognition import (
            format_vehicle_prompt,
            format_person_prompt,
            format_general_prompt,
            extract_vehicle_features,
            extract_person_features,
            extract_general_classifications,
            image_to_base64,
        )
        from glitch.protect import db as protect_db

        camera = await protect_db.get_camera(camera_id)
        camera_location = camera.get("location", camera_id) if camera else camera_id
        timestamp_str = timestamp.strftime("%Y-%m-%d %I:%M %p")

        if entity_type == "vehicle":
            prompt = format_vehicle_prompt(camera_location, timestamp_str)
        elif entity_type == "person":
            prompt = format_person_prompt(camera_location, timestamp_str)
        else:
            prompt = format_general_prompt(camera_location, timestamp_str)

        # vision_agent expects image_url or base64
        image_b64 = image_to_base64(snapshot_bytes)
        image_url = f"data:image/jpeg;base64,{image_b64}"

        # Import vision_agent tool function
        from glitch.tools.ollama_tools import vision_agent as _vision_agent

        t0 = time.monotonic()
        raw_output = await _vision_agent(
            image_url=image_url,
            prompt=prompt,
        )
        processing_ms = (time.monotonic() - t0) * 1000

        if entity_type == "vehicle":
            vehicles = extract_vehicle_features(str(raw_output))
            return {"vehicles": vehicles, "entity_type": "vehicle", "processing_ms": processing_ms}
        elif entity_type == "person":
            persons = extract_person_features(str(raw_output))
            return {"persons": persons, "entity_type": "person", "processing_ms": processing_ms}
        else:
            result = extract_general_classifications(str(raw_output))
            result["processing_ms"] = processing_ms
            return result


def _compute_anomaly_score(entity_type: str, classifications: Dict[str, Any]) -> float:
    """Heuristic anomaly score based on entity type and vision classifications."""
    if entity_type == "person" and (classifications.get("persons") or classifications.get("people")):
        return 0.75
    if entity_type == "vehicle" and classifications.get("vehicles"):
        return 0.55
    if entity_type == "motion":
        return 0.35
    if classifications:
        return 0.5
    return 0.2
