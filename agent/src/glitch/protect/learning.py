"""Phase 5: Learning and Reporting.

Implements the 5 learning/reporting skills:
- optimize_alert_thresholds (ROC-like FP feedback analysis)
- identify_regular_visitors (batch analysis for trust promotion)
- daily_security_briefing (morning push notification)
- generate_security_report (weekly/monthly report)
- learn_from_false_positives (root cause analysis + auto-correction)
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# Threshold Optimization
# ============================================================

async def optimize_alert_thresholds(
    lookback_days: int = 30,
    target_fp_rate: float = 0.20,
    target_miss_rate: float = 0.05,
) -> Dict[str, Any]:
    """Optimize alert thresholds per camera using FP feedback.

    Uses ROC-like analysis to find threshold that minimizes FP + miss rate.

    Returns:
        Dict with recommendations and applied changes
    """
    from glitch.protect import db as protect_db

    cameras = await protect_db.list_cameras()
    recommendations = []
    applied_changes = []

    for camera in cameras:
        cam_id = camera["camera_id"]
        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            # Get alerts with user responses for this camera
            alerts = await conn.fetch(
                """
                SELECT a.alert_id, a.timestamp, a.user_response,
                       e.anomaly_score
                FROM alerts a
                LEFT JOIN events e ON a.event_id = e.event_id
                WHERE a.camera_id = $1
                  AND a.timestamp > NOW() - ($2 || ' days')::interval
                  AND a.user_response IS NOT NULL
                ORDER BY e.anomaly_score
                """,
                cam_id, str(lookback_days),
            )

        if len(alerts) < 5:
            continue

        # Compute FP rate at different thresholds
        scores = [(a["anomaly_score"] or 0, a["user_response"]) for a in alerts]
        scores.sort(key=lambda x: x[0])

        total = len(scores)
        fp_count = sum(1 for _, r in scores if r == "false_positive")
        ack_count = sum(1 for _, r in scores if r == "acknowledged")

        current_fp_rate = fp_count / total if total > 0 else 0

        # Find optimal threshold
        best_threshold = None
        best_combined_rate = float("inf")

        thresholds = [s[0] for s in scores if s[0] > 0]
        thresholds = sorted(set(round(t, 2) for t in thresholds))

        for threshold in thresholds:
            above = [(s, r) for s, r in scores if s >= threshold]
            below = [(s, r) for s, r in scores if s < threshold]

            if not above:
                continue

            fp_above = sum(1 for _, r in above if r == "false_positive")
            fp_rate = fp_above / len(above) if above else 0

            # Miss rate: acknowledged alerts that would be suppressed
            missed = sum(1 for _, r in below if r == "acknowledged")
            miss_rate = missed / ack_count if ack_count > 0 else 0

            combined = fp_rate + miss_rate * 2  # Weight miss rate higher
            if combined < best_combined_rate:
                best_combined_rate = combined
                best_threshold = threshold
                best_fp_rate = fp_rate
                best_miss_rate = miss_rate

        if best_threshold is None:
            continue

        prefs = await protect_db.get_alert_preferences(cam_id)
        current_threshold = prefs.get("min_anomaly_score", 0.5)

        rec = {
            "camera_id": cam_id,
            "current_threshold": current_threshold,
            "recommended_threshold": round(best_threshold, 2),
            "current_fp_rate": round(current_fp_rate, 3),
            "projected_fp_rate": round(best_fp_rate, 3),
            "projected_miss_rate": round(best_miss_rate, 3),
            "alerts_analyzed": total,
        }
        recommendations.append(rec)

        # Auto-apply if improvement is significant and within safe bounds
        improvement = current_fp_rate - best_fp_rate
        threshold_change = abs(best_threshold - current_threshold)

        if improvement > 0.05 and threshold_change <= 0.2:
            await protect_db.upsert_alert_preferences(
                cam_id, min_anomaly_score=best_threshold
            )
            applied_changes.append({
                "camera_id": cam_id,
                "old_threshold": current_threshold,
                "new_threshold": best_threshold,
                "fp_rate_improvement": round(improvement, 3),
            })

    # Store optimization run
    run_id = str(uuid.uuid4())
    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO optimization_runs (run_id, alerts_analyzed, metrics_summary,
                                           recommendations, applied_changes)
            VALUES ($1, $2, $3, $4, $5)
            """,
            run_id,
            sum(r.get("alerts_analyzed", 0) for r in recommendations),
            json.dumps({"lookback_days": lookback_days, "cameras_analyzed": len(cameras)}),
            json.dumps(recommendations),
            json.dumps(applied_changes),
        )

    return {
        "run_id": run_id,
        "cameras_analyzed": len(cameras),
        "recommendations": recommendations,
        "applied_changes": applied_changes,
        "summary": f"Analyzed {len(cameras)} cameras, applied {len(applied_changes)} threshold updates",
    }


