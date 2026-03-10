"""Sentinel A2A server.

Implements the AgentCore A2A protocol contract:
- POST / — JSON-RPC 2.0 A2A message endpoint
- GET /.well-known/agent-card.json — Agent Card for discovery
- GET /ping — Health check

Port: 9000 (A2A protocol standard)

On startup: if Protect credentials and DB config are present, the
ProtectEventPoller is started as a background asyncio.Task to consume
the UniFi Protect WebSocket feed in real time.
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from strands.multiagent.a2a import A2AServer

from sentinel.agent import get_sentinel_agent

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")



# Runtime URL injected by AgentCore (used for Agent Card's url field)
RUNTIME_URL = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")

_startup_time = time.time()

# Component health state — updated by the lifespan context manager and read by /ping.
_component_health: dict = {
    "protect_configured": False,
    "protect_db": "unchecked",   # "ok" | "error: <msg>" | "unchecked"
    "protect_poller": "stopped", # "running" | "stopped"
    "protect_processor": "stopped",
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: start optional protect poller on startup, clean up on shutdown."""
    _poller: Optional[object] = None

    try:
        from sentinel.protect.config import is_protect_configured
        from sentinel.protect.poller import ProtectEventPoller
        from sentinel.protect.client import get_client as get_protect_client
        from sentinel.protect.config import get_protect_config

        _component_health["protect_configured"] = is_protect_configured()

        if is_protect_configured():
            logger.info("Protect config detected — starting event poller")

            try:
                from sentinel.protect.db import get_pool
                await get_pool()
                _component_health["protect_db"] = "ok"
                logger.info("Protect DB pool initialised")
            except Exception as exc:
                _component_health["protect_db"] = f"error: {exc}"
                logger.warning(
                    "Protect DB not reachable (%s) — DB writes disabled, Telegram alerts still active", exc
                )
                try:
                    from sentinel.tools.telegram_tools import send_telegram_alert
                    await send_telegram_alert.__wrapped__(
                        message=(
                            "⚠️ <b>Sentinel: Protect DB unreachable</b>\n"
                            f"DB writes are disabled until connectivity is restored.\n"
                            f"Error: <code>{exc}</code>"
                        ),
                        severity="medium",
                        component="ProtectDB",
                    )
                except Exception as telegram_exc:
                    logger.warning("Could not send Telegram alert for DB failure: %s", telegram_exc)

            client = get_protect_client()
            config = get_protect_config()

            if client.auth_mode == "api_key":
                logger.info("Protect auth: API key — WS streams use X-API-KEY header (no login needed)")
            else:
                try:
                    await client._authenticate()
                    logger.info("Protect pre-auth (cookie) succeeded — starting poller and processor")
                except Exception as auth_exc:
                    logger.warning("Protect pre-auth failed: %s — poller will retry with backoff", auth_exc)

            poller = ProtectEventPoller(protect_client=client, config=config)
            await poller.start()
            _poller = poller
            _component_health["protect_poller"] = "running"

            try:
                from sentinel.protect.event_processor import ProtectEventProcessor
                cameras = await client.get_cameras()
                camera_ids = [c["id"] for c in cameras if isinstance(c, dict)]
                _processor = ProtectEventProcessor()
                await _processor.start(
                    camera_ids=camera_ids,
                    check_interval=float(os.environ.get("GLITCH_PROTECT_CHECK_INTERVAL", "120")),
                )
                _component_health["protect_processor"] = "running"
                logger.info(f"Event processor started for {len(camera_ids)} cameras at "
                            f"{os.environ.get('GLITCH_PROTECT_CHECK_INTERVAL', '120')}s interval")
            except Exception as exc:
                _component_health["protect_processor"] = f"error: {exc}"
                logger.warning("Failed to start event processor: %s — continuing without it", exc)
                try:
                    from sentinel.tools.telegram_tools import send_telegram_alert
                    await send_telegram_alert.__wrapped__(
                        message=(
                            "⚠️ <b>Sentinel: Protect event processor failed to start</b>\n"
                            f"Camera polling and vision analysis are offline.\n"
                            f"Error: <code>{exc}</code>"
                        ),
                        severity="medium",
                        component="ProtectPoller",
                    )
                except Exception as telegram_exc:
                    logger.warning("Could not send Telegram alert for event processor failure: %s", telegram_exc)

            asyncio.create_task(_daily_report_loop(), name="daily-report")
            logger.info("Daily report scheduler started (fires at 08:00 UTC)")

            asyncio.create_task(_health_writer_loop(), name="health-writer")
        else:
            logger.info("Protect not configured (GLITCH_PROTECT_HOST missing) — skipping event poller")
    except ImportError as exc:
        logger.warning("Protect modules not available: %s — poller not started", exc)
    except Exception as exc:
        logger.warning("Failed to start Protect poller: %s — continuing without it", exc)

    yield  # server runs here

    # Shutdown
    if _poller is not None:
        try:
            _poller.stop()  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        from sentinel.protect.db import close_pool
        await close_pool()
    except Exception:
        pass
    logger.info("Sentinel shutdown complete")


