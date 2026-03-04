"""UniFi Protect API client.

Async httpx client with cookie-based auth. Re-authenticates on 401.
Endpoints depend on Protect version; tested against Protect 4.x.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from sentinel.protect.config import ProtectConfig, get_protect_config

logger = logging.getLogger(__name__)

_client_instance: Optional["ProtectClient"] = None


class ProtectAuthError(Exception):
    """Raised when authentication fails."""


class ProtectAPIError(Exception):
    """Raised on non-2xx API responses."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"Protect API error {status_code}: {message}")


class ProtectClient:
    """Async UniFi Protect API client with session management."""

    def __init__(self, config: ProtectConfig):
        self._config = config
        self._base_url = f"https://{config.host}:{config.port}"
        self._cookies: Dict[str, str] = {}
        self._csrf_token: Optional[str] = None
        self._http = httpx.AsyncClient(
            verify=config.verify_ssl,
            timeout=30.0,
            follow_redirects=True,
        )

    async def _authenticate(self) -> None:
        """Authenticate and store session cookies."""
        url = f"{self._base_url}/api/auth/login"
        payload = {
            "username": self._config.username,
            "password": self._config.password,
            "rememberMe": True,
        }
        try:
            response = await self._http.post(url, json=payload)
            if response.status_code not in (200, 201):
                raise ProtectAuthError(
                    f"Authentication failed: HTTP {response.status_code}"
                )
            self._cookies = dict(response.cookies)
            # Extract CSRF token from headers if present
            csrf = response.headers.get("x-csrf-token") or response.headers.get("X-CSRF-Token")
            if csrf:
                self._csrf_token = csrf
            logger.info("Protect authentication successful")
        except httpx.RequestError as e:
            raise ProtectAuthError(f"Authentication request failed: {e}") from e

    async def _request(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        """Make an authenticated request, re-authenticating on 401."""
        if not self._cookies:
            await self._authenticate()

        headers = kwargs.pop("headers", {})
        if self._csrf_token:
            headers["x-csrf-token"] = self._csrf_token

        url = f"{self._base_url}{path}"
        response = await self._http.request(
            method,
            url,
            cookies=self._cookies,
            headers=headers,
            **kwargs,
        )

        if response.status_code == 401:
            # Re-authenticate and retry once
            logger.info("Protect session expired, re-authenticating")
            self._cookies = {}
            await self._authenticate()
            headers = {}
            if self._csrf_token:
                headers["x-csrf-token"] = self._csrf_token
            response = await self._http.request(
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

    async def get_cameras(self) -> List[Dict[str, Any]]:
        """List all cameras."""
        data = await self._request("GET", "/proxy/protect/api/cameras")
        return data if isinstance(data, list) else data.get("data", [])

    async def get_events(
        self,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
        camera_ids: Optional[List[str]] = None,
        event_types: Optional[List[str]] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query events with optional filters."""
        params: Dict[str, Any] = {"limit": limit}
        if start:
            params["start"] = int(start.timestamp() * 1000)
        if end:
            params["end"] = int(end.timestamp() * 1000)
        if camera_ids:
            params["cameras"] = ",".join(camera_ids)
        if event_types:
            params["types"] = ",".join(event_types)

        data = await self._request("GET", "/proxy/protect/api/events", params=params)
        return data if isinstance(data, list) else data.get("data", [])

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
            f"/proxy/protect/api/cameras/{camera_id}/snapshot",
            params=params,
        )
        return data  # bytes

    async def get_event_thumbnail(self, event_id: str) -> bytes:
        """Get event thumbnail as raw image bytes."""
        data = await self._request(
            "GET",
            f"/proxy/protect/api/events/{event_id}/thumbnail",
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
            "/proxy/protect/api/video/export",
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
            f"/proxy/protect/api/cameras/{camera_id}",
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
