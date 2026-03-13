"""Protect Query Lambda — direct Postgres reader for the UI Protect tab.

Bypasses both LLMs entirely for the /api/protect/* structured-data endpoints,
reducing response latency from ~5-10s to <500ms.

Routes:
    GET /api/protect/summary   → entities_total, events_24h, alerts_unack, cameras_online/total
    GET /api/protect/cameras   → ?limit=N  (default 20)
    GET /api/protect/entities  → ?limit=N  (default 50)
    GET /api/protect/events    → ?hours=N&days=N&limit=N  (default 24h, 30 events)
    GET /api/protect/patrols   → ?hours=N&limit=N  (default 24h, 50 patrols)
    GET /api/protect/alerts    → ?limit=N&unack_only=true  (default 20)
    GET /api/protect/patterns  → ?limit=N  (default 20)
    GET /api/protect/health    → sentinel/protect system health

Connection: RDS IAM authentication via boto3 generate_db_auth_token.
The IAM token is generated locally (no network call) and used as the Postgres password.
SSL is required for RDS IAM auth.
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_REGION = os.environ.get('AWS_REGION', 'us-west-2')
PROTECT_DB_HOST = os.environ['PROTECT_DB_HOST']
PROTECT_DB_PORT = int(os.environ.get('PROTECT_DB_PORT', '5432'))
PROTECT_DB_NAME = os.environ.get('PROTECT_DB_NAME', 'glitch_protect')
PROTECT_DB_USER = os.environ.get('PROTECT_DB_USER', 'glitch_iam')

_rds_client = boto3.client('rds', region_name=_REGION)
_conn = None  # pg8000 connection, reused on warm invocations


def _get_connection():
    """Return a pg8000 connection, creating one if needed."""
    global _conn
    import pg8000.native as pg  # noqa: PLC0415

    if _conn is not None:
        # Health-check the existing connection; replace on failure.
        try:
            _conn.run("SELECT 1")
            return _conn
        except Exception:
            try:
                _conn.close()
            except Exception:
                pass
            _conn = None

    token = _rds_client.generate_db_auth_token(
        DBHostname=PROTECT_DB_HOST,
        Port=PROTECT_DB_PORT,
        DBUsername=PROTECT_DB_USER,
    )
    _conn = pg.Connection(
        user=PROTECT_DB_USER,
        password=token,
        host=PROTECT_DB_HOST,
        port=PROTECT_DB_PORT,
        database=PROTECT_DB_NAME,
        ssl_context=True,
    )
    return _conn


def _iso(val) -> Optional[str]:
    """Convert datetime to ISO-8601 string, pass through strings, None → None."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.isoformat()
    return str(val)


# ---------------------------------------------------------------------------
# Auri memory action handlers (invoked directly via lambda:InvokeFunction,
# not via the HTTP path routing used by the gateway).
#
# Caller (auri_memory.py in PUBLIC mode) generates the embedding via Bedrock,
# then invokes this Lambda to handle the actual RDS read/write inside the VPC.
# ---------------------------------------------------------------------------

def action_auri_memory_store(conn, event):
    import uuid as _uuid
    content = event.get("content", "")
    embedding = event.get("embedding", [])
    session_id = event.get("session_id", "")
    source = event.get("source", "agent")
    metadata = event.get("metadata", {})
    if not content or not embedding:
        return {"statusCode": 400, "error": "content and embedding required"}
    vec_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
    conn.run(
        """
        INSERT INTO auri_memory
            (memory_id, content, embedding, session_id, source, metadata)
        VALUES (:mem_id, :content, :vec::vector, :session_id, :source, :metadata)
        """,
        mem_id=str(_uuid.uuid4()),
        content=content,
        vec=vec_str,
        session_id=session_id or "",
        source=source,
        metadata=json.dumps(metadata or {}),
    )
    logger.info("auri_memory: stored (source=%s, len=%d)", source, len(content))
    return {"statusCode": 200, "result": "ok"}


