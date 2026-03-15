"""Unit tests for group moderation — invocation context, tool registration, tool structure.

These tests do NOT require AWS credentials or live services.
Run with: cd agent && pytest tests/test_moderation.py -v
"""

import ast
import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


# ---------------------------------------------------------------------------
# InvocationContext
# ---------------------------------------------------------------------------


class TestInvocationContext:
    def test_default_context_is_empty(self):
        from glitch.invocation_context import InvocationContext
        ctx = InvocationContext()
        assert ctx.chat_id == 0
        assert ctx.from_user_id == 0
        assert ctx.message_id == 0
        assert ctx.session_id == ""
        assert ctx.participant_id == ""
        assert ctx.is_group is False

    def test_set_and_get_context(self):
        from glitch.invocation_context import set_context, get_context, clear_context
        set_context(chat_id=123, from_user_id=456, message_id=789, is_group=True)
        ctx = get_context()
        assert ctx.chat_id == 123
        assert ctx.from_user_id == 456
        assert ctx.message_id == 789
        assert ctx.is_group is True
        clear_context()

    def test_clear_context_resets(self):
        from glitch.invocation_context import set_context, get_context, clear_context
        set_context(chat_id=999, from_user_id=888)
        clear_context()
        ctx = get_context()
        assert ctx.chat_id == 0
        assert ctx.from_user_id == 0

    def test_set_context_replaces_previous(self):
        from glitch.invocation_context import set_context, get_context, clear_context
        set_context(chat_id=111)
        set_context(chat_id=222)
        assert get_context().chat_id == 222
        clear_context()


# ---------------------------------------------------------------------------
# Tool Registry: moderation group
# ---------------------------------------------------------------------------


class TestModerationRegistry:
    @pytest.fixture(autouse=True)
    def _require_registry_deps(self):
        """Skip registry tests if optional deps (e.g. PyGithub) are missing."""
        pytest.importorskip("github", reason="PyGithub not installed locally")

    def test_moderation_group_registered(self):
        from glitch.tools.registry import registry
        groups = registry.list_groups()
        assert "moderation" in groups, f"moderation group not in registry: {list(groups.keys())}"

    def test_moderation_group_has_7_tools(self):
        from glitch.tools.registry import registry
        tools = registry.get_group("moderation")
        assert len(tools) == 7, f"Expected 7 moderation tools, got {len(tools)}"

    def test_moderation_tool_names(self):
        from glitch.tools.registry import registry
        tools = registry.get_group("moderation")
        names = {t.__name__ for t in tools}
        expected = {"warn_user", "mute_user", "kick_user", "ban_user",
                    "delete_message", "get_warnings", "get_group_rules"}
        assert names == expected, f"Unexpected tool names: {names}"

    def test_moderation_tools_in_all_tools(self):
        from glitch.tools.registry import registry
        all_tools = registry.get_all_tools()
        all_names = {t.__name__ for t in all_tools}
        for name in ("warn_user", "mute_user", "kick_user", "ban_user", "delete_message"):
            assert name in all_names, f"{name} missing from get_all_tools()"


# ---------------------------------------------------------------------------
# moderation_tools.py: AST checks
# ---------------------------------------------------------------------------


class TestModerationToolsStructure:
    """Verify moderation tools use invocation_context.get_context() for IDs."""

    @staticmethod
    def _get_tool_ast() -> ast.Module:
        path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "tools" / "moderation_tools.py"
        return ast.parse(path.read_text())

    def test_all_action_tools_call_get_context(self):
        """Each action tool (warn, mute, kick, ban, delete) must call get_context()."""
        tree = self._get_tool_ast()
        action_tools = {"warn_user", "mute_user", "kick_user", "ban_user", "delete_message"}

        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in action_tools:
                source = ast.dump(node)
                assert "get_context" in source, (
                    f"{node.name} does not call get_context() — "
                    "tools must read IDs from invocation_context, not LLM params"
                )
                action_tools.discard(node.name)

        assert not action_tools, f"Missing tool functions: {action_tools}"

    def test_no_tool_takes_user_id_param(self):
        """Moderation tools must not accept user_id as a parameter (prevents hallucination)."""
        tree = self._get_tool_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name in (
                "warn_user", "mute_user", "kick_user", "ban_user", "delete_message",
            ):
                param_names = [a.arg for a in node.args.args]
                assert "user_id" not in param_names, (
                    f"{node.name} accepts user_id param — must use invocation_context"
                )
                assert "chat_id" not in param_names, (
                    f"{node.name} accepts chat_id param — must use invocation_context"
                )

    def test_imports_get_context(self):
        """moderation_tools.py imports get_context from invocation_context."""
        tree = self._get_tool_ast()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "glitch.invocation_context":
                imported = [alias.name for alias in node.names]
                assert "get_context" in imported
                return
        pytest.fail("moderation_tools.py does not import get_context from invocation_context")


