"""Protect database layer.

asyncpg connection pool with schema auto-init and CRUD operations.
Schema is applied on first connect if tables don't exist.
"""

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_pool = None
_schema_applied = False

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


async def get_pool():
    """Get or create the asyncpg connection pool.

    For RDS IAM auth (config.use_iam_auth=True) a fresh token is generated and
    used as the password.  SSL is required by RDS for IAM auth connections.
    """
    global _pool
    if _pool is not None:
        return _pool

    try:
        import asyncpg
        import ssl as _ssl
    except ImportError:
        raise RuntimeError(
            "asyncpg is required for Protect DB integration. "
            "Install with: pip install asyncpg"
        )

    from sentinel.protect.config import get_db_config
    config = get_db_config()

    pool_kwargs: dict = dict(
        host=config.host,
        port=config.port,
        database=config.dbname,
        user=config.username,
        min_size=2,
        max_size=10,
        command_timeout=30,
    )

    if config.use_iam_auth:
        # RDS IAM auth: token is the password; SSL required.
        token = config.get_iam_token()
        ssl_ctx = _ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = _ssl.CERT_NONE
        pool_kwargs["password"] = token
        pool_kwargs["ssl"] = ssl_ctx
        logger.info(
            "Connecting to Protect DB via RDS IAM auth: %s:%s/%s user=%s",
            config.host, config.port, config.dbname, config.username,
        )
    else:
        pool_kwargs["password"] = config.password
        logger.info(
            "Connecting to Protect DB via password auth: %s:%s/%s user=%s",
            config.host, config.port, config.dbname, config.username,
        )

    _pool = await asyncpg.create_pool(**pool_kwargs)
    logger.info("Protect DB pool created: %s:%s/%s", config.host, config.port, config.dbname)
    await _apply_schema()
    return _pool


async def _apply_schema() -> None:
    """Apply schema.sql if tables don't exist yet."""
    global _schema_applied
    if _schema_applied:
        return

    pool = await get_pool()
    schema_sql = SCHEMA_PATH.read_text()

    async with pool.acquire() as conn:
        # Check if events table exists as a proxy for schema state
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
            "WHERE table_name = 'events' AND table_schema = 'public')"
        )
        if not exists:
            logger.info("Applying Protect DB schema")
            await conn.execute(schema_sql)
            logger.info("Protect DB schema applied successfully")
        else:
            logger.debug("Protect DB schema already applied")

    _schema_applied = True


async def close_pool() -> None:
    """Close the connection pool."""
    global _pool, _schema_applied
    if _pool is not None:
        await _pool.close()
        _pool = None
        _schema_applied = False


async def upsert_sentinel_health(
    status: str,
    protect_db: str,
    protect_poller: str,
    protect_processor: str,
    protect_configured: bool,
    uptime_seconds: int,
) -> None:
    """Write Sentinel component health to the DB so the UI can read it via protect-query."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO sentinel_health
                (id, status, protect_db, protect_poller, protect_processor,
                 protect_configured, uptime_seconds, updated_at)
            VALUES (1, $1, $2, $3, $4, $5, $6, NOW())
            ON CONFLICT (id) DO UPDATE
            SET status = EXCLUDED.status,
                protect_db = EXCLUDED.protect_db,
                protect_poller = EXCLUDED.protect_poller,
                protect_processor = EXCLUDED.protect_processor,
                protect_configured = EXCLUDED.protect_configured,
                uptime_seconds = EXCLUDED.uptime_seconds,
                updated_at = EXCLUDED.updated_at
            """,
            status, protect_db, protect_poller, protect_processor,
            protect_configured, uptime_seconds,
        )


# ============================================================
# EVENTS
# ============================================================