def action_auri_memory_search(conn, event):
    embedding = event.get("embedding", [])
    k = max(1, min(int(event.get("k", 5)), 20))
    if not embedding:
        return {"statusCode": 400, "error": "embedding required"}
    vec_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
    rows = conn.run(
        "SELECT content FROM auri_memory ORDER BY embedding <=> :vec::vector LIMIT :k",
        vec=vec_str,
        k=k,
    )
    return {"statusCode": 200, "memories": [r[0] for r in rows]}


def action_auri_memory_search_filtered(conn, event):
    """Search auri_memory with optional metadata filters (memory_type, participant_id)."""
    embedding = event.get("embedding", [])
    k = max(1, min(int(event.get("k", 5)), 20))
    memory_type = event.get("memory_type", "")
    participant_id = event.get("participant_id", "")
    if not embedding:
        return {"statusCode": 400, "error": "embedding required"}
    vec_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"

    # Build WHERE clause based on provided filters
    conditions = []
    params = {"vec": vec_str, "k": k}
    if memory_type:
        conditions.append("metadata->>'memory_type' = :mtype")
        params["mtype"] = memory_type
    if participant_id:
        conditions.append("metadata->>'participant_id' = :pid")
        params["pid"] = participant_id

    where = ""
    if conditions:
        where = "WHERE " + " AND ".join(conditions)

    rows = conn.run(
        f"SELECT content, metadata FROM auri_memory {where} ORDER BY embedding <=> :vec::vector LIMIT :k",
        **params,
    )
    return {
        "statusCode": 200,
        "memories": [{"content": r[0], "metadata": r[1]} for r in rows],
    }


def action_auri_participant_upsert(conn, event):
    """Upsert a participant profile — one canonical profile per participant_id.

    Deletes any existing profile for this participant, then inserts the new one.
    """
    import uuid as _uuid
    participant_id = event.get("participant_id", "")
    content = event.get("content", "")
    embedding = event.get("embedding", [])
    if not participant_id or not content or not embedding:
        return {"statusCode": 400, "error": "participant_id, content, and embedding required"}
    vec_str = "[" + ",".join(str(float(x)) for x in embedding) + "]"
    metadata = json.dumps({
        "memory_type": "participant_profile",
        "participant_id": participant_id,
    })
    # Delete existing profile(s) for this participant
    conn.run(
        """
        DELETE FROM auri_memory
        WHERE metadata->>'memory_type' = 'participant_profile'
          AND metadata->>'participant_id' = :pid
        """,
        pid=participant_id,
    )
    # Insert new profile
    conn.run(
        """
        INSERT INTO auri_memory
            (memory_id, content, embedding, session_id, source, metadata)
        VALUES (:mem_id, :content, :vec::vector, '', 'participant_profile', :metadata)
        """,
        mem_id=str(_uuid.uuid4()),
        content=content,
        vec=vec_str,
        metadata=metadata,
    )
    logger.info("auri_memory: upserted participant profile for %s (%d chars)", participant_id, len(content))
    return {"statusCode": 200, "result": "ok", "participant_id": participant_id}


# ---------------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------------

def query_summary(conn) -> Dict[str, int]:
    rows = conn.run("""
        SELECT
            (SELECT COUNT(*) FROM entities) AS entities_total,
            (SELECT COUNT(*) FROM events
             WHERE timestamp > NOW() - INTERVAL '24 hours') AS events_24h,
            (SELECT COUNT(*) FROM alerts
             WHERE user_response IS NULL) AS alerts_unack,
            (SELECT COUNT(*) FROM cameras) AS cameras_total,
            (SELECT COUNT(*) FROM cameras
             WHERE state = 'CONNECTED') AS cameras_online
    """)
    if rows:
        return {
            "entities_total": int(rows[0][0] or 0),
            "events_24h":     int(rows[0][1] or 0),
            "alerts_unack":   int(rows[0][2] or 0),
            "cameras_total":  int(rows[0][3] or 0),
            "cameras_online": int(rows[0][4] or 0),
        }
    return {"entities_total": 0, "events_24h": 0, "alerts_unack": 0, "cameras_total": 0, "cameras_online": 0}


