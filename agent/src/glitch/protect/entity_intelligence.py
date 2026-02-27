"""Phase 2: Entity Intelligence.

Implements the 5 entity intelligence skills:
- extract_person_details (via recognition.py + vision_agent)
- extract_face_features (LLaVA text description; InsightFace hook for Phase 2)
- classify_entity_role (frequency/pattern analysis)
- detect_anomalous_behavior (6-factor scoring)
- update_entity_trust_level (validated transitions with audit trail)
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# Trust Level Definitions
# ============================================================

TRUST_LEVELS = ["trusted", "neutral", "unknown", "suspicious", "hostile", "archived", "anonymized"]

TRUST_LEVEL_ORDER = {
    "trusted": 5,
    "neutral": 4,
    "unknown": 3,
    "suspicious": 2,
    "hostile": 1,
    "archived": 0,
    "anonymized": 0,
}

# Valid trust transitions: {from: [allowed_to]}
VALID_TRANSITIONS: Dict[str, List[str]] = {
    "unknown": ["trusted", "neutral", "suspicious", "hostile"],
    "neutral": ["trusted", "suspicious", "hostile", "unknown"],
    "suspicious": ["hostile", "neutral", "unknown"],
    "hostile": ["unknown"],  # hostile → trusted requires going through unknown first
    "trusted": ["neutral", "suspicious", "unknown"],
    "archived": ["unknown"],
    "anonymized": [],
}

# Transitions that require user actor (not system)
USER_ONLY_TRANSITIONS = {
    ("hostile", "unknown"),
    ("hostile", "neutral"),
    ("hostile", "trusted"),
    ("suspicious", "trusted"),
}

# ============================================================
# Role Classification
# ============================================================

ROLE_TRUST_MAP = {
    "resident": "trusted",
    "neighbor": "trusted",
    "delivery": "neutral",
    "service": "neutral",
    "guest": "neutral",
    "passerby": "neutral",
    "regular_visitor": "neutral",
    "suspicious": "suspicious",
    "hostile": "hostile",
}

ROLE_THRESHOLDS = {
    "resident": {
        "min_sightings": 5,
        "min_visits_per_week": 5,
        "time_consistency_hours": 2,
        "same_entry_camera": True,
    },
    "neighbor": {
        "min_sightings": 5,
        "min_visits_per_week": 2,
        "max_visits_per_week": 5,
        "adjacent_cameras_only": True,
    },
    "delivery": {
        "entity_type": "vehicle",
        "daytime_only": True,
        "max_dwell_minutes": 15,
        "weekday_only": True,
    },
    "regular_visitor": {
        "min_sightings": 5,
        "min_visits_per_week": 1,
        "max_visits_per_week": 5,
    },
    "passerby": {
        "max_dwell_minutes": 5,
        "no_property_approach": True,
    },
}


async def classify_entity_role(entity_id: str) -> Dict[str, Any]:
    """Classify entity role based on sighting patterns.

    Returns:
        Dict with role, confidence, reasoning, and suggested_trust_level
    """
    from glitch.protect import db as protect_db

    entity = await protect_db.get_entity(entity_id)
    if not entity:
        return {"error": f"Entity {entity_id} not found"}

    sightings = await protect_db.query_sightings(entity_id, limit=200)
    if len(sightings) < 3:
        return {
            "entity_id": entity_id,
            "role": None,
            "confidence": 0.0,
            "reasoning": f"Insufficient data: only {len(sightings)} sightings (need 3+)",
            "suggested_trust_level": entity.get("trust_level", "unknown"),
        }

    # Analyze patterns
    timestamps = []
    cameras = []
    dwell_times = []

    for s in sightings:
        ts = s.get("timestamp")
        if isinstance(ts, datetime):
            timestamps.append(ts)
        cameras.append(s.get("camera_id", ""))

    if not timestamps:
        return {"entity_id": entity_id, "role": None, "confidence": 0.0, "reasoning": "No valid timestamps"}

    timestamps.sort()
    first_seen = timestamps[0]
    last_seen = timestamps[-1]
    days_observed = max(1, (last_seen - first_seen).days)
    visits_per_week = len(timestamps) / max(1, days_observed / 7)

    # Time consistency: std dev of hour-of-day
    hours = [ts.hour for ts in timestamps]
    avg_hour = sum(hours) / len(hours)
    hour_std = (sum((h - avg_hour) ** 2 for h in hours) / len(hours)) ** 0.5

    # Camera diversity
    unique_cameras = set(cameras)
    primary_camera = max(set(cameras), key=cameras.count) if cameras else None
    primary_camera_pct = cameras.count(primary_camera) / len(cameras) if cameras and primary_camera else 0

    # Day of week distribution
    weekday_counts = [0] * 7
    for ts in timestamps:
        weekday_counts[ts.weekday()] += 1
    weekday_visits = sum(weekday_counts[:5])  # Mon-Fri
    weekend_visits = sum(weekday_counts[5:])

    # Daytime check (7am-7pm)
    daytime_count = sum(1 for ts in timestamps if 7 <= ts.hour < 19)
    daytime_pct = daytime_count / len(timestamps)

    # Apply classification rules
    role = None
    confidence = 0.0
    reasoning_parts = []

    if visits_per_week >= 5 and hour_std <= 2 and primary_camera_pct >= 0.7:
        role = "resident"
        confidence = min(0.95, 0.6 + (visits_per_week / 20) + (1 - hour_std / 12))
        reasoning_parts.append(f"High frequency ({visits_per_week:.1f}/week), consistent time (±{hour_std:.1f}h)")

    elif visits_per_week >= 2 and len(unique_cameras) <= 2 and primary_camera_pct >= 0.8:
        role = "neighbor"
        confidence = min(0.85, 0.5 + visits_per_week / 10)
        reasoning_parts.append(f"Regular visits ({visits_per_week:.1f}/week), limited camera range")

    elif (entity.get("type") == "vehicle" and daytime_pct >= 0.9
          and weekday_visits > weekend_visits * 2):
        role = "delivery"
        confidence = 0.7
        reasoning_parts.append("Vehicle, daytime-only, weekday-heavy pattern")

    elif visits_per_week >= 1:
        role = "regular_visitor"
        confidence = min(0.75, 0.4 + visits_per_week / 10)
        reasoning_parts.append(f"Regular visits ({visits_per_week:.1f}/week)")

    else:
        role = "passerby"
        confidence = 0.5
        reasoning_parts.append("Infrequent visits, no established pattern")

    suggested_trust = ROLE_TRUST_MAP.get(role, "unknown")

    return {
        "entity_id": entity_id,
        "role": role,
        "confidence": round(confidence, 3),
        "reasoning": "; ".join(reasoning_parts),
        "suggested_trust_level": suggested_trust,
        "stats": {
            "total_sightings": len(sightings),
            "days_observed": days_observed,
            "visits_per_week": round(visits_per_week, 2),
            "hour_std_dev": round(hour_std, 2),
            "primary_camera": primary_camera,
            "primary_camera_pct": round(primary_camera_pct, 2),
            "daytime_pct": round(daytime_pct, 2),
            "unique_cameras": len(unique_cameras),
        },
    }


# ============================================================
# Anomaly Detection
# ============================================================

async def detect_anomalous_behavior(
    event_id: str,
    entity_id: Optional[str],
    camera_id: str,
    timestamp: datetime,
    entity_type: str,
    behavior: Optional[Dict] = None,
    classifications: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Compute anomaly score using 6-factor model.

    Returns:
        Dict with anomaly_score (0-1), factors breakdown, and recommendations
    """
    from glitch.protect import db as protect_db

    factors: Dict[str, float] = {}

    # Factor 1: Trust level (0-0.4)
    if entity_id:
        entity = await protect_db.get_entity(entity_id)
        trust = entity.get("trust_level", "unknown") if entity else "unknown"
    else:
        trust = "unknown"
        entity = None

    trust_scores = {
        "hostile": 0.4,
        "suspicious": 0.3,
        "unknown": 0.2,
        "neutral": 0.05,
        "trusted": -0.1,
        "archived": 0.1,
    }
    factors["trust"] = trust_scores.get(trust, 0.2)

    # Factor 2: Time of day (0-0.2)
    hour = timestamp.hour
    if 23 <= hour or hour < 5:
        factors["time_of_day"] = 0.2
    elif 5 <= hour < 7 or 21 <= hour < 23:
        factors["time_of_day"] = 0.1
    else:
        factors["time_of_day"] = 0.0

    # Factor 3: Temporal vs baseline (0-0.3)
    baseline = await protect_db.get_baseline(camera_id, hour, timestamp.weekday())
    if baseline is None:
        factors["temporal"] = 0.1  # No baseline = mild uncertainty
    else:
        baseline_freq = baseline.get("frequency", 0)
        if baseline_freq < 0.1:
            factors["temporal"] = 0.3  # Very rare time slot
        elif baseline_freq < 0.5:
            factors["temporal"] = 0.15
        else:
            factors["temporal"] = 0.0

    # Factor 4: Spatial / camera zone (0-0.2)
    camera = await protect_db.get_camera(camera_id)
    if camera:
        zone = camera.get("zone", "")
        restricted = camera.get("is_restricted", False)
        if restricted:
            factors["spatial"] = 0.2
        elif zone in ("rear", "side", "garage"):
            factors["spatial"] = 0.15
        else:
            factors["spatial"] = 0.0
    else:
        factors["spatial"] = 0.05

    # Factor 5: Behavioral indicators (0-0.3)
    if behavior:
        from glitch.protect.recognition import compute_behavior_suspicion_score
        factors["behavioral"] = compute_behavior_suspicion_score(behavior) * 0.3
    elif classifications:
        # Extract behavior from person classifications
        persons = classifications.get("persons", [])
        if persons:
            max_suspicion = max(
                compute_behavior_suspicion_score_from_dict(p.get("behavior", {}))
                for p in persons
            )
            factors["behavioral"] = max_suspicion * 0.3
        else:
            factors["behavioral"] = 0.0
    else:
        factors["behavioral"] = 0.0

    # Factor 6: Frequency (0-0.2) - unusual burst
    if entity_id:
        recent_sightings = await protect_db.query_sightings(
            entity_id,
            start_time=timestamp - timedelta(hours=1),
            end_time=timestamp,
        )
        recent_count = len(recent_sightings)
        if recent_count >= 3:
            factors["frequency"] = 0.2
        elif recent_count >= 2:
            factors["frequency"] = 0.1
        else:
            factors["frequency"] = 0.0
    else:
        factors["frequency"] = 0.0

    # First-ever sighting bonus
    if entity_id and entity and entity.get("sightings_count", 0) <= 1:
        factors["first_sighting"] = 0.1
    else:
        factors["first_sighting"] = 0.0

    # Compute weighted sum
    raw_score = sum(factors.values())
    anomaly_score = max(0.0, min(1.0, raw_score))

    # Determine severity label
    if anomaly_score >= 0.8:
        severity = "critical"
    elif anomaly_score >= 0.6:
        severity = "high"
    elif anomaly_score >= 0.4:
        severity = "medium"
    elif anomaly_score >= 0.2:
        severity = "low"
    else:
        severity = "none"

    # Generate recommendations
    recommendations = []
    if factors.get("trust", 0) >= 0.3:
        recommendations.append("Entity has high-risk trust level")
    if factors.get("time_of_day", 0) >= 0.2:
        recommendations.append("Activity during high-risk hours (late night)")
    if factors.get("temporal", 0) >= 0.3:
        recommendations.append("Activity during unusually quiet time for this camera")
    if factors.get("spatial", 0) >= 0.15:
        recommendations.append("Activity in restricted or sensitive zone")
    if factors.get("behavioral", 0) >= 0.15:
        recommendations.append("Suspicious behavioral indicators detected")
    if factors.get("frequency", 0) >= 0.2:
        recommendations.append("Unusually high frequency of appearances")

    return {
        "event_id": event_id,
        "entity_id": entity_id,
        "camera_id": camera_id,
        "timestamp": timestamp.isoformat(),
        "anomaly_score": round(anomaly_score, 3),
        "severity": severity,
        "factors": {k: round(v, 3) for k, v in factors.items()},
        "trust_level": trust,
        "recommendations": recommendations,
    }


