"""Phase 3: Threat Assessment.

Implements the 3 threat assessment skills:
- assess_threat_level (4-dimension analysis)
- detect_coordinated_activity (sliding window correlation)
- detect_hostile_entity (trigger-based hostile detection with auto-response)
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ============================================================
# Threat Level Assessment
# ============================================================

THREAT_LEVELS = {
    (0.0, 0.2): "none",
    (0.2, 0.4): "low",
    (0.4, 0.6): "moderate",
    (0.6, 0.8): "high",
    (0.8, 1.0): "critical",
}

THREAT_ALERT_PRIORITY = {
    "none": None,
    "low": "low",
    "moderate": "medium",
    "high": "high",
    "critical": "critical",
}


def score_to_threat_level(score: float) -> str:
    for (low, high), level in THREAT_LEVELS.items():
        if low <= score < high:
            return level
    return "critical" if score >= 1.0 else "none"


async def assess_threat_level(
    event_id: str,
    entity_id: Optional[str],
    camera_id: str,
    timestamp: datetime,
    anomaly_score: float,
    anomaly_factors: Dict[str, float],
    classifications: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Perform 4-dimension threat assessment.

    Dimensions:
    - Intent: Evidence of purposeful threat
    - Capability: Ability to cause harm
    - Opportunity: Favorable conditions for threat
    - History: Prior incidents

    Returns:
        Dict with threat_score, threat_level, dimensions, recommendations
    """
    from sentinel.protect import db as protect_db

    entity = await protect_db.get_entity(entity_id) if entity_id else None
    trust = entity.get("trust_level", "unknown") if entity else "unknown"

    # Dimension 1: Intent (0-1.0)
    intent = _score_intent(trust, anomaly_factors, classifications)

    # Dimension 2: Capability (0-1.0)
    capability = _score_capability(entity, classifications, anomaly_factors)

    # Dimension 3: Opportunity (0-1.0)
    camera = await protect_db.get_camera(camera_id)
    opportunity = _score_opportunity(timestamp, camera, anomaly_factors)

    # Dimension 4: History (0-1.0)
    history = await _score_history(entity_id, entity)

    # Composite threat score
    threat_score = (
        max(intent, capability) * 0.5
        + opportunity * 0.3
        + history * 0.2
    )
    threat_score = max(0.0, min(1.0, threat_score))
    threat_level = score_to_threat_level(threat_score)

    # Generate recommendations
    recommendations = _generate_threat_recommendations(
        threat_level, intent, capability, opportunity, history, entity_id
    )

    # Store assessment
    assessment_id = str(uuid.uuid4())
    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO threat_assessments (assessment_id, event_id, entity_id, camera_id,
                                            threat_score, threat_level, dimensions, recommendations, summary)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
            """,
            assessment_id, event_id, entity_id, camera_id,
            threat_score, threat_level,
            json.dumps({
                "intent": round(intent, 3),
                "capability": round(capability, 3),
                "opportunity": round(opportunity, 3),
                "history": round(history, 3),
            }),
            json.dumps(recommendations),
            f"{threat_level.upper()} threat: intent={intent:.2f}, capability={capability:.2f}, "
            f"opportunity={opportunity:.2f}, history={history:.2f}",
        )

    return {
        "assessment_id": assessment_id,
        "event_id": event_id,
        "entity_id": entity_id,
        "camera_id": camera_id,
        "threat_score": round(threat_score, 3),
        "threat_level": threat_level,
        "alert_priority": THREAT_ALERT_PRIORITY.get(threat_level),
        "dimensions": {
            "intent": round(intent, 3),
            "capability": round(capability, 3),
            "opportunity": round(opportunity, 3),
            "history": round(history, 3),
        },
        "recommendations": recommendations,
        "auto_actions": _get_auto_actions(threat_level, entity_id),
    }


def _score_intent(
    trust: str,
    anomaly_factors: Dict[str, float],
    classifications: Optional[Dict],
) -> float:
    score = 0.0

    # Trust-based intent
    trust_intent = {
        "hostile": 0.9,
        "suspicious": 0.5,
        "unknown": 0.3,
        "neutral": 0.1,
        "trusted": 0.0,
    }
    score = trust_intent.get(trust, 0.3)

    # Behavioral indicators
    behavioral = anomaly_factors.get("behavioral", 0)
    score = max(score, behavioral * 0.7)

    # Reconnaissance patterns
    frequency = anomaly_factors.get("frequency", 0)
    if frequency >= 0.2:
        score = max(score, 0.7)  # Repeated appearances = possible recon

    return min(1.0, score)


def _score_capability(
    entity: Optional[Dict],
    classifications: Optional[Dict],
    anomaly_factors: Dict[str, float],
) -> float:
    score = 0.3  # Default: unknown capability

    if not classifications:
        return score

    # Check for weapons or tools in image
    anomalies = classifications.get("anomalies", [])
    for anomaly in anomalies:
        desc = str(anomaly.get("description", "")).lower()
        if any(w in desc for w in ("weapon", "gun", "knife", "crowbar", "tool")):
            return 0.9
        if any(w in desc for w in ("ladder", "bolt cutter", "pry bar")):
            score = max(score, 0.7)

    # Multiple persons coordinating
    persons = classifications.get("persons", [])
    if len(persons) >= 3:
        score = max(score, 0.7)
    elif len(persons) >= 2:
        score = max(score, 0.5)

    # Vehicle with tinted windows (concealment)
    vehicles = classifications.get("vehicles", [])
    for v in vehicles:
        features = v.get("distinguishing_features", [])
        for f in features:
            if "tinted" in str(f).lower():
                score = max(score, 0.4)

    return min(1.0, score)


def _score_opportunity(
    timestamp: datetime,
    camera: Optional[Dict],
    anomaly_factors: Dict[str, float],
) -> float:
    score = 0.0

    # Night hours
    hour = timestamp.hour
    if 23 <= hour or hour < 5:
        score += 0.4
    elif 5 <= hour < 7 or 21 <= hour < 23:
        score += 0.2

    # Restricted/vulnerable zone
    if camera:
        zone = camera.get("zone", "")
        restricted = camera.get("is_restricted", False)
        if restricted:
            score += 0.3
        elif zone in ("rear", "side"):
            score += 0.2

    # Temporal anomaly (unusual time = less witnesses)
    temporal = anomaly_factors.get("temporal", 0)
    score += temporal * 0.3

    return min(1.0, score)


async def _score_history(
    entity_id: Optional[str],
    entity: Optional[Dict],
) -> float:
    if not entity_id or not entity:
        return 0.2  # Unknown history = moderate concern

    from sentinel.protect import db as protect_db

    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        # Prior hostile events
        hostile_count = await conn.fetchval(
            "SELECT COUNT(*) FROM hostile_events WHERE entity_id = $1", entity_id
        )
        # Prior threat assessments
        threat_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM threat_assessments
            WHERE entity_id = $1 AND threat_level IN ('high', 'critical')
            """,
            entity_id,
        )
        # Prior false positive rate (if trusted entity, lower history concern)
        fp_count = await conn.fetchval(
            """
            SELECT COUNT(*) FROM alerts
            WHERE entity_id = $1 AND user_response = 'false_positive'
            """,
            entity_id,
        )

    if hostile_count > 0:
        return 0.8
    if threat_count > 2:
        return 0.5
    if threat_count > 0:
        return 0.3
    if fp_count > 3:
        return 0.05  # Many FPs = likely benign
    return 0.2


