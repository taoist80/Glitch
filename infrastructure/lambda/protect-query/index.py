"""Protect Query Lambda — direct Postgres reader for the UI Protect tab.

Bypasses both LLMs entirely for the /api/protect/* structured-data endpoints,
reducing response latency from ~5-10s to <500ms.

Routes:
    GET /api/protect/summary   → entities_total, events_24h, alerts_unack, cameras_online
    GET /api/protect/cameras   → ?limit=N  (default 20)
    GET /api/protect/entities  → ?limit=N  (default 50)
    GET /api/protect/events    → ?hours=N&limit=N  (default 24h, 30 events)
    GET /api/protect/alerts    → ?limit=N&unack_only=true  (default 20)
    GET /api/protect/patterns  → ?limit=N  (default 20)

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


def _row_to_dict(columns: list, row: tuple) -> Dict[str, Any]:
    return dict(zip(columns, row))


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
        d = _row_to_dict(columns, row)
        d["first_seen"] = _iso(d["first_seen"])
        d["last_seen"] = _iso(d["last_seen"])
        entities.append(d)
    total_rows = conn.run("SELECT COUNT(*) FROM entities")
    total = int(total_rows[0][0]) if total_rows else len(entities)
    return {"entities": entities, "total": total}


def query_events(conn, hours: int, limit: int) -> Dict[str, Any]:
    hours = max(1, min(hours, 168))
    limit = max(1, min(limit, 100))
    rows = conn.run(
        """
        SELECT event_id, camera_id, timestamp, entity_type, score,
               anomaly_score, snapshot_url, video_clip_url, processed
        FROM events
        WHERE timestamp > NOW() - (:hours * INTERVAL '1 hour')
        ORDER BY timestamp DESC
        LIMIT :limit
        """,
        hours=hours,
        limit=limit,
    )
    columns = [
        "event_id", "camera_id", "timestamp", "entity_type", "score",
        "anomaly_score", "snapshot_url", "video_clip_url", "processed",
    ]
    events = []
    for row in rows:
        d = _row_to_dict(columns, row)
        d["timestamp"] = _iso(d["timestamp"])
        d["score"] = float(d["score"]) if d["score"] is not None else None
        d["anomaly_score"] = float(d["anomaly_score"] or 0)
        d["processed"] = bool(d["processed"])
        events.append(d)
    count_rows = conn.run(
        "SELECT COUNT(*) FROM events WHERE timestamp > NOW() - (:hours * INTERVAL '1 hour')",
        hours=hours,
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
        d = _row_to_dict(columns, row)
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
        d = _row_to_dict(columns, row)
        d["updated_at"] = _iso(d["updated_at"])
        for bool_key in ("is_mic_enabled", "has_hdr", "has_mic", "has_speaker",
                         "has_led_status", "has_full_hd_snapshot"):
            if d[bool_key] is not None:
                d[bool_key] = bool(d[bool_key])
        cameras.append(d)
    total_rows = conn.run("SELECT COUNT(*) FROM cameras")
    total = int(total_rows[0][0]) if total_rows else len(cameras)
    return {"cameras": cameras, "total": total}


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
        d = _row_to_dict(columns, row)
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
    """Route /api/protect/* to direct Postgres queries."""
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
        elif path.endswith("/events"):
            body = query_events(conn, int(query.get("hours", 24)), int(query.get("limit", 30)))
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
        global _conn
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
