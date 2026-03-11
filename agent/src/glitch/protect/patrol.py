"""Camera Patrol: periodic snapshot capture + LLaVA analysis.

Runs as a background asyncio task, capturing a snapshot from each camera
every `interval_seconds` (default 120) and sending it to the local LLaVA
model for scene analysis.  Results are persisted to the `camera_patrols`
table so the UI can display the latest patrol scene per camera.

If LLaVA/Ollama is unreachable, the patrol continues and records an error
row — it is never fatal.
"""

import asyncio
import base64
import json
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from glitch.protect.client import ProtectClient

logger = logging.getLogger(__name__)

_SCENE_PROMPT = (
    "Analyze this security camera image. Describe the scene in 1-2 sentences. "
    "List any detected objects (people, vehicles, animals, packages). "
    "Note anything unusual or anomalous. "
    "Return ONLY valid JSON: "
    '{"scene": "...", "objects": ["person", "vehicle"], '
    '"anomaly": false, "anomaly_description": "", "confidence": 0.0-1.0}'
)


class CameraPatrol:
    """Periodic camera patrol with LLaVA vision analysis."""

    def __init__(self, protect_client: "ProtectClient", interval_seconds: int = 120) -> None:
        self._client = protect_client
        self._interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._camera_ids: List[str] = []

    async def start(self, camera_ids: List[str]) -> None:
        if self._running:
            return
        self._camera_ids = camera_ids
        self._running = True
        self._task = asyncio.create_task(self._patrol_loop(), name="camera-patrol")
        logger.info(
            "CameraPatrol started: %d cameras, %ds interval",
            len(camera_ids), self._interval,
        )

    def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
        logger.info("CameraPatrol stopped")

    async def scan_now(self) -> List[Dict[str, Any]]:
        """On-demand scan of all cameras. Returns results list."""
        results: List[Dict[str, Any]] = []
        for cam_id in self._camera_ids:
            r = await self._scan_camera(cam_id)
            results.append(r)
            await asyncio.sleep(2)
        return results

    async def _patrol_loop(self) -> None:
        """Main patrol loop — snapshot + analyse every camera, then sleep."""
        await asyncio.sleep(60)

        while self._running:
            for cam_id in self._camera_ids:
                if not self._running:
                    return
                try:
                    await self._scan_camera(cam_id)
                except Exception as exc:
                    logger.warning("Patrol scan failed for %s: %s", cam_id, exc)
                await asyncio.sleep(5)
            try:
                await asyncio.sleep(self._interval)
            except asyncio.CancelledError:
                return

    async def _scan_camera(self, camera_id: str) -> Dict[str, Any]:
        """Capture snapshot, run LLaVA, persist to DB."""
        from glitch.protect import db as protect_db

        t0 = time.monotonic()
        result: Dict[str, Any] = {"camera_id": camera_id}

        snapshot_bytes: Optional[bytes] = None
        try:
            snapshot_bytes = await self._client.get_snapshot(camera_id)
        except Exception as exc:
            error_msg = f"Snapshot fetch failed: {exc}"
            logger.warning("Patrol[%s]: %s", camera_id, error_msg)
            try:
                await protect_db.insert_patrol(camera_id=camera_id, error=error_msg)
            except Exception:
                pass
            result["error"] = error_msg
            return result

        scene_description = None
        detected_objects: List[str] = []
        anomaly_detected = False
        anomaly_description = None
        confidence = 0.0
        error_msg = None

        try:
            b64 = base64.b64encode(snapshot_bytes).decode("utf-8")
            image_url = f"data:image/jpeg;base64,{b64}"

            from glitch.tools.ollama_tools import vision_agent as _vision_agent
            raw_output = await _vision_agent.__wrapped__(
                image_url=image_url,
                prompt=_SCENE_PROMPT,
            )

            parsed = _parse_llava_response(str(raw_output))
            scene_description = parsed.get("scene", str(raw_output)[:500])
            detected_objects = parsed.get("objects", [])
            anomaly_detected = parsed.get("anomaly", False)
            anomaly_description = parsed.get("anomaly_description") or None
            confidence = float(parsed.get("confidence", 0.5))

        except Exception as exc:
            error_msg = f"LLaVA analysis failed: {exc}"
            logger.warning("Patrol[%s]: %s", camera_id, error_msg)

        processing_ms = int((time.monotonic() - t0) * 1000)

        try:
            patrol_id = await protect_db.insert_patrol(
                camera_id=camera_id,
                scene_description=scene_description,
                detected_objects=detected_objects,
                anomaly_detected=anomaly_detected,
                anomaly_description=anomaly_description,
                confidence=confidence,
                model_used="llava",
                processing_ms=processing_ms,
                error=error_msg,
            )
            result["patrol_id"] = patrol_id
        except Exception as db_exc:
            logger.warning("Patrol[%s]: DB insert failed: %s", camera_id, db_exc)

        result.update({
            "scene_description": scene_description,
            "detected_objects": detected_objects,
            "anomaly_detected": anomaly_detected,
            "anomaly_description": anomaly_description,
            "confidence": confidence,
            "processing_ms": processing_ms,
            "error": error_msg,
        })

        if not error_msg:
            logger.info(
                "Patrol[%s]: %s (%.0fms, confidence=%.2f)",
                camera_id,
                (scene_description or "")[:80],
                processing_ms,
                confidence,
            )

        return result


def _parse_llava_response(raw: str) -> Dict[str, Any]:
    """Best-effort JSON extraction from LLaVA output."""
    import re
    json_match = re.search(r"\{[^{}]*\}", raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(0))
        except json.JSONDecodeError:
            pass
    return {"scene": raw[:500]}
