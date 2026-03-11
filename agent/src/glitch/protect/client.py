"""UniFi Protect API client.

Supports two auth modes:
1. API key (recommended) — static ``X-API-KEY`` header, uses the public
   integration API at ``/proxy/protect/integration/v1/…``.
2. Cookie auth (legacy) — ``/api/auth/login`` session cookies, uses the
   private API at ``/proxy/protect/api/…``.  Re-authenticates on 401.

The mode is selected automatically based on whether ``ProtectConfig.api_key``
is set.  All public methods are mode-agnostic.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from glitch.protect.config import ProtectConfig, get_protect_config, parse_host_port

logger = logging.getLogger(__name__)

_client_instance: Optional["ProtectClient"] = None

_PRIVATE_API_PREFIX = "/proxy/protect/api"
_PUBLIC_API_PREFIX = "/proxy/protect/integration/v1"


class ProtectAuthError(Exception):
    """Raised when authentication fails."""


class ProtectRateLimitError(ProtectAuthError):
    """Raised when the controller returns HTTP 429."""

    def __init__(self, retry_after: float = 60.0):
        self.retry_after = retry_after
        super().__init__(f"Rate limited by controller — retry after {retry_after:.0f}s")


class ProtectAPIError(Exception):
    """Raised on non-2xx API responses."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Protect API error {status_code}: {message}")