async def _daily_report_loop() -> None:
    """Send a daily surveillance summary to Telegram at 08:00 UTC."""
    report_hour = int(os.environ.get("GLITCH_PROTECT_REPORT_HOUR", "8"))
    while True:
        now = datetime.utcnow()
        next_run = now.replace(hour=report_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())

        try:
            from sentinel.protect.learning import generate_security_report
            from sentinel.tools.telegram_tools import send_telegram_alert

            now = datetime.utcnow()
            yesterday_dt = now - timedelta(days=1)
            result = await generate_security_report(
                start_date=yesterday_dt,
                end_date=now,
            )
            report = result.get("report_data", result)

            event_stats = report.get("event_statistics", [])
            total = sum(row.get("count", 0) for row in event_stats) if isinstance(event_stats, list) else 0
            yesterday = yesterday_dt.date()
            alerts = report.get("alert_accuracy", {}).get("total_alerts", 0)
            token_totals = report.get("token_totals", {})
            prompt_tokens = token_totals.get("prompt_tokens", 0)
            output_tokens = token_totals.get("output_tokens", 0)
            avg_ms = report.get("avg_processing_ms", 0)
            rec_list = report.get("recommendations", [])
            recommendations = "\n".join(f"• {r}" for r in rec_list) if rec_list else ""

            lines = [
                f"📊 <b>Daily Surveillance Report — {yesterday}</b>",
                "",
                f"Events processed: {total}",
                f"Alerts sent: {alerts}",
            ]
            if prompt_tokens or output_tokens:
                lines += [
                    "",
                    "Vision processing:",
                    f"• Tokens: {prompt_tokens:,} prompt / {output_tokens:,} output",
                    f"• Avg processing: {avg_ms / 1000:.1f}s/event",
                ]
            if recommendations:
                lines += ["", recommendations]

            await send_telegram_alert.__wrapped__(
                message="\n".join(lines),
                severity="low",
                component="DailyReport",
            )
            logger.info(f"Daily report sent for {yesterday}")
        except Exception as e:
            logger.error(f"Daily report failed: {e}", exc_info=True)


async def _health_writer_loop() -> None:
    """Write Sentinel component health to the DB every 60 seconds.

    This lets the UI read health status via the protect-query Lambda without
    needing a direct connection to the Sentinel agent.  First write is immediate;
    subsequent writes are every 60 seconds.  Silently skips if the DB is down.
    """
    while True:
        try:
            from sentinel.protect.db import upsert_sentinel_health
            now = int(time.time())
            db_ok = _component_health.get("protect_db") == "ok"
            poller_ok = _component_health.get("protect_poller") == "running"
            overall = "Healthy" if (db_ok and poller_ok) else "Degraded"
            await upsert_sentinel_health(
                status=overall,
                protect_db=str(_component_health.get("protect_db", "unchecked")),
                protect_poller=str(_component_health.get("protect_poller", "stopped")),
                protect_processor=str(_component_health.get("protect_processor", "stopped")),
                protect_configured=bool(_component_health.get("protect_configured", False)),
                uptime_seconds=now - int(_startup_time),
            )
        except Exception as exc:
            logger.debug("Health writer: could not update DB: %s", exc)
        await asyncio.sleep(60)


def create_app() -> FastAPI:
    sentinel = get_sentinel_agent()
    strands_agent = sentinel.get_agent()

    a2a_server = A2AServer(
        agent=strands_agent,
        http_url=RUNTIME_URL,
        serve_at_root=True,
        enable_a2a_compliant_streaming=True,
    )

    application = FastAPI(
        title="Sentinel",
        description="Operations agent for the Glitch system",
        lifespan=lifespan,
    )

    # /ping must be registered BEFORE the catch-all mount("/", ...) below.
    # FastAPI evaluates routes in registration order; a mount at "/" intercepts
    # all paths that aren't already claimed by an earlier route.
    # Per AgentCore A2A contract: /ping returns {"status": "Healthy", "time_of_last_update": <epoch>}
    @application.get("/ping")
    def ping():
        now = int(time.time())
        # Derive an overall health status from sub-components.
        db_status = _component_health.get("protect_db", "unchecked")
        poller_status = _component_health.get("protect_poller", "stopped")
        protect_configured = _component_health.get("protect_configured", False)

        if protect_configured and (db_status.startswith("error") or poller_status != "running"):
            overall = "Degraded"
        else:
            overall = "Healthy"

        return {
            "status": overall,
            "agent": "Sentinel",
            "time_of_last_update": now,
            "uptime_seconds": now - int(_startup_time),
            "components": {
                "protect_configured": protect_configured,
                "protect_db": db_status,
                "protect_poller": poller_status,
                "protect_processor": _component_health.get("protect_processor", "stopped"),
            },
        }

    # Mount the A2A app last so it acts as the default handler for POST /
    # and GET /.well-known/agent-card.json without shadowing /ping.
    application.mount("/", a2a_server.to_fastapi_app())
    logger.info(f"Sentinel A2A server mounted at / (runtime_url={RUNTIME_URL})")
    return application


app = create_app()