def _generate_threat_recommendations(
    threat_level: str,
    intent: float,
    capability: float,
    opportunity: float,
    history: float,
    entity_id: Optional[str],
) -> List[str]:
    recs = []

    if threat_level in ("high", "critical"):
        recs.append("Send immediate high-priority alert")
        if entity_id:
            recs.append(f"Flag entity {entity_id} as suspicious")
    if threat_level == "critical":
        recs.append("Consider contacting authorities")
        if entity_id:
            recs.append(f"Mark entity {entity_id} as hostile")

    if intent >= 0.7:
        recs.append("Entity shows strong intent indicators - monitor closely")
    if capability >= 0.7:
        recs.append("Potential tools/weapons or group activity detected")
    if opportunity >= 0.7:
        recs.append("High-risk conditions (night, restricted zone, isolated)")
    if history >= 0.5:
        recs.append("Entity has prior security incidents")

    if not recs:
        recs.append("Continue monitoring - no immediate action required")

    return recs


def _get_auto_actions(threat_level: str, entity_id: Optional[str]) -> List[Dict]:
    actions = []

    if threat_level == "critical":
        actions.append({"action": "send_critical_alert", "immediate": True})
        if entity_id:
            actions.append({"action": "mark_entity_hostile", "entity_id": entity_id})
        actions.append({"action": "capture_high_quality_snapshot"})

    elif threat_level == "high":
        actions.append({"action": "send_high_alert"})
        if entity_id:
            actions.append({"action": "flag_entity_suspicious", "entity_id": entity_id})

    elif threat_level == "moderate":
        actions.append({"action": "send_medium_alert"})

    return actions