# ---------------------------------------------------------------------------
# server.py: invocation context lifecycle
# ---------------------------------------------------------------------------


class TestServerInvocationContext:
    def test_server_sets_invocation_context(self):
        """AST check: server.py calls set_context() before agent processing."""
        path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "server.py"
        source = path.read_text()
        assert "set_context(" in source, "server.py does not call set_context()"

    def test_server_clears_invocation_context(self):
        """AST check: server.py calls clear_context() in finally block."""
        path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "server.py"
        source = path.read_text()
        assert "clear_context()" in source, "server.py does not call clear_context()"

    def test_server_extracts_from_user_id(self):
        """server.py extracts from_user_id from payload."""
        path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "server.py"
        source = path.read_text()
        assert "from_user_id" in source, "server.py does not extract from_user_id"

    def test_server_extracts_message_id(self):
        """server.py extracts message_id from payload."""
        path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "server.py"
        source = path.read_text()
        assert "message_id" in source, "server.py does not extract message_id"


# ---------------------------------------------------------------------------
# auri_context.py: moderation layer
# ---------------------------------------------------------------------------


class TestAuriModerationLayer:
    def test_composer_has_load_moderation_context(self):
        """AuriContextComposer has _load_moderation_context method."""
        from glitch.auri_context import AuriContextComposer
        assert hasattr(AuriContextComposer, "_load_moderation_context")

    def test_preamble_mentions_group_guardian(self):
        """The roleplay preamble mentions group guardian role."""
        from glitch.modes import _ROLEPLAY_PREAMBLE
        assert "group guardian" in _ROLEPLAY_PREAMBLE.lower()

    def test_preamble_mentions_never_moderate_owner(self):
        """The preamble instructs Auri to never moderate the owner."""
        from glitch.modes import _ROLEPLAY_PREAMBLE
        assert "never moderate the group owner" in _ROLEPLAY_PREAMBLE.lower()


# ---------------------------------------------------------------------------
# types.py: InvocationRequest fields
# ---------------------------------------------------------------------------


class TestInvocationRequestFields:
    def test_invocation_request_has_from_user_id(self):
        """InvocationRequest TypedDict includes from_user_id."""
        from glitch.types import InvocationRequest
        annotations = InvocationRequest.__annotations__
        assert "from_user_id" in annotations, "from_user_id missing from InvocationRequest"

    def test_invocation_request_has_message_id(self):
        """InvocationRequest TypedDict includes message_id."""
        from glitch.types import InvocationRequest
        annotations = InvocationRequest.__annotations__
        assert "message_id" in annotations, "message_id missing from InvocationRequest"

    def test_invocation_request_has_chat_id(self):
        """InvocationRequest TypedDict includes chat_id."""
        from glitch.types import InvocationRequest
        annotations = InvocationRequest.__annotations__
        assert "chat_id" in annotations, "chat_id missing from InvocationRequest"


# ---------------------------------------------------------------------------
# DEFAULT_RULES
# ---------------------------------------------------------------------------


class TestDefaultRules:
    def test_default_rules_has_5_entries(self):
        from glitch.tools.moderation_tools import DEFAULT_RULES
        assert len(DEFAULT_RULES) == 5

    def test_default_rules_have_required_fields(self):
        from glitch.tools.moderation_tools import DEFAULT_RULES
        for rule in DEFAULT_RULES:
            assert "id" in rule
            assert "text" in rule
            assert "severity" in rule
            assert rule["severity"] in ("low", "medium", "high")