async def insert_event(
    event_id: str,
    camera_id: str,
    timestamp: datetime,
    entity_type: Optional[str] = None,
    score: Optional[float] = None,
    snapshot_url: Optional[str] = None,
    video_clip_url: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO events (event_id, camera_id, timestamp, entity_type, score,
                                snapshot_url, video_clip_url, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (event_id) DO NOTHING
            """,
            event_id, camera_id, timestamp, entity_type, score,
            snapshot_url, video_clip_url,
            json.dumps(metadata or {}),
        )


async def get_event(event_id: str) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM events WHERE event_id = $1", event_id)
        return dict(row) if row else None


async def query_events(
    camera_id: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    entity_type: Optional[str] = None,
    min_anomaly_score: float = 0.0,
    limit: int = 100,
) -> List[Dict]:
    pool = await get_pool()
    conditions = ["anomaly_score >= $1"]
    params: List[Any] = [min_anomaly_score]
    idx = 2

    if camera_id:
        conditions.append(f"camera_id = ${idx}")
        params.append(camera_id)
        idx += 1
    if start_time:
        conditions.append(f"timestamp >= ${idx}")
        params.append(start_time)
        idx += 1
    if end_time:
        conditions.append(f"timestamp <= ${idx}")
        params.append(end_time)
        idx += 1
    if entity_type:
        conditions.append(f"entity_type = ${idx}")
        params.append(entity_type)
        idx += 1

    where = " AND ".join(conditions)
    params.append(limit)
    sql = f"SELECT * FROM events WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]


async def update_event_anomaly(
    event_id: str,
    anomaly_score: float,
    anomaly_factors: Dict,
    classifications: Optional[Dict] = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE events
            SET anomaly_score = $2,
                anomaly_factors = $3,
                classifications = COALESCE($4, classifications),
                processed = TRUE,
                processed_at = NOW()
            WHERE event_id = $1
            """,
            event_id, anomaly_score,
            json.dumps(anomaly_factors),
            json.dumps(classifications) if classifications else None,
        )


# ============================================================
# ENTITIES
# ============================================================

async def insert_entity(
    entity_id: str,
    entity_type: str,
    trust_level: str = "unknown",
    label: Optional[str] = None,
    plate_text: Optional[str] = None,
    plate_state: Optional[str] = None,
    vehicle_color: Optional[str] = None,
    vehicle_make_model: Optional[str] = None,
    first_seen: Optional[datetime] = None,
    last_seen: Optional[datetime] = None,
    metadata: Optional[Dict] = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO entities (
                entity_id, type, trust_level, label,
                plate_text, plate_state, vehicle_color, vehicle_make_model,
                first_seen, last_seen, sightings_count, metadata
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 1, $11)
            ON CONFLICT (entity_id) DO NOTHING
            """,
            entity_id, entity_type, trust_level, label,
            plate_text, plate_state, vehicle_color, vehicle_make_model,
            first_seen or datetime.now(), last_seen or datetime.now(),
            json.dumps(metadata or {}),
        )


async def get_entity(entity_id: str) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM entities WHERE entity_id = $1", entity_id)
        return dict(row) if row else None


async def update_entity_trust(
    entity_id: str,
    trust_level: str,
    actor: str = "system",
    reason: str = "",
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        old_trust = await conn.fetchval(
            "SELECT trust_level FROM entities WHERE entity_id = $1", entity_id
        )
        await conn.execute(
            """
            UPDATE entities
            SET trust_level = $2,
                updated_at = NOW(),
                metadata = metadata || jsonb_build_object(
                    'trust_history',
                    COALESCE(metadata->'trust_history', '[]'::jsonb) ||
                    jsonb_build_array(jsonb_build_object(
                        'from', $3::text,
                        'to', $2::text,
                        'actor', $4::text,
                        'reason', $5::text,
                        'timestamp', NOW()::text
                    ))
                )
            WHERE entity_id = $1
            """,
            entity_id, trust_level, old_trust, actor, reason,
        )
        await conn.execute(
            """
            INSERT INTO entity_audit_log (entity_id, action, actor, old_values, new_values)
            VALUES ($1, 'trust_level_changed', $2,
                    jsonb_build_object('trust_level', $3::text),
                    jsonb_build_object('trust_level', $4::text, 'reason', $5::text))
            """,
            entity_id, actor, old_trust, trust_level, reason,
        )


async def update_entity_sighting(entity_id: str, timestamp: datetime) -> None:
    """Update last_seen and increment sightings_count."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE entities
            SET last_seen = $2,
                sightings_count = sightings_count + 1,
                updated_at = NOW()
            WHERE entity_id = $1
            """,
            entity_id, timestamp,
        )


async def search_entities_by_plate(
    plate_text: str,
    plate_state: Optional[str] = None,
    similarity_threshold: float = 0.6,
) -> List[Dict]:
    """Search entities by plate text with fuzzy matching."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if plate_state:
            rows = await conn.fetch(
                """
                SELECT *, similarity(plate_text, $1) as plate_sim
                FROM entities
                WHERE type = 'vehicle'
                  AND plate_text IS NOT NULL
                  AND plate_state = $2
                  AND similarity(plate_text, $1) > $3
                ORDER BY plate_sim DESC
                LIMIT 5
                """,
                plate_text, plate_state, similarity_threshold,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT *, similarity(plate_text, $1) as plate_sim
                FROM entities
                WHERE type = 'vehicle'
                  AND plate_text IS NOT NULL
                  AND similarity(plate_text, $1) > $2
                ORDER BY plate_sim DESC
                LIMIT 5
                """,
                plate_text, similarity_threshold,
            )
        return [dict(r) for r in rows]


# ============================================================
# ENTITY SIGHTINGS
# ============================================================

async def insert_sighting(
    entity_id: str,
    event_id: str,
    camera_id: str,
    timestamp: datetime,
    features_snapshot: Optional[Dict] = None,
) -> str:
    sighting_id = str(uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO entity_sightings (sighting_id, entity_id, event_id, camera_id,
                                          timestamp, features_snapshot)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            sighting_id, entity_id, event_id, camera_id, timestamp,
            json.dumps(features_snapshot or {}),
        )
    return sighting_id


async def query_sightings(
    entity_id: str,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = 100,
) -> List[Dict]:
    pool = await get_pool()
    conditions = ["entity_id = $1"]
    params: List[Any] = [entity_id]
    idx = 2

    if start_time:
        conditions.append(f"timestamp >= ${idx}")
        params.append(start_time)
        idx += 1
    if end_time:
        conditions.append(f"timestamp <= ${idx}")
        params.append(end_time)
        idx += 1

    params.append(limit)
    where = " AND ".join(conditions)
    sql = f"SELECT * FROM entity_sightings WHERE {where} ORDER BY timestamp DESC LIMIT ${idx}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]


# ============================================================
# PATTERNS
# ============================================================

async def insert_pattern(
    camera_id: str,
    entity_id: Optional[str],
    entity_type: str,
    time_pattern: Dict,
    frequency: float = 1.0,
    confidence: float = 0.1,
    pattern_type: str = "entity_visit",
    metadata: Optional[Dict] = None,
) -> str:
    pattern_id = str(uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO patterns (pattern_id, camera_id, entity_id, entity_type,
                                  pattern_type, time_pattern, frequency, last_seen,
                                  confidence, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), $8, $9)
            """,
            pattern_id, camera_id, entity_id, entity_type,
            pattern_type, json.dumps(time_pattern), frequency,
            confidence, json.dumps(metadata or {}),
        )
    return pattern_id


async def get_baseline(
    camera_id: str,
    hour: int,
    day_of_week: int,
) -> Optional[Dict]:
    """Get baseline traffic pattern for a camera/time slot."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT *
            FROM patterns
            WHERE camera_id = $1
              AND (time_pattern->>'hour_of_day')::int = $2
              AND (time_pattern->>'day_of_week')::int = $3
              AND entity_type = 'baseline'
              AND pattern_type = 'baseline_traffic'
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            camera_id, hour, day_of_week,
        )
        return dict(row) if row else None


async def query_patterns(
    camera_id: Optional[str] = None,
    entity_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 50,
) -> List[Dict]:
    pool = await get_pool()
    conditions: List[str] = []
    params: List[Any] = []
    idx = 1

    if camera_id:
        conditions.append(f"camera_id = ${idx}")
        params.append(camera_id)
        idx += 1
    if entity_id:
        conditions.append(f"entity_id = ${idx}")
        params.append(entity_id)
        idx += 1
    if entity_type:
        conditions.append(f"entity_type = ${idx}")
        params.append(entity_type)
        idx += 1

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    sql = f"SELECT * FROM patterns {where} ORDER BY confidence DESC LIMIT ${idx}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]


# ============================================================
# ALERTS
# ============================================================

async def insert_alert(
    event_id: Optional[str],
    entity_id: Optional[str],
    camera_id: Optional[str],
    priority: str,
    title: str,
    body: Optional[str] = None,
    delivered: bool = False,
    metadata: Optional[Dict] = None,
) -> str:
    alert_id = str(uuid.uuid4())
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO alerts (alert_id, event_id, entity_id, camera_id,
                                priority, title, body, delivered, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            alert_id, event_id, entity_id, camera_id,
            priority, title, body, delivered,
            json.dumps(metadata or {}),
        )
    return alert_id


async def update_alert_response(alert_id: str, user_response: str) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE alerts
            SET user_response = $2, response_timestamp = NOW()
            WHERE alert_id = $1
            """,
            alert_id, user_response,
        )


async def get_camera_fp_rate(camera_id: str, days: int = 7) -> float:
    """Return false positive rate for a camera over the last N days."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE user_response = 'false_positive') as fp_count
            FROM alerts
            WHERE camera_id = $1
              AND timestamp > NOW() - ($2 || ' days')::interval
              AND user_response IS NOT NULL
            """,
            camera_id, str(days),
        )
        if row and row["total"] > 0:
            return row["fp_count"] / row["total"]
        return 0.0