# ============================================================
# Regular Visitor Identification
# ============================================================

async def identify_regular_visitors(
    min_sightings: int = 5,
    min_visits_per_week: float = 1.0,
    lookback_days: int = 30,
) -> Dict[str, Any]:
    """Identify regular unknown visitors and suggest trust promotion.

    Returns:
        Dict with candidates for trust promotion
    """
    from glitch.protect import db as protect_db
    from glitch.protect.entity_intelligence import classify_entity_role

    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        # Find unknown entities with sufficient sightings
        candidates = await conn.fetch(
            """
            SELECT e.entity_id, e.type, e.label, e.sightings_count,
                   e.first_seen, e.last_seen
            FROM entities e
            WHERE e.trust_level = 'unknown'
              AND e.sightings_count >= $1
              AND e.last_seen > NOW() - ($2 || ' days')::interval
              AND e.trust_level NOT IN ('hostile', 'archived', 'anonymized')
            ORDER BY e.sightings_count DESC
            LIMIT 50
            """,
            min_sightings, str(lookback_days),
        )

    results = []
    for candidate in candidates:
        entity_id = candidate["entity_id"]

        # Run role classification
        classification = await classify_entity_role(entity_id)

        if classification.get("confidence", 0) >= 0.6:
            role = classification.get("role")
            suggested_trust = classification.get("suggested_trust_level", "neutral")

            results.append({
                "entity_id": entity_id,
                "type": candidate["type"],
                "label": candidate["label"],
                "sightings_count": candidate["sightings_count"],
                "first_seen": str(candidate["first_seen"]),
                "last_seen": str(candidate["last_seen"]),
                "suggested_role": role,
                "suggested_trust_level": suggested_trust,
                "confidence": classification.get("confidence"),
                "reasoning": classification.get("reasoning"),
                "stats": classification.get("stats", {}),
            })

    return {
        "candidates_found": len(results),
        "candidates": results,
        "summary": (
            f"Found {len(results)} regular visitors that could be promoted. "
            f"Use protect_classify_entity to apply suggestions."
        ),
    }


# ============================================================
# Daily Security Briefing
# ============================================================

