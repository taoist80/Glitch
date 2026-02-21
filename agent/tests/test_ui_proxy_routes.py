"""Tests for UI proxy routes: ProxyApp, bounded sessions, and HTTP handlers."""

import pytest
from unittest.mock import AsyncMock, patch

from starlette.applications import Starlette
from starlette.testclient import TestClient
from starlette.routing import Route

from glitch.ui_proxy_routes import (
    _BoundedSessionDict,
    ProxyApp,
    create_proxy_app,
)


class TestBoundedSessionDict:
    """Tests for _BoundedSessionDict eviction."""

    def test_evicts_oldest_when_over_max(self):
        # Use a small max for the test
        class SmallBounded(_BoundedSessionDict):
            MAX = 3

        d: SmallBounded = SmallBounded()
        d["a"] = "s1"
        d["b"] = "s2"
        d["c"] = "s3"
        assert len(d) == 3
        assert list(d.keys()) == ["a", "b", "c"]
        d["d"] = "s4"
        assert len(d) == 3
        assert "a" not in d
        assert list(d.keys()) == ["b", "c", "d"]

    def test_holds_up_to_max(self):
        class SmallBounded(_BoundedSessionDict):
            MAX = 2

        d: SmallBounded = SmallBounded()
        d["x"] = "1"
        d["y"] = "2"
        assert d["x"] == "1"
        assert d["y"] == "2"


class TestCreateProxyApp:
    """Tests for create_proxy_app and ProxyApp."""

    def test_returns_proxy_app(self):
        proxy = create_proxy_app()
        assert isinstance(proxy, ProxyApp)
        assert proxy.api_router is not None
        assert proxy.invocations_handler is not None

    def test_proxy_app_is_asgi_callable(self):
        """ProxyApp __call__ delegates to api_router (ASGI)."""
        proxy = create_proxy_app()
        assert callable(proxy)
        # Same ASGI interface as the router
        assert hasattr(proxy.api_router, "__call__")


class TestProxyApiHandler:
    """Tests for _proxy_api_handler via TestClient on the proxy api_router."""

    def test_options_returns_cors_headers(self):
        proxy = create_proxy_app()
        with patch(
            "glitch.ui_proxy_routes.invoke_deployed_agent_async",
            new_callable=AsyncMock,
            return_value={},
        ):
            with TestClient(proxy.api_router) as client:
                resp = client.options("/any/path")
        assert resp.status_code == 204
        assert "access-control-allow-origin" in [h.lower() for h in resp.headers.keys()]
        assert "access-control-allow-methods" in [h.lower() for h in resp.headers.keys()]

    def test_get_status_invokes_agent_and_returns_json(self):
        proxy = create_proxy_app()
        mock_result = {"session_id": "s1", "memory_id": "m1"}
        with patch(
            "glitch.ui_proxy_routes.invoke_deployed_agent_async",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            with TestClient(proxy.api_router) as client:
                resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == "s1"
        assert data["memory_id"] == "m1"


class TestProxyInvocationsHandler:
    """Tests for _proxy_invocations_handler."""

    def test_invalid_json_returns_400(self):
        proxy = create_proxy_app()
        # Mount single route POST / so we can call the handler via TestClient
        from starlette.applications import Starlette
        app = Starlette(routes=[Route("/", proxy.invocations_handler, methods=["POST"])])
        with TestClient(app) as client:
            resp = client.post(
                "/", content="not json", headers={"Content-Type": "text/plain"}
            )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_success_returns_agent_response(self):
        proxy = create_proxy_app()
        app = Starlette(routes=[Route("/", proxy.invocations_handler, methods=["POST"])])
        with patch(
            "glitch.ui_proxy_routes.invoke_deployed_agent_async",
            new_callable=AsyncMock,
            return_value={"message": "Hi", "session_id": "s2"},
        ):
            with TestClient(app) as client:
                resp = client.post("/", json={"prompt": "Hello"})
        assert resp.status_code == 200
        assert resp.json()["message"] == "Hi"
        assert resp.json()["session_id"] == "s2"
