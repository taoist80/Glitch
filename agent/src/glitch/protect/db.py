"""Protect database layer.

asyncpg connection pool with schema auto-init and CRUD operations.
Schema is applied on first connect if tables don't exist.
"""

import asyncio
import concurrent.futures
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_pool = None
_pool_loop: Optional[asyncio.AbstractEventLoop] = None
_schema_applied = False
_pool_available = False  # True once a pool has been successfully created

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def is_pool_available() -> bool:
    """Return True if the DB pool is ready for use (non-blocking)."""
    return _pool is not None and _pool_available


async def get_pool():
    """Return the pool if ready; raise RuntimeError immediately if not yet available.

    Pool initialization runs as a background task (started by main.py via
    ``init_pool_background()``).  Callers in the tool request path must *not*
    wait for the pool — they should surface a friendly error and let the user
    retry once the background task has finished connecting.
    """
    if _pool is not None and _pool_available:
        return _pool
    raise RuntimeError(
        "Protect DB pool is not ready yet. "
        "Connection is being established in the background — please try again in a moment."
    )


async def run_in_pool_loop(coro_fn: Callable[..., Awaitable[T]], *args: Any) -> T:
    """Execute *coro_fn(*args)* on the event loop that owns the asyncpg pool.

    Strands' ConcurrentToolExecutor schedules async tool functions on a
    different thread / event loop than the one that created the pool.  asyncpg
    binds its internal futures to the creating loop, so calling ``pool.acquire``
    from another loop raises ``RuntimeError: ... attached to a different loop``.

    This helper detects the mismatch and uses ``run_coroutine_threadsafe`` to
    dispatch the coroutine to the pool's loop, then awaits the future from the
    calling loop via ``asyncio.wrap_future``.

    When there is no mismatch (same loop), the coroutine runs directly.
    """
    if _pool_loop is None:
        raise RuntimeError("Pool loop not initialised yet")

    try:
        calling_loop = asyncio.get_running_loop()
    except RuntimeError:
        calling_loop = None

    if calling_loop is _pool_loop:
        return await coro_fn(*args)

    future = asyncio.run_coroutine_threadsafe(coro_fn(*args), _pool_loop)
    return await asyncio.wrap_future(future)


async def init_pool_background() -> None:
    """Initialize the asyncpg pool with exponential-backoff retries.

    This should be called exactly once from ``main.py`` as a fire-and-forget
    ``asyncio.create_task``.  It never raises; all errors are logged and retried.

    For RDS IAM auth the token is refreshed on every attempt (tokens expire
    after 15 min).  SSL is required by RDS for IAM auth connections.
    """
    global _pool, _pool_available, _pool_loop

    try:
        import asyncpg
        import ssl as _ssl
    except ImportError:
        logger.error("asyncpg not installed — Protect DB unavailable")
        return

    from glitch.protect.config import get_db_config
    config = get_db_config()

    attempt = 0
    backoff = 15

    while True:
        attempt += 1
        try:
            if config.use_iam_auth:
                token = config.get_iam_token()
                ssl_ctx = _ssl.create_default_context()
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = _ssl.CERT_NONE
                pool_kwargs: dict = dict(
                    host=config.host,
                    port=config.port,
                    database=config.dbname,
                    user=config.username,
                    password=token,
                    ssl=ssl_ctx,
                    min_size=1,
                    max_size=10,
                    command_timeout=30,
                    timeout=30,
                )
                logger.info(
                    "Connecting to Protect DB via RDS IAM auth: %s:%s/%s user=%s (attempt %d)",
                    config.host, config.port, config.dbname, config.username, attempt,
                )
            else:
                pool_kwargs = dict(
                    host=config.host,
                    port=config.port,
                    database=config.dbname,
                    user=config.username,
                    password=config.password,
                    min_size=1,
                    max_size=10,
                    command_timeout=30,
                    timeout=30,
                )
                logger.info(
                    "Connecting to Protect DB via password auth: %s:%s/%s user=%s (attempt %d)",
                    config.host, config.port, config.dbname, config.username, attempt,
                )

            _pool = await asyncpg.create_pool(**pool_kwargs)
            _pool_loop = asyncio.get_running_loop()
            _pool_available = True
            logger.info("Protect DB pool created: %s:%s/%s", config.host, config.port, config.dbname)
            await _apply_schema(_pool)
            return

        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.warning(
                "Protect DB connection failed (attempt %d): [%s] %s — retrying in %ds",
                attempt, type(exc).__name__, exc or "(no message)", backoff,
            )
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)