# ============================================================
# Coordinated Activity Detection
# ============================================================

COORDINATION_PATTERNS = {
    "vehicle_person_pair": {
        "description": "Vehicle parks, person approaches property within 5 min",
        "score": 0.4,
        "window_minutes": 5,
    },
    "camera_sweep": {
        "description": "Same entity on 3+ cameras in sequence within 10 min",
        "score": 0.35,
        "window_minutes": 10,
        "min_cameras": 3,
    },
    "multiple_unknowns": {
        "description": "3+ unknown entities within 15 min",
        "score": 0.3,
        "window_minutes": 15,
        "min_entities": 3,
    },
    "loiter_approach": {
        "description": "Entity loiters 10+ min then approaches entry",
        "score": 0.45,
        "loiter_minutes": 10,
    },
    "synchronized_arrival": {
        "description": "Multiple entities arrive within 2 min of each other",
        "score": 0.35,
        "window_minutes": 2,
        "min_entities": 2,
    },
}


async def detect_coordinated_activity(
    trigger_event_id: str,
    camera_id: str,
    timestamp: datetime,
    window_minutes: int = 15,
) -> Dict[str, Any]:
    """Detect coordinated activity patterns in a sliding time window.

    Returns:
        Dict with coordination_score, patterns detected, entities involved
    """
    from sentinel.protect import db as protect_db

    window_start = timestamp - timedelta(minutes=window_minutes)
    window_end = timestamp + timedelta(minutes=2)  # Small lookahead

    # Get all events in window
    events = await protect_db.query_events(
        start_time=window_start,
        end_time=window_end,
        limit=200,
    )

    if len(events) < 2:
        return {
            "trigger_event_id": trigger_event_id,
            "coordination_score": 0.0,
            "patterns": [],
            "events_analyzed": len(events),
            "entities_involved": [],
            "alert_warranted": False,
        }

    # Get entity sightings for all events
    entity_events: Dict[str, List[Dict]] = {}
    all_entities = set()

    for ev in events:
        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            sightings = await conn.fetch(
                "SELECT * FROM entity_sightings WHERE event_id = $1", ev["event_id"]
            )
        for s in sightings:
            eid = s["entity_id"]
            if eid:
                all_entities.add(eid)
                if eid not in entity_events:
                    entity_events[eid] = []
                entity_events[eid].append({**ev, "sighting": dict(s)})

    # Detect patterns
    detected_patterns = []
    total_score = 0.0

    # Pattern: Multiple unknowns
    unknown_entities = []
    for eid in all_entities:
        entity = await protect_db.get_entity(eid)
        if entity and entity.get("trust_level") in ("unknown", "suspicious", "hostile"):
            unknown_entities.append(eid)

    if len(unknown_entities) >= 3:
        pattern = COORDINATION_PATTERNS["multiple_unknowns"]
        detected_patterns.append({
            "type": "multiple_unknowns",
            "description": pattern["description"],
            "score": pattern["score"],
            "entities": unknown_entities[:5],
        })
        total_score += pattern["score"]

    # Pattern: Camera sweep (same entity on 3+ cameras)
    for eid, ev_list in entity_events.items():
        cameras_seen = list(set(ev["camera_id"] for ev in ev_list))
        if len(cameras_seen) >= 3:
            pattern = COORDINATION_PATTERNS["camera_sweep"]
            detected_patterns.append({
                "type": "camera_sweep",
                "description": pattern["description"],
                "score": pattern["score"],
                "entity_id": eid,
                "cameras": cameras_seen,
            })
            total_score += pattern["score"]

    # Pattern: Vehicle + person pair
    vehicle_events = [ev for ev in events if ev.get("entity_type") == "vehicle"]
    person_events = [ev for ev in events if ev.get("entity_type") == "person"]

    if vehicle_events and person_events:
        for vev in vehicle_events:
            vts = vev.get("timestamp")
            for pev in person_events:
                pts = pev.get("timestamp")
                if isinstance(vts, datetime) and isinstance(pts, datetime):
                    diff = abs((pts - vts).total_seconds())
                    if diff <= 300:  # 5 minutes
                        pattern = COORDINATION_PATTERNS["vehicle_person_pair"]
                        detected_patterns.append({
                            "type": "vehicle_person_pair",
                            "description": pattern["description"],
                            "score": pattern["score"],
                            "vehicle_event": vev["event_id"],
                            "person_event": pev["event_id"],
                            "time_diff_seconds": diff,
                        })
                        total_score += pattern["score"]
                        break

    # Hostile entity multiplier
    hostile_involved = any(
        (await protect_db.get_entity(eid) or {}).get("trust_level") == "hostile"
        for eid in all_entities
    )
    if hostile_involved:
        total_score += 0.4

    # Multiple patterns multiplier
    if len(detected_patterns) >= 2:
        total_score *= 1.5

    coordination_score = min(1.0, total_score)

    # Store coordination event if significant
    if coordination_score >= 0.3:
        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO coordination_events (trigger_event_id, coordination_score,
                                                  patterns, events_involved, entities_involved,
                                                  alert_generated)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                trigger_event_id, coordination_score,
                json.dumps(detected_patterns),
                [ev["event_id"] for ev in events],
                list(all_entities),
                coordination_score >= 0.5,
            )

    return {
        "trigger_event_id": trigger_event_id,
        "coordination_score": round(coordination_score, 3),
        "patterns": detected_patterns,
        "events_analyzed": len(events),
        "entities_involved": list(all_entities),
        "unknown_entities": unknown_entities,
        "alert_warranted": coordination_score >= 0.5,
        "alert_priority": "critical" if coordination_score >= 0.8 else "high" if coordination_score >= 0.5 else "medium",
    }


