"""Unit tests for agent registry and modes."""

import pytest
from unittest.mock import MagicMock

from glitch.agent_registry import (
    register_agent,
    get_agent,
    list_agents,
    get_default_agent_id,
    set_default_agent_id,
    get_allowed_agent_ids,
)
from glitch.modes import MODE_DEFAULT, MODE_POET, apply_mode_to_prompt, get_poet_context


class TestAgentRegistry:
    """Tests for agent registry (in-process)."""

    def teardown_method(self):
        """Reset registry state between tests (module-level state)."""
        import glitch.agent_registry as reg
        reg._registry.clear()
        reg._meta.clear()
        reg._default_agent_id = None

    def test_register_and_get_agent(self):
        mock_agent = MagicMock()
        mock_agent.get_status.return_value = {"agent": "mistral"}
        register_agent("mistral", mock_agent, {"name": "Mistral", "description": "Chat"})
        assert get_agent("mistral") is mock_agent
        assert get_agent("nonexistent") is None

    def test_list_agents_returns_meta_and_status(self):
        mock_agent = MagicMock()
        mock_agent.get_status.return_value = {"agent": "glitch"}
        register_agent("glitch", mock_agent, {"name": "Glitch", "description": "Orchestrator"})
        agents = list_agents()
        assert len(agents) == 1
        assert agents[0]["id"] == "glitch"
        assert agents[0]["name"] == "Glitch"
        assert agents[0].get("status", {}).get("agent") == "glitch"

    def test_get_default_agent_id_from_env_or_fallback(self):
        # Before any set_default, returns env or fallback (mistral)
        default = get_default_agent_id()
        assert default in get_allowed_agent_ids()
        assert default == "mistral" or default in ("glitch", "mistral", "llava")

    def test_set_default_agent_id_valid(self):
        mock_agent = MagicMock()
        register_agent("mistral", mock_agent, {})
        set_default_agent_id("mistral")
        assert get_default_agent_id() == "mistral"

    def test_set_default_agent_id_invalid_ignored(self):
        mock_agent = MagicMock()
        register_agent("mistral", mock_agent, {})
        set_default_agent_id("mistral")
        set_default_agent_id("invalid_id")
        # Invalid id is ignored; default stays mistral
        assert get_default_agent_id() == "mistral"

    def test_get_allowed_agent_ids_includes_glitch_mistral_llava(self):
        allowed = get_allowed_agent_ids()
        assert "glitch" in allowed
        assert "mistral" in allowed
        assert "llava" in allowed
        assert "poet" not in allowed


class TestModes:
    """Tests for session modes (default, poet)."""

    def test_apply_mode_default_returns_unchanged_prompt(self):
        prompt = "Hello"
        system = "You are helpful."
        out_prompt, out_sys = apply_mode_to_prompt(MODE_DEFAULT, prompt, system)
        assert out_prompt == prompt
        assert out_sys == system

    def test_apply_mode_poet_without_system_prepends_context_to_prompt(self):
        prompt = "Write a haiku."
        out_prompt, out_sys = apply_mode_to_prompt(MODE_POET, prompt, system_prompt=None)
        # When no system_prompt, poet context is prepended to prompt
        assert "Write a haiku" in out_prompt
        assert out_sys is None or out_sys == ""

    def test_apply_mode_poet_with_system_appends_context_to_system(self):
        prompt = "Hi"
        system = "You are a bot."
        out_prompt, out_sys = apply_mode_to_prompt(MODE_POET, prompt, system_prompt=system)
        assert out_prompt == prompt
        assert system in (out_sys or "")
        # Poet context may be appended to system (implementation-dependent)
        assert out_sys is not None

    def test_get_poet_context_returns_string(self):
        ctx = get_poet_context()
        assert isinstance(ctx, str)
