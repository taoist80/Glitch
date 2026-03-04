"""Async event processor for UniFi Protect events.

Manages an asyncio.Queue + worker pool for real-time event processing.
Each worker runs: snapshot -> LLaVA -> recognition -> DB match -> anomaly -> alert -> store.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProtectEventProcessor:
    """Async event processor with bounded queue and worker pool."""

    def __init__(self, max_workers: int = 3, queue_size: int = 100):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._workers: List[asyncio.Task] = []
        self._running = False
        self._camera_ids: List[str] = []
        self._check_interval: float = 2.0
        self._alert_profile: str = "balanced"
        self._last_event_ids: Dict[str, str] = {}
        self._stats = {
            "processed": 0,
            "errors": 0,
            "alerts_sent": 0,
            "last_processed": None,
            "started_at": None,
        }
        self._max_workers = max_workers

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
        """Poll Protect API for new events and enqueue them."""
        from sentinel.protect.client import get_client

        while self._running:
            try:
                client = get_client()
                end_time = datetime.now()
                start_time = end_time - timedelta(seconds=self._check_interval * 2)

                events = await client.get_events(
                    start=start_time,
                    end=end_time,
                    camera_ids=self._camera_ids if self._camera_ids else None,
                )

                for event in events:
                    event_id = event.get("id") or event.get("event_id")
                    if not event_id:
                        continue

                    # Deduplicate
                    camera_id = event.get("camera") or event.get("camera_id", "unknown")
                    last_id = self._last_event_ids.get(camera_id)
                    if event_id == last_id:
                        continue

                    self._last_event_ids[camera_id] = event_id
                    await self.enqueue(event)

            except Exception as e:
                logger.error(f"Ingest loop error: {e}", exc_info=True)

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
        from sentinel.protect import db as protect_db
        from sentinel.protect.client import get_client

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

        # Store raw event
        await protect_db.insert_event(
            event_id=event_id,
            camera_id=camera_id,
            timestamp=timestamp,
            entity_type=entity_type,
            score=event_data.get("score"),
        )

        # Fetch snapshot for vision analysis
        snapshot_bytes = None
        try:
            client = get_client()
            snapshot_bytes = await client.get_snapshot(camera_id, timestamp)
        except Exception as e:
            logger.warning(f"Could not fetch snapshot for event {event_id}: {e}")

        # Vision analysis (LLaVA) - only for person/vehicle events
        classifications: Dict[str, Any] = {}
        if snapshot_bytes and entity_type in ("person", "vehicle", "motion"):
            try:
                classifications = await self._run_vision_analysis(
                    snapshot_bytes, camera_id, timestamp, entity_type
                )
            except Exception as e:
                logger.warning(f"Vision analysis failed for event {event_id}: {e}")

        # Update event with classifications
        if classifications:
            await protect_db.update_event_anomaly(
                event_id=event_id,
                anomaly_score=0.0,  # Will be updated after anomaly scoring
                anomaly_factors={},
                classifications=classifications,
            )

    async def _run_vision_analysis(
        self,
        snapshot_bytes: bytes,
        camera_id: str,
        timestamp: datetime,
        entity_type: str,
    ) -> Dict[str, Any]:
        """Run LLaVA vision analysis on a snapshot."""
        from sentinel.protect.recognition import (
            format_vehicle_prompt,
            format_person_prompt,
            format_general_prompt,
            extract_vehicle_features,
            extract_person_features,
            extract_general_classifications,
            image_to_base64,
        )
        from sentinel.protect import db as protect_db

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

        # Call vision_agent - it's a strands tool, call underlying function
        raw_output = await _vision_agent.__wrapped__(
            image_url=image_url,
            prompt=prompt,
        ) if hasattr(_vision_agent, "__wrapped__") else str(
            await asyncio.get_event_loop().run_in_executor(
                None, lambda: _vision_agent(image_url=image_url, prompt=prompt)
            )
        )

        if entity_type == "vehicle":
            vehicles = extract_vehicle_features(str(raw_output))
            return {"vehicles": vehicles, "entity_type": "vehicle"}
        elif entity_type == "person":
            persons = extract_person_features(str(raw_output))
            return {"persons": persons, "entity_type": "person"}
        else:
            return extract_general_classifications(str(raw_output))
