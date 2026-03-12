"""Main entry point for Glitch agent.

Dataflow:
    Environment Variables -> TelemetryConfig, AgentConfig, ServerConfig
                                    |
                                    v
                            setup_telemetry()
                                    |
                                    v
                            create_glitch_agent()
                                    |
                                    v
                    Telegram Channel (if bot token in Secrets Manager)
                                    |
                                    v
                            run_server_async() or interactive_mode()
"""

import asyncio
import json
import logging
import os
import time as _time
from datetime import datetime, timedelta, timezone
from typing import Optional as _Optional

# Strands SDK: allow non-interactive tool execution (required for AgentCore/serverless).
# Set before any Strands/glitch.agent imports.
os.environ.setdefault("BYPASS_TOOL_CONSENT", "true")

# Load SSH config from agent/.env.ssh when present (written by scripts/ssh-setup.sh).
_env_ssh = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env.ssh")
if os.path.isfile(_env_ssh):
    from dotenv import load_dotenv
    load_dotenv(_env_ssh)

import sys
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from glitch.agent import GlitchAgent
from glitch.agent_factory import bootstrap_agents_and_register
from glitch.poet_agent import create_poet_agent
from glitch.telemetry import setup_telemetry, write_startup_heartbeat_to_cloudwatch
from glitch.types import (
    TelemetryConfig,
    ServerConfig,
    InvocationResponse,
)
from glitch.channels import (
    ConfigManager,
    DynamoDBConfigManager,
    OwnerBootstrap,
    TelegramChannel,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def get_telegram_bot_token() -> Optional[str]:
    """Retrieve Telegram bot token from AWS Secrets Manager.
    
    Returns:
        Bot token string if available, None otherwise
    """
    secret_name = os.getenv("GLITCH_TELEGRAM_SECRET_NAME", "glitch/telegram-bot-token")
    
    try:
        from glitch.aws_utils import get_client
        client = get_client("secretsmanager")
        
        response = client.get_secret_value(SecretId=secret_name)
        
        if "SecretString" in response:
            return response["SecretString"]
        else:
            logger.warning(f"Secret {secret_name} does not contain a string value")
            return None
    except client.exceptions.ResourceNotFoundException:
        logger.info(f"Telegram bot token secret not found: {secret_name}")
        return None
    except Exception as e:
        logger.warning(f"Failed to retrieve Telegram bot token from Secrets Manager: {e}")
        return None


def get_telemetry_config() -> TelemetryConfig:
    """Build TelemetryConfig from environment variables.
    
    Environment Variables:
        OTEL_CONSOLE_ENABLED: Enable console exporter (default: false)
        OTEL_OTLP_ENABLED: Enable OTLP exporter (default: false in AgentCore, true if endpoint set)
        OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint URL
    
    Returns:
        TelemetryConfig instance
    """
    # Only enable OTLP if explicitly requested OR if an endpoint is configured
    # This avoids connection errors to localhost:4318 in AgentCore where no collector runs
    has_endpoint = bool(os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"))
    otlp_enabled_env = os.getenv("OTEL_OTLP_ENABLED", "").lower()
    enable_otlp = otlp_enabled_env == "true" if otlp_enabled_env else has_endpoint
    
    return TelemetryConfig(
        service_name="glitch-agent",
        enable_console=os.getenv("OTEL_CONSOLE_ENABLED", "false").lower() == "true",
        enable_otlp=enable_otlp,
    )


def get_server_config() -> ServerConfig:
    """Build ServerConfig from environment variables.
    
    Environment Variables:
        GLITCH_HOST: Host to bind to (default: 0.0.0.0)
        GLITCH_PORT: Port to bind to (default: 8080)
        GLITCH_DEBUG: Enable debug mode (default: false)
    
    Returns:
        ServerConfig instance
    """
    port_str = os.getenv("GLITCH_PORT", "8080")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning("Invalid GLITCH_PORT '%s', using default 8080", port_str)
        port = 8080
    return ServerConfig(
        host=os.getenv("GLITCH_HOST", "0.0.0.0"),
        port=port,
        debug=os.getenv("GLITCH_DEBUG", "false").lower() == "true",
    )


def get_current_telegram_webhook(bot_token: str) -> Optional[str]:
    """Get current webhook URL from Telegram (getWebhookInfo). Returns None on error."""
    info_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    try:
        with urllib.request.urlopen(info_url, timeout=10) as response:
            result = json.loads(response.read().decode())
            if result.get("ok"):
                return (result.get("result") or {}).get("url") or ""
            return None
    except Exception:
        return None


def register_telegram_webhook(bot_token: str, webhook_url: str, secret_token: str) -> bool:
    """Register webhook URL with Telegram API.
    
    If getWebhookInfo shows the URL is already set to webhook_url, skips setWebhook to avoid
    rate limits when multiple runtime instances start. Retries on 429 with exponential backoff.
    
    Args:
        bot_token: Telegram bot token
        webhook_url: URL for Telegram to send updates to
        secret_token: Secret token for webhook validation
        
    Returns:
        True if registration succeeded or webhook already set to this URL
    """
    current = get_current_telegram_webhook(bot_token)
    if current is not None and current.rstrip("/") == webhook_url.rstrip("/"):
        logger.info("Telegram webhook already set to %s, skipping setWebhook", webhook_url)
        return True

    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": secret_token,
        "allowed_updates": ["message", "edited_message", "callback_query"],
        "drop_pending_updates": True,
    }
    data = json.dumps(payload).encode()
    max_attempts = 4
    base_delay = 5.0

    for attempt in range(max_attempts):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                if result.get("ok"):
                    logger.info(f"Telegram webhook registered: {webhook_url}")
                    return True
                logger.error(f"Failed to register webhook: {result}")
                return False
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_attempts - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Telegram rate limit (429) when registering webhook, retrying in %.0fs (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(delay)
                continue
            logger.error(f"Error registering webhook: {e}")
            return False
        except Exception as e:
            logger.error(f"Error registering webhook: {e}")
            return False
    return False


def get_webhook_url() -> Optional[str]:
    """Resolve webhook URL: env GLITCH_TELEGRAM_WEBHOOK_URL, else Lambda function URL by name.
    
    Returns:
        Webhook URL if found, None otherwise
    """
    url = os.getenv("GLITCH_TELEGRAM_WEBHOOK_URL")
    if url:
        return url
    function_name = os.getenv("GLITCH_TELEGRAM_WEBHOOK_FUNCTION_NAME", "glitch-telegram-webhook")
    try:
        from glitch.aws_utils import get_client
        lambda_client = get_client("lambda")
        resp = lambda_client.get_function_url_config(FunctionName=function_name)
        return resp.get("FunctionUrl")
    except Exception as e:
        logger.warning(f"Failed to get webhook URL from Lambda {function_name}: {e}")
    return None


_startup_time = _time.time()

# Component health state — updated by background tasks, readable via /api/status.
_protect_health: dict = {
    "protect_configured": False,
    "protect_db": "unchecked",
    "protect_poller": "stopped",
    "protect_processor": "stopped",
}

_protect_pollers: dict = {}
_protect_processors: dict = {}
_protect_patrols: dict = {}
_protect_camera_ids_by_site: dict = {}
_protect_site_configs: dict = {}


async def _start_protect_site(site_cfg) -> None:
    """Start poller, event processor, and patrol for a single Protect site."""
    global _protect_pollers, _protect_processors, _protect_patrols, _protect_camera_ids_by_site, _protect_site_configs

    from glitch.protect.client import get_client_for_config
    from glitch.protect.config import SiteConfig

    site_id = site_cfg.site_id
    protect_cfg = site_cfg.protect
    _protect_site_configs[site_id] = site_cfg

    client = get_client_for_config(site_id, protect_cfg)

    if protect_cfg.use_api_key:
        logger.info("[%s] Protect auth: API key", site_id)
    else:
        try:
            await client._authenticate()
            logger.info("[%s] Protect pre-auth (cookie) succeeded", site_id)
        except Exception as auth_exc:
            logger.warning("[%s] Protect pre-auth failed: %s — poller will retry", site_id, auth_exc)

    from glitch.protect.poller import ProtectEventPoller
    poller = ProtectEventPoller(protect_client=client, config=protect_cfg, site_id=site_id)
    await poller.start()
    _protect_pollers[site_id] = poller
    _protect_health["protect_poller"] = "running"

    camera_ids: list = []
    try:
        cameras = await client.get_cameras()
        camera_ids = [c["id"] for c in cameras if isinstance(c, dict)]
        _protect_camera_ids_by_site[site_id] = camera_ids
        logger.info("[%s] Protect cameras fetched: %d", site_id, len(camera_ids))
    except Exception as exc:
        logger.warning("[%s] Failed to fetch cameras: %s", site_id, exc)

    try:
        from glitch.protect.event_processor import ProtectEventProcessor
        processor = ProtectEventProcessor()
        await processor.start(
            camera_ids=camera_ids,
            check_interval=float(os.environ.get("GLITCH_PROTECT_CHECK_INTERVAL", "120")),
        )
        _protect_processors[site_id] = processor
        _protect_health["protect_processor"] = "running"
        logger.info("[%s] Event processor started for %d cameras", site_id, len(camera_ids))
    except Exception as exc:
        _protect_health["protect_processor"] = f"error: {exc}"
        logger.warning("[%s] Failed to start event processor: %s", site_id, exc, exc_info=True)

    try:
        from glitch.protect.patrol import CameraPatrol
        patrol = CameraPatrol(
            protect_client=client,
            interval_seconds=int(os.environ.get("GLITCH_PROTECT_PATROL_INTERVAL", "600")),
            site_id=site_id,
        )
        _protect_patrols[site_id] = patrol
        if camera_ids:
            await patrol.start(camera_ids)
            logger.info("[%s] Camera patrol started for %d cameras", site_id, len(camera_ids))
        else:
            logger.warning("[%s] No camera IDs — camera patrol not started (watchdog will retry seed)", site_id)
    except Exception as exc:
        logger.warning("[%s] Failed to start camera patrol: %s", site_id, exc, exc_info=True)


async def _start_protect_subsystem() -> None:
    """Initialize Protect DB, poller, and event processor in the background.

    Launched as an asyncio task from main() before run_server_async() so the
    /ping health check can respond immediately while SSM, DB, and WS connections
    complete in the background.
    """
    # Wait for the health check to pass before making outbound connections.
    await asyncio.sleep(10)

    from glitch.protect.config import is_protect_configured

    try:
        configured = is_protect_configured()
    except Exception as exc:
        logger.warning("Could not check Protect config: %s — skipping", exc)
        configured = False

    _protect_health["protect_configured"] = configured
    if not configured:
        logger.info("Protect not configured — skipping event poller")
        return

    # Start pool initialisation as a non-blocking background task.
    # Tools call get_pool() which fast-fails with RuntimeError when the pool
    # isn't ready yet, so they never block the request path.
    async def _db_init_watcher():
        from glitch.protect.db import init_pool_background, is_pool_available
        await init_pool_background()
        if is_pool_available():
            _protect_health["protect_db"] = "ok"
            logger.info("Protect DB pool initialised")
        else:
            _protect_health["protect_db"] = "failed"

    asyncio.create_task(_db_init_watcher(), name="protect-db-init")

    from glitch.protect.config import get_all_site_configs
    site_configs = get_all_site_configs()
    if not site_configs:
        logger.warning("No Protect sites configured — skipping poller/processor/patrol")
        return

    for site_cfg in site_configs:
        await _start_protect_site(site_cfg)

    asyncio.create_task(_daily_report_loop(), name="daily-report")
    asyncio.create_task(_daily_briefing_loop(), name="daily-briefing")
    asyncio.create_task(_weekly_fp_learning_loop(), name="weekly-fp-learning")
    asyncio.create_task(_weekly_threshold_optimization_loop(), name="weekly-threshold-opt")
    asyncio.create_task(_health_writer_loop(), name="health-writer")
    asyncio.create_task(_protect_watchdog_loop(), name="protect-watchdog")
    logger.info(
        "Protect subsystem started: %d site(s) (poller + processor + patrol + watchdog)",
        len(site_configs),
    )


async def _protect_watchdog_loop() -> None:
    """Watchdog: check Protect subsystem health every 60s and restart stopped components.

    Detects:
    - Event processor stopped (running=False or all workers done)
    - Poller tasks all completed/cancelled (WS lost and not reconnecting)
    - Camera patrol stopped
    - Sites with 0 cameras (e.g. port forward not ready at startup): retries camera
      seed and starts processor/patrol when cameras appear.
    Restarts each component independently using the stored camera IDs.
    """
    global _protect_pollers, _protect_processors, _protect_patrols, _protect_camera_ids_by_site, _protect_site_configs

    _WATCHDOG_INTERVAL = int(os.environ.get("GLITCH_PROTECT_WATCHDOG_INTERVAL", "60"))
    _check_interval = float(os.environ.get("GLITCH_PROTECT_CHECK_INTERVAL", "120"))

    while True:
        await asyncio.sleep(_WATCHDOG_INTERVAL)

        # Retry camera seed for sites that have 0 cameras (e.g. site2 when port forward wasn't ready).
        for site_id in list(_protect_pollers.keys()):
            if _protect_camera_ids_by_site.get(site_id):
                continue
            site_cfg = _protect_site_configs.get(site_id)
            if not site_cfg:
                continue
            try:
                from glitch.protect.client import get_client_for_config
                client = get_client_for_config(site_id, site_cfg.protect)
                cameras = await client.get_cameras()
                new_ids = [c["id"] for c in cameras if isinstance(c, dict)]
                if not new_ids:
                    continue
                _protect_camera_ids_by_site[site_id] = new_ids
                processor = _protect_processors.get(site_id)
                if processor:
                    await processor.start(camera_ids=new_ids, check_interval=_check_interval)
                    _protect_health["protect_processor"] = "running"
                # Create patrol if not yet started for this site
                if site_id not in _protect_patrols:
                    from glitch.protect.patrol import CameraPatrol
                    patrol = CameraPatrol(
                        protect_client=client,
                        interval_seconds=int(os.environ.get("GLITCH_PROTECT_PATROL_INTERVAL", "600")),
                        site_id=site_id,
                    )
                    await patrol.start(new_ids)
                    _protect_patrols[site_id] = patrol
                else:
                    await _protect_patrols[site_id].start(new_ids)
                logger.info(
                    "Watchdog[%s]: camera seed succeeded (%d cameras) — processor and patrol started",
                    site_id, len(new_ids),
                )
            except Exception as exc:
                logger.debug("Watchdog[%s]: camera seed retry failed: %s", site_id, exc)

        for site_id, processor in list(_protect_processors.items()):
            try:
                status = processor.get_status()
            except Exception:
                status = {"running": False}
            if not status.get("running"):
                logger.warning("Watchdog[%s]: event processor stopped — restarting", site_id)
                try:
                    camera_ids = _protect_camera_ids_by_site.get(site_id, [])
                    await processor.start(
                        camera_ids=camera_ids,
                        check_interval=_check_interval,
                    )
                    _protect_health["protect_processor"] = "running"
                    logger.info("Watchdog[%s]: event processor restarted", site_id)
                except Exception as exc:
                    _protect_health["protect_processor"] = f"watchdog_error: {exc}"
                    logger.error("Watchdog[%s]: failed to restart event processor: %s", site_id, exc)

        for site_id, poller in list(_protect_pollers.items()):
            tasks = getattr(poller, "_tasks", [])
            if tasks and all(t.done() for t in tasks):
                logger.warning("Watchdog[%s]: all poller tasks done — restarting", site_id)
                try:
                    await poller.start()
                    _protect_health["protect_poller"] = "running"
                    logger.info("Watchdog[%s]: poller restarted", site_id)
                except Exception as exc:
                    _protect_health["protect_poller"] = f"watchdog_error: {exc}"
                    logger.error("Watchdog[%s]: failed to restart poller: %s", site_id, exc)

        for site_id, patrol in list(_protect_patrols.items()):
            camera_ids = _protect_camera_ids_by_site.get(site_id, [])
            if not getattr(patrol, "_running", False) and camera_ids:
                logger.warning("Watchdog[%s]: camera patrol stopped — restarting", site_id)
                try:
                    await patrol.start(camera_ids)
                    logger.info("Watchdog[%s]: camera patrol restarted", site_id)
                except Exception as exc:
                    logger.error("Watchdog[%s]: failed to restart patrol: %s", site_id, exc)


async def _daily_report_loop() -> None:
    """Send a daily surveillance summary to Telegram at 08:00 UTC."""
    report_hour = int(os.environ.get("GLITCH_PROTECT_REPORT_HOUR", "8"))
    while True:
        now = datetime.now(timezone.utc)
        next_run = now.replace(hour=report_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())

        try:
            from glitch.protect.learning import generate_security_report
            from glitch.tools.ops_telegram_tools import send_telegram_alert

            now = datetime.now(timezone.utc)
            yesterday_dt = now - timedelta(days=1)
            result = await generate_security_report(start_date=yesterday_dt, end_date=now)
            report = result.get("report_data", result)

            event_stats = report.get("event_statistics", [])
            total = sum(row.get("count", 0) for row in event_stats) if isinstance(event_stats, list) else 0
            yesterday = yesterday_dt.date()
            alerts = report.get("alert_accuracy", {}).get("total_alerts", 0)
            rec_list = report.get("recommendations", [])
            recommendations = "\n".join(f"• {r}" for r in rec_list) if rec_list else ""

            lines = [
                f"📊 <b>Daily Surveillance Report — {yesterday}</b>",
                "",
                f"Events processed: {total}",
                f"Alerts sent: {alerts}",
            ]
            if recommendations:
                lines += ["", recommendations]

            await send_telegram_alert.__wrapped__(
                message="\n".join(lines),
                severity="low",
                component="DailyReport",
            )
            logger.info("Daily report sent for %s", yesterday)
        except Exception as exc:
            logger.error("Daily report failed: %s", exc, exc_info=True)


async def _daily_briefing_loop() -> None:
    """Send a daily security briefing to Telegram covering overnight activity."""
    briefing_hour = int(os.environ.get("GLITCH_PROTECT_BRIEFING_HOUR", "7"))
    while True:
        now = datetime.now(timezone.utc)
        next_run = now.replace(hour=briefing_hour, minute=0, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())

        try:
            from glitch.protect.learning import generate_daily_briefing
            from glitch.tools.ops_telegram_tools import send_telegram_alert

            result = await generate_daily_briefing()
            message = result.get("briefing_message", "")
            if message:
                await send_telegram_alert.__wrapped__(
                    message=message,
                    severity="low",
                    component="DailyBriefing",
                )
            logger.info("Daily briefing sent: assessment=%s", result.get("assessment"))
        except Exception as exc:
            logger.error("Daily briefing failed: %s", exc, exc_info=True)


async def _weekly_fp_learning_loop() -> None:
    """Run false-positive root-cause analysis every Sunday and auto-apply corrections."""
    fp_learn_hour = int(os.environ.get("GLITCH_PROTECT_FP_LEARN_HOUR", "6"))
    while True:
        now = datetime.now(timezone.utc)
        # Advance to the next Sunday (weekday 6) at the configured hour
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0:
            candidate = now.replace(hour=fp_learn_hour, minute=0, second=0, microsecond=0)
            if candidate <= now:
                days_until_sunday = 7
        next_run = (now + timedelta(days=days_until_sunday)).replace(
            hour=fp_learn_hour, minute=0, second=0, microsecond=0
        )
        await asyncio.sleep((next_run - now).total_seconds())

        try:
            from glitch.protect.learning import learn_from_false_positives
            from glitch.tools.ops_telegram_tools import send_telegram_alert

            result = await learn_from_false_positives(lookback_days=7)
            applied = result.get("corrections_applied", [])
            analyzed = result.get("false_positives_analyzed", 0)
            logger.info(
                "FP learning complete: analyzed=%d applied=%d", analyzed, len(applied)
            )
            if applied:
                await send_telegram_alert.__wrapped__(
                    message=(
                        f"🧠 <b>Weekly FP Learning</b>\n\n"
                        f"Analyzed {analyzed} false positives.\n"
                        f"Auto-applied {len(applied)} corrections."
                    ),
                    severity="low",
                    component="FPLearning",
                )
        except Exception as exc:
            logger.error("Weekly FP learning failed: %s", exc, exc_info=True)


async def _weekly_threshold_optimization_loop() -> None:
    """Optimize per-camera alert thresholds every Sunday based on FP feedback."""
    fp_learn_hour = int(os.environ.get("GLITCH_PROTECT_FP_LEARN_HOUR", "6"))
    opt_hour = fp_learn_hour + 1  # Run one hour after FP learning
    while True:
        now = datetime.now(timezone.utc)
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0:
            candidate = now.replace(hour=opt_hour, minute=0, second=0, microsecond=0)
            if candidate <= now:
                days_until_sunday = 7
        next_run = (now + timedelta(days=days_until_sunday)).replace(
            hour=opt_hour, minute=0, second=0, microsecond=0
        )
        await asyncio.sleep((next_run - now).total_seconds())

        try:
            from glitch.protect.learning import optimize_alert_thresholds
            from glitch.tools.ops_telegram_tools import send_telegram_alert

            result = await optimize_alert_thresholds(lookback_days=30)
            applied = result.get("applied_changes", [])
            cameras = result.get("cameras_analyzed", 0)
            logger.info(
                "Threshold optimization complete: cameras=%d applied=%d", cameras, len(applied)
            )
            if applied:
                await send_telegram_alert.__wrapped__(
                    message=(
                        f"⚙️ <b>Weekly Threshold Optimization</b>\n\n"
                        f"Analyzed {cameras} cameras.\n"
                        f"Updated thresholds for {len(applied)} camera(s)."
                    ),
                    severity="low",
                    component="ThresholdOpt",
                )
        except Exception as exc:
            logger.error("Weekly threshold optimization failed: %s", exc, exc_info=True)


async def _health_writer_loop() -> None:
    """Write Glitch component health to the Protect DB every 60 seconds."""
    while True:
        try:
            from glitch.protect.db import upsert_sentinel_health
            now = int(_time.time())
            db_ok = _protect_health.get("protect_db") == "ok"
            poller_ok = _protect_health.get("protect_poller") == "running"
            overall = "Healthy" if (db_ok and poller_ok) else "Degraded"
            await upsert_sentinel_health(
                status=overall,
                protect_db=str(_protect_health.get("protect_db", "unchecked")),
                protect_poller=str(_protect_health.get("protect_poller", "stopped")),
                protect_processor=str(_protect_health.get("protect_processor", "stopped")),
                protect_configured=bool(_protect_health.get("protect_configured", False)),
                uptime_seconds=now - int(_startup_time),
            )
        except Exception as exc:
            logger.debug("Health writer: could not update DB: %s", exc)
        await asyncio.sleep(60)


async def _shutdown_protect_subsystem() -> None:
    """Gracefully stop the Protect poller, processor, patrol, and DB pool."""
    global _protect_processors, _protect_pollers, _protect_patrols
    for processor in _protect_processors.values():
        try:
            await processor.stop()
        except Exception:
            pass
    for patrol in _protect_patrols.values():
        try:
            patrol.stop()
        except Exception:
            pass
    for poller in _protect_pollers.values():
        try:
            poller.stop()
        except Exception:
            pass
    try:
        from glitch.protect.db import close_pool
        await close_pool()
    except Exception:
        pass
    try:
        from glitch.protect.client import reset_client
        await reset_client()
    except Exception:
        pass
    logger.info("Protect subsystem shutdown complete")


async def main() -> None:
    """Main execution function.
    
    Initializes telemetry, creates agent, and starts server or interactive mode.
    Optionally starts Telegram channel if bot token is provided.
    """
    print("=" * 60)
    print("GLITCH AGENT STARTUP")
    print("=" * 60)
    print(f"GLITCH_MODE env var: {os.getenv('GLITCH_MODE', 'NOT_SET')}")
    print(f"Python version: {sys.version}")
    print(f"Current working directory: {os.getcwd()}")
    print("=" * 60)
    
    logger.info("Starting Glitch agent...")
    logger.info(f"GLITCH_MODE environment variable: {os.getenv('GLITCH_MODE', 'NOT_SET')}")
    
    telemetry_config = get_telemetry_config()
    setup_telemetry(telemetry_config)
    
    agent = bootstrap_agents_and_register()

    logger.info("Glitch agent initialized for session: %s", agent.session_id)
    sys.stdout.flush()
    sys.stderr.flush()

    # Write one event to /glitch/telemetry so you can verify CloudWatch log group and IAM
    write_startup_heartbeat_to_cloudwatch()
    sys.stdout.flush()
    sys.stderr.flush()

    # Skip blocking connectivity check on startup - run on-demand via /status command instead
    # connectivity = await agent.check_connectivity()
    # logger.info(f"Connectivity check: {connectivity}")
    
    # Initialize Telegram channel if bot token is in Secrets Manager
    telegram_channel = None
    telegram_token = get_telegram_bot_token()

    # In AgentCore mode the runtime is in PRIVATE_ISOLATED VPC subnets with no internet egress.
    # Webhook registration (setWebhook → api.telegram.org) must happen in the webhook Lambda,
    # which has full internet access. The runtime only loads DynamoDB config and optionally
    # starts the polling channel in local/non-AgentCore mode.
    is_agentcore = os.path.exists("/app") or "agentcore" in os.getenv("AWS_EXECUTION_ENV", "").lower()

    if telegram_token:
        try:
            config_table = os.getenv("GLITCH_CONFIG_TABLE", "glitch-telegram-config")
            use_dynamodb = os.getenv("GLITCH_CONFIG_BACKEND", "dynamodb").lower() == "dynamodb"

            if use_dynamodb:
                logger.info("Using DynamoDB config backend (table: %s)", config_table)
                config_manager = DynamoDBConfigManager(table_name=config_table)
                config = config_manager.load(bot_token=telegram_token)

                if is_agentcore:
                    # Webhook registration is handled by the glitch-telegram-webhook Lambda
                    # on its cold start (it has internet access; this container does not).
                    logger.info("AgentCore mode: webhook registration delegated to glitch-telegram-webhook Lambda")
                else:
                    # Local mode: register webhook and start polling channel
                    webhook_url = get_webhook_url()
                    if webhook_url:
                        webhook_secret = config_manager.get_webhook_secret()
                        if register_telegram_webhook(telegram_token, webhook_url, webhook_secret):
                            config_manager.set_webhook_url(webhook_url)
                            logger.info("Telegram webhook registered: %s", webhook_url)
                        else:
                            logger.warning("Failed to register Telegram webhook")
                    else:
                        logger.info("No webhook URL configured (GLITCH_TELEGRAM_WEBHOOK_URL not set)")
            else:
                config_dir = os.getenv("GLITCH_CONFIG_DIR")
                config_path = Path(config_dir) if config_dir else None
                config_manager = ConfigManager(config_dir=config_path)
                config = config_manager.load(bot_token=telegram_token)

            if not is_agentcore:
                # Local / non-AgentCore: start the polling channel
                logger.info("Starting Telegram polling channel...")
                bootstrap = OwnerBootstrap(config_manager)
                poet_agent = create_poet_agent()
                telegram_channel = TelegramChannel(
                    config_manager=config_manager,
                    bootstrap=bootstrap,
                    agent=agent,
                    poet_agent=poet_agent,
                )
                await telegram_channel.start()
                logger.info("Telegram channel started successfully")
            else:
                logger.info("AgentCore mode: webhook Lambda handles incoming messages; polling channel not started")

        except Exception as e:
            logger.error("Failed to initialize Telegram: %s", e, exc_info=True)
            # Continue without Telegram if it fails
    else:
        logger.info("No Telegram bot token found in Secrets Manager (%s), skipping Telegram",
                    os.getenv("GLITCH_TELEGRAM_SECRET_NAME", "glitch/telegram-bot-token"))
    
    mode = os.getenv("GLITCH_MODE", "server")
    logger.info(f"Mode determined: {mode}")
    print(f"Starting in {mode} mode")

    try:
        if mode == "interactive":
            logger.warning("INTERACTIVE MODE - This will fail in containers without stdin!")
            print("ERROR: Interactive mode requested but container has no stdin")
            await interactive_mode(agent)
        else:
            logger.info("Starting HTTP server")
            server_config = get_server_config()
            print(f"Starting HTTP server on {server_config.host}:{server_config.port}")

            # Start the Protect subsystem as a background task before entering the
            # uvicorn event loop. Both share the same asyncio loop so DB connections,
            # WebSocket pollers, and the daily-report scheduler run alongside the server.
            asyncio.create_task(_start_protect_subsystem(), name="protect-startup")

            from glitch.server import run_server_async
            await run_server_async(agent, server_config)
    finally:
        # Clean up Telegram channel on shutdown
        if telegram_channel:
            logger.info("Shutting down Telegram channel...")
            try:
                await telegram_channel.stop()
            except Exception as e:
                logger.error(f"Error stopping Telegram channel: {e}")
        # Shut down Protect subsystem gracefully
        await _shutdown_protect_subsystem()


async def interactive_mode(agent: GlitchAgent) -> None:
    """Run agent in interactive CLI mode.
    
    Args:
        agent: GlitchAgent instance to interact with
    """
    print("\n" + "=" * 60)
    print("Glitch Agent - Interactive Mode")
    print("=" * 60)
    print(f"Session ID: {agent.session_id}")
    print(f"Memory ID: {agent.memory_id}")
    print("\nType 'quit' or 'exit' to stop, 'status' for agent status.")
    print("=" * 60 + "\n")
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ["quit", "exit"]:
                print("\nShutting down Glitch agent...")
                break
            
            if user_input.lower() == "status":
                status = agent.get_status()
                print(f"\n{status}")
                continue
            
            response: InvocationResponse = await agent.process_message(user_input)
            print(f"\nGlitch: {response.get('message', '')}")
            
            metrics = response.get("metrics")
            if metrics:
                token_usage = metrics.get("token_usage", {})
                print(
                    f"\n[Tokens: {token_usage.get('input_tokens', 0)}in/"
                    f"{token_usage.get('output_tokens', 0)}out]"
                )
            
        except KeyboardInterrupt:
            print("\n\nInterrupted. Shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in interactive mode: {e}")
            print(f"\nError: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