class ProtectClient:
    """Async UniFi Protect API client with session management."""

    def __init__(self, config: ProtectConfig):
        self._config = config

        # Parse host (may include port, e.g. "protect.awoo.agency:8443").
        hostname, effective_port = parse_host_port(config.host, config.port)

        if effective_port == 443:
            self._base_url = f"https://{hostname}"
        else:
            self._base_url = f"https://{hostname}:{effective_port}"

        self._hostname = hostname
        self._effective_port = effective_port

        self._use_api_key = config.use_api_key
        self._api_prefix = _PUBLIC_API_PREFIX if self._use_api_key else _PRIVATE_API_PREFIX

        self._cookies: Dict[str, str] = {}
        self._csrf_token: Optional[str] = None
        self._auth_lock = asyncio.Lock()
        self._http = self._new_http_client()

    def _new_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            verify=self._config.verify_ssl,
            timeout=30.0,
            follow_redirects=True,
        )

    def _ensure_http_client(self) -> httpx.AsyncClient:
        """Return a live httpx client, recreating it if the previous one was closed."""
        if self._http.is_closed:
            logger.info("Protect httpx client was closed — recreating")
            self._http = self._new_http_client()
        return self._http

    @property
    def auth_mode(self) -> str:
        return "api_key" if self._use_api_key else "cookie"

    # ------------------------------------------------------------------
    # Cookie auth (legacy) — only used when no API key is configured
    # ------------------------------------------------------------------

    async def _authenticate(self) -> None:
        """Authenticate via username/password and store session cookies.

        Skipped entirely when API key auth is active.
        """
        if self._use_api_key:
            return

        async with self._auth_lock:
            if self._cookies:
                return

            url = f"{self._base_url}/api/auth/login"
            payload = {
                "username": self._config.username,
                "password": self._config.password,
                "rememberMe": True,
            }
            try:
                http = self._ensure_http_client()
                response = await http.post(url, json=payload)
                if response.status_code == 429:
                    retry_after = float(
                        response.headers.get("Retry-After", "60")
                    )
                    raise ProtectRateLimitError(retry_after)
                if response.status_code not in (200, 201):
                    raise ProtectAuthError(
                        f"Authentication failed: HTTP {response.status_code}"
                    )
                self._cookies = dict(response.cookies)
                csrf = response.headers.get("x-csrf-token") or response.headers.get("X-CSRF-Token")
                if csrf:
                    self._csrf_token = csrf
                logger.info("Protect cookie authentication successful")
            except httpx.RequestError as e:
                raise ProtectAuthError(f"Authentication request failed: {e}") from e

    # ------------------------------------------------------------------
    # Core request dispatcher
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        """Make an authenticated request.

        API key mode: sends X-API-KEY header, no cookies.
        Cookie mode: sends session cookies, re-authenticates on 401.
        """
        headers = kwargs.pop("headers", {})

        if self._use_api_key:
            headers["X-API-KEY"] = self._config.api_key
        else:
            if not self._cookies:
                await self._authenticate()
            if self._csrf_token:
                headers["x-csrf-token"] = self._csrf_token

        url = f"{self._base_url}{path}"
        try:
            http = self._ensure_http_client()
            response = await http.request(
                method,
                url,
                cookies=self._cookies if not self._use_api_key else None,
                headers=headers,
                **kwargs,
            )
        except RuntimeError as exc:
            if "Event loop is closed" in str(exc) or "closed" in str(exc).lower():
                logger.info("Protect httpx hit stale event loop — recreating client and retrying")
                self._http = self._new_http_client()
                response = await self._http.request(
                    method,
                    url,
                    cookies=self._cookies if not self._use_api_key else None,
                    headers=headers,
                    **kwargs,
                )
            else:
                raise

        if response.status_code == 401:
            if self._use_api_key:
                raise ProtectAuthError(
                    "API key rejected (401). Verify the key is valid and the "
                    "account has Super Admin privileges."
                )
            logger.info("Protect session expired, re-authenticating")
            self._cookies.clear()
            self._csrf_token = None
            await self._authenticate()
            headers = {}
            if self._csrf_token:
                headers["x-csrf-token"] = self._csrf_token
            http = self._ensure_http_client()
            response = await http.request(
                method,
                url,
                cookies=self._cookies,
                headers=headers,
                **kwargs,
            )

        if response.status_code >= 400:
            raise ProtectAPIError(response.status_code, response.text[:500])

        if response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response.content

    # ------------------------------------------------------------------
    # Public API methods (path-agnostic — uses self._api_prefix)
    # ------------------------------------------------------------------

    async def get_cameras(self) -> List[Dict[str, Any]]:
        """List all cameras."""
        data = await self._request("GET", f"{self._api_prefix}/cameras")
        return data if isinstance(data, list) else data.get("data", [])

    async def get_events(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        camera_ids: Optional[List[str]] = None,  # kept for call-site compat; silently ignored (API doesn't support it)
        event_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query events from the integration API.

        Note: the UniFi Protect integration API does not support filtering by
        camera_ids via query parameter — passing it causes a 404. Camera
        filtering must be done client-side after fetching.
        """
        params: Dict[str, Any] = {"limit": limit}
        if start:
            params["start"] = int(start.timestamp() * 1000)
        if end:
            params["end"] = int(end.timestamp() * 1000)
        if event_types:
            params["types"] = ",".join(event_types)

        data = await self._request("GET", f"{self._api_prefix}/events", params=params)
        events = data if isinstance(data, list) else data.get("data", [])

        # Client-side camera filter if requested
        if camera_ids:
            camera_set = set(camera_ids)
            events = [e for e in events if e.get("camera") in camera_set]

        return events

    async def get_snapshot(
        self,
        camera_id: str,
        timestamp: Optional[datetime] = None,
        width: int = 1280,
        quality: int = 85,
    ) -> bytes:
        """Get camera snapshot as raw image bytes."""
        params: Dict[str, Any] = {"width": width, "quality": quality}
        if timestamp:
            params["ts"] = int(timestamp.timestamp() * 1000)

        data = await self._request(
            "GET",
            f"{self._api_prefix}/cameras/{camera_id}/snapshot",
            params=params,
        )
        return data

    async def get_event_thumbnail(self, event_id: str) -> bytes:
        """Get event thumbnail as raw image bytes."""
        data = await self._request(
            "GET",
            f"{self._api_prefix}/events/{event_id}/thumbnail",
        )
        return data

    async def get_video_export(
        self,
        camera_id: str,
        start: datetime,
        end: datetime,
    ) -> bytes:
        """Export a video clip as raw bytes."""
        params = {
            "camera": camera_id,
            "start": int(start.timestamp() * 1000),
            "end": int(end.timestamp() * 1000),
        }
        data = await self._request(
            "GET",
            f"{self._api_prefix}/video/export",
            params=params,
        )
        return data

    async def update_camera_settings(
        self,
        camera_id: str,
        settings: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update camera settings via PATCH."""
        return await self._request(
            "PATCH",
            f"{self._api_prefix}/cameras/{camera_id}",
            json=settings,
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._http.aclose()


def get_client() -> ProtectClient:
    """Get or create the singleton Protect client."""
    global _client_instance
    if _client_instance is None:
        config = get_protect_config()
        _client_instance = ProtectClient(config)
    return _client_instance


async def reset_client() -> None:
    """Close and reset the singleton client (for testing or config reload)."""
    global _client_instance
    if _client_instance is not None:
        await _client_instance.close()
        _client_instance = None