def query_entities(conn, limit: int) -> Dict[str, Any]:
    limit = max(1, min(limit, 100))
    rows = conn.run(
        """
        SELECT entity_id, type, label, trust_level, role,
               first_seen, last_seen, sightings_count,
               plate_text, vehicle_color, vehicle_make_model
        FROM entities
        ORDER BY last_seen DESC NULLS LAST
        LIMIT :limit
        """,
        limit=limit,
    )
    columns = [
        "entity_id", "type", "label", "trust_level", "role",
        "first_seen", "last_seen", "sightings_count",
        "plate_text", "vehicle_color", "vehicle_make_model",
    ]
    entities = []
    for row in rows:
        d = dict(zip(columns, row))
        d["first_seen"] = _iso(d["first_seen"])
        d["last_seen"] = _iso(d["last_seen"])
        entities.append(d)
    total_rows = conn.run("SELECT COUNT(*) FROM entities")
    total = int(total_rows[0][0]) if total_rows else len(entities)
    return {"entities": entities, "total": total}


def query_events(conn, hours: int = 24, days: int = 0, limit: int = 30) -> Dict[str, Any]:
    if days > 0:
        lookback_hours = days * 24
    else:
        lookback_hours = max(1, min(hours, 168))
    limit = max(1, min(limit, 500))
    rows = conn.run(
        """
        SELECT e.event_id, e.camera_id, e.timestamp, e.entity_type, e.score,
               e.anomaly_score, e.snapshot_url, e.video_clip_url, e.processed,
               c.name AS camera_name
        FROM events e
        LEFT JOIN cameras c ON c.camera_id = e.camera_id
        WHERE e.timestamp > NOW() - (:hours * INTERVAL '1 hour')
        ORDER BY e.timestamp DESC
        LIMIT :limit
        """,
        hours=lookback_hours,
        limit=limit,
    )
    columns = [
        "event_id", "camera_id", "timestamp", "entity_type", "score",
        "anomaly_score", "snapshot_url", "video_clip_url", "processed",
        "camera_name",
    ]
    events = []
    for row in rows:
        d = dict(zip(columns, row))
        d["timestamp"] = _iso(d["timestamp"])
        d["score"] = float(d["score"]) if d["score"] is not None else None
        d["anomaly_score"] = float(d["anomaly_score"] or 0)
        d["processed"] = bool(d["processed"])
        events.append(d)
    count_rows = conn.run(
        "SELECT COUNT(*) FROM events WHERE timestamp > NOW() - (:hours * INTERVAL '1 hour')",
        hours=lookback_hours,
    )
    total = int(count_rows[0][0]) if count_rows else len(events)
    return {"events": events, "total": total}


def query_alerts(conn, limit: int, unack_only: bool) -> Dict[str, Any]:
    limit = max(1, min(limit, 100))
    where = "WHERE user_response IS NULL" if unack_only else ""
    rows = conn.run(
        f"""
        SELECT alert_id, event_id, entity_id, camera_id, timestamp,
               priority, title, body, delivered, user_response
        FROM alerts
        {where}
        ORDER BY timestamp DESC
        LIMIT :limit
        """,
        limit=limit,
    )
    columns = [
        "alert_id", "event_id", "entity_id", "camera_id", "timestamp",
        "priority", "title", "body", "delivered", "user_response",
    ]
    alerts = []
    for row in rows:
        d = dict(zip(columns, row))
        d["timestamp"] = _iso(d["timestamp"])
        d["delivered"] = bool(d["delivered"])
        alerts.append(d)
    count_sql = f"SELECT COUNT(*) FROM alerts {where}"
    count_rows = conn.run(count_sql)
    total = int(count_rows[0][0]) if count_rows else len(alerts)
    return {"alerts": alerts, "total": total}