async def generate_daily_briefing(
    briefing_date: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Generate daily security briefing.

    Covers overnight activity (10pm-7am), notable events, system health.

    Returns:
        Dict with briefing data and formatted message
    """
    from glitch.protect import db as protect_db

    if briefing_date is None:
        briefing_date = datetime.now()

    # Overnight window: yesterday 10pm to today 7am
    today_7am = briefing_date.replace(hour=7, minute=0, second=0, microsecond=0)
    yesterday_10pm = today_7am - timedelta(hours=9)

    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        # Overnight events
        overnight_events = await conn.fetchval(
            "SELECT COUNT(*) FROM events WHERE timestamp BETWEEN $1 AND $2",
            yesterday_10pm, today_7am,
        )
        overnight_alerts = await conn.fetchval(
            "SELECT COUNT(*) FROM alerts WHERE timestamp BETWEEN $1 AND $2",
            yesterday_10pm, today_7am,
        )
        overnight_unknowns = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT es.entity_id)
            FROM entity_sightings es
            JOIN entities e ON es.entity_id = e.entity_id
            WHERE es.timestamp BETWEEN $1 AND $2
              AND e.trust_level = 'unknown'
            """,
            yesterday_10pm, today_7am,
        )
        overnight_hostile = await conn.fetchval(
            """
            SELECT COUNT(DISTINCT es.entity_id)
            FROM entity_sightings es
            JOIN entities e ON es.entity_id = e.entity_id
            WHERE es.timestamp BETWEEN $1 AND $2
              AND e.trust_level = 'hostile'
            """,
            yesterday_10pm, today_7am,
        )

        # High anomaly events overnight
        high_anomaly_events = await conn.fetch(
            """
            SELECT e.event_id, e.camera_id, e.timestamp, e.entity_type,
                   e.anomaly_score, e.anomaly_factors
            FROM events e
            WHERE e.timestamp BETWEEN $1 AND $2
              AND e.anomaly_score >= 0.7
            ORDER BY e.anomaly_score DESC
            LIMIT 5
            """,
            yesterday_10pm, today_7am,
        )

        # New entities registered yesterday
        new_entities = await conn.fetchval(
            "SELECT COUNT(*) FROM entities WHERE created_at BETWEEN $1 AND $2",
            yesterday_10pm, today_7am,
        )

        # System health
        queue_depth = 0  # Will be populated from processor if running
        total_entities = await conn.fetchval("SELECT COUNT(*) FROM entities")
        db_events_count = await conn.fetchval("SELECT COUNT(*) FROM events")

        # FP rate last 7 days
        fp_stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE user_response = 'false_positive') as fp
            FROM alerts
            WHERE timestamp > NOW() - INTERVAL '7 days'
              AND user_response IS NOT NULL
            """,
        )

    fp_rate = (fp_stats["fp"] / fp_stats["total"]) if fp_stats and fp_stats["total"] > 0 else 0

    # Determine overall assessment
    if overnight_hostile > 0:
        assessment = "NEEDS ATTENTION"
        assessment_emoji = "🚨"
    elif overnight_unknowns >= 3 or (overnight_alerts and overnight_alerts >= 5):
        assessment = "ELEVATED ACTIVITY"
        assessment_emoji = "⚠️"
    elif overnight_unknowns >= 1 or overnight_alerts >= 1:
        assessment = "MONITOR"
        assessment_emoji = "👁️"
    else:
        assessment = "ALL CLEAR"
        assessment_emoji = "✅"

    # Format briefing message
    lines = [
        f"{assessment_emoji} *Daily Security Briefing*",
        f"📅 {briefing_date.strftime('%A, %B %d %Y')}",
        f"🌙 Overnight Assessment: *{assessment}*",
        "",
        "📊 *Overnight Summary* (10pm-7am):",
        f"  • Events: {overnight_events}",
        f"  • Alerts: {overnight_alerts}",
        f"  • Unknown entities: {overnight_unknowns}",
        f"  • Hostile sightings: {overnight_hostile}",
        f"  • New entities registered: {new_entities}",
    ]

    if high_anomaly_events:
        lines.append("")
        lines.append("⚠️ *Notable Events*:")
        for ev in high_anomaly_events:
            ts = ev["timestamp"]
            ts_str = ts.strftime("%H:%M") if isinstance(ts, datetime) else str(ts)
            lines.append(
                f"  • {ts_str} - {ev['entity_type']} on {ev['camera_id']} "
                f"(anomaly: {ev['anomaly_score']:.0%})"
            )

    lines.extend([
        "",
        "🔧 *System Health*:",
        f"  • Total entities tracked: {total_entities}",
        f"  • Total events in DB: {db_events_count}",
        f"  • Alert FP rate (7d): {fp_rate:.0%}",
    ])

    if fp_rate > 0.3:
        lines.append(f"  ⚠️ High FP rate - consider running optimize_alert_thresholds")

    briefing_message = "\n".join(lines)

    briefing_data = {
        "assessment": assessment,
        "overnight_events": overnight_events,
        "overnight_alerts": overnight_alerts,
        "overnight_unknowns": overnight_unknowns,
        "overnight_hostile": overnight_hostile,
        "new_entities": new_entities,
        "high_anomaly_events": [dict(e) for e in high_anomaly_events],
        "system_health": {
            "total_entities": total_entities,
            "db_events_count": db_events_count,
            "fp_rate_7d": round(fp_rate, 3),
        },
    }

    # Store briefing
    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO security_briefings (assessment, briefing_data) VALUES ($1, $2)",
            assessment, json.dumps(briefing_data, default=str),
        )

    return {
        "assessment": assessment,
        "briefing_message": briefing_message,
        "briefing_data": briefing_data,
        "date": briefing_date.isoformat(),
    }


# ============================================================
# Security Report Generation
# ============================================================

async def generate_security_report(
    start_date: datetime,
    end_date: datetime,
    report_type: str = "weekly",
) -> Dict[str, Any]:
    """Generate comprehensive security report.

    Returns:
        Dict with full report data and formatted summary
    """
    from glitch.protect import db as protect_db

    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        # Event statistics
        event_stats = await conn.fetch(
            """
            SELECT entity_type,
                   COUNT(*) as count,
                   AVG(anomaly_score) as avg_anomaly,
                   MAX(anomaly_score) as max_anomaly
            FROM events
            WHERE timestamp BETWEEN $1 AND $2
            GROUP BY entity_type
            ORDER BY count DESC
            """,
            start_date, end_date,
        )

        # Alert statistics
        alert_stats = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE priority = 'critical') as critical,
                COUNT(*) FILTER (WHERE priority = 'high') as high,
                COUNT(*) FILTER (WHERE priority = 'medium') as medium,
                COUNT(*) FILTER (WHERE priority = 'low') as low,
                COUNT(*) FILTER (WHERE user_response = 'false_positive') as fp,
                COUNT(*) FILTER (WHERE user_response = 'acknowledged') as ack
            FROM alerts
            WHERE timestamp BETWEEN $1 AND $2
            """,
            start_date, end_date,
        )

        # New entities
        new_entities = await conn.fetch(
            """
            SELECT type, trust_level, COUNT(*) as count
            FROM entities
            WHERE created_at BETWEEN $1 AND $2
            GROUP BY type, trust_level
            ORDER BY count DESC
            """,
            start_date, end_date,
        )

        # Top cameras by activity
        camera_activity = await conn.fetch(
            """
            SELECT camera_id, COUNT(*) as event_count,
                   AVG(anomaly_score) as avg_anomaly
            FROM events
            WHERE timestamp BETWEEN $1 AND $2
            GROUP BY camera_id
            ORDER BY event_count DESC
            LIMIT 10
            """,
            start_date, end_date,
        )

        # Threat assessments summary
        threat_summary = await conn.fetchrow(
            """
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE threat_level = 'critical') as critical,
                COUNT(*) FILTER (WHERE threat_level = 'high') as high,
                COUNT(*) FILTER (WHERE threat_level = 'moderate') as moderate,
                AVG(threat_score) as avg_score
            FROM threat_assessments
            WHERE timestamp BETWEEN $1 AND $2
            """,
            start_date, end_date,
        )

        # Hostile events
        hostile_count = await conn.fetchval(
            "SELECT COUNT(*) FROM hostile_events WHERE timestamp BETWEEN $1 AND $2",
            start_date, end_date,
        )

    # Calculate metrics
    total_alerts = alert_stats["total"] if alert_stats else 0
    fp_count = alert_stats["fp"] if alert_stats else 0
    fp_rate = fp_count / total_alerts if total_alerts > 0 else 0

    # Recommendations
    recommendations = []
    if fp_rate > 0.25:
        recommendations.append(
            f"High false positive rate ({fp_rate:.0%}) - run optimize_alert_thresholds"
        )
    if hostile_count > 0:
        recommendations.append(
            f"{hostile_count} hostile events detected - review entity classifications"
        )

    # Build report
    report_data = {
        "period": {
            "start": start_date.isoformat(),
            "end": end_date.isoformat(),
            "type": report_type,
            "days": (end_date - start_date).days,
        },
        "event_statistics": [dict(e) for e in event_stats],
        "alert_statistics": dict(alert_stats) if alert_stats else {},
        "alert_accuracy": {
            "total_alerts": total_alerts,
            "false_positives": fp_count,
            "fp_rate": round(fp_rate, 3),
            "acknowledged": alert_stats["ack"] if alert_stats else 0,
        },
        "new_entities": [dict(e) for e in new_entities],
        "camera_activity": [dict(c) for c in camera_activity],
        "threat_summary": dict(threat_summary) if threat_summary else {},
        "hostile_events": hostile_count,
        "recommendations": recommendations,
    }

    # Store report
    report_id = str(uuid.uuid4())
    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO security_reports (report_id, period_start, period_end,
                                          report_type, report_data)
            VALUES ($1, $2, $3, $4, $5)
            """,
            report_id, start_date, end_date, report_type,
            json.dumps(report_data, default=str),
        )

    return {
        "report_id": report_id,
        "report_data": report_data,
        "generated_at": datetime.now().isoformat(),
    }


# ============================================================
# False Positive Learning
# ============================================================

FP_ROOT_CAUSES = {
    "unknown_regular": "Entity is a regular visitor not yet classified",
    "time_exception": "Normal activity at an unusual time",
    "threshold_too_low": "Camera sensitivity threshold is too low",
    "baseline_incomplete": "Baseline data insufficient for this time slot",
    "new_vehicle": "New vehicle for known resident/neighbor",
    "delivery_pattern": "Regular delivery not yet recognized as pattern",
}


async def learn_from_false_positives(
    lookback_days: int = 7,
    auto_apply_threshold: float = 0.8,
) -> Dict[str, Any]:
    """Analyze false positives and apply targeted corrections.

    Returns:
        Dict with root causes, corrections applied, and pending user review
    """
    from glitch.protect import db as protect_db
    from glitch.protect.entity_intelligence import classify_entity_role

    pool = await protect_db.get_pool()
    async with pool.acquire() as conn:
        # Get recent false positives
        fp_alerts = await conn.fetch(
            """
            SELECT a.alert_id, a.event_id, a.entity_id, a.camera_id,
                   a.timestamp, a.metadata,
                   e.anomaly_score, e.anomaly_factors, e.entity_type
            FROM alerts a
            LEFT JOIN events e ON a.event_id = e.event_id
            WHERE a.user_response = 'false_positive'
              AND a.timestamp > NOW() - ($1 || ' days')::interval
            ORDER BY a.timestamp DESC
            LIMIT 100
            """,
            str(lookback_days),
        )

    fp_analyses = []
    corrections_applied = []
    pending_review = []

    for fp in fp_alerts:
        entity_id = fp["entity_id"]
        camera_id = fp["camera_id"]
        anomaly_score = fp["anomaly_score"] or 0

        causes = []
        corrections: List[Dict] = []
        confidence = 0.0

        # Analyze root cause
        if entity_id:
            entity = await protect_db.get_entity(entity_id)
            if entity:
                trust = entity.get("trust_level", "unknown")
                sightings = entity.get("sightings_count", 0)

                # Cause: Regular visitor not classified
                if trust == "unknown" and sightings >= 5:
                    classification = await classify_entity_role(entity_id)
                    if classification.get("confidence", 0) >= 0.6:
                        causes.append({
                            "type": "unknown_regular",
                            "description": FP_ROOT_CAUSES["unknown_regular"],
                            "confidence": classification["confidence"],
                        })
                        corrections.append({
                            "action": "classify_entity",
                            "entity_id": entity_id,
                            "role": classification["role"],
                            "trust_level": classification["suggested_trust_level"],
                            "confidence": classification["confidence"],
                        })
                        confidence = max(confidence, classification["confidence"])

        # Cause: Threshold too low for this camera
        if camera_id and anomaly_score < 0.6:
            fp_rate = await protect_db.get_camera_fp_rate(camera_id, days=lookback_days)
            if fp_rate > 0.3:
                prefs = await protect_db.get_alert_preferences(camera_id)
                current_threshold = prefs.get("min_anomaly_score", 0.5)
                new_threshold = min(0.9, current_threshold + 0.05)
                causes.append({
                    "type": "threshold_too_low",
                    "description": FP_ROOT_CAUSES["threshold_too_low"],
                    "confidence": min(0.9, fp_rate),
                    "fp_rate": round(fp_rate, 3),
                })
                corrections.append({
                    "action": "raise_threshold",
                    "camera_id": camera_id,
                    "old_threshold": current_threshold,
                    "new_threshold": new_threshold,
                    "confidence": min(0.9, fp_rate),
                })
                confidence = max(confidence, min(0.9, fp_rate))

        # Cause: Incomplete baseline
        if fp.get("timestamp"):
            ts = fp["timestamp"]
            if isinstance(ts, datetime):
                baseline = await protect_db.get_baseline(camera_id or "", ts.hour, ts.weekday())
                if baseline is None:
                    causes.append({
                        "type": "baseline_incomplete",
                        "description": FP_ROOT_CAUSES["baseline_incomplete"],
                        "confidence": 0.6,
                    })
                    corrections.append({
                        "action": "rebuild_baseline",
                        "camera_id": camera_id,
                        "confidence": 0.6,
                    })
                    confidence = max(confidence, 0.6)

        analysis = {
            "alert_id": str(fp["alert_id"]),
            "event_id": fp["event_id"],
            "entity_id": entity_id,
            "camera_id": camera_id,
            "causes": causes,
            "corrections": corrections,
            "confidence": round(confidence, 3),
        }
        fp_analyses.append(analysis)

        # Auto-apply high-confidence corrections
        for correction in corrections:
            if correction.get("confidence", 0) >= auto_apply_threshold:
                applied = await _apply_fp_correction(correction)
                if applied:
                    corrections_applied.append(correction)
            else:
                pending_review.append({
                    "analysis": analysis,
                    "correction": correction,
                })

        # Store FP analysis
        pool = await protect_db.get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO fp_analysis (alert_id, event_id, entity_id, camera_id,
                                         causes, corrections_applied)
                VALUES ($1, $2, $3, $4, $5, $6)
                """,
                fp["alert_id"], fp["event_id"], entity_id, camera_id,
                json.dumps(causes),
                json.dumps([c for c in corrections if c.get("confidence", 0) >= auto_apply_threshold]),
            )

    return {
        "false_positives_analyzed": len(fp_analyses),
        "corrections_applied": corrections_applied,
        "pending_user_review": pending_review[:10],  # Top 10 for user review
        "summary": (
            f"Analyzed {len(fp_analyses)} false positives. "
            f"Applied {len(corrections_applied)} corrections automatically. "
            f"{len(pending_review)} corrections need user review."
        ),
    }


