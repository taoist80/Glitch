"""Tests for server UI API handling: _handle_ui_api_request routing.

Requires bedrock_agentcore and fastapi (runtime deps). Skipped when not installed.
"""

import pytest

pytest.importorskip("bedrock_agentcore")
pytest.importorskip("fastapi")

from unittest.mock import AsyncMock, MagicMock, patch

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
        with patch("glitch.api.router.get_status", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(session_id="s1", memory_id="m1")
            result = await _handle_ui_api_request({"path": "/status", "method": "GET"})
        mock_get.assert_called_once()
        assert result["session_id"] == "s1"
        assert result["memory_id"] == "m1"

    @pytest.mark.asyncio
    async def test_skills_get_calls_get_skills_and_returns_dict(self):
        with patch("glitch.api.router.get_skills", new_callable=AsyncMock) as mock_get:
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
        with patch("glitch.api.router.toggle_skill", new_callable=AsyncMock) as mock_toggle:
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
    async def test_method_defaults_to_get(self):
        with patch("glitch.api.router.get_status", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _mock_response(session_id="s1", memory_id="m1")
            result = await _handle_ui_api_request({"path": "/status"})
        mock_get.assert_called_once()
        assert result["session_id"] == "s1"

    @pytest.mark.asyncio
    async def test_exception_returns_error_dict(self):
        with patch("glitch.api.router.get_status", new_callable=AsyncMock) as mock_get:
            mock_get.side_effect = RuntimeError("agent not ready")
            result = await _handle_ui_api_request({"path": "/status", "method": "GET"})
        assert "error" in result
        assert "agent not ready" in result["error"]
