"""Phase 4: Investigation Skills.

Implements the 3 investigation skills:
- track_entity_across_cameras (movement path reconstruction)
- generate_entity_dossier (comprehensive entity report)
- forensic_timeline_search (time-window event reconstruction)
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# Cross-Camera Tracking
# ============================================================

async def track_entity_across_cameras(
    entity_id: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    origin_camera: Optional[str] = None,
) -> Dict[str, Any]:
    """Reconstruct entity movement path across cameras.

    Returns:
        Dict with movement_path, dwell_times, gaps, tracking_quality, and summary
    """
    from sentinel.protect import db as protect_db
    from sentinel.protect.tracking import build_movement_path, format_path_summary

    if start_time is None:
        start_time = datetime.now() - timedelta(hours=4)
    if end_time is None:
        end_time = datetime.now()

    sightings = await protect_db.query_sightings(
        entity_id=entity_id,
        start_time=start_time,
        end_time=end_time,
        limit=500,
    )

    if not sightings:
        return {
            "entity_id": entity_id,
            "status": "no_sightings",
            "time_range": {
                "start": start_time.isoformat(),
                "end": end_time.isoformat(),
            },
            "movement_path": None,
        }

    # Filter to origin camera if specified
    if origin_camera:
        origin_sightings = [s for s in sightings if s.get("camera_id") == origin_camera]
        if origin_sightings:
            # Start from first sighting at origin camera
            first_origin = min(origin_sightings, key=lambda s: s["timestamp"])
            sightings = [s for s in sightings if s["timestamp"] >= first_origin["timestamp"]]

    movement_path = await build_movement_path(sightings)
    summary = format_path_summary(movement_path)

    # Store track record
    if movement_path.get("total_waypoints", 0) >= 2:
        from sentinel.protect import db as protect_db
        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            track_id = str(uuid.uuid4())
            await conn.execute(
                """
                INSERT INTO entity_tracks (track_id, entity_id, start_time, end_time,
                                           cameras_visited, path_data, tracking_quality,
                                           gaps_count, total_duration_seconds)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                track_id, entity_id,
                start_time, end_time,
                movement_path.get("cameras_visited", []),
                json.dumps(movement_path),
                movement_path.get("tracking_quality", "unknown"),
                len(movement_path.get("gaps", [])),
                movement_path.get("total_tracking_duration", 0),
            )

    return {
        "entity_id": entity_id,
        "time_range": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
        },
        "movement_path": movement_path,
        "summary": summary,
        "sightings_analyzed": len(sightings),
    }


# ============================================================
# Entity Dossier
# ============================================================