def query_sentinel_health(conn) -> Dict[str, Any]:
    """Return Sentinel component health from the sentinel_health table."""
    rows = conn.run("""
        SELECT status, protect_db, protect_poller, protect_processor,
               protect_configured, uptime_seconds, updated_at
        FROM sentinel_health
        WHERE id = 1
    """)
    if rows:
        row = rows[0]
        return {
            "status": row[0],
            "protect_db": row[1],
            "protect_poller": row[2],
            "protect_processor": row[3],
            "protect_configured": bool(row[4]),
            "uptime_seconds": row[5],
            "updated_at": _iso(row[6]),
            "source": "db",
        }
    return {
        "status": "unknown",
        "protect_db": "no_data",
        "protect_poller": "no_data",
        "protect_processor": "no_data",
        "protect_configured": False,
        "uptime_seconds": None,
        "updated_at": None,
        "source": "db",
    }


def query_cameras(conn, limit: int) -> Dict[str, Any]:
    limit = max(1, min(limit, 50))
    rows = conn.run(
        """
        SELECT camera_id, name, mac, model_key, state, type, zone,
               is_mic_enabled, mic_volume, video_mode, hdr_type,
               has_hdr, has_mic, has_speaker, has_led_status, has_full_hd_snapshot,
               video_modes, smart_detect_types, smart_detect_audio_types,
               smart_detect_object_types, smart_detect_audio_config,
               led_settings, osd_settings, lcd_message,
               updated_at
        FROM cameras
        ORDER BY name
        LIMIT :limit
        """,
        limit=limit,
    )
    columns = [
        "camera_id", "name", "mac", "model_key", "state", "type", "zone",
        "is_mic_enabled", "mic_volume", "video_mode", "hdr_type",
        "has_hdr", "has_mic", "has_speaker", "has_led_status", "has_full_hd_snapshot",
        "video_modes", "smart_detect_types", "smart_detect_audio_types",
        "smart_detect_object_types", "smart_detect_audio_config",
        "led_settings", "osd_settings", "lcd_message",
        "updated_at",
    ]
    cameras = []
    for row in rows:
        d = dict(zip(columns, row))
        d["updated_at"] = _iso(d["updated_at"])
        for bool_key in ("is_mic_enabled", "has_hdr", "has_mic", "has_speaker",
                         "has_led_status", "has_full_hd_snapshot"):
            if d[bool_key] is not None:
                d[bool_key] = bool(d[bool_key])
        cameras.append(d)
    total_rows = conn.run("SELECT COUNT(*) FROM cameras")
    total = int(total_rows[0][0]) if total_rows else len(cameras)
    return {"cameras": cameras, "total": total}


def query_patrols(conn, hours: int = 24, limit: int = 50) -> Dict[str, Any]:
    hours = max(1, min(hours, 168 * 4))
    limit = max(1, min(limit, 200))
    rows = conn.run(
        """
        SELECT cp.patrol_id, cp.camera_id, c.name AS camera_name,
               cp.timestamp, cp.scene_description, cp.detected_objects,
               cp.anomaly_detected, cp.anomaly_description, cp.confidence,
               cp.model_used, cp.processing_ms, cp.error
        FROM camera_patrols cp
        LEFT JOIN cameras c ON c.camera_id = cp.camera_id
        WHERE cp.timestamp > NOW() - (:hours * INTERVAL '1 hour')
        ORDER BY cp.timestamp DESC
        LIMIT :limit
        """,
        hours=hours,
        limit=limit,
    )
    columns = [
        "patrol_id", "camera_id", "camera_name", "timestamp",
        "scene_description", "detected_objects", "anomaly_detected",
        "anomaly_description", "confidence", "model_used",
        "processing_ms", "error",
    ]
    patrols = []
    for row in rows:
        d = dict(zip(columns, row))
        d["timestamp"] = _iso(d["timestamp"])
        d["anomaly_detected"] = bool(d["anomaly_detected"])
        d["confidence"] = float(d["confidence"] or 0)
        if isinstance(d["detected_objects"], str):
            try:
                d["detected_objects"] = json.loads(d["detected_objects"])
            except Exception:
                d["detected_objects"] = []
        patrols.append(d)
    return {"patrols": patrols, "total": len(patrols)}