async def _apply_schema(pool) -> None:
    """Apply schema.sql on first connect if tables don't yet exist."""
    global _schema_applied
    if _schema_applied:
        return

    schema_sql = SCHEMA_PATH.read_text()

    async with pool.acquire() as conn:
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
    global _pool, _pool_available, _pool_loop, _schema_applied
    if _pool is not None:
        await _pool.close()
        _pool = None
        _pool_loop = None
        _pool_available = False
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


async def get_recent_events(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    camera_ids: Optional[List[str]] = None,
    entity_types: Optional[List[str]] = None,
    limit: int = 100,
) -> List[Dict]:
    """Query recent events from the DB (replacement for REST API get_events).

    The integration API has no REST events endpoint \u2014 events arrive only via
    WebSocket and are persisted by the poller.  This function queries those
    persisted events.
    """
    pool = await get_pool()
    conditions: List[str] = []
    params: List[Any] = []
    idx = 1

    if start_time:
        conditions.append(f"timestamp >= ${idx}")
        params.append(start_time)
        idx += 1
    if end_time:
        conditions.append(f"timestamp <= ${idx}")
        params.append(end_time)
        idx += 1
    if camera_ids:
        conditions.append(f"camera_id = ANY(${idx})")
        params.append(camera_ids)
        idx += 1
    if entity_types:
        conditions.append(f"entity_type = ANY(${idx})")
        params.append(entity_types)
        idx += 1

    where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    params.append(limit)
    sql = f"SELECT * FROM events{where} ORDER BY timestamp DESC LIMIT ${idx}"

    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
        return [dict(r) for r in rows]


async def get_unprocessed_events(limit: int = 50) -> List[Dict]:
    """Return events that haven't been through the enrichment pipeline yet."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM events WHERE processed = FALSE "
            "ORDER BY timestamp ASC LIMIT $1",
            limit,
        )
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
    *,
    mac: Optional[str] = None,
    model_key: Optional[str] = None,
    state: Optional[str] = None,
    is_mic_enabled: Optional[bool] = None,
    mic_volume: Optional[int] = None,
    video_mode: Optional[str] = None,
    hdr_type: Optional[str] = None,
    has_hdr: Optional[bool] = None,
    has_mic: Optional[bool] = None,
    has_speaker: Optional[bool] = None,
    has_led_status: Optional[bool] = None,
    has_full_hd_snapshot: Optional[bool] = None,
    video_modes: Optional[List[str]] = None,
    smart_detect_types: Optional[List[str]] = None,
    smart_detect_audio_types: Optional[List[str]] = None,
    smart_detect_object_types: Optional[List[str]] = None,
    smart_detect_audio_config: Optional[List[str]] = None,
    led_settings: Optional[Dict] = None,
    osd_settings: Optional[Dict] = None,
    lcd_message: Optional[Dict] = None,
    site_id: str = "site1",
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO cameras (
                camera_id, name, site_id, mac, model_key, state,
                location, type, zone,
                is_mic_enabled, mic_volume, video_mode, hdr_type,
                has_hdr, has_mic, has_speaker, has_led_status, has_full_hd_snapshot,
                video_modes, smart_detect_types, smart_detect_audio_types,
                smart_detect_object_types, smart_detect_audio_config,
                led_settings, osd_settings, lcd_message,
                metadata
            ) VALUES (
                $1, $2, $27, $3, $4, $5,
                $6, $7, $8,
                $9, $10, $11, $12,
                $13, $14, $15, $16, $17,
                $18, $19, $20,
                $21, $22,
                $23, $24, $25,
                $26
            )
            ON CONFLICT (camera_id) DO UPDATE SET
                name = COALESCE($2, cameras.name),
                site_id = $27,
                mac = COALESCE($3, cameras.mac),
                model_key = COALESCE($4, cameras.model_key),
                state = COALESCE($5, cameras.state),
                location = COALESCE($6, cameras.location),
                type = COALESCE($7, cameras.type),
                zone = COALESCE($8, cameras.zone),
                is_mic_enabled = COALESCE($9, cameras.is_mic_enabled),
                mic_volume = COALESCE($10, cameras.mic_volume),
                video_mode = COALESCE($11, cameras.video_mode),
                hdr_type = COALESCE($12, cameras.hdr_type),
                has_hdr = COALESCE($13, cameras.has_hdr),
                has_mic = COALESCE($14, cameras.has_mic),
                has_speaker = COALESCE($15, cameras.has_speaker),
                has_led_status = COALESCE($16, cameras.has_led_status),
                has_full_hd_snapshot = COALESCE($17, cameras.has_full_hd_snapshot),
                video_modes = COALESCE($18, cameras.video_modes),
                smart_detect_types = COALESCE($19, cameras.smart_detect_types),
                smart_detect_audio_types = COALESCE($20, cameras.smart_detect_audio_types),
                smart_detect_object_types = COALESCE($21, cameras.smart_detect_object_types),
                smart_detect_audio_config = COALESCE($22, cameras.smart_detect_audio_config),
                led_settings = COALESCE($23, cameras.led_settings),
                osd_settings = COALESCE($24, cameras.osd_settings),
                lcd_message = COALESCE($25, cameras.lcd_message),
                metadata = COALESCE($26, cameras.metadata),
                updated_at = NOW()
            """,
            camera_id, name, mac, model_key, state,
            location, camera_type, zone,
            is_mic_enabled, mic_volume, video_mode, hdr_type,
            has_hdr, has_mic, has_speaker, has_led_status, has_full_hd_snapshot,
            video_modes, smart_detect_types, smart_detect_audio_types,
            smart_detect_object_types, smart_detect_audio_config,
            json.dumps(led_settings) if led_settings else None,
            json.dumps(osd_settings) if osd_settings else None,
            json.dumps(lcd_message) if lcd_message else None,
            json.dumps(metadata or {}),
            site_id,
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