async def generate_entity_dossier(entity_id: str) -> Dict[str, Any]:
    """Compile a comprehensive entity report.

    Includes: identity, activity summary, patterns, threat history,
    associations, movement paths, and audit trail.

    Returns:
        Structured dossier dict
    """
    from sentinel.protect import db as protect_db

    entity = await protect_db.get_entity(entity_id)
    if not entity:
        return {"error": f"Entity {entity_id} not found"}

    # Recent sightings (last 90 days)
    sightings_90d = await protect_db.query_sightings(
        entity_id,
        start_time=datetime.now() - timedelta(days=90),
        limit=500,
    )

    # Patterns
    patterns = await protect_db.query_patterns(entity_id=entity_id)

    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        # Alert history
        alerts = await conn.fetch(
            """
            SELECT * FROM alerts
            WHERE entity_id = $1
            ORDER BY timestamp DESC
            LIMIT 50
            """,
            entity_id,
        )

        # Threat assessments
        threats = await conn.fetch(
            """
            SELECT * FROM threat_assessments
            WHERE entity_id = $1
            ORDER BY timestamp DESC
            LIMIT 20
            """,
            entity_id,
        )

        # Hostile events
        hostile = await conn.fetch(
            "SELECT * FROM hostile_events WHERE entity_id = $1 ORDER BY timestamp DESC LIMIT 10",
            entity_id,
        )

        # Audit log
        audit = await conn.fetch(
            "SELECT * FROM entity_audit_log WHERE entity_id = $1 ORDER BY timestamp DESC LIMIT 30",
            entity_id,
        )

        # Movement tracks
        tracks = await conn.fetch(
            "SELECT * FROM entity_tracks WHERE entity_id = $1 ORDER BY start_time DESC LIMIT 10",
            entity_id,
        )

        # Associated entities (seen at same time/place)
        associated = await conn.fetch(
            """
            SELECT DISTINCT e2.entity_id, e2.type, e2.label, e2.trust_level,
                            COUNT(*) as co_occurrences
            FROM entity_sightings es1
            JOIN entity_sightings es2 ON es1.camera_id = es2.camera_id
                AND ABS(EXTRACT(EPOCH FROM (es1.timestamp - es2.timestamp))) < 300
                AND es2.entity_id != $1
            JOIN entities e2 ON es2.entity_id = e2.entity_id
            WHERE es1.entity_id = $1
            GROUP BY e2.entity_id, e2.type, e2.label, e2.trust_level
            ORDER BY co_occurrences DESC
            LIMIT 10
            """,
            entity_id,
        )

    # Activity summary
    cameras_visited = list(set(s.get("camera_id", "") for s in sightings_90d))
    alert_count = len(alerts)
    fp_count = sum(1 for a in alerts if a.get("user_response") == "false_positive")
    max_threat = max(
        (t.get("threat_score", 0) for t in threats), default=0
    )

    # Typical visit times
    if sightings_90d:
        hours = [s["timestamp"].hour for s in sightings_90d if isinstance(s.get("timestamp"), datetime)]
        typical_hour = round(sum(hours) / len(hours)) if hours else None
    else:
        typical_hour = None

    # Format identity section
    identity: Dict[str, Any] = {
        "entity_id": entity_id,
        "type": entity.get("type"),
        "label": entity.get("label"),
        "trust_level": entity.get("trust_level"),
        "role": entity.get("role"),
    }

    if entity.get("type") == "vehicle":
        identity["vehicle"] = {
            "plate_text": entity.get("plate_text"),
            "plate_state": entity.get("plate_state"),
            "color": entity.get("vehicle_color"),
            "make_model": entity.get("vehicle_make_model"),
        }

    face_desc = entity.get("metadata", {})
    if isinstance(face_desc, str):
        try:
            face_desc = json.loads(face_desc)
        except Exception:
            face_desc = {}
    if face_desc.get("face_description"):
        identity["face_description"] = face_desc["face_description"]

    return {
        "identity": identity,
        "activity_summary": {
            "first_seen": str(entity.get("first_seen", "")),
            "last_seen": str(entity.get("last_seen", "")),
            "total_sightings": entity.get("sightings_count", 0),
            "sightings_last_90d": len(sightings_90d),
            "cameras_visited": cameras_visited,
            "typical_visit_hour": typical_hour,
            "total_alerts": alert_count,
            "false_positives": fp_count,
            "max_threat_score": round(max_threat, 3),
        },
        "patterns": patterns,
        "threat_history": {
            "assessments": [dict(t) for t in threats],
            "hostile_events": [dict(h) for h in hostile],
            "max_threat_score": round(max_threat, 3),
        },
        "associations": [dict(a) for a in associated],
        "movement_tracks": [dict(t) for t in tracks],
        "recent_alerts": [dict(a) for a in alerts[:10]],
        "audit_log": [dict(a) for a in audit[:20]],
        "generated_at": datetime.now().isoformat(),
    }


# ============================================================
# Forensic Timeline Search
# ============================================================