def compute_behavior_suspicion_score_from_dict(behavior: Dict) -> float:
    """Compute suspicion score from behavior dict (0-1)."""
    from glitch.protect.recognition import compute_behavior_suspicion_score
    return compute_behavior_suspicion_score(behavior)


# ============================================================
# Trust Level Management
# ============================================================

async def update_entity_trust(
    entity_id: str,
    new_trust_level: str,
    actor: str,
    reason: str,
) -> Dict[str, Any]:
    """Update entity trust level with validation and cascade effects.

    Returns:
        Dict with status, old_trust, new_trust, and cascade_effects
    """
    from glitch.protect import db as protect_db

    entity = await protect_db.get_entity(entity_id)
    if not entity:
        return {"error": f"Entity {entity_id} not found"}

    current_trust = entity.get("trust_level", "unknown")

    # Validate transition
    allowed = VALID_TRANSITIONS.get(current_trust, [])
    if new_trust_level not in allowed:
        return {
            "error": f"Invalid trust transition: {current_trust} → {new_trust_level}",
            "allowed_transitions": allowed,
        }

    # Check user-only transitions
    if (current_trust, new_trust_level) in USER_ONLY_TRANSITIONS and actor == "system":
        return {
            "error": f"Transition {current_trust} → {new_trust_level} requires user confirmation",
            "requires_user_confirmation": True,
        }

    # Apply trust update
    await protect_db.update_entity_trust(entity_id, new_trust_level, actor, reason)

    # Cascade effects
    cascade_effects = []

    if new_trust_level == "trusted":
        # Remove suppressions
        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM alert_suppressions WHERE entity_id = $1", entity_id
            )
        cascade_effects.append("Removed alert suppressions")

    elif new_trust_level == "hostile":
        # Add to hostile events log
        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO hostile_events (entity_id, triggers, severity, actions_taken)
                VALUES ($1, $2, 0.8, '["trust_level_set_hostile"]'::jsonb)
                """,
                entity_id,
                json.dumps([{"reason": reason, "actor": actor}]),
            )
        cascade_effects.append("Logged to hostile_events")
        cascade_effects.append("Next sighting will trigger critical alert")

    elif new_trust_level == "suspicious":
        cascade_effects.append("Alert threshold raised for this entity")

    return {
        "status": "updated",
        "entity_id": entity_id,
        "old_trust_level": current_trust,
        "new_trust_level": new_trust_level,
        "actor": actor,
        "reason": reason,
        "cascade_effects": cascade_effects,
    }


# ============================================================
# Face Feature Extraction (Phase 1: text; Phase 2: embeddings)
# ============================================================

async def extract_and_store_face_features(
    entity_id: str,
    image_url: str,
    use_insightface: bool = False,
) -> Dict[str, Any]:
    """Extract face features and store in entity record.

    Phase 1: LLaVA text description + text signature
    Phase 2: InsightFace 512-d embedding (if use_insightface=True)
    """
    from glitch.protect.recognition import format_face_prompt, extract_face_features, generate_text_signature
    from glitch.protect import db as protect_db

    # Phase 1: LLaVA text description
    from glitch.tools.ollama_tools import vision_agent

    prompt = format_face_prompt()
    raw_output = str(vision_agent(image_url=image_url, prompt=prompt))
    face_desc = extract_face_features(raw_output)

    if not face_desc:
        return {"error": "Could not extract face features from image"}

    quality = face_desc.get("image_quality", "unknown")
    if quality in ("poor",):
        return {
            "status": "skipped",
            "reason": f"Image quality too low for face extraction: {quality}",
            "face_desc": face_desc,
        }

    text_signature = generate_text_signature(face_desc)

    # Store in entity metadata
    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            UPDATE entities
            SET metadata = metadata || jsonb_build_object(
                'face_description', $2::jsonb,
                'face_text_signature', $3::text,
                'face_quality', $4::text
            ),
            updated_at = NOW()
            WHERE entity_id = $1
            """,
            entity_id,
            json.dumps(face_desc),
            text_signature,
            quality,
        )

    result: Dict[str, Any] = {
        "entity_id": entity_id,
        "face_description": face_desc,
        "text_signature": text_signature,
        "quality": quality,
        "method": "llava_text",
    }

    # Phase 2: InsightFace embedding (optional)
    if use_insightface:
        try:
            embedding = await _extract_insightface_embedding(image_url)
            if embedding is not None:
                await conn.execute(
                    "UPDATE entities SET face_embedding = $2 WHERE entity_id = $1",
                    entity_id, embedding,
                )
                result["embedding_method"] = "insightface_512d"
                result["embedding_stored"] = True
        except Exception as e:
            logger.warning(f"InsightFace embedding failed: {e}")
            result["embedding_method"] = "failed"

    return result


async def _extract_insightface_embedding(image_url: str) -> Optional[List[float]]:
    """Extract 512-d face embedding using InsightFace via code_interpreter."""
    # InsightFace runs via code_interpreter sandbox
    # This is a hook for Phase 2 implementation
    logger.info("InsightFace embedding extraction (Phase 2 - not yet implemented)")
    return None
