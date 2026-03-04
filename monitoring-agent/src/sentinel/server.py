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

import logging
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

from fastapi import FastAPI
from strands.multiagent.a2a import A2AServer

from sentinel.agent import get_sentinel_agent

logger = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

# Runtime URL injected by AgentCore (used for Agent Card's url field)
RUNTIME_URL = os.environ.get("AGENTCORE_RUNTIME_URL", "http://127.0.0.1:9000/")

_startup_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: start optional protect poller on startup, clean up on shutdown."""
    _poller_task: Optional[object] = None

    try:
        from sentinel.protect.config import is_protect_configured, is_db_configured
        from sentinel.protect.poller import ProtectEventPoller
        from sentinel.protect.db import get_pool
        from sentinel.protect.client import get_client as get_protect_client
        from sentinel.protect.config import get_protect_config

        if is_protect_configured() and is_db_configured():
            logger.info("Protect config detected — initialising DB pool and event poller")
            await get_pool()  # initialises pool + applies schema on first call
            poller = ProtectEventPoller(
                protect_client=get_protect_client(),
                config=get_protect_config(),
            )
            _poller_task = await poller.start()
        else:
            logger.info(
                "Protect not configured (GLITCH_PROTECT_HOST or DB config missing) — "
                "skipping event poller"
            )
    except ImportError as exc:
        logger.warning("Protect modules not available: %s — poller not started", exc)
    except Exception as exc:
        logger.warning("Failed to start Protect poller: %s — continuing without it", exc)

    yield  # server runs here

    # Shutdown
    if _poller_task is not None:
        try:
            _poller_task.cancel()  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        from sentinel.protect.db import close_pool
        await close_pool()
    except Exception:
        pass
    logger.info("Sentinel shutdown complete")


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
        return {
            "status": "Healthy",
            "agent": "Sentinel",
            "time_of_last_update": int(time.time()),
            "uptime_seconds": int(time.time() - _startup_time),
        }

    # Mount the A2A app last so it acts as the default handler for POST /
    # and GET /.well-known/agent-card.json without shadowing /ping.
    application.mount("/", a2a_server.to_fastapi_app())
    logger.info(f"Sentinel A2A server mounted at / (runtime_url={RUNTIME_URL})")
    return application


app = create_app()