async def list_cameras_summary() -> List[Dict]:
    """Compact camera listing: id, name, state, detection capabilities, and last update."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT camera_id, name, mac, state, type, zone,
                   smart_detect_types, smart_detect_audio_types,
                   video_mode, hdr_type, has_speaker, has_mic,
                   updated_at
            FROM cameras
            ORDER BY name
            """
        )
        return [dict(r) for r in rows]


async def get_cameras_by_state(state: str) -> List[Dict]:
    """List cameras filtered by connection state (e.g. CONNECTED, DISCONNECTED)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM cameras WHERE state = $1 ORDER BY name", state
        )
        return [dict(r) for r in rows]


async def get_cameras_with_capability(capability: str) -> List[Dict]:
    """List cameras that support a specific smart detect type (e.g. 'package', 'person')."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM cameras WHERE $1 = ANY(smart_detect_types) ORDER BY name",
            capability,
        )
        return [dict(r) for r in rows]


# ============================================================
# CAMERA PATROLS
# ============================================================

async def insert_patrol(
    camera_id: str,
    scene_description: Optional[str] = None,
    detected_objects: Optional[List] = None,
    anomaly_detected: bool = False,
    anomaly_description: Optional[str] = None,
    confidence: float = 0.0,
    model_used: str = "llava",
    processing_ms: Optional[int] = None,
    error: Optional[str] = None,
    site_id: str = "site1",
) -> str:
    pool = await get_pool()
    patrol_id = str(uuid.uuid4())
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO camera_patrols
                (patrol_id, camera_id, site_id, scene_description, detected_objects,
                 anomaly_detected, anomaly_description, confidence,
                 model_used, processing_ms, error)
            VALUES ($1, $2, $11, $3, $4, $5, $6, $7, $8, $9, $10)
            """,
            patrol_id, camera_id, scene_description,
            json.dumps(detected_objects or []),
            anomaly_detected, anomaly_description, confidence,
            model_used, processing_ms, error,
            site_id,
        )
    return patrol_id


async def get_latest_patrols() -> List[Dict]:
    """Return the most recent patrol result per camera."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT DISTINCT ON (cp.camera_id)
                cp.*, c.name AS camera_name
            FROM camera_patrols cp
            LEFT JOIN cameras c ON c.camera_id = cp.camera_id
            ORDER BY cp.camera_id, cp.timestamp DESC
            """
        )
        return [dict(r) for r in rows]


async def get_patrols(
    camera_id: Optional[str] = None,
    hours: int = 24,
    limit: int = 100,
) -> List[Dict]:
    """Return recent patrol results, optionally filtered by camera."""
    pool = await get_pool()
    conditions = ["cp.timestamp > NOW() - ($1 || ' hours')::interval"]
    params: List[Any] = [str(hours)]
    idx = 2

    if camera_id:
        conditions.append(f"cp.camera_id = ${idx}")
        params.append(camera_id)
        idx += 1

    params.append(limit)
    where = " AND ".join(conditions)
    sql = f"""
        SELECT cp.*, c.name AS camera_name
        FROM camera_patrols cp
        LEFT JOIN cameras c ON c.camera_id = cp.camera_id
        WHERE {where}
        ORDER BY cp.timestamp DESC
        LIMIT ${idx}
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(sql, *params)
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