async def forensic_timeline_search(
    start_time: datetime,
    end_time: datetime,
    camera_ids: Optional[List[str]] = None,
    entity_ids: Optional[List[str]] = None,
    min_anomaly_score: float = 0.0,
) -> Dict[str, Any]:
    """Reconstruct a detailed timeline of events in a time window.

    Returns:
        Chronological event list with entity context, anomaly scores, and evidence
    """
    from sentinel.protect import db as protect_db

    events = await protect_db.query_events(
        start_time=start_time,
        end_time=end_time,
        min_anomaly_score=min_anomaly_score,
        limit=1000,
    )

    if camera_ids:
        events = [ev for ev in events if ev.get("camera_id") in camera_ids]

    # Enrich each event with entity context
    timeline_entries = []
    entity_cache: Dict[str, Optional[Dict]] = {}

    for ev in sorted(events, key=lambda e: e.get("timestamp", datetime.min)):
        event_id = ev["event_id"]
        ts = ev.get("timestamp")

        # Get entity sightings for this event
        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            sightings = await conn.fetch(
                "SELECT * FROM entity_sightings WHERE event_id = $1", event_id
            )
            alerts_for_event = await conn.fetch(
                "SELECT * FROM alerts WHERE event_id = $1", event_id
            )
            threats_for_event = await conn.fetch(
                "SELECT * FROM threat_assessments WHERE event_id = $1", event_id
            )

        entities_in_event = []
        for s in sightings:
            eid = s["entity_id"]
            if eid:
                if eid not in entity_cache:
                    entity_cache[eid] = await protect_db.get_entity(eid)
                entity = entity_cache[eid]
                if entity:
                    if entity_ids and eid not in entity_ids:
                        continue
                    entities_in_event.append({
                        "entity_id": eid,
                        "type": entity.get("type"),
                        "label": entity.get("label"),
                        "trust_level": entity.get("trust_level"),
                        "role": entity.get("role"),
                    })

        entry = {
            "timestamp": ts.isoformat() if isinstance(ts, datetime) else str(ts),
            "event_id": event_id,
            "camera_id": ev.get("camera_id"),
            "entity_type": ev.get("entity_type"),
            "anomaly_score": ev.get("anomaly_score", 0),
            "entities": entities_in_event,
            "alerts": [dict(a) for a in alerts_for_event],
            "threat_assessments": [dict(t) for t in threats_for_event],
            "snapshot_url": ev.get("snapshot_url"),
            "classifications": ev.get("classifications", {}),
        }
        timeline_entries.append(entry)

    # Summary statistics
    total_events = len(timeline_entries)
    high_anomaly = sum(1 for e in timeline_entries if e.get("anomaly_score", 0) >= 0.7)
    unique_entities = set()
    for e in timeline_entries:
        for ent in e.get("entities", []):
            unique_entities.add(ent["entity_id"])

    cameras_active = set(e.get("camera_id") for e in timeline_entries if e.get("camera_id"))

    # Key moments: first appearance, peak activity, last event
    key_moments = []
    if timeline_entries:
        key_moments.append({
            "type": "first_event",
            "timestamp": timeline_entries[0]["timestamp"],
            "description": f"First event: {timeline_entries[0].get('entity_type')} on {timeline_entries[0].get('camera_id')}",
        })

        # Find peak activity (5-min window with most events)
        if len(timeline_entries) > 5:
            max_window = 0
            peak_ts = None
            for i, entry in enumerate(timeline_entries):
                ts_i = datetime.fromisoformat(entry["timestamp"]) if isinstance(entry["timestamp"], str) else entry["timestamp"]
                window_count = sum(
                    1 for e2 in timeline_entries
                    if abs((datetime.fromisoformat(e2["timestamp"]) if isinstance(e2["timestamp"], str) else e2["timestamp"] - ts_i).total_seconds()) <= 300
                )
                if window_count > max_window:
                    max_window = window_count
                    peak_ts = entry["timestamp"]

            if peak_ts:
                key_moments.append({
                    "type": "peak_activity",
                    "timestamp": peak_ts,
                    "description": f"Peak activity: {max_window} events in 5-min window",
                })

        key_moments.append({
            "type": "last_event",
            "timestamp": timeline_entries[-1]["timestamp"],
            "description": f"Last event: {timeline_entries[-1].get('entity_type')} on {timeline_entries[-1].get('camera_id')}",
        })

    return {
        "time_range": {
            "start": start_time.isoformat(),
            "end": end_time.isoformat(),
            "duration_minutes": round((end_time - start_time).total_seconds() / 60, 1),
        },
        "summary": {
            "total_events": total_events,
            "high_anomaly_events": high_anomaly,
            "unique_entities": len(unique_entities),
            "cameras_active": list(cameras_active),
            "entity_ids": list(unique_entities),
        },
        "key_moments": key_moments,
        "timeline": timeline_entries,
        "generated_at": datetime.now().isoformat(),
    }
