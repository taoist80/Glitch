"""Tests for UI proxy (ui_proxy module): payload building and invoke with mocked boto3."""

import json
import pytest
from unittest.mock import MagicMock, patch

from glitch.ui_proxy import (
    create_api_proxy_payload,
    get_runtime_arn,
    invoke_deployed_agent,
    invoke_deployed_agent_async,
)


class TestCreateApiProxyPayload:
    """Tests for create_api_proxy_payload."""

    def test_shape_has_ui_api_request_key(self):
        payload = create_api_proxy_payload("/status", "GET")
        assert "_ui_api_request" in payload
        inner = payload["_ui_api_request"]
        assert inner["path"] == "/status"
        assert inner["method"] == "GET"
        assert "body" in inner

    def test_method_uppercased(self):
        payload = create_api_proxy_payload("/skills", "get")
        assert payload["_ui_api_request"]["method"] == "GET"

    def test_with_body(self):
        body = {"enabled": True}
        payload = create_api_proxy_payload("/skills/foo/toggle", "POST", body=body)
        assert payload["_ui_api_request"]["body"] == body


class TestGetRuntimeArn:
    """Tests for get_runtime_arn (mocked control plane). boto3 is imported inside the function."""

    def test_returns_arn_when_name_matches(self):
        mock_control = MagicMock()
        mock_control.list_agent_runtimes.return_value = {
            "agentRuntimes": [
                {
                    "agentRuntimeName": "Glitch",
                    "agentRuntimeId": "abc-123",
                    "agentRuntimeArn": "arn:aws:bedrock-agentcore:us-west-2:123:runtime/Glitch-abc",
                }
            ]
        }
        with patch("boto3.client", return_value=mock_control):
            arn = get_runtime_arn("Glitch", "us-west-2")
        assert arn == "arn:aws:bedrock-agentcore:us-west-2:123:runtime/Glitch-abc"

    def test_returns_none_when_no_match(self):
        mock_control = MagicMock()
        mock_control.list_agent_runtimes.return_value = {"agentRuntimes": []}
        with patch("boto3.client", return_value=mock_control):
            arn = get_runtime_arn("Unknown", "us-west-2")
        assert arn is None


class TestInvokeDeployedAgent:
    """Tests for invoke_deployed_agent with mocked boto3."""

    def test_returns_error_when_no_arn(self):
        with patch("glitch.ui_proxy.get_runtime_arn", return_value=None), patch.dict(
            "os.environ", {}, clear=False
        ):
            with patch.dict("os.environ", {"GLITCH_AGENT_RUNTIME_ARN": ""}, clear=False):
                result = invoke_deployed_agent("Unknown", "us-west-2", {"prompt": "hi"})
        assert "error" in result
        assert "ARN" in result["error"]

    def test_uses_runtime_arn_env_when_set(self):
        env_arn = "arn:aws:bedrock-agentcore:us-west-2:123:runtime/Glitch-env"
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b'{"message":"ok"}'
        mock_client.invoke_agent_runtime.return_value = {
            "statusCode": 200,
            "response": mock_body,
        }
        with patch.dict("os.environ", {"GLITCH_AGENT_RUNTIME_ARN": env_arn}, clear=False):
            with patch("boto3.client", return_value=mock_client):
                result = invoke_deployed_agent("Any", "us-west-2", {"prompt": "hi"})
        assert result.get("message") == "ok"
        mock_client.invoke_agent_runtime.assert_called_once()
        call_kw = mock_client.invoke_agent_runtime.call_args[1]
        assert call_kw["agentRuntimeArn"] == env_arn

    def test_success_parses_json_response(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = json.dumps({"message": "Hello", "session_id": "s1"}).encode(
            "utf-8"
        )
        mock_client.invoke_agent_runtime.return_value = {
            "statusCode": 200,
            "response": mock_body,
        }
        with patch("glitch.ui_proxy.get_runtime_arn", return_value="arn:test"):
            with patch("boto3.client", return_value=mock_client):
                result = invoke_deployed_agent("Glitch", "us-west-2", {"prompt": "hi"})
        assert result["message"] == "Hello"
        assert result["session_id"] == "s1"

    def test_non_200_returns_error(self):
        mock_client = MagicMock()
        mock_client.invoke_agent_runtime.return_value = {"statusCode": 500}
        with patch("glitch.ui_proxy.get_runtime_arn", return_value="arn:test"):
            with patch("boto3.client", return_value=mock_client):
                result = invoke_deployed_agent("Glitch", "us-west-2", {"prompt": "hi"})
        assert "error" in result
        assert "500" in result["error"]

    def test_empty_body_returns_error(self):
        mock_client = MagicMock()
        mock_client.invoke_agent_runtime.return_value = {"statusCode": 200, "response": None}
        with patch("glitch.ui_proxy.get_runtime_arn", return_value="arn:test"):
            with patch("boto3.client", return_value=mock_client):
                result = invoke_deployed_agent("Glitch", "us-west-2", {"prompt": "hi"})
        assert "error" in result
        assert "Empty" in result["error"]

    def test_cli_style_fallback_parses_response(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b'Some text\nResponse: {"message":"from cli"}'
        mock_client.invoke_agent_runtime.return_value = {
            "statusCode": 200,
            "response": mock_body,
        }
        with patch("glitch.ui_proxy.get_runtime_arn", return_value="arn:test"):
            with patch("boto3.client", return_value=mock_client):
                result = invoke_deployed_agent("Glitch", "us-west-2", {"prompt": "hi"})
        assert result.get("message") == "from cli"

    def test_invalid_json_returns_error_with_raw_snippet(self):
        mock_client = MagicMock()
        mock_body = MagicMock()
        mock_body.read.return_value = b"not json at all"
        mock_client.invoke_agent_runtime.return_value = {
            "statusCode": 200,
            "response": mock_body,
        }
        with patch("glitch.ui_proxy.get_runtime_arn", return_value="arn:test"):
            with patch("boto3.client", return_value=mock_client):
                result = invoke_deployed_agent("Glitch", "us-west-2", {"prompt": "hi"})
        assert "error" in result
        assert "raw" in result
        assert len(result["raw"]) <= 500


class TestInvokeDeployedAgentAsync:
    """Tests for invoke_deployed_agent_async (mocked sync invoke)."""

    @pytest.mark.asyncio
    async def test_returns_same_result_as_sync(self):
        expected = {"message": "async ok", "session_id": "s1"}
        with patch(
            "glitch.ui_proxy.invoke_deployed_agent",
            return_value=expected,
        ):
            result = await invoke_deployed_agent_async(
                "Glitch", "us-west-2", {"prompt": "hi"}, session_id="s0"
            )
        assert result == expected
