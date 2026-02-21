"""ASGI routes for UI proxy to deployed AgentCore runtime."""

import logging
import os
from collections import OrderedDict
from typing import Awaitable, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from glitch.ui_proxy import (
    create_api_proxy_payload,
    invoke_deployed_agent_async,
)

logger = logging.getLogger(__name__)


class _BoundedSessionDict(OrderedDict):
    """Session storage for proxy mode; max 1000 client IDs, evict oldest when full."""

    MAX = 1000

    def __setitem__(self, key: str, value: str) -> None:
        super().__setitem__(key, value)
        if len(self) > self.MAX:
            self.popitem(last=False)


_proxy_sessions: _BoundedSessionDict = _BoundedSessionDict()

AsyncRouteHandler = Callable[[Request], Awaitable[JSONResponse]]


async def _proxy_api_handler(request: Request) -> JSONResponse:
    """Handle /api/* requests by invoking deployed agent with _ui_api_request payload."""
    if request.method == "OPTIONS":
        return JSONResponse(
            content={},
            status_code=204,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Client-Id",
            },
        )
    path_param = request.path_params.get("path") or ""
    api_path = "/" + path_param.lstrip("/")
    method = request.method
    body = None
    if method in ("POST", "PUT", "PATCH") and request.headers.get("content-length"):
        try:
            body = await request.json()
        except Exception:
            body = None

    payload = create_api_proxy_payload(api_path, method, body)
    agent_name = os.environ.get("GLITCH_DEPLOYED_AGENT_NAME") or os.environ.get("GLITCH_AGENT_NAME", "Glitch")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
    client_id = request.headers.get("x-client-id", "default")
    session_id = _proxy_sessions.get(client_id)

    result = await invoke_deployed_agent_async(
        agent_name=agent_name,
        region=region,
        payload=payload,
        session_id=session_id,
    )
    if "session_id" in result and result.get("session_id"):
        _proxy_sessions[client_id] = result["session_id"]
    # Return 503 when invocation failed so the UI can show the error (e.g. after redeploy)
    if result.get("error"):
        return JSONResponse(
            content=result,
            status_code=503,
            headers={"X-Proxy-Error": "1"},
        )
    return JSONResponse(result)


async def _proxy_invocations_handler(request: Request) -> JSONResponse:
    """Handle POST /invocations by invoking deployed agent with prompt payload."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    agent_name = os.environ.get("GLITCH_DEPLOYED_AGENT_NAME") or os.environ.get("GLITCH_AGENT_NAME", "Glitch")
    region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION", "us-west-2")
    client_id = request.headers.get("x-client-id", "default")
    session_id = _proxy_sessions.get(client_id)

    result = await invoke_deployed_agent_async(
        agent_name=agent_name,
        region=region,
        payload=body,
        session_id=session_id,
    )
    if "session_id" in result and result.get("session_id"):
        _proxy_sessions[client_id] = result["session_id"]
    if result.get("error"):
        return JSONResponse(
            content=result,
            status_code=503,
            headers={"X-Proxy-Error": "1"},
        )
    return JSONResponse(result)


def create_proxy_app() -> "ProxyApp":
    """Create the proxy app and router for mounting at /api or /ui-proxy/api."""
    api_routes = [
        Route(
            "/{path:path}",
            endpoint=_proxy_api_handler,
            methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        ),
    ]
    api_router = Starlette(routes=api_routes)
    return ProxyApp(api_router=api_router, invocations_handler=_proxy_invocations_handler)


class ProxyApp:
    """Holds the API router (for mount) and the invocations route handler."""

    __slots__ = ("api_router", "invocations_handler")

    def __init__(
        self,
        api_router: Starlette,
        invocations_handler: AsyncRouteHandler,
    ) -> None:
        self.api_router = api_router
        self.invocations_handler = invocations_handler

    def __call__(self, scope, receive, send):
        """ASGI: when mounted at /api, delegate to api_router."""
        return self.api_router(scope, receive, send)
