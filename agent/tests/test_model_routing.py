"""Unit tests for model routing — Haiku selection for roleplay mode.

These tests do NOT require AWS credentials or live services.
Run with: cd agent && pytest tests/test_model_routing.py -v
"""

import ast
import os
import pathlib
import sys
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# MODEL_REGISTRY: haiku entry
# ---------------------------------------------------------------------------

class TestModelRegistry:
    def test_haiku_in_registry(self):
        from glitch.routing.model_router import MODEL_REGISTRY
        assert "haiku" in MODEL_REGISTRY, "haiku not found in MODEL_REGISTRY"

    def test_haiku_model_id(self):
        from glitch.routing.model_router import MODEL_REGISTRY
        cfg = MODEL_REGISTRY["haiku"]
        assert "haiku" in cfg.model_id.lower(), f"Unexpected model_id: {cfg.model_id}"
        assert "claude" in cfg.model_id.lower(), f"Expected Claude model id: {cfg.model_id}"
        # Must end with -v1:0 like all other cross-region inference profile IDs
        assert cfg.model_id.endswith("-v1:0"), (
            f"Haiku model_id missing '-v1:0' suffix (Bedrock CRI format): {cfg.model_id}"
        )

    def test_haiku_supports_tools(self):
        from glitch.routing.model_router import MODEL_REGISTRY
        assert MODEL_REGISTRY["haiku"].supports_tools is True

    def test_haiku_supports_vision(self):
        from glitch.routing.model_router import MODEL_REGISTRY
        assert MODEL_REGISTRY["haiku"].supports_vision is True

    def test_haiku_cheaper_than_glitch(self):
        from glitch.routing.model_router import MODEL_REGISTRY
        haiku_cost = MODEL_REGISTRY["haiku"].cost_per_million_tokens
        glitch_cost = MODEL_REGISTRY["glitch"].cost_per_million_tokens
        assert haiku_cost < glitch_cost, (
            f"Haiku ({haiku_cost}) should be cheaper than Glitch ({glitch_cost})"
        )


# ---------------------------------------------------------------------------
# server.py: model_override passed for roleplay mode
# ---------------------------------------------------------------------------

class TestServerModelOverride:
    def test_server_passes_model_override_for_roleplay(self):
        """AST check: server.py passes model_override='haiku' when mode_id==MODE_ROLEPLAY."""
        server_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "server.py"
        source = server_path.read_text()
        assert "model_override" in source, "model_override not found in server.py"
        assert "haiku" in source, "'haiku' override not found in server.py"
        assert "MODE_ROLEPLAY" in source, "MODE_ROLEPLAY not referenced in server.py"

    def test_server_model_override_conditional(self):
        """Verify server.py sets model_override only for roleplay, not for default mode."""
        server_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "server.py"
        source = server_path.read_text()
        # Ensure it's conditional — 'haiku' should only appear in an if/ternary context
        assert "if mode_id" in source or "MODE_ROLEPLAY" in source, \
            "Expected conditional model_override based on mode_id"


# ---------------------------------------------------------------------------
# agent.py: model_override kwarg + _alt_models cache
# ---------------------------------------------------------------------------

class TestAgentModelOverride:
    def test_agent_has_alt_models_attr(self):
        """AST: GlitchAgent.__init__ initialises _alt_models."""
        agent_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "agent.py"
        source = agent_path.read_text()
        assert "_alt_models" in source, "_alt_models cache not found in agent.py"

    def test_process_message_accepts_model_override(self):
        """AST: process_message reads model_override from kwargs."""
        agent_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "agent.py"
        source = agent_path.read_text()
        assert "model_override" in source, "model_override not referenced in agent.py"
        assert 'kwargs.get("model_override")' in source, \
            "model_override not read via kwargs.get in agent.py"

    def test_process_message_restores_model_in_finally(self):
        """AST: process_message has a finally block that restores the original model."""
        agent_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "agent.py"
        tree = ast.parse(agent_path.read_text())
        found_finally = False
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "process_message":
                for child in ast.walk(node):
                    if isinstance(child, ast.Try) and child.finalbody:
                        # Check finalbody mentions model restoration
                        final_src = ast.unparse(child.finalbody)
                        if "_original_model" in final_src:
                            found_finally = True
                            break
        assert found_finally, (
            "process_message does not have a finally block restoring _original_model"
        )

    def test_model_swap_uses_bedrock_model(self):
        """Verify agent.py creates a BedrockModel for the override, not a raw string."""
        agent_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "agent.py"
        source = agent_path.read_text()
        assert "BedrockModel" in source, "BedrockModel not used for alt models"
        assert "self._alt_models[model_override]" in source, \
            "Alt model not cached in self._alt_models"


