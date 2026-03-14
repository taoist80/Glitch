"""Integration tests for the Auri layered memory architecture.

These tests hit real AWS services (S3, Lambda, RDS via Lambda bridge, DynamoDB)
and require valid credentials. Mark with @pytest.mark.integration so unit-only
runs skip them.

Run:
    cd agent && pytest tests/test_auri_integration.py -v -m integration
"""

import json
import os
import sys
import uuid

import pytest

# Allow importing from agent/src
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Phase 1: GlitchAgent system prompt injection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_apply_mode_with_memories_returns_3_tuple():
    """Verify apply_mode_with_memories returns (prompt, sys_prompt, mode_context)."""
    from glitch.modes import apply_mode_with_memories, MODE_ROLEPLAY, MODE_DEFAULT

    # Default mode should return None mode_context
    prompt_out, sys_out, mode_context = await apply_mode_with_memories(
        MODE_DEFAULT, "hello", system_prompt=None,
    )
    assert mode_context is None
    assert prompt_out == "hello"

    # Roleplay mode should return mode_context (may be None if no persona loaded,
    # but the 3-tuple itself should always be returned)
    result = await apply_mode_with_memories(
        MODE_ROLEPLAY, "hello", system_prompt=None,
    )
    assert len(result) == 3, f"Expected 3-tuple, got {len(result)}"