# ============================================================
# ALERT PREFERENCES
# ============================================================

async def get_alert_preferences(camera_id: str) -> Dict:
    """Get alert preferences for a camera, falling back to global defaults."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM alert_preferences WHERE camera_id = $1", camera_id
        )
        if not row:
            row = await conn.fetchrow(
                "SELECT * FROM alert_preferences WHERE camera_id = 'global'"
            )
        return dict(row) if row else {
            "camera_id": camera_id,
            "sensitivity": "balanced",
            "entity_filters": None,
            "quiet_hours_start": None,
            "quiet_hours_end": None,
            "min_anomaly_score": 0.5,
        }


async def upsert_alert_preferences(camera_id: str, **kwargs: Any) -> None:
    pool = await get_pool()
    fields = {k: v for k, v in kwargs.items() if v is not None}
    if not fields:
        return

    set_clauses = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
    params = [camera_id] + list(fields.values())

    async with pool.acquire() as conn:
        await conn.execute(
            f"""
            INSERT INTO alert_preferences (camera_id, {', '.join(fields)})
            VALUES ($1, {', '.join(f'${i+2}' for i in range(len(fields)))})
            ON CONFLICT (camera_id) DO UPDATE
            SET {set_clauses}, updated_at = NOW()
            """,
            *params,
        )


# ============================================================
# ALERT SUPPRESSIONS
# ============================================================

async def get_suppression(entity_id: Optional[str] = None, camera_id: Optional[str] = None) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if entity_id:
            row = await conn.fetchrow(
                "SELECT * FROM alert_suppressions WHERE entity_id = $1 AND suppressed_until > NOW()",
                entity_id,
            )
        elif camera_id:
            row = await conn.fetchrow(
                "SELECT * FROM alert_suppressions WHERE camera_id = $1 AND suppressed_until > NOW()",
                camera_id,
            )
        else:
            return None
        return dict(row) if row else None


async def upsert_suppression(
    entity_id: Optional[str],
    camera_id: Optional[str],
    suppressed_until: datetime,
    reason: Optional[str] = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if entity_id:
            await conn.execute(
                """
                INSERT INTO alert_suppressions (entity_id, suppressed_until, reason)
                VALUES ($1, $2, $3)
                ON CONFLICT (entity_id) DO UPDATE
                SET suppressed_until = $2, reason = $3
                """,
                entity_id, suppressed_until, reason,
            )
        elif camera_id:
            await conn.execute(
                """
                INSERT INTO alert_suppressions (camera_id, suppressed_until, reason)
                VALUES ($1, $2, $3)
                ON CONFLICT DO NOTHING
                """,
                camera_id, suppressed_until, reason,
            )


# ============================================================
# CAMERAS
# ============================================================

async def upsert_camera(
    camera_id: str,
    name: str,
    location: Optional[str] = None,
    camera_type: Optional[str] = None,
    zone: Optional[str] = None,
    metadata: Optional[Dict] = None,
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cameras (camera_id, name, location, type, zone, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (camera_id) DO UPDATE
            SET name = $2, location = $3, type = $4, zone = $5,
                metadata = $6, updated_at = NOW()
            """,
            camera_id, name, location, camera_type, zone,
            json.dumps(metadata or {}),
        )