# ============================================================
# Hostile Entity Detection
# ============================================================

IMMEDIATE_HOSTILE_TRIGGERS = [
    "weapon", "gun", "knife", "firearm", "rifle", "pistol",
    "crowbar", "forced entry", "breaking", "smashing",
    "property damage",
]

ESCALATED_HOSTILE_TRIGGERS = [
    "testing door", "testing handle", "checking locks",
    "peering through window", "photographing property",
    "crouching near door", "hiding near",
]


async def detect_hostile_entity(
    event_id: str,
    entity_id: Optional[str],
    camera_id: str,
    timestamp: datetime,
    classifications: Optional[Dict] = None,
    threat_assessment: Optional[Dict] = None,
    coordination_result: Optional[Dict] = None,
) -> Dict[str, Any]:
    """Detect hostile entity and trigger auto-response.

    Returns:
        Dict with hostile_detected, severity, triggers, actions_taken
    """
    from sentinel.protect import db as protect_db

    hostile_triggers = []
    severity = 0.0
    is_hostile = False

    # Check 1: Entity already marked hostile
    if entity_id:
        entity = await protect_db.get_entity(entity_id)
        if entity and entity.get("trust_level") == "hostile":
            hostile_triggers.append("Entity in hostile list")
            severity = max(severity, 1.0)
            is_hostile = True

    # Check 2: Weapon/immediate threat in image
    if classifications:
        anomalies = classifications.get("anomalies", [])
        for anomaly in anomalies:
            desc = str(anomaly.get("description", "")).lower()
            for trigger in IMMEDIATE_HOSTILE_TRIGGERS:
                if trigger in desc:
                    hostile_triggers.append(f"Immediate threat detected: {trigger}")
                    severity = max(severity, 0.95)
                    is_hostile = True

        # Check person behaviors
        persons = classifications.get("persons", [])
        for person in persons:
            behavior = person.get("behavior", {})
            notes = str(behavior.get("notes", "")).lower()
            attention = str(behavior.get("attention_focus", "")).lower()
            posture = str(behavior.get("posture", "")).lower()
            combined = f"{notes} {attention} {posture}"

            for trigger in ESCALATED_HOSTILE_TRIGGERS:
                if trigger in combined:
                    hostile_triggers.append(f"Escalated behavior: {trigger}")
                    severity = max(severity, 0.8)
                    is_hostile = True

    # Check 3: Critical threat assessment
    if threat_assessment and threat_assessment.get("threat_level") == "critical":
        hostile_triggers.append("Critical threat assessment")
        severity = max(severity, 0.85)
        is_hostile = True

    # Check 4: High coordination score
    if coordination_result and coordination_result.get("coordination_score", 0) >= 0.8:
        hostile_triggers.append("High coordination score with unknown entities")
        severity = max(severity, 0.75)
        is_hostile = True

    if not is_hostile:
        return {
            "event_id": event_id,
            "hostile_detected": False,
            "severity": 0.0,
            "triggers": [],
            "actions_taken": [],
        }

    # Auto-response actions
    actions_taken = []

    # 1. Record hostile event
    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        hostile_event_id = str(uuid.uuid4())
        await conn.execute(
            """
            INSERT INTO hostile_events (hostile_event_id, event_id, entity_id, camera_id,
                                         triggers, severity, actions_taken)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            hostile_event_id, event_id, entity_id, camera_id,
            json.dumps(hostile_triggers),
            severity,
            json.dumps(["recorded"]),
        )
    actions_taken.append("Recorded in hostile_events")

    # 2. Mark entity hostile if not already
    if entity_id:
        entity = await protect_db.get_entity(entity_id)
        if entity and entity.get("trust_level") != "hostile":
            await protect_db.update_entity_trust(
                entity_id, "hostile", "system",
                f"Auto-detected: {'; '.join(hostile_triggers[:2])}"
            )
            actions_taken.append(f"Entity {entity_id} marked hostile")

    # 3. Generate critical alert (no rate limiting)
    alert_message = (
        f"🚨 HOSTILE ENTITY DETECTED\n\n"
        f"Camera: {camera_id}\n"
        f"Time: {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Severity: {severity:.0%}\n\n"
        f"Triggers:\n" + "\n".join(f"• {t}" for t in hostile_triggers)
    )

    if entity_id:
        alert_message += f"\n\nEntity ID: {entity_id}"

    actions_taken.append("Critical alert queued")

    return {
        "event_id": event_id,
        "hostile_detected": True,
        "hostile_event_id": hostile_event_id,
        "entity_id": entity_id,
        "camera_id": camera_id,
        "severity": round(severity, 3),
        "triggers": hostile_triggers,
        "actions_taken": actions_taken,
        "alert_message": alert_message,
        "alert_priority": "critical",
    }
