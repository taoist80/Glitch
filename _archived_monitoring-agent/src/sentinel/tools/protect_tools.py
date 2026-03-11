"""UniFi Protect tools - 48 tools across 14 groups.

Tools are split into CORE_PROTECT_TOOLS (13) and EXTENDED_PROTECT_TOOLS (35).
Only CORE tools are registered by default; EXTENDED tools are loaded when the
surveillance skill is active (reduces LLM context and improves tool selection).

ALL_PROTECT_TOOLS = CORE_PROTECT_TOOLS + EXTENDED_PROTECT_TOOLS (all 48).
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from strands import tool

logger = logging.getLogger(__name__)

_monitoring_processor = None


def _get_processor():
    global _monitoring_processor
    if _monitoring_processor is None:
        from sentinel.protect.event_processor import ProtectEventProcessor
        _monitoring_processor = ProtectEventProcessor()
    return _monitoring_processor


def _not_configured_msg(feature: str = "Protect") -> str:
    return (
        f"{feature} not configured. Set GLITCH_PROTECT_HOST, GLITCH_PROTECT_USERNAME, "
        "GLITCH_PROTECT_PASSWORD env vars (or SSM /glitch/protect/* parameters)."
    )


def _db_not_configured_msg() -> str:
    return (
        "Protect DB not configured. Set GLITCH_PROTECT_DB_URI env var "
        "(or SSM /glitch/protect-db/* + Secrets Manager glitch/protect-db)."
    )


# ============================================================
# GROUP 1: Core Protect Access (5 tools)
# ============================================================

@tool
async def protect_get_cameras() -> str:
    """List all UniFi Protect cameras with status and settings.

    Returns:
        JSON list of cameras with id, name, type, location, recording state, and motion settings.
    """
    from sentinel.protect.config import is_protect_configured
    if not is_protect_configured():
        return _not_configured_msg()

    try:
        from sentinel.protect.client import get_client
        from sentinel.protect import db as protect_db

        client = get_client()
        cameras = await client.get_cameras()

        result = []
        for cam in cameras:
            cam_id = cam.get("id", "")
            cam_info = {
                "camera_id": cam_id,
                "name": cam.get("name", ""),
                "type": cam.get("type", ""),
                "state": cam.get("state", ""),
                "is_recording": cam.get("isRecording", False),
                "is_connected": cam.get("isConnected", False),
                "last_motion": cam.get("lastMotion"),
                "location": cam.get("featureFlags", {}).get("hasSpeaker"),
            }
            result.append(cam_info)

            # Sync to DB
            if cam_id:
                await protect_db.upsert_camera(
                    camera_id=cam_id,
                    name=cam.get("name", cam_id),
                    camera_type=cam.get("type"),
                )

        return json.dumps({"cameras": result, "count": len(result)}, indent=2)
    except Exception as e:
        logger.error(f"protect_get_cameras error: {e}")
        return f"Error: {e}"


@tool
async def protect_get_events(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    camera_ids: Optional[str] = None,
    event_types: Optional[str] = None,
    limit: int = 50,
) -> str:
    """Query UniFi Protect events with optional filters.

    Args:
        start_time: ISO 8601 start time (default: 1 hour ago)
        end_time: ISO 8601 end time (default: now)
        camera_ids: Comma-separated camera IDs to filter by
        event_types: Comma-separated event types (motion, person, vehicle, animal, package)
        limit: Maximum number of events to return (default 50)

    Returns:
        JSON list of events with id, timestamp, camera_id, event_type, score, and media URLs.
    """
    from sentinel.protect.config import is_protect_configured
    if not is_protect_configured():
        return _not_configured_msg()

    try:
        from sentinel.protect.client import get_client

        client = get_client()

        start_dt = datetime.fromisoformat(start_time) if start_time else datetime.now() - timedelta(hours=1)
        end_dt = datetime.fromisoformat(end_time) if end_time else datetime.now()
        cam_list = [c.strip() for c in camera_ids.split(",")] if camera_ids else None
        type_list = [t.strip() for t in event_types.split(",")] if event_types else None

        events = await client.get_events(
            start=start_dt,
            end=end_dt,
            camera_ids=cam_list,
            event_types=type_list,
            limit=limit,
        )

        result = []
        for ev in events:
            ts_raw = ev.get("start") or ev.get("timestamp")
            if isinstance(ts_raw, (int, float)):
                ts = datetime.fromtimestamp(ts_raw / 1000 if ts_raw > 1e10 else ts_raw).isoformat()
            else:
                ts = str(ts_raw)

            result.append({
                "event_id": ev.get("id", ""),
                "timestamp": ts,
                "camera_id": ev.get("camera", ""),
                "event_type": ev.get("type", ""),
                "score": ev.get("score"),
                "thumbnail_url": ev.get("thumbnail"),
                "video_clip_url": ev.get("heatmap"),
            })

        return json.dumps({"events": result, "count": len(result)}, indent=2)
    except Exception as e:
        logger.error(f"protect_get_events error: {e}")
        return f"Error: {e}"


@tool
async def protect_get_snapshot(
    camera_id: str,
    timestamp: Optional[str] = None,
) -> str:
    """Get a camera snapshot for vision analysis.

    Args:
        camera_id: Camera ID to get snapshot from
        timestamp: ISO 8601 timestamp for historical snapshot (default: current)

    Returns:
        Base64-encoded JPEG image data URL suitable for vision_agent, or error message.
    """
    from sentinel.protect.config import is_protect_configured
    if not is_protect_configured():
        return _not_configured_msg()

    try:
        from sentinel.protect.client import get_client
        from sentinel.protect.recognition import image_to_base64

        client = get_client()
        ts_dt = datetime.fromisoformat(timestamp) if timestamp else None
        snapshot_bytes = await client.get_snapshot(camera_id, ts_dt)

        b64 = image_to_base64(snapshot_bytes)
        data_url = f"data:image/jpeg;base64,{b64}"

        return json.dumps({
            "camera_id": camera_id,
            "timestamp": timestamp or datetime.now().isoformat(),
            "image_url": data_url,
            "size_bytes": len(snapshot_bytes),
        })
    except Exception as e:
        logger.error(f"protect_get_snapshot error: {e}")
        return f"Error: {e}"


@tool
async def protect_get_video_clip(
    event_id: Optional[str] = None,
    camera_id: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
) -> str:
    """Get a video clip for an event or time range.

    Args:
        event_id: Event ID to get clip for (uses event's camera and time range)
        camera_id: Camera ID (required if not using event_id)
        start_time: ISO 8601 start time (required if not using event_id)
        end_time: ISO 8601 end time (required if not using event_id)

    Returns:
        Video clip URL or base64 data, or error message.
    """
    from sentinel.protect.config import is_protect_configured
    if not is_protect_configured():
        return _not_configured_msg()

    try:
        from sentinel.protect.client import get_client
        from sentinel.protect import db as protect_db

        client = get_client()

        if event_id:
            event = await protect_db.get_event(event_id)
            if not event:
                return f"Event {event_id} not found in database"
            camera_id = event["camera_id"]
            ts = event["timestamp"]
            if isinstance(ts, datetime):
                start_dt = ts - timedelta(seconds=10)
                end_dt = ts + timedelta(seconds=30)
            else:
                return "Cannot determine time range from event"
        elif camera_id and start_time and end_time:
            start_dt = datetime.fromisoformat(start_time)
            end_dt = datetime.fromisoformat(end_time)
        else:
            return "Provide either event_id or (camera_id + start_time + end_time)"

        clip_bytes = await client.get_video_export(camera_id, start_dt, end_dt)
        import base64
        b64 = base64.b64encode(clip_bytes).decode("utf-8")

        return json.dumps({
            "camera_id": camera_id,
            "start_time": start_dt.isoformat(),
            "end_time": end_dt.isoformat(),
            "size_bytes": len(clip_bytes),
            "video_data": f"data:video/mp4;base64,{b64[:100]}...",  # Truncated for display
        })
    except Exception as e:
        logger.error(f"protect_get_video_clip error: {e}")
        return f"Error: {e}"


@tool
async def protect_update_camera_settings(
    camera_id: str,
    motion_sensitivity: Optional[int] = None,
    recording_mode: Optional[str] = None,
    smart_detection_person: Optional[bool] = None,
    smart_detection_vehicle: Optional[bool] = None,
) -> str:
    """Update camera settings.

    Args:
        camera_id: Camera ID to update
        motion_sensitivity: Motion sensitivity 0-100
        recording_mode: Recording mode (always, motion, never)
        smart_detection_person: Enable/disable person smart detection
        smart_detection_vehicle: Enable/disable vehicle smart detection

    Returns:
        Success or error message.
    """
    from sentinel.protect.config import is_protect_configured
    if not is_protect_configured():
        return _not_configured_msg()

    try:
        from sentinel.protect.client import get_client

        settings: Dict[str, Any] = {}
        if motion_sensitivity is not None:
            settings["motionZones"] = [{"sensitivity": motion_sensitivity}]
        if recording_mode is not None:
            settings["recordingSettings"] = {"mode": recording_mode}
        if smart_detection_person is not None or smart_detection_vehicle is not None:
            smart = {}
            if smart_detection_person is not None:
                smart["person"] = smart_detection_person
            if smart_detection_vehicle is not None:
                smart["vehicle"] = smart_detection_vehicle
            settings["smartDetectSettings"] = {"objectTypes": smart}

        if not settings:
            return "No settings to update"

        client = get_client()
        result = await client.update_camera_settings(camera_id, settings)
        return json.dumps({"status": "updated", "camera_id": camera_id, "settings_applied": settings})
    except Exception as e:
        logger.error(f"protect_update_camera_settings error: {e}")
        return f"Error: {e}"


# ============================================================
# GROUP 2: Database Integration (5 tools)
# ============================================================

@tool
async def protect_db_store_observation(
    event_id: str,
    camera_id: str,
    timestamp: str,
    classifications: str,
    entities_detected: str = "[]",
    confidence_scores: str = "{}",
    contextual_notes: str = "",
) -> str:
    """Store an event observation in the database.

    Args:
        event_id: Protect event ID
        camera_id: Camera that captured the event
        timestamp: ISO 8601 event timestamp
        classifications: JSON string of vision classifications
        entities_detected: JSON array of entity IDs detected
        confidence_scores: JSON object of entity_id -> confidence
        contextual_notes: Free-text notes about the observation

    Returns:
        Confirmation with stored event ID.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        ts_dt = datetime.fromisoformat(timestamp)
        cls_dict = json.loads(classifications) if isinstance(classifications, str) else classifications
        entities = json.loads(entities_detected) if isinstance(entities_detected, str) else entities_detected
        scores = json.loads(confidence_scores) if isinstance(confidence_scores, str) else confidence_scores

        await protect_db.insert_event(
            event_id=event_id,
            camera_id=camera_id,
            timestamp=ts_dt,
            metadata={
                "classifications": cls_dict,
                "entities_detected": entities,
                "confidence_scores": scores,
                "contextual_notes": contextual_notes,
            },
        )

        return json.dumps({
            "status": "stored",
            "event_id": event_id,
            "camera_id": camera_id,
            "timestamp": timestamp,
        })
    except Exception as e:
        logger.error(f"protect_db_store_observation error: {e}")
        return f"Error: {e}"


@tool
async def protect_db_query_patterns(
    camera_id: Optional[str] = None,
    time_pattern: Optional[str] = None,
    entity_type: Optional[str] = None,
    lookback_period: str = "30d",
) -> str:
    """Query traffic patterns from the database.

    Args:
        camera_id: Filter by camera ID
        time_pattern: JSON with hour_of_day and/or day_of_week filters
        entity_type: Filter by entity type (vehicle, person, baseline)
        lookback_period: Lookback period (e.g., 7d, 30d, 90d)

    Returns:
        JSON list of patterns with frequency, confidence, and anomaly indicators.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        patterns = await protect_db.query_patterns(
            camera_id=camera_id,
            entity_type=entity_type,
        )

        return json.dumps({
            "patterns": patterns,
            "count": len(patterns),
            "camera_id": camera_id,
            "entity_type": entity_type,
        }, indent=2, default=str)
    except Exception as e:
        logger.error(f"protect_db_query_patterns error: {e}")
        return f"Error: {e}"


@tool
async def protect_db_get_baseline(
    camera_id: str,
    hour_of_day: int,
    day_of_week: int,
) -> str:
    """Get baseline traffic pattern for a camera/time context.

    Args:
        camera_id: Camera ID
        hour_of_day: Hour 0-23
        day_of_week: Day 0-6 (0=Monday, 6=Sunday)

    Returns:
        JSON baseline with expected activity level, typical entities, and confidence intervals.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        baseline = await protect_db.get_baseline(camera_id, hour_of_day, day_of_week)

        if not baseline:
            return json.dumps({
                "camera_id": camera_id,
                "hour_of_day": hour_of_day,
                "day_of_week": day_of_week,
                "baseline_available": False,
                "message": "No baseline data yet. Run skill_establish_baseline_traffic first.",
            })

        return json.dumps({
            "camera_id": camera_id,
            "hour_of_day": hour_of_day,
            "day_of_week": day_of_week,
            "baseline_available": True,
            "frequency": baseline.get("frequency", 0),
            "confidence": baseline.get("confidence", 0),
            "time_pattern": baseline.get("time_pattern", {}),
            "metadata": baseline.get("metadata", {}),
        }, indent=2, default=str)
    except Exception as e:
        logger.error(f"protect_db_get_baseline error: {e}")
        return f"Error: {e}"


@tool
async def protect_db_record_alert(
    event_id: str,
    alert_type: str,
    reason: str,
    priority: str = "medium",
    user_response: Optional[str] = None,
    entity_id: Optional[str] = None,
    camera_id: Optional[str] = None,
) -> str:
    """Record an alert in the database.

    Args:
        event_id: Associated event ID
        alert_type: Type of alert (motion, person, vehicle, threat, hostile)
        reason: Human-readable reason for the alert
        priority: Alert priority (critical, high, medium, low)
        user_response: Optional user response (acknowledged, false_positive, dismissed)
        entity_id: Optional entity ID involved
        camera_id: Optional camera ID

    Returns:
        Alert record confirmation with alert_id.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        alert_id = await protect_db.insert_alert(
            event_id=event_id,
            entity_id=entity_id,
            camera_id=camera_id,
            priority=priority,
            title=f"{alert_type.title()} Alert",
            body=reason,
            delivered=True,
            metadata={"alert_type": alert_type, "reason": reason},
        )

        if user_response:
            await protect_db.update_alert_response(alert_id, user_response)

        return json.dumps({
            "status": "recorded",
            "alert_id": alert_id,
            "event_id": event_id,
            "priority": priority,
        })
    except Exception as e:
        logger.error(f"protect_db_record_alert error: {e}")
        return f"Error: {e}"


@tool
async def protect_db_update_pattern(
    camera_id: str,
    entity_type: str,
    hour_of_day: int,
    day_of_week: int,
    reinforcement_data: str = "{}",
    entity_id: Optional[str] = None,
) -> str:
    """Update or create a traffic pattern in the database.

    Args:
        camera_id: Camera ID
        entity_type: Entity type (vehicle, person, baseline)
        hour_of_day: Hour 0-23
        day_of_week: Day 0-6
        reinforcement_data: JSON with additional context (e.g., "normal for Saturday mornings")
        entity_id: Optional specific entity ID

    Returns:
        Updated pattern confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        extra = json.loads(reinforcement_data) if isinstance(reinforcement_data, str) else reinforcement_data

        pattern_id = await protect_db.insert_pattern(
            camera_id=camera_id,
            entity_id=entity_id,
            entity_type=entity_type,
            time_pattern={"hour_of_day": hour_of_day, "day_of_week": day_of_week},
            frequency=extra.get("frequency", 1.0),
            confidence=extra.get("confidence", 0.5),
            metadata=extra,
        )

        return json.dumps({
            "status": "updated",
            "pattern_id": pattern_id,
            "camera_id": camera_id,
            "entity_type": entity_type,
        })
    except Exception as e:
        logger.error(f"protect_db_update_pattern error: {e}")
        return f"Error: {e}"


# ============================================================
# GROUP 3: Alert Intelligence (5 tools)
# ============================================================

@tool
async def protect_analyze_event(event_id: str) -> str:
    """Analyze a Protect event with full context.

    Args:
        event_id: Event ID to analyze

    Returns:
        JSON with vision classifications, pattern context, anomaly score, and alert recommendation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        event = await protect_db.get_event(event_id)
        if not event:
            return f"Event {event_id} not found"

        ts = event.get("timestamp")
        if isinstance(ts, datetime):
            hour = ts.hour
            dow = ts.weekday()
        else:
            hour = 12
            dow = 0

        baseline = await protect_db.get_baseline(event["camera_id"], hour, dow)
        prefs = await protect_db.get_alert_preferences(event["camera_id"])
        fp_rate = await protect_db.get_camera_fp_rate(event["camera_id"])

        return json.dumps({
            "event_id": event_id,
            "event": {
                "camera_id": event.get("camera_id"),
                "timestamp": str(event.get("timestamp")),
                "entity_type": event.get("entity_type"),
                "anomaly_score": event.get("anomaly_score", 0),
                "anomaly_factors": event.get("anomaly_factors", {}),
                "classifications": event.get("classifications", {}),
            },
            "context": {
                "baseline_available": baseline is not None,
                "baseline_frequency": baseline.get("frequency", 0) if baseline else 0,
                "camera_fp_rate_7d": fp_rate,
                "alert_preferences": {
                    "sensitivity": prefs.get("sensitivity"),
                    "min_anomaly_score": prefs.get("min_anomaly_score"),
                    "quiet_hours_start": prefs.get("quiet_hours_start"),
                    "quiet_hours_end": prefs.get("quiet_hours_end"),
                },
            },
            "recommendation": {
                "should_alert": event.get("anomaly_score", 0) > prefs.get("min_anomaly_score", 0.5),
                "confidence": min(1.0, event.get("anomaly_score", 0) * 1.5),
                "reasoning": f"Anomaly score {event.get('anomaly_score', 0):.2f} vs threshold {prefs.get('min_anomaly_score', 0.5):.2f}",
            },
        }, indent=2, default=str)
    except Exception as e:
        logger.error(f"protect_analyze_event error: {e}")
        return f"Error: {e}"


@tool
async def protect_should_alert(
    event_analysis: str,
    user_context: str = "{}",
) -> str:
    """Determine if an event warrants an alert using adaptive thresholds.

    Args:
        event_analysis: JSON from protect_analyze_event
        user_context: JSON with user context (home/away, time_sensitivity, etc.)

    Returns:
        JSON with should_alert, confidence, reasoning, and priority.
    """
    try:
        analysis = json.loads(event_analysis) if isinstance(event_analysis, str) else event_analysis
        context = json.loads(user_context) if isinstance(user_context, str) else user_context

        event = analysis.get("event", {})
        event_context = analysis.get("context", {})
        anomaly_score = event.get("anomaly_score", 0)
        prefs = event_context.get("alert_preferences", {})
        fp_rate = event_context.get("camera_fp_rate_7d", 0)

        # Adaptive threshold: raise threshold if FP rate is high
        base_threshold = prefs.get("min_anomaly_score", 0.5)
        if fp_rate > 0.3:
            adaptive_threshold = min(0.9, base_threshold + (fp_rate - 0.3) * 0.5)
        else:
            adaptive_threshold = base_threshold

        # User context adjustments
        if context.get("user_away"):
            adaptive_threshold = max(0.1, adaptive_threshold - 0.1)  # More sensitive when away
        if context.get("quiet_mode"):
            adaptive_threshold = min(0.95, adaptive_threshold + 0.2)  # Less sensitive in quiet mode

        # Check quiet hours
        sensitivity = prefs.get("sensitivity", "balanced")
        ts = event.get("timestamp", "")
        in_quiet_hours = False
        if prefs.get("quiet_hours_start") is not None and ts:
            try:
                hour = datetime.fromisoformat(ts).hour
                qs = prefs["quiet_hours_start"]
                qe = prefs["quiet_hours_end"]
                if qs <= qe:
                    in_quiet_hours = qs <= hour < qe
                else:
                    in_quiet_hours = hour >= qs or hour < qe
            except Exception:
                pass

        should_alert = anomaly_score >= adaptive_threshold and not in_quiet_hours

        # Determine priority
        if anomaly_score >= 0.9:
            priority = "critical"
        elif anomaly_score >= 0.75:
            priority = "high"
        elif anomaly_score >= 0.5:
            priority = "medium"
        else:
            priority = "low"

        reasoning_parts = [
            f"Anomaly score: {anomaly_score:.2f}",
            f"Adaptive threshold: {adaptive_threshold:.2f} (base: {base_threshold:.2f}, FP rate: {fp_rate:.1%})",
        ]
        if in_quiet_hours:
            reasoning_parts.append("In quiet hours - alert suppressed")
        if context.get("user_away"):
            reasoning_parts.append("User away - threshold lowered")

        return json.dumps({
            "should_alert": should_alert,
            "confidence": min(1.0, abs(anomaly_score - adaptive_threshold) * 2),
            "reasoning": "; ".join(reasoning_parts),
            "priority": priority,
            "anomaly_score": anomaly_score,
            "threshold_used": adaptive_threshold,
            "in_quiet_hours": in_quiet_hours,
        })
    except Exception as e:
        logger.error(f"protect_should_alert error: {e}")
        return f"Error: {e}"


@tool
async def protect_send_telegram_alert(
    event_id: str,
    alert_priority: str,
    message: str,
    snapshot_url: Optional[str] = None,
    video_clip_url: Optional[str] = None,
    entity_id: Optional[str] = None,
) -> str:
    """Send an alert via Telegram with optional snapshot.

    Args:
        event_id: Event ID for reference
        alert_priority: Priority (critical, high, medium, low)
        message: Alert message text
        snapshot_url: Optional snapshot image URL or base64 data URL
        video_clip_url: Optional video clip URL
        entity_id: Optional entity ID for quick-action buttons

    Returns:
        Delivery confirmation or error message.
    """
    try:
        from glitch.channels.telegram import send_message

        priority_emoji = {
            "critical": "🚨",
            "high": "⚠️",
            "medium": "📷",
            "low": "ℹ️",
        }.get(alert_priority, "📷")

        full_message = f"{priority_emoji} *Protect Alert* [{alert_priority.upper()}]\n\n{message}"

        if video_clip_url:
            full_message += f"\n\n📹 [View Clip]({video_clip_url})"

        quick_actions = []
        if entity_id:
            quick_actions.append(f"Mark Friendly: `/protect_trust {entity_id} trusted`")
            quick_actions.append(f"Mark Hostile: `/protect_trust {entity_id} hostile`")
        quick_actions.append(f"False Positive: `/protect_fp {event_id}`")

        if quick_actions:
            full_message += "\n\n" + "\n".join(quick_actions)

        # Use existing Telegram channel if available
        try:
            await send_message(full_message)
            delivery_status = "delivered"
        except Exception as telegram_err:
            logger.warning(f"Telegram send failed: {telegram_err}")
            delivery_status = f"failed: {telegram_err}"

        from sentinel.protect.config import is_db_configured
        if is_db_configured():
            from sentinel.protect import db as protect_db
            await protect_db.insert_alert(
                event_id=event_id,
                entity_id=entity_id,
                camera_id=None,
                priority=alert_priority,
                title=f"Protect Alert [{alert_priority}]",
                body=message,
                delivered=delivery_status == "delivered",
            )

        return json.dumps({
            "status": delivery_status,
            "event_id": event_id,
            "priority": alert_priority,
        })
    except Exception as e:
        logger.error(f"protect_send_telegram_alert error: {e}")
        return f"Error: {e}"


@tool
async def protect_get_alert_preferences(camera_id: Optional[str] = None) -> str:
    """Get alert preferences for a camera or global defaults.

    Args:
        camera_id: Camera ID (omit for global defaults)

    Returns:
        JSON with sensitivity, entity_filters, quiet_hours, and min_anomaly_score.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db
        prefs = await protect_db.get_alert_preferences(camera_id or "global")
        return json.dumps(prefs, indent=2, default=str)
    except Exception as e:
        logger.error(f"protect_get_alert_preferences error: {e}")
        return f"Error: {e}"


@tool
async def protect_update_alert_preferences(
    camera_id: str,
    sensitivity: Optional[str] = None,
    entity_filters: Optional[str] = None,
    quiet_hours_start: Optional[int] = None,
    quiet_hours_end: Optional[int] = None,
    min_anomaly_score: Optional[float] = None,
) -> str:
    """Update alert preferences for a camera.

    Args:
        camera_id: Camera ID (use 'global' for defaults)
        sensitivity: Sensitivity level (paranoid, balanced, relaxed)
        entity_filters: Comma-separated entity types to alert on (vehicle,person,animal)
        quiet_hours_start: Quiet hours start (hour 0-23)
        quiet_hours_end: Quiet hours end (hour 0-23)
        min_anomaly_score: Minimum anomaly score to trigger alert (0.0-1.0)

    Returns:
        Updated preferences confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        filters_list = [f.strip() for f in entity_filters.split(",")] if entity_filters else None

        await protect_db.upsert_alert_preferences(
            camera_id=camera_id,
            sensitivity=sensitivity,
            entity_filters=filters_list,
            quiet_hours_start=quiet_hours_start,
            quiet_hours_end=quiet_hours_end,
            min_anomaly_score=min_anomaly_score,
        )

        return json.dumps({"status": "updated", "camera_id": camera_id})
    except Exception as e:
        logger.error(f"protect_update_alert_preferences error: {e}")
        return f"Error: {e}"


# ============================================================
# GROUP 4: Vision Integration (2 tools)
# ============================================================

@tool
async def protect_classify_snapshot(
    image_url: str,
    camera_location: str = "unknown",
    timestamp: Optional[str] = None,
) -> str:
    """Classify all entities in a snapshot using LLaVA vision analysis.

    Args:
        image_url: Image URL or base64 data URL
        camera_location: Camera location description for context
        timestamp: ISO 8601 timestamp for context

    Returns:
        JSON with structured classifications: people, vehicles, animals, packages, anomalies.
    """
    try:
        from sentinel.protect.recognition import (
            format_general_prompt,
            extract_general_classifications,
        )
        from glitch.tools.ollama_tools import vision_agent

        ts_str = timestamp or datetime.now().strftime("%Y-%m-%d %I:%M %p")
        prompt = format_general_prompt(camera_location, ts_str)

        result = await vision_agent.__wrapped__(
            image_url=image_url,
            prompt=prompt,
        ) if hasattr(vision_agent, "__wrapped__") else str(vision_agent(image_url=image_url, prompt=prompt))

        classifications = extract_general_classifications(str(result))
        return json.dumps(classifications, indent=2)
    except Exception as e:
        logger.error(f"protect_classify_snapshot error: {e}")
        return f"Error: {e}"


@tool
async def protect_detect_anomalies(
    current_snapshot: str,
    baseline_description: str = "",
    camera_location: str = "unknown",
) -> str:
    """Detect anomalies by comparing current snapshot to baseline description.

    Args:
        current_snapshot: Current image URL or base64 data URL
        baseline_description: Text description of normal state for this camera
        camera_location: Camera location description

    Returns:
        JSON list of anomalies with description, location, and confidence.
    """
    try:
        from glitch.tools.ollama_tools import vision_agent

        prompt = f"""Analyze this security camera image from {camera_location}.

Normal baseline for this camera: {baseline_description or "No baseline provided - describe what you see."}

Identify any anomalies or unusual elements:
1. Unexpected objects or vehicles
2. Unusual positions or behaviors
3. Changes from the described normal state
4. Anything that would warrant security attention

Return ONLY valid JSON:
{{
  "anomalies": [
    {{
      "description": "...",
      "location_in_frame": "...",
      "severity": "low|medium|high",
      "confidence": 0.0-1.0,
      "type": "object|person|vehicle|behavior|other"
    }}
  ],
  "overall_anomaly_score": 0.0-1.0,
  "scene_normal": true/false,
  "summary": "..."
}}"""

        result = await vision_agent.__wrapped__(
            image_url=current_snapshot,
            prompt=prompt,
        ) if hasattr(vision_agent, "__wrapped__") else str(
            vision_agent(image_url=current_snapshot, prompt=prompt)
        )

        import re
        json_match = re.search(r"\{.*\}", str(result), re.DOTALL)
        if json_match:
            return json_match.group(0)
        return str(result)
    except Exception as e:
        logger.error(f"protect_detect_anomalies error: {e}")
        return f"Error: {e}"


# ============================================================
# GROUP 5: Heatmap (3 tools)
# ============================================================

@tool
async def protect_get_heatmap(camera_id: str, timeframe: str = "24h") -> str:
    """Get motion heatmap for a camera.

    Args:
        camera_id: Camera ID
        timeframe: Timeframe (1h, 6h, 24h, 7d)

    Returns:
        Heatmap data or image URL.
    """
    return json.dumps({
        "status": "not_available",
        "message": "Heatmap API availability depends on Protect version. "
                   "Use protect_get_events with motion type to reconstruct motion patterns.",
        "camera_id": camera_id,
        "timeframe": timeframe,
    })


@tool
async def protect_get_baseline_heatmap(camera_id: str, time_context: str = "{}") -> str:
    """Get baseline heatmap for a camera/time context.

    Args:
        camera_id: Camera ID
        time_context: JSON with hour_of_day and day_of_week

    Returns:
        Baseline heatmap data or description.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        ctx = json.loads(time_context) if isinstance(time_context, str) else time_context
        hour = ctx.get("hour_of_day", datetime.now().hour)
        dow = ctx.get("day_of_week", datetime.now().weekday())

        baseline = await protect_db.get_baseline(camera_id, hour, dow)

        return json.dumps({
            "camera_id": camera_id,
            "time_context": ctx,
            "baseline": baseline,
            "note": "Baseline heatmap derived from event patterns, not raw pixel heatmap",
        }, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_compare_heatmaps(
    current_data: str,
    baseline_data: str,
) -> str:
    """Compare current activity patterns to baseline.

    Args:
        current_data: JSON current activity data
        baseline_data: JSON baseline activity data

    Returns:
        JSON with anomaly zones, overall deviation, and recommendations.
    """
    try:
        current = json.loads(current_data) if isinstance(current_data, str) else current_data
        baseline = json.loads(baseline_data) if isinstance(baseline_data, str) else baseline_data

        current_freq = current.get("frequency", 0) if current else 0
        baseline_freq = baseline.get("frequency", 0) if baseline else 0

        if baseline_freq > 0:
            deviation = abs(current_freq - baseline_freq) / baseline_freq
        else:
            deviation = 1.0 if current_freq > 0 else 0.0

        return json.dumps({
            "overall_deviation": round(deviation, 3),
            "current_frequency": current_freq,
            "baseline_frequency": baseline_freq,
            "anomaly_zones": [
                {
                    "description": "Activity level deviation",
                    "confidence": min(1.0, deviation),
                }
            ] if deviation > 0.5 else [],
            "assessment": "anomalous" if deviation > 0.5 else "normal",
        })
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 6: Workflow Orchestration (4 tools)
# ============================================================

@tool
async def protect_start_monitoring(
    camera_ids: str,
    check_interval: float = 2.0,
    alert_profile: str = "balanced",
) -> str:
    """Start real-time event monitoring for specified cameras.

    Args:
        camera_ids: Comma-separated camera IDs to monitor
        check_interval: Polling interval in seconds (default 2.0)
        alert_profile: Alert sensitivity profile (paranoid, balanced, relaxed)

    Returns:
        Monitoring started confirmation with status.
    """
    from sentinel.protect.config import is_protect_configured
    if not is_protect_configured():
        return _not_configured_msg()

    try:
        cam_list = [c.strip() for c in camera_ids.split(",")]
        processor = _get_processor()
        await processor.start(cam_list, check_interval, alert_profile)

        return json.dumps({
            "status": "started",
            "cameras": cam_list,
            "check_interval": check_interval,
            "alert_profile": alert_profile,
            "workers": 3,
        })
    except Exception as e:
        logger.error(f"protect_start_monitoring error: {e}")
        return f"Error: {e}"


@tool
async def protect_stop_monitoring(camera_ids: Optional[str] = None) -> str:
    """Stop real-time event monitoring.

    Args:
        camera_ids: Comma-separated camera IDs to stop (omit for all)

    Returns:
        Monitoring stopped confirmation.
    """
    try:
        processor = _get_processor()
        if processor._running:
            await processor.stop()
            return json.dumps({"status": "stopped", "cameras": camera_ids or "all"})
        return json.dumps({"status": "not_running"})
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_get_monitoring_status() -> str:
    """Get current monitoring status.

    Returns:
        JSON with running state, cameras, queue depth, events/min, and worker count.
    """
    try:
        processor = _get_processor()
        status = processor.get_status()
        return json.dumps(status, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_manual_review(
    camera_id: str,
    start_time: str,
    end_time: str,
    generate_summary: bool = True,
) -> str:
    """Manually review events for a camera in a time range.

    Args:
        camera_id: Camera ID to review
        start_time: ISO 8601 start time
        end_time: ISO 8601 end time
        generate_summary: Whether to generate an AI summary

    Returns:
        Event summary with notable patterns and threshold suggestions.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        start_dt = datetime.fromisoformat(start_time)
        end_dt = datetime.fromisoformat(end_time)

        events = await protect_db.query_events(
            camera_id=camera_id,
            start_time=start_dt,
            end_time=end_dt,
            limit=500,
        )

        entity_types = {}
        anomaly_scores = []
        for ev in events:
            et = ev.get("entity_type", "unknown")
            entity_types[et] = entity_types.get(et, 0) + 1
            if ev.get("anomaly_score"):
                anomaly_scores.append(ev["anomaly_score"])

        avg_anomaly = sum(anomaly_scores) / len(anomaly_scores) if anomaly_scores else 0
        high_anomaly = sum(1 for s in anomaly_scores if s > 0.7)

        return json.dumps({
            "camera_id": camera_id,
            "time_range": {"start": start_time, "end": end_time},
            "total_events": len(events),
            "entity_type_breakdown": entity_types,
            "anomaly_stats": {
                "average_score": round(avg_anomaly, 3),
                "high_anomaly_count": high_anomaly,
                "max_score": max(anomaly_scores) if anomaly_scores else 0,
            },
            "summary": f"{len(events)} events: {entity_types}. {high_anomaly} high-anomaly events.",
            "threshold_suggestion": round(avg_anomaly + 0.2, 2) if avg_anomaly > 0 else 0.5,
        }, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 7: Learning & Feedback (3 tools)
# ============================================================

@tool
async def protect_mark_false_positive(
    event_id: str,
    reason: Optional[str] = None,
) -> str:
    """Mark an event as a false positive alert.

    Args:
        event_id: Event ID to mark as false positive
        reason: Optional reason (e.g., "known delivery truck", "neighbor's car")

    Returns:
        Updated event confirmation and pattern adjustment summary.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        event = await protect_db.get_event(event_id)
        if not event:
            return f"Event {event_id} not found"

        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE alerts
                SET user_response = 'false_positive', response_timestamp = NOW()
                WHERE event_id = $1
                """,
                event_id,
            )

        return json.dumps({
            "status": "marked_false_positive",
            "event_id": event_id,
            "reason": reason,
            "recommendation": "Run skill_learn_from_false_positives to apply corrections",
        })
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_mark_missed_event(
    camera_id: str,
    timestamp: str,
    description: str,
) -> str:
    """Flag a missed event that should have triggered an alert.

    Args:
        camera_id: Camera where event occurred
        timestamp: ISO 8601 timestamp of missed event
        description: Description of what was missed

    Returns:
        Flagged event confirmation and sensitivity adjustment suggestion.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        event_id = f"missed_{uuid.uuid4().hex[:8]}"
        ts_dt = datetime.fromisoformat(timestamp)

        await protect_db.insert_event(
            event_id=event_id,
            camera_id=camera_id,
            timestamp=ts_dt,
            metadata={"missed_event": True, "description": description, "user_flagged": True},
        )

        return json.dumps({
            "status": "flagged",
            "event_id": event_id,
            "camera_id": camera_id,
            "description": description,
            "recommendation": "Consider lowering min_anomaly_score for this camera via protect_update_alert_preferences",
        })
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_retrain_patterns(
    lookback_period: str = "30d",
    focus_areas: Optional[str] = None,
) -> str:
    """Recompute baselines and patterns from historical data.

    Args:
        lookback_period: Period to analyze (e.g., 7d, 30d, 90d)
        focus_areas: Comma-separated camera IDs to focus on (omit for all)

    Returns:
        Retraining results with updated pattern counts.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        days = int(lookback_period.rstrip("d"))
        start_dt = datetime.now() - timedelta(days=days)

        cameras = await protect_db.list_cameras()
        focus_list = [c.strip() for c in focus_areas.split(",")] if focus_areas else None
        if focus_list:
            cameras = [c for c in cameras if c["camera_id"] in focus_list]

        updated_patterns = 0
        for camera in cameras:
            cam_id = camera["camera_id"]
            events = await protect_db.query_events(
                camera_id=cam_id,
                start_time=start_dt,
                limit=10000,
            )

            # Aggregate by hour and day_of_week
            hourly: Dict[str, int] = {}
            for ev in events:
                ts = ev.get("timestamp")
                if isinstance(ts, datetime):
                    key = f"{ts.hour}_{ts.weekday()}"
                    hourly[key] = hourly.get(key, 0) + 1

            for key, count in hourly.items():
                hour, dow = map(int, key.split("_"))
                await protect_db.insert_pattern(
                    camera_id=cam_id,
                    entity_id=None,
                    entity_type="baseline",
                    time_pattern={"hour_of_day": hour, "day_of_week": dow},
                    frequency=count / days,
                    confidence=min(0.9, days / 30),
                    pattern_type="baseline_traffic",
                )
                updated_patterns += 1

        return json.dumps({
            "status": "completed",
            "lookback_period": lookback_period,
            "cameras_processed": len(cameras),
            "patterns_updated": updated_patterns,
        })
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 8: Adaptive Alerting (3 tools)
# ============================================================

@tool
async def protect_snooze_entity(entity_id: str, duration_hours: float = 24.0) -> str:
    """Snooze alerts for a specific entity.

    Args:
        entity_id: Entity ID to snooze
        duration_hours: Snooze duration in hours (default 24)

    Returns:
        Suppression created confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        suppressed_until = datetime.now() + timedelta(hours=duration_hours)
        await protect_db.upsert_suppression(
            entity_id=entity_id,
            camera_id=None,
            suppressed_until=suppressed_until,
            reason=f"Snoozed for {duration_hours}h",
        )

        return json.dumps({
            "status": "snoozed",
            "entity_id": entity_id,
            "suppressed_until": suppressed_until.isoformat(),
            "duration_hours": duration_hours,
        })
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_group_similar_alerts(event_ids: str) -> str:
    """Group similar alerts into a single summary.

    Args:
        event_ids: Comma-separated event IDs to group

    Returns:
        Single grouped alert summary.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        ids = [e.strip() for e in event_ids.split(",")]
        events = []
        for eid in ids:
            ev = await protect_db.get_event(eid)
            if ev:
                events.append(ev)

        if not events:
            return "No events found"

        cameras = list(set(ev.get("camera_id", "") for ev in events))
        types = list(set(ev.get("entity_type", "") for ev in events))
        timestamps = [str(ev.get("timestamp", "")) for ev in events]

        return json.dumps({
            "grouped_event_ids": ids,
            "event_count": len(events),
            "cameras": cameras,
            "entity_types": types,
            "time_range": {
                "first": min(timestamps),
                "last": max(timestamps),
            },
            "summary": f"{len(events)} similar events across {len(cameras)} camera(s): {', '.join(types)}",
        }, indent=2)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_tune_camera_sensitivity(
    camera_id: str,
    adjustment: str,
) -> str:
    """Tune camera alert sensitivity.

    Args:
        camera_id: Camera ID to tune
        adjustment: Adjustment direction (more_sensitive, less_sensitive)

    Returns:
        Updated threshold confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        prefs = await protect_db.get_alert_preferences(camera_id)
        current = prefs.get("min_anomaly_score", 0.5)

        if adjustment == "more_sensitive":
            new_threshold = max(0.1, current - 0.1)
        elif adjustment == "less_sensitive":
            new_threshold = min(0.95, current + 0.1)
        else:
            return f"Invalid adjustment: {adjustment}. Use 'more_sensitive' or 'less_sensitive'"

        await protect_db.upsert_alert_preferences(
            camera_id=camera_id,
            min_anomaly_score=new_threshold,
        )

        return json.dumps({
            "status": "updated",
            "camera_id": camera_id,
            "old_threshold": current,
            "new_threshold": new_threshold,
            "adjustment": adjustment,
        })
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 9: Entity Management (4 tools)
# ============================================================

@tool
async def protect_register_entity(
    entity_type: str,
    features: str,
    label: Optional[str] = None,
    trust_level: str = "unknown",
) -> str:
    """Register a new entity in the database.

    Args:
        entity_type: Entity type (vehicle, person, face)
        features: JSON string with entity features (plate, color, make_model, etc.)
        label: Optional human-readable label (e.g., "John's Tesla")
        trust_level: Initial trust level (trusted, neutral, unknown, suspicious, hostile)

    Returns:
        New entity_id confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        feat = json.loads(features) if isinstance(features, str) else features
        entity_id = f"{entity_type[:3]}_{uuid.uuid4().hex[:12]}"

        await protect_db.insert_entity(
            entity_id=entity_id,
            entity_type=entity_type,
            trust_level=trust_level,
            label=label,
            plate_text=feat.get("plate_text") or feat.get("plate", {}).get("text"),
            plate_state=feat.get("plate_state") or feat.get("plate", {}).get("state"),
            vehicle_color=feat.get("vehicle_color") or feat.get("color", {}).get("primary"),
            vehicle_make_model=feat.get("vehicle_make_model") or feat.get("make_model", {}).get("make"),
            metadata=feat,
        )

        return json.dumps({
            "status": "registered",
            "entity_id": entity_id,
            "entity_type": entity_type,
            "trust_level": trust_level,
            "label": label,
        })
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_classify_entity(
    entity_id: str,
    role: str,
    reason: Optional[str] = None,
) -> str:
    """Classify an entity's role.

    Args:
        entity_id: Entity ID to classify
        role: Role (resident, neighbor, delivery, service, guest, suspicious, hostile, passerby)
        reason: Optional reason for classification

    Returns:
        Updated entity confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "UPDATE entities SET role = $2, updated_at = NOW() WHERE entity_id = $1",
                entity_id, role,
            )
            await conn.execute(
                """
                INSERT INTO entity_audit_log (entity_id, action, actor, old_values, new_values)
                VALUES ($1, 'role_classified', 'user',
                        '{}'::jsonb,
                        jsonb_build_object('role', $2::text, 'reason', $3::text))
                """,
                entity_id, role, reason or "",
            )

        # Auto-update trust level based on role
        trust_map = {
            "resident": "trusted",
            "neighbor": "trusted",
            "delivery": "neutral",
            "service": "neutral",
            "guest": "neutral",
            "passerby": "neutral",
            "suspicious": "suspicious",
            "hostile": "hostile",
        }
        if role in trust_map:
            await protect_db.update_entity_trust(entity_id, trust_map[role], "system", f"role={role}")

        return json.dumps({
            "status": "classified",
            "entity_id": entity_id,
            "role": role,
            "trust_level": trust_map.get(role, "unknown"),
        })
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_search_entities(
    query: str,
    entity_type: Optional[str] = None,
    timeframe: Optional[str] = None,
    limit: int = 10,
) -> str:
    """Search entities by plate, vehicle description, or person description.

    Args:
        query: Search query (plate text, vehicle description, person description)
        entity_type: Filter by type (vehicle, person, face)
        timeframe: Limit to entities seen in timeframe (e.g., 7d, 30d)
        limit: Maximum results

    Returns:
        JSON list of matching entities with sighting history.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        # Try plate search first
        results = await protect_db.search_entities_by_plate(query, similarity_threshold=0.4)

        if not results:
            # Fall back to metadata text search
            pool = await protect_db.get_pool()
            async with pool.acquire() as conn:
                conditions = ["metadata::text ILIKE $1"]
                params: List[Any] = [f"%{query}%"]
                idx = 2

                if entity_type:
                    conditions.append(f"type = ${idx}")
                    params.append(entity_type)
                    idx += 1

                if timeframe:
                    days = int(timeframe.rstrip("d"))
                    conditions.append(f"last_seen > NOW() - (${idx} || ' days')::interval")
                    params.append(str(days))
                    idx += 1

                params.append(limit)
                sql = (
                    f"SELECT * FROM entities WHERE {' AND '.join(conditions)} "
                    f"ORDER BY last_seen DESC LIMIT ${idx}"
                )
                rows = await conn.fetch(sql, *params)
                results = [dict(r) for r in rows]

        return json.dumps({
            "query": query,
            "results": results[:limit],
            "count": len(results),
        }, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_get_entity_dossier(entity_id: str) -> str:
    """Get a full profile for an entity.

    Args:
        entity_id: Entity ID

    Returns:
        JSON with identifiers, sightings, patterns, trust history, and notes.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        entity = await protect_db.get_entity(entity_id)
        if not entity:
            return f"Entity {entity_id} not found"

        sightings = await protect_db.query_sightings(entity_id, limit=50)
        patterns = await protect_db.query_patterns(entity_id=entity_id)

        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            alerts = await conn.fetch(
                "SELECT * FROM alerts WHERE entity_id = $1 ORDER BY timestamp DESC LIMIT 20",
                entity_id,
            )
            audit = await conn.fetch(
                "SELECT * FROM entity_audit_log WHERE entity_id = $1 ORDER BY timestamp DESC LIMIT 20",
                entity_id,
            )

        return json.dumps({
            "entity": entity,
            "sightings_summary": {
                "total": entity.get("sightings_count", 0),
                "recent_50": sightings,
            },
            "patterns": patterns,
            "alerts": [dict(a) for a in alerts],
            "audit_log": [dict(a) for a in audit],
        }, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 10: Cross-Camera Tracking (2 tools)
# ============================================================

@tool
async def protect_track_entity(
    entity_id: str,
    origin_camera: Optional[str] = None,
    origin_time: Optional[str] = None,
    lookback_hours: float = 4.0,
) -> str:
    """Track an entity's movement across cameras.

    Args:
        entity_id: Entity ID to track
        origin_camera: Starting camera ID (optional)
        origin_time: ISO 8601 starting time (optional)
        lookback_hours: How many hours back to look (default 4)

    Returns:
        JSON with trajectory, dwell times, and tracking quality.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db
        from sentinel.protect.tracking import build_movement_path, format_path_summary

        start_time = datetime.now() - timedelta(hours=lookback_hours)
        if origin_time:
            start_time = datetime.fromisoformat(origin_time) - timedelta(hours=1)

        sightings = await protect_db.query_sightings(
            entity_id=entity_id,
            start_time=start_time,
            limit=200,
        )

        if not sightings:
            return json.dumps({
                "entity_id": entity_id,
                "status": "no_sightings",
                "message": f"No sightings found in the last {lookback_hours} hours",
            })

        movement_path = await build_movement_path(sightings)
        summary = format_path_summary(movement_path)

        return json.dumps({
            "entity_id": entity_id,
            "movement_path": movement_path,
            "summary": summary,
        }, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_configure_camera_topology(
    camera_pairs: str,
) -> str:
    """Configure camera adjacency topology for cross-camera tracking.

    Args:
        camera_pairs: JSON array of {camera_a, camera_b, distance_meters, typical_walk_seconds, typical_drive_seconds}

    Returns:
        Topology saved confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import tracking

        pairs = json.loads(camera_pairs) if isinstance(camera_pairs, str) else camera_pairs

        topology: Dict[str, Any] = {}
        for pair in pairs:
            cam_a = pair["camera_a"]
            cam_b = pair["camera_b"]
            walk_s = pair.get("typical_walk_seconds", pair.get("distance_meters", 10) / 1.4)
            drive_s = pair.get("typical_drive_seconds", pair.get("distance_meters", 10) / 8)

            if cam_a not in topology:
                topology[cam_a] = {"adjacent": [], "typical_transition_seconds": {}}
            if cam_b not in topology:
                topology[cam_b] = {"adjacent": [], "typical_transition_seconds": {}}

            topology[cam_a]["adjacent"].append(cam_b)
            topology[cam_b]["adjacent"].append(cam_a)
            topology[cam_a]["typical_transition_seconds"][cam_b] = walk_s
            topology[cam_b]["typical_transition_seconds"][cam_a] = walk_s

        tracking.set_topology(topology)

        # Persist to DB
        pool_fn = None
        try:
            from sentinel.protect import db as protect_db
            pool = await protect_db.get_pool()
            async with pool.acquire() as conn:
                for pair in pairs:
                    await conn.execute(
                        """
                        INSERT INTO camera_topology (camera_a, camera_b, distance_meters,
                                                     typical_walk_seconds, typical_drive_seconds)
                        VALUES ($1, $2, $3, $4, $5)
                        ON CONFLICT (camera_a, camera_b) DO UPDATE
                        SET distance_meters = $3, typical_walk_seconds = $4, typical_drive_seconds = $5
                        """,
                        pair["camera_a"], pair["camera_b"],
                        pair.get("distance_meters"),
                        pair.get("typical_walk_seconds"),
                        pair.get("typical_drive_seconds"),
                    )
        except Exception:
            pass

        return json.dumps({
            "status": "configured",
            "pairs_configured": len(pairs),
            "cameras_in_topology": list(topology.keys()),
        })
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 11: Threat Intelligence (4 tools)
# ============================================================

@tool
async def protect_import_hostile_list(
    file_path_or_url: str,
    format: str = "json",
) -> str:
    """Import a hostile entity list from a file or URL.

    Args:
        file_path_or_url: Path to JSON/CSV file or URL
        format: File format (json, csv)

    Returns:
        Import count and summary.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        import os
        from sentinel.protect import db as protect_db

        if file_path_or_url.startswith("http"):
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.get(file_path_or_url)
                content = response.text
        else:
            with open(file_path_or_url, "r") as f:
                content = f.read()

        if format == "json":
            entities_data = json.loads(content)
        else:
            import csv
            import io
            reader = csv.DictReader(io.StringIO(content))
            entities_data = list(reader)

        imported = 0
        for item in entities_data:
            entity_id = item.get("entity_id") or f"hostile_{uuid.uuid4().hex[:8]}"
            await protect_db.insert_entity(
                entity_id=entity_id,
                entity_type=item.get("type", "vehicle"),
                trust_level="hostile",
                label=item.get("label") or item.get("description"),
                plate_text=item.get("plate_text"),
                metadata=item,
            )
            imported += 1

        return json.dumps({"status": "imported", "count": imported})
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_export_hostile_list(format: str = "json") -> str:
    """Export all hostile entities.

    Args:
        format: Export format (json, csv)

    Returns:
        Hostile entity list in requested format.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM entities WHERE trust_level = 'hostile' ORDER BY updated_at DESC"
            )

        entities = [dict(r) for r in rows]

        if format == "csv":
            import csv
            import io
            output = io.StringIO()
            if entities:
                writer = csv.DictWriter(output, fieldnames=entities[0].keys())
                writer.writeheader()
                writer.writerows(entities)
            return output.getvalue()

        return json.dumps({"hostile_entities": entities, "count": len(entities)}, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_mark_entity_hostile(
    entity_id: str,
    reason: str,
    evidence_event_ids: Optional[str] = None,
) -> str:
    """Mark an entity as hostile.

    Args:
        entity_id: Entity ID to mark hostile
        reason: Reason for hostile classification
        evidence_event_ids: Comma-separated event IDs as evidence

    Returns:
        Entity flagged hostile confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        await protect_db.update_entity_trust(entity_id, "hostile", "user", reason)

        evidence = [e.strip() for e in evidence_event_ids.split(",")] if evidence_event_ids else []

        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO hostile_events (entity_id, triggers, severity, actions_taken)
                VALUES ($1, $2, 1.0, '["marked_hostile"]'::jsonb)
                """,
                entity_id, json.dumps([{"reason": reason, "evidence": evidence}]),
            )

        return json.dumps({
            "status": "marked_hostile",
            "entity_id": entity_id,
            "reason": reason,
            "evidence_events": evidence,
        })
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_clear_hostile_status(entity_id: str, reason: str) -> str:
    """Remove hostile flag from an entity.

    Args:
        entity_id: Entity ID to clear
        reason: Reason for clearing hostile status

    Returns:
        Hostile flag removed confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        await protect_db.update_entity_trust(entity_id, "unknown", "user", f"hostile_cleared: {reason}")

        return json.dumps({
            "status": "hostile_cleared",
            "entity_id": entity_id,
            "reason": reason,
            "new_trust_level": "unknown",
        })
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 12: Privacy & Retention (3 tools)
# ============================================================

@tool
async def protect_privacy_export_entity_data(entity_id: str) -> str:
    """Export all data for an entity (GDPR access request).

    Args:
        entity_id: Entity ID to export data for

    Returns:
        JSON with all entity data including sightings, patterns, alerts, and audit log.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect.privacy import export_entity_data
        data = await export_entity_data(entity_id)
        return json.dumps(data, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_privacy_delete_entity(entity_id: str, reason: str = "user_request") -> str:
    """Anonymize/delete all data for an entity (GDPR erasure request).

    Args:
        entity_id: Entity ID to delete
        reason: Reason for deletion

    Returns:
        Anonymization/deletion confirmation.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect.privacy import delete_entity_data
        result = await delete_entity_data(entity_id, reason)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_privacy_run_retention_cleanup() -> str:
    """Run automated data retention cleanup.

    Deletes expired snapshots, archives inactive unknown entities, and cleans old records
    per configured retention policy.

    Returns:
        Cleanup report with counts of deleted/archived records.
    """
    from sentinel.protect.config import is_db_configured, is_protect_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect.privacy import run_retention_cleanup
        from sentinel.protect.config import get_protect_config

        # Try to get retention config from SSM
        snapshots_days = 7
        video_days = 30
        unknown_entity_days = 90

        try:
            from sentinel.protect.config import _get_ssm_parameter
            s = _get_ssm_parameter("/glitch/protect/retention/snapshots_days")
            if s:
                snapshots_days = int(s)
            v = _get_ssm_parameter("/glitch/protect/retention/video_days")
            if v:
                video_days = int(v)
            u = _get_ssm_parameter("/glitch/protect/retention/unknown_entity_days")
            if u:
                unknown_entity_days = int(u)
        except Exception:
            pass

        result = await run_retention_cleanup(snapshots_days, video_days, unknown_entity_days)
        return json.dumps(result, indent=2)
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 13: Reporting (3 tools)
# ============================================================

@tool
async def protect_generate_report(
    start_date: str,
    end_date: str,
    camera_ids: Optional[str] = None,
) -> str:
    """Generate an event report for a date range.

    Args:
        start_date: ISO 8601 start date
        end_date: ISO 8601 end date
        camera_ids: Comma-separated camera IDs (omit for all)

    Returns:
        JSON report with event counts by type, top entities, and alert accuracy metrics.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        start_dt = datetime.fromisoformat(start_date)
        end_dt = datetime.fromisoformat(end_date)
        cam_list = [c.strip() for c in camera_ids.split(",")] if camera_ids else None

        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            # Event counts by type
            rows = await conn.fetch(
                """
                SELECT entity_type, COUNT(*) as count,
                       AVG(anomaly_score) as avg_anomaly
                FROM events
                WHERE timestamp BETWEEN $1 AND $2
                GROUP BY entity_type
                ORDER BY count DESC
                """,
                start_dt, end_dt,
            )
            event_counts = [dict(r) for r in rows]

            # Alert accuracy
            alert_row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_alerts,
                    COUNT(*) FILTER (WHERE user_response = 'false_positive') as fp_count,
                    COUNT(*) FILTER (WHERE user_response = 'acknowledged') as ack_count
                FROM alerts
                WHERE timestamp BETWEEN $1 AND $2
                """,
                start_dt, end_dt,
            )

            # Top entities
            top_entities = await conn.fetch(
                """
                SELECT e.entity_id, e.type, e.label, e.trust_level,
                       COUNT(es.sighting_id) as sighting_count
                FROM entities e
                JOIN entity_sightings es ON e.entity_id = es.entity_id
                WHERE es.timestamp BETWEEN $1 AND $2
                GROUP BY e.entity_id, e.type, e.label, e.trust_level
                ORDER BY sighting_count DESC
                LIMIT 10
                """,
                start_dt, end_dt,
            )

        total_alerts = alert_row["total_alerts"] if alert_row else 0
        fp_count = alert_row["fp_count"] if alert_row else 0
        fp_rate = fp_count / total_alerts if total_alerts > 0 else 0

        return json.dumps({
            "report_period": {"start": start_date, "end": end_date},
            "event_counts": event_counts,
            "alert_accuracy": {
                "total_alerts": total_alerts,
                "false_positives": fp_count,
                "fp_rate": round(fp_rate, 3),
                "acknowledged": alert_row["ack_count"] if alert_row else 0,
            },
            "top_entities": [dict(r) for r in top_entities],
        }, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_get_stats() -> str:
    """Get current Protect system statistics.

    Returns:
        JSON with events today, alerts sent, FP rate, and DB size.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

            events_today = await conn.fetchval(
                "SELECT COUNT(*) FROM events WHERE timestamp >= $1", today_start
            )
            alerts_today = await conn.fetchval(
                "SELECT COUNT(*) FROM alerts WHERE timestamp >= $1", today_start
            )
            fp_today = await conn.fetchval(
                """
                SELECT COUNT(*) FROM alerts
                WHERE timestamp >= $1 AND user_response = 'false_positive'
                """,
                today_start,
            )
            total_entities = await conn.fetchval("SELECT COUNT(*) FROM entities")
            hostile_entities = await conn.fetchval(
                "SELECT COUNT(*) FROM entities WHERE trust_level = 'hostile'"
            )

        fp_rate = fp_today / alerts_today if alerts_today > 0 else 0

        return json.dumps({
            "events_today": events_today,
            "alerts_today": alerts_today,
            "fp_today": fp_today,
            "fp_rate_today": round(fp_rate, 3),
            "total_entities": total_entities,
            "hostile_entities": hostile_entities,
            "monitoring": _get_processor().get_status() if _monitoring_processor else {"running": False},
        }, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_generate_performance_report() -> str:
    """Generate a performance report for the Protect integration.

    Returns:
        JSON with recognition accuracy, alert accuracy, throughput, and queue depth.
    """
    from sentinel.protect.config import is_db_configured
    if not is_db_configured():
        return _db_not_configured_msg()

    try:
        from sentinel.protect import db as protect_db

        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            week_start = datetime.now() - timedelta(days=7)

            # Processing stats
            processed = await conn.fetchval(
                "SELECT COUNT(*) FROM events WHERE processed = TRUE AND timestamp >= $1",
                week_start,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM events WHERE timestamp >= $1", week_start
            )
            avg_anomaly = await conn.fetchval(
                "SELECT AVG(anomaly_score) FROM events WHERE timestamp >= $1 AND processed = TRUE",
                week_start,
            )

            # Alert accuracy
            alert_stats = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE user_response = 'false_positive') as fp,
                    COUNT(*) FILTER (WHERE user_response = 'acknowledged') as ack
                FROM alerts WHERE timestamp >= $1
                """,
                week_start,
            )

        processor_status = _get_processor().get_status() if _monitoring_processor else {}

        return json.dumps({
            "period": "last_7_days",
            "event_processing": {
                "total_events": total,
                "processed_events": processed,
                "processing_rate": round(processed / total, 3) if total > 0 else 0,
                "avg_anomaly_score": round(float(avg_anomaly or 0), 3),
            },
            "alert_accuracy": {
                "total_alerts": alert_stats["total"] if alert_stats else 0,
                "false_positives": alert_stats["fp"] if alert_stats else 0,
                "fp_rate": round(
                    (alert_stats["fp"] / alert_stats["total"]) if alert_stats and alert_stats["total"] > 0 else 0,
                    3,
                ),
            },
            "processor_status": processor_status,
        }, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# GROUP 14: Event Processing (2 tools)
# ============================================================

@tool
async def protect_process_event_async(event_data: str) -> str:
    """Enqueue an event for async processing.

    Args:
        event_data: JSON string with event data

    Returns:
        Queued confirmation or error.
    """
    try:
        event = json.loads(event_data) if isinstance(event_data, str) else event_data
        processor = _get_processor()
        queued = await processor.enqueue(event)

        return json.dumps({
            "status": "queued" if queued else "dropped",
            "event_id": event.get("id") or event.get("event_id", "unknown"),
            "queue_depth": processor._queue.qsize(),
        })
    except Exception as e:
        return f"Error: {e}"


@tool
async def protect_get_queue_status() -> str:
    """Get the event processing queue status.

    Returns:
        JSON with backlog depth, events/min, last processed, and worker count.
    """
    try:
        processor = _get_processor()
        status = processor.get_status()
        return json.dumps(status, indent=2, default=str)
    except Exception as e:
        return f"Error: {e}"


# ============================================================
# CORE (13): Essential daily surveillance loop
# ============================================================
# Covers the minimum required for the standard event-processing workflow:
#   get_events → get_snapshot → search_entities → register_entity /
#   store_observation → get_baseline → should_alert → send_telegram_alert →
#   record_alert, plus monitoring controls.

CORE_PROTECT_TOOLS = [
    # Group 1: Basic access
    protect_get_cameras,
    protect_get_events,
    protect_get_snapshot,
    # Group 2: Essential DB ops
    protect_db_store_observation,
    protect_db_get_baseline,
    protect_db_record_alert,
    # Group 3: Alert core
    protect_should_alert,
    protect_send_telegram_alert,
    # Group 6: Monitoring controls
    protect_start_monitoring,
    protect_stop_monitoring,
    protect_get_monitoring_status,
    # Group 9: Entity core
    protect_register_entity,
    protect_search_entities,
]

# ============================================================
# EXTENDED (35): Advanced entity mgmt, analytics, config, reporting
# ============================================================
# Load these in addition to CORE when the surveillance skill is active.

EXTENDED_PROTECT_TOOLS = [
    # Group 1: Video and camera config
    protect_get_video_clip,
    protect_update_camera_settings,
    # Group 2: Pattern analytics
    protect_db_query_patterns,
    protect_db_update_pattern,
    # Group 3: Alert intelligence
    protect_analyze_event,
    protect_get_alert_preferences,
    protect_update_alert_preferences,
    # Group 4: Vision
    protect_classify_snapshot,
    protect_detect_anomalies,
    # Group 5: Heatmaps
    protect_get_heatmap,
    protect_get_baseline_heatmap,
    protect_compare_heatmaps,
    # Group 6: Advanced workflow
    protect_manual_review,
    # Group 7: Learning
    protect_mark_false_positive,
    protect_mark_missed_event,
    protect_retrain_patterns,
    # Group 8: Adaptive alerting
    protect_snooze_entity,
    protect_group_similar_alerts,
    protect_tune_camera_sensitivity,
    # Group 9: Advanced entity mgmt
    protect_classify_entity,
    protect_get_entity_dossier,
    # Group 10: Cross-camera tracking
    protect_track_entity,
    protect_configure_camera_topology,
    # Group 11: Threat intelligence
    protect_import_hostile_list,
    protect_export_hostile_list,
    protect_mark_entity_hostile,
    protect_clear_hostile_status,
    # Group 12: Privacy & retention
    protect_privacy_export_entity_data,
    protect_privacy_delete_entity,
    protect_privacy_run_retention_cleanup,
    # Group 13: Reporting
    protect_generate_report,
    protect_get_stats,
    protect_generate_performance_report,
    # Group 14: Event processing
    protect_process_event_async,
    protect_get_queue_status,
]

# All 48 tools for backward compatibility
ALL_PROTECT_TOOLS = CORE_PROTECT_TOOLS + EXTENDED_PROTECT_TOOLS