async def get_camera(camera_id: str) -> Optional[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM cameras WHERE camera_id = $1", camera_id)
        return dict(row) if row else None


async def list_cameras() -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT * FROM cameras ORDER BY name")
        return [dict(r) for r in rows]


# ============================================================
# RETENTION / CLEANUP
# ============================================================

async def cleanup_retention(
    snapshots_days: int = 7,
    unknown_entity_days: int = 90,
) -> Dict[str, int]:
    """Delete expired data per retention policy."""
    pool = await get_pool()
    counts: Dict[str, int] = {}

    async with pool.acquire() as conn:
        # Clear snapshot URLs from old events
        result = await conn.execute(
            """
            UPDATE events
            SET snapshot_url = NULL, video_clip_url = NULL
            WHERE timestamp < NOW() - ($1 || ' days')::interval
              AND (snapshot_url IS NOT NULL OR video_clip_url IS NOT NULL)
            """,
            str(snapshots_days),
        )
        counts["snapshots_cleared"] = int(result.split()[-1])

        # Archive unknown entities with few sightings
        result = await conn.execute(
            """
            UPDATE entities
            SET trust_level = 'archived',
                metadata = metadata || '{"archived_reason": "inactive_retention"}'::jsonb
            WHERE trust_level = 'unknown'
              AND last_seen < NOW() - ($1 || ' days')::interval
              AND sightings_count < 3
            """,
            str(unknown_entity_days),
        )
        counts["entities_archived"] = int(result.split()[-1])

    return counts
