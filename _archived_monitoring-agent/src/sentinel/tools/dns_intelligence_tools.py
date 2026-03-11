"""DNS intelligence and analytics tools for Sentinel.

Extends Pi-hole capabilities with real-time monitoring, historical analytics,
threat detection, and blocklist management.

Builds on glitch/pihole-api credentials already used by pihole_tools.py.
"""

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set

import httpx
from strands import tool

from sentinel.aws_utils import get_client

logger = logging.getLogger(__name__)

SECRET_NAME = "glitch/pihole-api"

# Known suspicious TLD patterns and domain indicators
_SUSPICIOUS_TLDS = {".tk", ".ml", ".ga", ".cf", ".gq", ".pw", ".top", ".xyz", ".click", ".download"}
_SUSPICIOUS_KEYWORDS = {"track", "telemetry", "phish", "malware", "botnet", "c2", "cnc", "payload", "exploit"}
_DGA_MIN_LENGTH = 12  # Domains with random-looking names above this length

_cached_creds = None


async def _get_pihole_creds():
    global _cached_creds
    if _cached_creds:
        return _cached_creds
    sm = get_client("secretsmanager")
    resp = sm.get_secret_value(SecretId=SECRET_NAME)
    _cached_creds = json.loads(resp["SecretString"])
    return _cached_creds


async def _get_auth_token(host: str, password: str) -> Optional[str]:
    login_url = f"http://{host}/admin/index.php?login"
    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        try:
            resp = await client.post(login_url, data={"pw": password},
                                     headers={"Content-Type": "application/x-www-form-urlencoded"})
            cookies = dict(resp.cookies)
            return cookies.get("PHPSESSID")
        except Exception as e:
            logger.error(f"Pi-hole auth failed for {host}: {e}")
            return None


async def _pihole_api(host: str, session_id: str, params: str) -> Optional[dict]:
    url = f"http://{host}/admin/api.php?{params}"
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            resp = await client.get(url, cookies={"PHPSESSID": session_id})
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.error(f"Pi-hole API call failed for {host}: {e}")
    return None


def _is_suspicious(domain: str) -> bool:
    """Heuristic check for suspicious domain characteristics."""
    lower = domain.lower()
    # Check TLD
    for tld in _SUSPICIOUS_TLDS:
        if lower.endswith(tld):
            return True
    # Check keywords
    for kw in _SUSPICIOUS_KEYWORDS:
        if kw in lower:
            return True
    # DGA-like: long random-looking subdomain
    parts = lower.split(".")
    if parts and len(parts[0]) > _DGA_MIN_LENGTH:
        alphanum = sum(c.isalnum() for c in parts[0])
        if alphanum / max(len(parts[0]), 1) > 0.85:
            consonants = sum(1 for c in parts[0] if c in "bcdfghjklmnpqrstvwxyz")
            if consonants / max(len(parts[0]), 1) > 0.6:
                return True
    return False