def test_glitch_agent_accepts_mode_context():
    """Verify GlitchAgent.process_message signature accepts **kwargs (includes mode_context)."""
    import ast
    import pathlib
    agent_path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "agent.py"
    tree = ast.parse(agent_path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "process_message":
            has_kwargs = any(
                isinstance(a, ast.arg) and a.arg in ("kwargs",)
                for a in [node.args.kwarg] if a is not None
            ) or any(
                isinstance(a, ast.arg) and a.arg == "mode_context"
                for a in node.args.args + node.args.kwonlyargs
            )
            assert has_kwargs, "process_message does not accept **kwargs or mode_context"
            return
    pytest.fail("process_message not found in agent.py")


# ---------------------------------------------------------------------------
# Phase 2: S3 split files (auri-core + auri-runtime-rules)
# ---------------------------------------------------------------------------

def test_auri_core_s3_roundtrip():
    """Write auri-core.md to S3 and read it back."""
    from glitch.tools.soul_tools import save_auri_core_to_s3, load_auri_core_from_s3

    marker = f"# Integration Test Core {uuid.uuid4().hex[:8]}"
    content = f"{marker}\nAuri is a test lion."
    ok, err = save_auri_core_to_s3(content)
    assert ok, f"S3 write failed: {err}"

    loaded = load_auri_core_from_s3()
    assert marker in loaded, f"Marker not found in loaded content: {loaded[:200]}"


def test_auri_rules_s3_roundtrip():
    """Write auri-runtime-rules.md to S3 and read it back."""
    from glitch.tools.soul_tools import save_auri_rules_to_s3, load_auri_rules_from_s3

    marker = f"# Integration Test Rules {uuid.uuid4().hex[:8]}"
    content = f"{marker}\nTeasing level: 3"
    ok, err = save_auri_rules_to_s3(content)
    assert ok, f"S3 write failed: {err}"

    loaded = load_auri_rules_from_s3()
    assert marker in loaded, f"Marker not found in loaded content: {loaded[:200]}"


# ---------------------------------------------------------------------------
# Phase 3: Dynamic session state (DynamoDB)
# ---------------------------------------------------------------------------

def test_auri_state_roundtrip():
    """Write and read AuriState from DynamoDB."""
    from glitch.auri_state import AuriStateManager, AuriState

    mgr = AuriStateManager()
    test_session = f"test-state-{uuid.uuid4().hex[:8]}"

    state = AuriState(mode="bratty", mood="mischievous", dynamic_level=4)
    mgr.save_state(test_session, state)

    loaded = mgr.load_state(test_session)
    assert loaded.mode == "bratty"
    assert loaded.mood == "mischievous"
    assert loaded.dynamic_level == 4


def test_scene_summary_roundtrip():
    """Write and read SceneSummary from DynamoDB."""
    from glitch.auri_state import AuriStateManager, SceneSummary

    mgr = AuriStateManager()
    test_session = f"test-scene-{uuid.uuid4().hex[:8]}"

    scene = SceneSummary(energy="playful", recent_events=["Arc got bratty"], open_loops=["unresolved dare"])
    mgr.save_scene(test_session, scene)

    loaded = mgr.load_scene(test_session)
    assert loaded.energy == "playful"
    assert "Arc got bratty" in loaded.recent_events
    assert "unresolved dare" in loaded.open_loops


# ---------------------------------------------------------------------------
# Phase 4: Vector DB — episodic memories + participant profiles
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_remember_and_search_auri_memory():
    """Store a memory via Lambda bridge, then search and find it."""
    from glitch.auri_memory import store_memory, retrieve_memories

    test_content = f"Integration test memory {uuid.uuid4().hex[:8]}: Arc likes warm blankets"
    await store_memory(None, test_content, source="test")

    results = await retrieve_memories(None, test_content, k=3)
    assert any(test_content in r for r in results), \
        f"Stored memory not found in search results: {results}"


@pytest.mark.asyncio
async def test_participant_profile_store_and_retrieve():
    """Store a participant profile and retrieve it by participant_id."""
    from glitch.auri_memory import store_participant_profile, retrieve_participant_profiles

    test_pid = f"test_participant_{uuid.uuid4().hex[:8]}"
    test_profile = f"{test_pid} likes bratty callouts and warm teasing"
    await store_participant_profile(test_pid, test_profile)

    profiles = await retrieve_participant_profiles([test_pid], k=1)
    assert len(profiles) > 0, "No profiles returned"
    assert test_pid in profiles[0], f"Profile content mismatch: {profiles[0]}"


@pytest.mark.asyncio
async def test_lambda_auri_memory_search_filtered():
    """Invoke protect-query Lambda directly with filtered search."""
    import boto3

    lambda_name = os.environ.get("GLITCH_PROTECT_QUERY_LAMBDA", "glitch-protect-query")
    region = os.environ.get("AWS_REGION", "us-west-2")
    client = boto3.client("lambda", region_name=region)

    # We need a real embedding — generate one via Bedrock
    from glitch.auri_memory import embed_text
    embedding = embed_text("test filtered search")

    resp = client.invoke(
        FunctionName=lambda_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({
            "action": "auri_memory_search_filtered",
            "embedding": embedding,
            "k": 3,
            "memory_type": "participant_profile",
        }),
    )
    result = json.loads(resp["Payload"].read())
    assert result.get("statusCode") == 200, f"Lambda returned error: {result}"
    assert "memories" in result


# ---------------------------------------------------------------------------
# Phase 5: Context Composer
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_composer_assembles_layers():
    """Verify composer loads available layers and returns SystemContentBlock list."""
    from glitch.auri_context import AuriContextComposer

    composer = AuriContextComposer()
    blocks = await composer.compose(
        session_id=f"test-composer-{uuid.uuid4().hex[:8]}",
        user_message="hello Arc",
        active_members=["Arc"],
    )

    # Should return at least one block if any S3 content exists
    # (may be empty if split files haven't been migrated yet — that's OK for pre-migration)
    if blocks:
        assembled = " ".join(
            b.get("text", "") for b in blocks if isinstance(b, dict) and "text" in b
        )
        assert "Auri" in assembled, f"Auri not found in assembled context: {assembled[:200]}"

        est_tokens = int(len(assembled.split()) * 1.3)
        assert est_tokens < 3000, f"Assembled context too large: ~{est_tokens} tokens"


# ---------------------------------------------------------------------------
# Phase 6: Migration script dry-run
# ---------------------------------------------------------------------------

def test_migration_script_dry_run():
    """Verify the migration script runs in dry-run mode without errors."""
    from scripts.migrate_auri_split import AURI_CORE, AURI_RULES, AURI_LORE, estimate_tokens

    # Core should be under 900 tokens
    core_tokens = estimate_tokens(AURI_CORE)
    assert core_tokens < 900, f"Core too large: {core_tokens} tokens"

    # Rules should be under 900 tokens (relaxed from 500 due to user-requested content)
    rules_tokens = estimate_tokens(AURI_RULES)
    assert rules_tokens < 900, f"Rules too large: {rules_tokens} tokens"

    # Combined should be under 2000 tokens
    combined = core_tokens + rules_tokens
    assert combined < 2000, f"Combined too large: {combined} tokens"

    # Content checks
    assert "AB/DL" in AURI_CORE or "ab/dl" in AURI_CORE.lower(), "Core missing AB/DL caretaker role"
    assert "remember_auri" in AURI_RULES, "Rules missing memory tool instructions"
    assert "update_participant_profile" in AURI_RULES, "Rules missing participant profile tool"
    assert "Naughty" in AURI_RULES or "naughty" in AURI_RULES.lower(), "Rules missing naughty escalation"
    assert "Growth" in AURI_RULES, "Rules missing growth/learning rules"


# ---------------------------------------------------------------------------
# Haiku model routing + brevity instruction
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_context_composer_includes_brevity_instruction():
    """Verify the roleplay preamble injected by AuriContextComposer contains the brevity rule."""
    from glitch.auri_context import AuriContextComposer

    composer = AuriContextComposer()
    blocks = await composer.compose(
        session_id=f"test-brevity-{uuid.uuid4().hex[:8]}",
        user_message="hello",
        active_members=[],
    )
    if blocks:
        assembled = " ".join(
            b.get("text", "") for b in blocks if isinstance(b, dict) and "text" in b
        )
        assert "1" in assembled and "3 sentence" in assembled.lower() or \
               "1–3 sentences" in assembled or "brevity" in assembled.lower(), \
            f"Brevity instruction not found in assembled context: {assembled[:400]}"


@pytest.mark.asyncio
async def test_apply_mode_with_memories_roleplay_includes_brevity():
    """Verify the fallback roleplay preamble (modes.py) also includes the brevity rule."""
    from glitch.modes import apply_mode_with_memories, MODE_ROLEPLAY

    _prompt, sys_out, _ctx = await apply_mode_with_memories(
        MODE_ROLEPLAY, "tell me a story", system_prompt=None,
    )
    # sys_out may be None if no Auri content in S3, but if set it must include brevity
    if sys_out:
        assert "1–3 sentences" in sys_out or "brevity" in sys_out.lower(), \
            f"Brevity rule missing from roleplay system prompt: {sys_out[:400]}"