def query_patterns(conn, limit: int) -> Dict[str, Any]:
    limit = max(1, min(limit, 100))
    rows = conn.run(
        """
        SELECT pattern_id, camera_id, entity_id, entity_type,
               pattern_type, frequency, last_seen, confidence
        FROM patterns
        ORDER BY last_seen DESC NULLS LAST
        LIMIT :limit
        """,
        limit=limit,
    )
    columns = [
        "pattern_id", "camera_id", "entity_id", "entity_type",
        "pattern_type", "frequency", "last_seen", "confidence",
    ]
    patterns = []
    for row in rows:
        d = dict(zip(columns, row))
        d["last_seen"] = _iso(d["last_seen"])
        d["frequency"] = float(d["frequency"] or 1.0)
        d["confidence"] = float(d["confidence"] or 0.0)
        patterns.append(d)
    total_rows = conn.run("SELECT COUNT(*) FROM patterns")
    total = int(total_rows[0][0]) if total_rows else len(patterns)
    return {"patterns": patterns, "total": total}


# ---------------------------------------------------------------------------
# Lambda handler
# ---------------------------------------------------------------------------

def handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Route /api/protect/* to direct Postgres queries, or dispatch action-based calls."""
    global _conn
    # Action-based dispatch (direct Lambda invocations from the agent runtime).
    action = event.get("action")
    if action:
        try:
            conn = _get_connection()
            if action == "auri_memory_store":
                return action_auri_memory_store(conn, event)
            elif action == "auri_memory_search":
                return action_auri_memory_search(conn, event)
            elif action == "auri_memory_search_filtered":
                return action_auri_memory_search_filtered(conn, event)
            elif action == "auri_participant_upsert":
                return action_auri_participant_upsert(conn, event)
            else:
                return {"statusCode": 400, "error": f"Unknown action: {action}"}
        except Exception as exc:
            logger.error("auri_memory action %s error: %s", action, exc, exc_info=True)
            _conn = None
            return {"statusCode": 503, "error": str(exc)}

    path = event.get("path", "")
    query = event.get("queryStringParameters") or {}

    cors_headers = {
        "Content-Type": "application/json",
        "Access-Control-Allow-Origin": "*",
    }

    try:
        conn = _get_connection()

        if path.endswith("/summary"):
            body = query_summary(conn)
        elif path.endswith("/cameras"):
            body = query_cameras(conn, int(query.get("limit", 20)))
        elif path.endswith("/entities"):
            body = query_entities(conn, int(query.get("limit", 50)))
        elif path.endswith("/patrols"):
            body = query_patrols(conn, int(query.get("hours", 24)), int(query.get("limit", 50)))
        elif path.endswith("/events"):
            body = query_events(
                conn,
                hours=int(query.get("hours", 24)),
                days=int(query.get("days", 0)),
                limit=int(query.get("limit", 30)),
            )
        elif path.endswith("/alerts"):
            body = query_alerts(
                conn,
                int(query.get("limit", 20)),
                query.get("unack_only", "").lower() in ("true", "1", "yes"),
            )
        elif path.endswith("/patterns"):
            body = query_patterns(conn, int(query.get("limit", 20)))
        elif path.endswith("/health"):
            body = query_sentinel_health(conn)
        else:
            return {
                "statusCode": 404,
                "headers": cors_headers,
                "body": json.dumps({"error": f"Unknown protect path: {path}"}),
            }

    except Exception as exc:
        logger.error("protect-query error: %s", exc, exc_info=True)
        # Reset connection so next invocation gets a fresh one
        _conn = None
        return {
            "statusCode": 503,
            "headers": cors_headers,
            "body": json.dumps({"error": f"protect-query: {exc}"}),
        }

    return {
        "statusCode": 200,
        "headers": cors_headers,
        "body": json.dumps(body, default=str),
    }
