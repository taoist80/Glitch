"""Tests for Poet sub-agent and poet-soul loader."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from glitch.poet_soul import load_poet_soul, get_default_poet_soul_path
from glitch.poet_agent import PoetAgent, build_poet_system_prompt


class TestLoadPoetSoul:
    """Tests for load_poet_soul and get_default_poet_soul_path."""

    def test_get_default_poet_soul_path_ends_with_poet_soul_md(self):
        """Default path should point to poet-soul.md."""
        path = get_default_poet_soul_path()
        assert path.name == "poet-soul.md"
        assert path.suffix == ".md"

    def test_load_poet_soul_when_file_exists(self):
        """When poet-soul.md exists in agent dir, load_poet_soul returns non-empty content."""
        # In repo, agent/poet-soul.md exists
        path = get_default_poet_soul_path()
        if path.exists():
            content = load_poet_soul()
            assert isinstance(content, str)
            assert len(content) > 0
            assert "Poet" in content or "poet" in content
        else:
            pytest.skip("poet-soul.md not found at default path")

    def test_build_poet_system_prompt_includes_technical_context(self):
        """System prompt should include technical context."""
        prompt = build_poet_system_prompt()
        assert "Poet" in prompt
        assert "creative writing" in prompt or "writing" in prompt.lower()


class TestPoetAgent:
    """Tests for PoetAgent."""

    def test_poet_agent_constructs(self):
        """PoetAgent can be constructed with defaults."""
        agent = PoetAgent(session_id="test-session", memory_id="test-memory")
        assert agent.session_id == "test-session"
        assert agent.memory_id == "test-memory"
        assert agent.agent is not None

    @pytest.mark.asyncio
    async def test_poet_agent_process_message_returns_invocation_response(self):
        """process_message returns InvocationResponse with message and no error when agent is mocked."""
        mock_result = MagicMock()
        mock_result.metrics.get_summary.return_value = {
            "total_duration": 0.5,
            "total_cycles": 1,
            "accumulated_usage": {
                "inputTokens": 10,
                "outputTokens": 20,
                "totalTokens": 30,
                "cacheReadInputTokens": 0,
                "cacheWriteInputTokens": 0,
            },
            "accumulated_metrics": {"latencyMs": 100},
            "tool_usage": {},
        }
        mock_result.stop_reason = "end_turn"
        mock_result.__str__ = lambda _: "Rain falls soft / on the window glass— / winter haiku."

        with patch("glitch.poet_agent.Agent") as MockAgent:
            MockAgent.return_value = MagicMock(return_value=mock_result)
            agent = PoetAgent(session_id="test", memory_id="test-mem")
            response = await agent.process_message("Write a haiku about rain")

        assert isinstance(response, dict)
        assert "message" in response
        assert response["message"]
        assert response.get("session_id") == "test"
        assert response.get("memory_id") == "test-mem"
        assert "metrics" in response
        assert response.get("error") is None

    def test_poet_agent_get_status(self):
        """get_status returns dict with agent and model."""
        agent = PoetAgent()
        status = agent.get_status()
        assert status.get("agent") == "poet"
        assert status.get("model") == "sonnet-4.5"
        assert "session_id" in status