@tool
async def dns_analyze_query_patterns(hours: int = 6) -> str:
    """Analyze DNS query volume by client and domain to detect anomalies.

    Args:
        hours: Hours of query history to analyze (default 6).

    Returns:
        JSON with total queries, top domains, top clients, and anomaly flags.
    """
    try:
        creds = await _get_pihole_creds()
        host = creds.get("hosts", ["10.10.100.70"])[0]
        session_id = await _get_auth_token(host, creds["password"])
        if not session_id:
            return json.dumps({"error": "Pi-hole authentication failed"})

        data = await _pihole_api(host, session_id, "getAllQueries&auth=true")
        if not data:
            return json.dumps({"error": "Could not retrieve query data"})

        queries = data.get("data", [])
        # Query format: [timestamp, type, domain, client, status, dnssec]
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
        recent = [q for q in queries if float(q[0]) >= cutoff]

        domain_counts: Counter = Counter()
        client_counts: Counter = Counter()
        blocked_count = 0
        for q in recent:
            domain_counts[q[2]] += 1
            client_counts[q[3]] += 1
            if str(q[4]) in ("1", "4", "5", "6", "7", "8", "9", "10", "11"):
                blocked_count += 1

        top_domains = domain_counts.most_common(15)
        top_clients = client_counts.most_common(10)
        total = len(recent)
        block_rate = (blocked_count / max(total, 1)) * 100

        return json.dumps({
            "hours": hours,
            "total_queries": total,
            "blocked_count": blocked_count,
            "block_rate_pct": round(block_rate, 1),
            "top_domains": [{"domain": d, "count": c} for d, c in top_domains],
            "top_clients": [{"client": cl, "count": ct} for cl, ct in top_clients],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def dns_detect_suspicious_domains(hours: int = 3) -> str:
    """Check recent DNS queries against known suspicious domain patterns and DGA detection.

    Args:
        hours: Hours of query history to check (default 3).

    Returns:
        JSON list of suspicious domains with the clients querying them.
    """
    try:
        creds = await _get_pihole_creds()
        host = creds.get("hosts", ["10.10.100.70"])[0]
        session_id = await _get_auth_token(host, creds["password"])
        if not session_id:
            return json.dumps({"error": "Pi-hole authentication failed"})

        data = await _pihole_api(host, session_id, "getAllQueries&auth=true")
        if not data:
            return json.dumps({"error": "Could not retrieve query data"})

        queries = data.get("data", [])
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp()
        recent = [q for q in queries if float(q[0]) >= cutoff]

        suspicious: Dict[str, Set[str]] = defaultdict(set)
        for q in recent:
            domain = q[2]
            client = q[3]
            if _is_suspicious(domain):
                suspicious[domain].add(client)

        findings = [
            {"domain": d, "querying_clients": list(clients), "query_count": len(clients)}
            for d, clients in sorted(suspicious.items(), key=lambda x: -len(x[1]))
        ]

        return json.dumps({
            "hours": hours,
            "suspicious_domain_count": len(findings),
            "findings": findings[:50],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def dns_get_top_blocked(limit: int = 25) -> str:
    """Get the top blocked domains with request counts and client breakdown.

    Args:
        limit: Number of top blocked domains to return (default 25).

    Returns:
        JSON list of most-blocked domains with counts.
    """
    try:
        creds = await _get_pihole_creds()
        host = creds.get("hosts", ["10.10.100.70"])[0]
        session_id = await _get_auth_token(host, creds["password"])
        if not session_id:
            return json.dumps({"error": "Pi-hole authentication failed"})

        data = await _pihole_api(host, session_id, "topList&auth=true")
        if not data:
            return json.dumps({"error": "Could not retrieve blocked domain data"})

        blocked = data.get("top_ads", {})
        top_blocked = sorted(blocked.items(), key=lambda x: -x[1])[:limit]

        return json.dumps({
            "top_blocked": [{"domain": d, "count": c} for d, c in top_blocked],
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def dns_get_client_query_stats() -> str:
    """Get per-client DNS query statistics including volume and blocked ratio.

    Returns:
        JSON with each client's total queries, blocked count, and block ratio.
    """
    try:
        creds = await _get_pihole_creds()
        host = creds.get("hosts", ["10.10.100.70"])[0]
        session_id = await _get_auth_token(host, creds["password"])
        if not session_id:
            return json.dumps({"error": "Pi-hole authentication failed"})

        data = await _pihole_api(host, session_id, "topClients&auth=true")
        stats_data = await _pihole_api(host, session_id, "getForwardDestinations&auth=true")
        if not data:
            return json.dumps({"error": "Could not retrieve client stats"})

        clients = data.get("top_sources", {})
        blocked_clients = data.get("top_sources_blocked", {})

        results = []
        for client, total in sorted(clients.items(), key=lambda x: -x[1])[:20]:
            blocked = blocked_clients.get(client, 0)
            results.append({
                "client": client,
                "total_queries": total,
                "blocked_queries": blocked,
                "block_pct": round((blocked / max(total, 1)) * 100, 1),
            })

        return json.dumps({"clients": results}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def dns_monitor_live_queries(sample_seconds: int = 30, alert_threshold: int = 100) -> str:
    """Capture live DNS queries over a brief window and flag sudden spikes.

    Args:
        sample_seconds: How many seconds to sample (max 60, default 30).
        alert_threshold: Queries-per-second rate above which to flag as spike (default 100).

    Returns:
        JSON with query rate, top queried domains in window, and spike flag.
    """
    import asyncio
    sample_seconds = min(sample_seconds, 60)
    try:
        creds = await _get_pihole_creds()
        host = creds.get("hosts", ["10.10.100.70"])[0]
        session_id = await _get_auth_token(host, creds["password"])
        if not session_id:
            return json.dumps({"error": "Pi-hole authentication failed"})

        before = await _pihole_api(host, session_id, "summary&auth=true")
        await asyncio.sleep(sample_seconds)
        after = await _pihole_api(host, session_id, "summary&auth=true")

        if not before or not after:
            return json.dumps({"error": "Could not retrieve summary data"})

        queries_before = int(before.get("dns_queries_all_types", 0))
        queries_after = int(after.get("dns_queries_all_types", 0))
        delta = queries_after - queries_before
        rate_per_sec = delta / max(sample_seconds, 1)
        is_spike = rate_per_sec >= alert_threshold

        return json.dumps({
            "sample_seconds": sample_seconds,
            "queries_in_window": delta,
            "rate_per_second": round(rate_per_sec, 2),
            "spike_detected": is_spike,
            "spike_threshold": alert_threshold,
            "total_queries_today": queries_after,
            "total_blocked_today": int(after.get("ads_blocked_today", 0)),
            "block_pct_today": float(after.get("ads_percentage_today", 0)),
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def dns_get_query_trends(days: int = 7) -> str:
    """Get historical DNS query trends over recent days with daily breakdowns.

    Args:
        days: Number of days of history to retrieve (default 7, max 30).

    Returns:
        JSON with daily query totals, blocked counts, and trends.
    """
    days = min(days, 30)
    try:
        creds = await _get_pihole_creds()
        host = creds.get("hosts", ["10.10.100.70"])[0]
        session_id = await _get_auth_token(host, creds["password"])
        if not session_id:
            return json.dumps({"error": "Pi-hole authentication failed"})

        # Use overTimeData10mins for trend data
        data = await _pihole_api(host, session_id, "overTimeData10mins&auth=true")
        if not data:
            return json.dumps({"error": "Could not retrieve trend data"})

        domains_over_time = data.get("domains_over_time", {})
        ads_over_time = data.get("ads_over_time", {})

        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()
        daily_totals: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "blocked": 0})

        for ts_str, count in domains_over_time.items():
            ts = float(ts_str)
            if ts >= cutoff:
                day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                daily_totals[day]["total"] += count

        for ts_str, count in ads_over_time.items():
            ts = float(ts_str)
            if ts >= cutoff:
                day = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")
                daily_totals[day]["blocked"] += count

        trend = [
            {
                "date": day,
                "total_queries": totals["total"],
                "blocked_queries": totals["blocked"],
                "block_pct": round((totals["blocked"] / max(totals["total"], 1)) * 100, 1),
            }
            for day, totals in sorted(daily_totals.items())
        ]

        return json.dumps({"days": days, "trend": trend}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def dns_manage_blocklists(
    action: str,
    target: Optional[str] = None,
) -> str:
    """Manage Pi-hole blocklists and whitelist/blacklist domains.

    Args:
        action: One of:
                "list_sources" — list all configured blocklist URLs and their domain counts.
                "whitelist_domain" — whitelist a domain (requires target=domain).
                "blacklist_domain" — add a domain to the local blacklist (requires target=domain).
                "remove_whitelist" — remove a domain from the whitelist (requires target=domain).
                "remove_blacklist" — remove a domain from the local blacklist (requires target=domain).
                "list_whitelist" — list all whitelisted domains.
                "list_blacklist" — list all locally blacklisted domains.
        target: Domain name for whitelist/blacklist actions.

    Returns:
        JSON result of the action.
    """
    try:
        creds = await _get_pihole_creds()
        results = []

        for host in creds.get("hosts", ["10.10.100.70"]):
            session_id = await _get_auth_token(host, creds["password"])
            if not session_id:
                results.append({"host": host, "error": "auth failed"})
                continue

            if action == "list_sources":
                data = await _pihole_api(host, session_id, "list=adlists&auth=true")
                sources = data.get("data", []) if data else []
                results.append({
                    "host": host,
                    "adlists": [
                        {
                            "url": s.get("address"),
                            "enabled": s.get("enabled"),
                            "domains_count": s.get("number"),
                            "comment": s.get("comment"),
                        }
                        for s in sources
                    ],
                })
            elif action in ("whitelist_domain", "remove_whitelist") and target:
                list_type = "white"
                act = "add" if action == "whitelist_domain" else "sub"
                data = await _pihole_api(host, session_id, f"list={list_type}&add={target}&auth=true" if act == "add" else f"list={list_type}&sub={target}&auth=true")
                results.append({"host": host, "action": action, "domain": target, "result": data})
            elif action in ("blacklist_domain", "remove_blacklist") and target:
                list_type = "black"
                act = "add" if action == "blacklist_domain" else "sub"
                data = await _pihole_api(host, session_id, f"list={list_type}&add={target}&auth=true" if act == "add" else f"list={list_type}&sub={target}&auth=true")
                results.append({"host": host, "action": action, "domain": target, "result": data})
            elif action == "list_whitelist":
                data = await _pihole_api(host, session_id, "list=white&auth=true")
                results.append({"host": host, "whitelist": data.get("data", []) if data else []})
            elif action == "list_blacklist":
                data = await _pihole_api(host, session_id, "list=black&auth=true")
                results.append({"host": host, "blacklist": data.get("data", []) if data else []})
            else:
                results.append({"error": f"Unknown action: {action}. Valid: list_sources, whitelist_domain, blacklist_domain, remove_whitelist, remove_blacklist, list_whitelist, list_blacklist"})
                break

        return json.dumps({"results": results}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
