"""Tests for server UI API handling: _handle_ui_api_request routing.

Requires bedrock_agentcore and fastapi (runtime deps). Skipped when not installed.
"""

import pytest

pytest.importorskip("bedrock_agentcore")
pytest.importorskip("fastapi")

import importlib
from unittest.mock import AsyncMock, MagicMock, patch

# Use the actual router module (get_status, get_skills, etc. live here).
# glitch.api.router as a name resolves to the APIRouter instance from api/__init__.py.
router_module = importlib.import_module("glitch.api.router")
from glitch.server import _handle_ui_api_request


def _mock_response(**kwargs):
    m = MagicMock()
    m.model_dump.return_value = kwargs
    return m


class TestHandleUiApiRequest:
    """Tests for _handle_ui_api_request with mocked API handlers."""

    @pytest.mark.asyncio
    async def test_unknown_endpoint_returns_error(self):
        result = await _handle_ui_api_request({"path": "/unknown", "method": "GET"})
        assert "error" in result
        assert "Unknown API endpoint" in result["error"]

    @pytest.mark.asyncio
    async def test_status_get_calls_get_status_and_returns_dict(self):
        with patch.object(router_module, "get_status", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(session_id="s1", memory_id="m1")
            result = await _handle_ui_api_request({"path": "/status", "method": "GET"})
        mock_get.assert_called_once()
        assert result["session_id"] == "s1"
        assert result["memory_id"] == "m1"

    @pytest.mark.asyncio
    async def test_skills_get_calls_get_skills_and_returns_dict(self):
        with patch.object(router_module, "get_skills", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(skills=[], disabled=[])
            result = await _handle_ui_api_request({"path": "/skills", "method": "GET"})
        mock_get.assert_called_once()
        assert "skills" in result

    @pytest.mark.asyncio
    async def test_skill_toggle_missing_skill_id_returns_error(self):
        # Path like /skills//toggle has empty skill_id
        result = await _handle_ui_api_request({
            "path": "/skills//toggle",
            "method": "POST",
            "body": {"enabled": True},
        })
        assert "error" in result
        assert "Missing skill_id" in result["error"]

    @pytest.mark.asyncio
    async def test_skill_toggle_invalid_path_returns_error(self):
        result = await _handle_ui_api_request({
            "path": "/skills",
            "method": "POST",
            "body": {},
        })
        assert "error" in result

    @pytest.mark.asyncio
    async def test_skill_toggle_valid_path_calls_toggle_skill(self):
        with patch.object(router_module, "toggle_skill", new_callable=AsyncMock) as mock_toggle:
            mock_toggle.return_value = _mock_response(skill_id="demo-skill", enabled=True)
            result = await _handle_ui_api_request({
                "path": "/skills/demo-skill/toggle",
                "method": "POST",
                "body": {"enabled": True},
            })
        mock_toggle.assert_called_once()
        assert result.get("skill_id") == "demo-skill"
        assert result.get("enabled") is True

    @pytest.mark.asyncio
    async def test_path_api_prefix_normalized_to_internal_path(self):
        """Request with path /api/status is normalized to /status and routed correctly."""
        with patch.object(router_module, "get_status", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(session_id="norm", memory_id="m1")
            result = await _handle_ui_api_request({"path": "/api/status", "method": "GET"})
        mock_get.assert_called_once()
        assert result["session_id"] == "norm"

    @pytest.mark.asyncio
    async def test_method_defaults_to_get(self):
        with patch.object(router_module, "get_status", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(session_id="s1", memory_id="m1")
            result = await _handle_ui_api_request({"path": "/status"})
        mock_get.assert_called_once()
        assert result["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_exception_returns_error_dict(self):
        with patch.object(router_module, "get_status", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = RuntimeError("agent not ready")
            result = await _handle_ui_api_request({"path": "/status", "method": "GET"})
        assert "error" in result
        assert "agent not ready" in result["error"]

    @pytest.mark.asyncio
    async def test_modes_get_calls_list_modes_and_returns_dict(self):
        with patch.object(router_module, "list_modes", new_callable=AsyncMock) as mock_list:
            mock_list.return_value = _mock_response(modes=[{"id": "default", "name": "Default"}])
            result = await _handle_ui_api_request({"path": "/modes", "method": "GET"})
        mock_list.assert_called_once()
        assert "modes" in result
        assert len(result["modes"]) == 1
        assert result["modes"][0]["id"] == "default"


# ---------------------------------------------------------------------------
# Integration smoke tests: real routing and handlers (no mocks).
# Run with: pytest tests/test_ui_server.py -m integration -v
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestHandleUiApiRequestSmoke:
    """Smoke tests for UI API routing with real handlers.

    Verifies path normalization and routing work end-to-end without mocks.
    /modes and /skills do not require agent or AWS.
    /status and /auri/* may return error dicts if no agent/AWS is set — that is acceptable.
    """

    @pytest.mark.asyncio
    async def test_modes_get_real_handler_returns_modes_list(self):
        """GET /modes via real list_modes(); no agent or AWS required.

        Asserts exact mode set so additions to list_modes() are caught immediately.
        """
        result = await _handle_ui_api_request({"path": "/modes", "method": "GET"})
        assert isinstance(result, dict)
        assert "modes" in result
        assert len(result["modes"]) == 3, f"Expected 3 modes, got: {result['modes']}"
        mode_ids = {m["id"] for m in result["modes"]}
        assert mode_ids == {"default", "poet", "roleplay"}
        for mode in result["modes"]:
            assert "id" in mode
            assert "name" in mode
            assert isinstance(mode["name"], str) and mode["name"], "name must be non-empty string"

    @pytest.mark.asyncio
    async def test_path_api_prefix_normalized_modes(self):
        """/api/modes and /modes must produce identical results.

        Verifies path normalisation (/api/ prefix strip) rather than just response shape.
        """
        plain = await _handle_ui_api_request({"path": "/modes", "method": "GET"})
        prefixed = await _handle_ui_api_request({"path": "/api/modes", "method": "GET"})
        assert plain == prefixed, f"Path normalisation mismatch:\n  /modes={plain}\n  /api/modes={prefixed}"

    @pytest.mark.asyncio
    async def test_status_get_real_handler_returns_dict(self):
        """GET /status via real get_status(); returns error dict when no agent is set."""
        result = await _handle_ui_api_request({"path": "/status", "method": "GET"})
        assert isinstance(result, dict)
        if "error" in result:
            # No agent initialised in the test process — this is expected.
            assert isinstance(result["error"], str)
        else:
            # All three fields are required by StatusResponse.
            assert "session_id" in result
            assert "memory_id" in result
            assert "connected" in result

    @pytest.mark.asyncio
    async def test_skills_get_real_handler_returns_skills_list(self):
        """GET /skills via real get_skills(); reads skill dir from filesystem (no AWS).

        May return empty list if skill dir is absent; shape must still be valid.
        """
        result = await _handle_ui_api_request({"path": "/skills", "method": "GET"})
        assert isinstance(result, dict)
        if "error" in result:
            assert isinstance(result["error"], str)
        else:
            assert "skills" in result
            assert isinstance(result["skills"], list)
            assert "total" in result
            assert result["total"] == len(result["skills"])

    @pytest.mark.asyncio
    async def test_auri_channels_routed_not_unknown(self):
        """GET /auri/channels must be dispatched by _handle_ui_api_request, not fall through.

        Without the Auri routes in server.py this returns {"error": "Unknown API endpoint"}.
        May return a real error (no DynamoDB) but must NOT return "Unknown API endpoint".
        """
        result = await _handle_ui_api_request({"path": "/auri/channels", "method": "GET"})
        assert isinstance(result, dict)
        assert "Unknown API endpoint" not in result.get("error", ""), (
            "/auri/channels fell through to the unknown-endpoint catch-all — "
            "add it to _handle_ui_api_request in server.py"
        )

    @pytest.mark.asyncio
    async def test_auri_persona_core_routed_not_unknown(self):
        """GET /auri/persona/core must be dispatched, not fall through to unknown-endpoint."""
        result = await _handle_ui_api_request({"path": "/auri/persona/core", "method": "GET"})
        assert isinstance(result, dict)
        assert "Unknown API endpoint" not in result.get("error", "")

    @pytest.mark.asyncio
    async def test_auri_dm_users_routed_not_unknown(self):
        """GET /auri/dm-users must be dispatched, not fall through to unknown-endpoint."""
        result = await _handle_ui_api_request({"path": "/auri/dm-users", "method": "GET"})
        assert isinstance(result, dict)
        assert "Unknown API endpoint" not in result.get("error", ""), (
            "/auri/dm-users fell through to the unknown-endpoint catch-all — "
            "add it to _handle_ui_api_request in server.py"
        )

    @pytest.mark.asyncio
    async def test_auri_profiles_routed_not_unknown(self):
        """GET /auri/profiles must be dispatched, not fall through to unknown-endpoint."""
        result = await _handle_ui_api_request({"path": "/auri/profiles", "method": "GET"})
        assert isinstance(result, dict)
        assert "Unknown API endpoint" not in result.get("error", ""), (
            "/auri/profiles fell through to the unknown-endpoint catch-all — "
            "add it to _handle_ui_api_request in server.py"
        )