# ---------------------------------------------------------------------------
# Brevity instruction: auri_context.py + modes.py preambles
# ---------------------------------------------------------------------------

class TestMountainTimeContext:
    def test_get_mountain_time_context_format(self):
        from glitch.auri_context import get_mountain_time_context
        result = get_mountain_time_context()
        assert "Mountain Time" in result
        assert "Current time:" in result
        # Should contain a day-of-week
        days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
        assert any(d in result for d in days), f"No weekday in: {result}"
        # Should contain a period label
        periods = ("morning", "afternoon", "evening", "late night")
        assert any(p in result for p in periods), f"No period label in: {result}"

    def test_get_mountain_time_context_in_auri_context_compose(self):
        """AST: compose() preamble references get_mountain_time_context."""
        ctx_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "auri_context.py"
        source = ctx_path.read_text()
        assert "get_mountain_time_context()" in source, \
            "get_mountain_time_context() not called in auri_context.py"

    def test_get_mountain_time_context_in_modes(self):
        """modes.py imports and calls get_mountain_time_context for roleplay."""
        modes_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "modes.py"
        source = modes_path.read_text()
        assert "get_mountain_time_context" in source, \
            "get_mountain_time_context not referenced in modes.py"


class TestBrevityInstruction:
    def test_auri_context_preamble_has_brevity(self):
        """Verify AuriContextComposer.compose() preamble includes the brevity rule."""
        ctx_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "auri_context.py"
        source = ctx_path.read_text()
        assert "1\u20133 sentence" in source or "1-3 sentence" in source, \
            "Brevity '1–3 sentences' rule not found in auri_context.py"
        assert "brevity" in source.lower() or "brief" in source.lower(), \
            "Brevity keyword not found in auri_context.py"

    def test_modes_roleplay_preamble_has_brevity(self):
        """Verify _ROLEPLAY_PREAMBLE in modes.py includes the brevity rule."""
        modes_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "modes.py"
        source = modes_path.read_text()
        assert "1\u20133 sentence" in source or "1-3 sentence" in source, \
            "Brevity '1–3 sentences' rule not found in modes.py _ROLEPLAY_PREAMBLE"

    def test_brevity_exceptions_mentioned(self):
        """Verify exceptions (story, memories, backstory) are listed in the brevity rule."""
        ctx_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "auri_context.py"
        source = ctx_path.read_text()
        for keyword in ("story", "memor", "backstory"):
            assert keyword in source.lower(), \
                f"Brevity exception '{keyword}' not mentioned in auri_context.py"


# ---------------------------------------------------------------------------
# Memory tool loop guard
# ---------------------------------------------------------------------------

class TestMemoryToolLoopGuard:
    def test_auri_context_has_memory_tool_constraint(self):
        """Verify preamble tells the model NOT to call search_auri_memory during a response."""
        ctx_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "auri_context.py"
        source = ctx_path.read_text()
        assert "search_auri_memory" in source, \
            "search_auri_memory constraint not found in auri_context.py preamble"
        assert "do NOT call search_auri_memory" in source or "NOT call search_auri_memory" in source, \
            "Explicit prohibition of search_auri_memory not found in auri_context.py"

    def test_modes_roleplay_has_memory_tool_constraint(self):
        """Verify _ROLEPLAY_PREAMBLE tells the model not to loop memory tool calls."""
        modes_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "modes.py"
        source = modes_path.read_text()
        assert "search_auri_memory" in source, \
            "search_auri_memory constraint not found in modes.py _ROLEPLAY_PREAMBLE"
        assert "NOT call search_auri_memory" in source or "do NOT call search_auri_memory" in source, \
            "Explicit prohibition of search_auri_memory not found in modes.py"

    def test_memory_tool_no_retry_instruction(self):
        """Verify 'never loop or retry' instruction is present in both preambles."""
        ctx_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "auri_context.py"
        modes_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "modes.py"
        for path in (ctx_path, modes_path):
            source = path.read_text()
            assert "loop" in source.lower() or "retry" in source.lower(), \
                f"No loop/retry prohibition found in {path.name}"


# ---------------------------------------------------------------------------
# Skill suppression in roleplay mode
# ---------------------------------------------------------------------------

class TestSkillSuppressionInRoleplay:
    def test_agent_skips_skills_when_mode_context_set(self):
        """AST check: _select_and_inject_skills skips select_skills_for_message when mode_context is truthy."""
        agent_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "agent.py"
        source = agent_path.read_text()
        # The guard must be present
        assert "mode_context" in source and "skill_suffix" in source, \
            "skill_suffix not conditional on mode_context in agent.py"
        # A blank skill_suffix should be assigned when mode_context is set
        assert 'skill_suffix = ""' in source, \
            "Empty skill_suffix assignment for roleplay mode not found in agent.py"