async def _apply_fp_correction(correction: Dict) -> bool:
    """Apply a single FP correction. Returns True if applied."""
    from glitch.protect import db as protect_db

    action = correction.get("action")

    try:
        if action == "classify_entity":
            entity_id = correction["entity_id"]
            role = correction["role"]
            trust_level = correction["trust_level"]

            pool = await protect_db.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "UPDATE entities SET role = $2, updated_at = NOW() WHERE entity_id = $1",
                    entity_id, role,
                )
            await protect_db.update_entity_trust(
                entity_id, trust_level, "system",
                f"Auto-classified from FP analysis: role={role}"
            )
            logger.info(f"Auto-classified entity {entity_id} as {role}/{trust_level}")
            return True

        elif action == "raise_threshold":
            camera_id = correction["camera_id"]
            new_threshold = correction["new_threshold"]
            await protect_db.upsert_alert_preferences(
                camera_id, min_anomaly_score=new_threshold
            )
            logger.info(f"Raised threshold for {camera_id} to {new_threshold}")
            return True

        elif action == "rebuild_baseline":
            # Queue baseline rebuild - will be picked up by retrain_patterns
            logger.info(f"Baseline rebuild queued for {correction.get('camera_id')}")
            return True

    except Exception as e:
        logger.error(f"Failed to apply FP correction {action}: {e}")

    return False
