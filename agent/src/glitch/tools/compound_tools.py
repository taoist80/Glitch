"""Compound tools for Glitch — reduce LLM round-trips for common workflows.

Each compound tool combines multiple primitive tool calls into a single
operation, returning a rich structured result so the LLM can act without
additional tool calls.

Tools:
  security_correlation_scan  — protect events + network clients + DNS logs in one call
  analyze_and_alert          — full pipeline: get events → analyze → decide → alert
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from strands import tool

logger = logging.getLogger(__name__)


@tool
async def security_correlation_scan(
    lookback_minutes: int = 60,
    camera_ids: Optional[str] = None,
) -> str:
    """Correlate UniFi Protect events, network clients, and DNS logs in a single scan.

    Combines three data sources to surface security-relevant correlations:
    - Protect: motion/person/vehicle events in the lookback window
    - UniFi Network: currently connected clients (MAC, IP, hostname)
    - Pi-hole DNS: suspicious domain queries in the same window

    Saves 2 LLM round-trips compared to calling each tool individually.

    Args:
        lookback_minutes: How far back to look for events and DNS queries (default 60).
        camera_ids: Optional comma-separated camera IDs to filter Protect events.

    Returns:
        JSON with keys:
          protect_events   — list of events (same schema as protect_get_events)
          network_clients  — list of active clients (same schema as unifi_list_clients)
          suspicious_dns   — list of suspicious domain queries (from dns_detect_suspicious_domains)
          correlations     — list of inferred correlations (e.g. unknown MAC + motion event)
          scan_time_utc    — ISO timestamp of when the scan ran
          errors           — dict of any per-source errors (source → error string)
    """
    from glitch.protect.config import is_protect_configured

    errors: dict = {}
    protect_events: list = []
    network_clients: list = []
    suspicious_dns: list = []

    # --- Protect events ---
    if is_protect_configured():
        try:
            from glitch.protect.client import get_client as get_protect_client

            client = get_protect_client()
            start_dt = datetime.now() - timedelta(minutes=lookback_minutes)
            end_dt = datetime.now()
            cam_list = [c.strip() for c in camera_ids.split(",")] if camera_ids else None

            events = await client.get_events(
                start=start_dt,
                end=end_dt,
                camera_ids=cam_list,
                limit=100,
            )
            for ev in events:
                ts_raw = ev.get("start") or ev.get("timestamp")
                if isinstance(ts_raw, (int, float)):
                    ts = datetime.fromtimestamp(ts_raw / 1000 if ts_raw > 1e10 else ts_raw).isoformat()
                else:
                    ts = str(ts_raw)
                protect_events.append({
                    "event_id": ev.get("id", ""),
                    "timestamp": ts,
                    "camera_id": ev.get("camera", ""),
                    "event_type": ev.get("type", ""),
                    "score": ev.get("score"),
                })
        except Exception as e:
            logger.warning("security_correlation_scan: protect error: %s", e)
            errors["protect"] = str(e)
    else:
        errors["protect"] = "not_configured"

    # --- Network clients ---
    try:
        from glitch.tools.unifi_network_tools import unifi_list_clients

        raw = await unifi_list_clients(active_only=True)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, list):
            network_clients = parsed
        elif isinstance(parsed, dict):
            network_clients = parsed.get("clients", [parsed])
    except Exception as e:
        logger.warning("security_correlation_scan: network error: %s", e)
        errors["network"] = str(e)

    # --- Suspicious DNS ---
    try:
        from glitch.tools.dns_intelligence_tools import dns_detect_suspicious_domains

        hours = max(1, lookback_minutes // 60)
        raw = await dns_detect_suspicious_domains(hours=hours)
        parsed = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(parsed, list):
            suspicious_dns = parsed
        elif isinstance(parsed, dict):
            suspicious_dns = parsed.get("suspicious_domains", parsed.get("domains", []))
    except Exception as e:
        logger.warning("security_correlation_scan: dns error: %s", e)
        errors["dns"] = str(e)

    # --- Correlations ---
    correlations: list = []

    # Correlation 1: unknown MAC addresses (not in known-device list) with recent motion
    known_hostnames = {c.get("hostname", "").lower() for c in network_clients if c.get("hostname")}
    unknown_clients = [
        c for c in network_clients
        if not c.get("hostname") or c.get("hostname", "").lower() not in known_hostnames
    ]
    if unknown_clients and protect_events:
        correlations.append({
            "type": "unknown_client_during_motion",
            "description": (
                f"{len(unknown_clients)} client(s) without hostname connected "
                f"while {len(protect_events)} Protect event(s) occurred"
            ),
            "unknown_clients": [
                {"mac": c.get("mac"), "ip": c.get("ip"), "hostname": c.get("hostname")}
                for c in unknown_clients[:5]
            ],
            "recent_events": protect_events[:3],
        })

    # Correlation 2: suspicious DNS + protect events in same window
    if suspicious_dns and protect_events:
        correlations.append({
            "type": "suspicious_dns_during_motion",
            "description": (
                f"{len(suspicious_dns)} suspicious DNS domain(s) queried "
                f"during window with {len(protect_events)} Protect event(s)"
            ),
            "suspicious_domains": suspicious_dns[:5],
        })

    return json.dumps({
        "protect_events": protect_events,
        "network_clients": network_clients,
        "suspicious_dns": suspicious_dns,
        "correlations": correlations,
        "scan_time_utc": datetime.utcnow().isoformat() + "Z",
        "errors": errors,
    }, indent=2, default=str)


@tool
async def analyze_and_alert(
    lookback_minutes: int = 60,
    camera_ids: Optional[str] = None,
    user_context: str = "{}",
    min_score: float = 0.0,
) -> str:
    """Full surveillance pipeline: fetch events → analyze → decide → alert.

    Combines protect_get_events + protect_analyze_event + protect_should_alert +
    protect_send_telegram_alert into a single tool call.

    Saves 3+ LLM round-trips for the most common surveillance workflow.
    Only sends alerts for events that pass the adaptive threshold.

    Args:
        lookback_minutes: How far back to look for events (default 60).
        camera_ids: Optional comma-separated camera IDs to filter.
        user_context: JSON string with user context for alert threshold adjustment.
                      Keys: user_away (bool), quiet_mode (bool).
        min_score: Minimum anomaly score to consider for analysis (0.0–1.0).
                   Events below this are skipped entirely. Default 0.0 (all events).

    Returns:
        JSON with keys:
          events_fetched    — total events in window
          events_analyzed   — events that passed min_score filter
          alerts_sent       — number of Telegram alerts sent
          alert_results     — list of per-event results (event_id, analyzed, alerted, reason)
          errors            — list of per-event errors
    """
    from glitch.protect.config import is_protect_configured, is_db_configured

    if not is_protect_configured():
        return json.dumps({"error": "Protect not configured. Set GLITCH_PROTECT_HOST/USERNAME/PASSWORD."})

    # Step 1: Fetch events
    try:
        from glitch.protect.client import get_client as get_protect_client

        client = get_protect_client()
        start_dt = datetime.now() - timedelta(minutes=lookback_minutes)
        end_dt = datetime.now()
        cam_list = [c.strip() for c in camera_ids.split(",")] if camera_ids else None

        raw_events = await client.get_events(
            start=start_dt,
            end=end_dt,
            camera_ids=cam_list,
            limit=50,
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to fetch events: {e}"})

    events_fetched = len(raw_events)
    alert_results: list = []
    errors: list = []
    alerts_sent = 0

    # Step 2: Analyze each event and decide/alert
    for ev in raw_events:
        event_id = ev.get("id", "")
        if not event_id:
            continue

        # Quick score filter before hitting the DB
        score = ev.get("score", 0) or 0
        if score < min_score:
            continue

        try:
            # Analyze (requires DB)
            if is_db_configured():
                from glitch.protect import db as protect_db

                event = await protect_db.get_event(event_id)
                if not event:
                    # Fall back to raw event data
                    event = {
                        "camera_id": ev.get("camera", ""),
                        "timestamp": ev.get("start") or ev.get("timestamp"),
                        "entity_type": ev.get("type", ""),
                        "anomaly_score": score,
                        "anomaly_factors": {},
                        "classifications": {},
                    }
                ts = event.get("timestamp")
                if isinstance(ts, datetime):
                    hour = ts.hour
                    dow = ts.weekday()
                else:
                    hour = 12
                    dow = 0

                baseline = await protect_db.get_baseline(event.get("camera_id", ""), hour, dow)
                prefs = await protect_db.get_alert_preferences(event.get("camera_id", ""))
                fp_rate = await protect_db.get_camera_fp_rate(event.get("camera_id", ""))
                anomaly_score = event.get("anomaly_score", score)
            else:
                # No DB — use raw score and default prefs
                prefs = {"min_anomaly_score": 0.5}
                fp_rate = 0.0
                anomaly_score = score

            # Decide
            base_threshold = prefs.get("min_anomaly_score", 0.5)
            if fp_rate > 0.3:
                adaptive_threshold = min(0.9, base_threshold + (fp_rate - 0.3) * 0.5)
            else:
                adaptive_threshold = base_threshold

            ctx = json.loads(user_context) if isinstance(user_context, str) else user_context
            if ctx.get("user_away"):
                adaptive_threshold = max(0.1, adaptive_threshold - 0.1)
            if ctx.get("quiet_mode"):
                adaptive_threshold = min(0.95, adaptive_threshold + 0.2)

            should_alert = anomaly_score >= adaptive_threshold

            if should_alert:
                # Determine priority
                if anomaly_score >= 0.9:
                    priority = "critical"
                elif anomaly_score >= 0.75:
                    priority = "high"
                elif anomaly_score >= 0.5:
                    priority = "medium"
                else:
                    priority = "low"

                event_type = ev.get("type", "unknown")
                camera_id = ev.get("camera", "unknown")
                ts_raw = ev.get("start") or ev.get("timestamp")
                if isinstance(ts_raw, (int, float)):
                    ts_str = datetime.fromtimestamp(ts_raw / 1000 if ts_raw > 1e10 else ts_raw).strftime("%H:%M:%S")
                else:
                    ts_str = str(ts_raw)

                message = (
                    f"{event_type.capitalize()} detected on camera {camera_id} at {ts_str}.\n"
                    f"Anomaly score: {anomaly_score:.2f} (threshold: {adaptive_threshold:.2f})"
                )

                # Alert
                try:
                    from glitch.channels.telegram import send_message

                    priority_emoji = {"critical": "🚨", "high": "⚠️", "medium": "📷", "low": "ℹ️"}.get(priority, "📷")
                    await send_message(f"{priority_emoji} *Protect Alert* [{priority.upper()}]\n\n{message}")
                    alerts_sent += 1
                    alert_status = "sent"
                except Exception as alert_err:
                    alert_status = f"failed: {alert_err}"

                alert_results.append({
                    "event_id": event_id,
                    "analyzed": True,
                    "alerted": alert_status == "sent",
                    "alert_status": alert_status,
                    "priority": priority,
                    "anomaly_score": anomaly_score,
                    "threshold": adaptive_threshold,
                })
            else:
                alert_results.append({
                    "event_id": event_id,
                    "analyzed": True,
                    "alerted": False,
                    "reason": f"score {anomaly_score:.2f} below threshold {adaptive_threshold:.2f}",
                })

        except Exception as e:
            logger.error("analyze_and_alert: error processing event %s: %s", event_id, e)
            errors.append({"event_id": event_id, "error": str(e)})

    return json.dumps({
        "events_fetched": events_fetched,
        "events_analyzed": len(alert_results),
        "alerts_sent": alerts_sent,
        "alert_results": alert_results,
        "errors": errors,
    }, indent=2, default=str)
