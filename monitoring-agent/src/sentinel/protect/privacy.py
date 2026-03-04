"""Data retention, export, and deletion for privacy compliance.

Implements GDPR-style data subject access and erasure requests,
plus automated retention cleanup per configured policies.
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


async def export_entity_data(entity_id: str) -> Dict[str, Any]:
    """Export all data for an entity (GDPR access request)."""
    from sentinel.protect import db as protect_db

    entity = await protect_db.get_entity(entity_id)
    if not entity:
        return {"error": f"Entity {entity_id} not found"}

    sightings = await protect_db.query_sightings(entity_id, limit=1000)
    patterns = await protect_db.query_patterns(entity_id=entity_id)

    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        alerts = await conn.fetch(
            "SELECT * FROM alerts WHERE entity_id = $1 ORDER BY timestamp DESC",
            entity_id,
        )
        audit_log = await conn.fetch(
            "SELECT * FROM entity_audit_log WHERE entity_id = $1 ORDER BY timestamp DESC",
            entity_id,
        )

    return {
        "entity": entity,
        "sightings": sightings,
        "patterns": patterns,
        "alerts": [dict(a) for a in alerts],
        "audit_log": [dict(a) for a in audit_log],
        "export_timestamp": datetime.now().isoformat(),
    }


async def delete_entity_data(entity_id: str, reason: str = "user_request") -> Dict[str, Any]:
    """Anonymize/delete all data for an entity (GDPR erasure request)."""
    from sentinel.protect import db as protect_db

    pool = await protect_db.get_pool()
    counts: Dict[str, int] = {}

    async with pool.acquire() as conn:
        # Anonymize entity record (keep for statistical purposes, remove PII)
        result = await conn.execute(
            """
            UPDATE entities
            SET label = NULL,
                plate_text = NULL,
                plate_state = NULL,
                vehicle_color = NULL,
                vehicle_make_model = NULL,
                face_embedding = NULL,
                vehicle_embedding = NULL,
                metadata = jsonb_build_object(
                    'anonymized', true,
                    'anonymized_at', NOW()::text,
                    'anonymized_reason', $2::text
                ),
                trust_level = 'anonymized',
                updated_at = NOW()
            WHERE entity_id = $1
            """,
            entity_id, reason,
        )
        counts["entity_anonymized"] = 1

        # Delete sightings
        result = await conn.execute(
            "DELETE FROM entity_sightings WHERE entity_id = $1", entity_id
        )
        counts["sightings_deleted"] = int(result.split()[-1])

        # Delete patterns
        result = await conn.execute(
            "DELETE FROM patterns WHERE entity_id = $1", entity_id
        )
        counts["patterns_deleted"] = int(result.split()[-1])

        # Anonymize audit log
        await conn.execute(
            """
            UPDATE entity_audit_log
            SET old_values = '{"anonymized": true}'::jsonb,
                new_values = '{"anonymized": true}'::jsonb
            WHERE entity_id = $1
            """,
            entity_id,
        )

        # Log the erasure
        await conn.execute(
            """
            INSERT INTO entity_audit_log (entity_id, action, actor, old_values, new_values)
            VALUES ($1, 'gdpr_erasure', 'system',
                    '{"action": "erasure_requested"}'::jsonb,
                    jsonb_build_object('reason', $2::text, 'timestamp', NOW()::text))
            """,
            entity_id, reason,
        )

    return {
        "entity_id": entity_id,
        "status": "anonymized",
        "counts": counts,
        "timestamp": datetime.now().isoformat(),
    }


async def run_retention_cleanup(
    snapshots_days: int = 7,
    video_days: int = 30,
    unknown_entity_days: int = 90,
) -> Dict[str, Any]:
    """Run automated retention cleanup per policy."""
    from sentinel.protect import db as protect_db

    logger.info(
        f"Running retention cleanup: snapshots={snapshots_days}d, "
        f"video={video_days}d, unknown_entities={unknown_entity_days}d"
    )

    counts = await protect_db.cleanup_retention(
        snapshots_days=snapshots_days,
        unknown_entity_days=unknown_entity_days,
    )

    return {
        "status": "completed",
        "timestamp": datetime.now().isoformat(),
        "policy": {
            "snapshots_days": snapshots_days,
            "video_days": video_days,
            "unknown_entity_days": unknown_entity_days,
        },
        "results": counts,
    }
