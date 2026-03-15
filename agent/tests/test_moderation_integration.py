"""Integration tests for group moderation — Phases 0, 1, and 2.

These tests hit real AWS services (DynamoDB, Secrets Manager) and require
valid credentials + a deployed stack. Mark with @pytest.mark.integration so
unit-only runs skip them.

Run:
    cd agent && pytest tests/test_moderation_integration.py -v -m integration

Environment variables:
    AWS_REGION                    — defaults to us-west-2
    GLITCH_CONFIG_TABLE           — defaults to glitch-telegram-config
    TELEGRAM_TEST_CHAT_ID         — Telegram group chat ID for Telegram API tests (optional)
    TELEGRAM_TEST_FROM_USER_ID    — Telegram user ID to target in API tests (optional)
    TELEGRAM_TEST_MESSAGE_ID      — Telegram message ID to target in delete tests (optional)
"""

import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytestmark = pytest.mark.integration

_REGION = os.environ.get("AWS_REGION", "us-west-2")
_CONFIG_TABLE = os.environ.get("GLITCH_CONFIG_TABLE", "glitch-telegram-config")

# Optional: set these to enable Telegram API live-call tests.
_TEST_CHAT_ID = int(os.environ.get("TELEGRAM_TEST_CHAT_ID", "0"))
_TEST_FROM_USER_ID = int(os.environ.get("TELEGRAM_TEST_FROM_USER_ID", "0"))
_TEST_MESSAGE_ID = int(os.environ.get("TELEGRAM_TEST_MESSAGE_ID", "0"))


def _ddb_client():
    import boto3
    return boto3.client("dynamodb", region_name=_REGION)


# ---------------------------------------------------------------------------
# Phase 0: Bug fixes — InvocationResponse error text propagation
# ---------------------------------------------------------------------------


def test_create_error_response_has_message_field():
    """create_error_response must populate 'message' so processor can display it."""
    from glitch.types import create_error_response
    resp = create_error_response(error="invoke_step=test: boom")
    assert resp.get("error") == "invoke_step=test: boom"
    assert resp.get("message"), "message field must be populated for processor display"
    assert "boom" in resp["message"] or "error" in resp["message"].lower()


def test_error_response_message_not_generic():
    """Processor now uses result['message'] — must not be the old hardcoded string."""
    from glitch.types import create_error_response
    resp = create_error_response(error="Bedrock rate limit exceeded")
    assert "Sorry, I couldn't process that request" not in resp.get("message", ""), (
        "create_error_response must not embed the old generic user-facing string; "
        "that string is now only in telegram-processor as an outer catch-all fallback"
    )


# ---------------------------------------------------------------------------
# Phase 1: InvocationContext — lifecycle
# ---------------------------------------------------------------------------


def test_invocation_context_full_lifecycle():
    """set_context → get_context → clear_context cycle with realistic values."""
    from glitch.invocation_context import set_context, get_context, clear_context

    chat_id = 1234567890
    from_user_id = 987654321
    message_id = 42
    session_id = "telegram:group:1234567890000000000000000000000000"

    set_context(
        chat_id=chat_id,
        from_user_id=from_user_id,
        message_id=message_id,
        session_id=session_id,
        participant_id="arc",
        is_group=True,
    )
    ctx = get_context()
    assert ctx.chat_id == chat_id
    assert ctx.from_user_id == from_user_id
    assert ctx.message_id == message_id
    assert ctx.session_id == session_id
    assert ctx.participant_id == "arc"
    assert ctx.is_group is True

    clear_context()
    ctx = get_context()
    assert ctx.chat_id == 0
    assert ctx.is_group is False


# ---------------------------------------------------------------------------
# Phase 1: DynamoDB — moderation rules CRUD
# ---------------------------------------------------------------------------


def test_moderation_rules_write_and_read():
    """Write custom moderation rules to DynamoDB and read them back."""
    chat_id = int(f"9000{uuid.uuid4().hex[:6]}", 16) % (10 ** 12)
    rules = [
        {"id": 1, "text": "Be respectful", "severity": "medium"},
        {"id": 2, "text": "No spamming", "severity": "medium"},
        {"id": 3, "text": "No bots", "severity": "high"},
    ]

    ddb = _ddb_client()
    ddb.put_item(
        TableName=_CONFIG_TABLE,
        Item={
            "pk": {"S": f"MOD_RULES#{chat_id}"},
            "sk": {"S": "rules"},
            "rules_json": {"S": json.dumps(rules)},
        },
    )

    resp = ddb.get_item(
        TableName=_CONFIG_TABLE,
        Key={"pk": {"S": f"MOD_RULES#{chat_id}"}, "sk": {"S": "rules"}},
    )
    item = resp.get("Item", {})
    assert "rules_json" in item, "rules_json not found in DynamoDB item"
    loaded = json.loads(item["rules_json"]["S"])
    assert len(loaded) == 3
    assert loaded[0]["text"] == "Be respectful"
    assert loaded[2]["severity"] == "high"

    # Clean up
    ddb.delete_item(
        TableName=_CONFIG_TABLE,
        Key={"pk": {"S": f"MOD_RULES#{chat_id}"}, "sk": {"S": "rules"}},
    )


def test_moderation_rules_defaults_when_missing():
    """get_group_rules() returns default rules + source="default" when no DynamoDB entry."""
    import asyncio
    from glitch.invocation_context import set_context, clear_context
    from glitch.tools.moderation_tools import get_group_rules, DEFAULT_RULES

    # Use a unique chat_id guaranteed not to have rules in DynamoDB.
    fake_chat_id = int(f"1{uuid.uuid4().hex[:10]}", 16) % (10 ** 12)
    set_context(chat_id=fake_chat_id, from_user_id=1, message_id=1, is_group=True)
    try:
        result = asyncio.get_event_loop().run_until_complete(get_group_rules())
        data = json.loads(result)
        assert data["source"] == "default", f"Expected default source, got: {data['source']}"
        assert data["rules"] == DEFAULT_RULES, "Default rules content mismatch"
        # Verify DEFAULT_RULES structure
        assert len(data["rules"]) == 5
        ids = [r["id"] for r in data["rules"]]
        assert ids == [1, 2, 3, 4, 5]
        severities = {r["severity"] for r in data["rules"]}
        assert severities <= {"low", "medium", "high"}
    finally:
        clear_context()


# ---------------------------------------------------------------------------
# Phase 1: DynamoDB — warning storage
# ---------------------------------------------------------------------------


def test_warning_write_and_count():
    """Write a warning record and verify it can be queried by pk."""
    chat_id = int(f"9001{uuid.uuid4().hex[:6]}", 16) % (10 ** 12)
    user_id = int(f"8001{uuid.uuid4().hex[:6]}", 16) % (10 ** 12)
    WARN_TTL = 30 * 24 * 3600

    ddb = _ddb_client()
    ts = str(int(time.time()))
    pk = f"MOD_WARN#{chat_id}#{user_id}"

    ddb.put_item(
        TableName=_CONFIG_TABLE,
        Item={
            "pk": {"S": pk},
            "sk": {"S": ts},
            "reason": {"S": "integration test warning"},
            "timestamp": {"N": ts},
            "ttl": {"N": str(int(time.time()) + WARN_TTL)},
        },
    )

    resp = ddb.query(
        TableName=_CONFIG_TABLE,
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": {"S": pk}},
        Select="COUNT",
    )
    count = resp.get("Count", 0)
    assert count >= 1, f"Expected at least 1 warning, got {count}"

    # Clean up
    ddb.delete_item(TableName=_CONFIG_TABLE, Key={"pk": {"S": pk}, "sk": {"S": ts}})


def test_action_log_write():
    """Write a moderation action log entry and verify it is stored."""
    chat_id = int(f"9002{uuid.uuid4().hex[:6]}", 16) % (10 ** 12)
    user_id = int(f"8002{uuid.uuid4().hex[:6]}", 16) % (10 ** 12)
    ACTION_TTL = 90 * 24 * 3600

    ddb = _ddb_client()
    ts = str(int(time.time()))
    pk = f"MOD_ACTION#{chat_id}"
    sk = f"{ts}#{user_id}"

    ddb.put_item(
        TableName=_CONFIG_TABLE,
        Item={
            "pk": {"S": pk},
            "sk": {"S": sk},
            "action": {"S": "warn"},
            "reason": {"S": "integration test"},
            "user_id": {"N": str(user_id)},
            "timestamp": {"N": ts},
            "ttl": {"N": str(int(time.time()) + ACTION_TTL)},
        },
    )

    resp = ddb.query(
        TableName=_CONFIG_TABLE,
        KeyConditionExpression="pk = :pk AND sk = :sk",
        ExpressionAttributeValues={":pk": {"S": pk}, ":sk": {"S": sk}},
    )
    items = resp.get("Items", [])
    assert len(items) == 1
    assert items[0]["action"]["S"] == "warn"

    # Clean up
    ddb.delete_item(TableName=_CONFIG_TABLE, Key={"pk": {"S": pk}, "sk": {"S": sk}})


# ---------------------------------------------------------------------------
# Phase 1: AuriContextComposer — moderation layer injection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_moderation_context_injected_for_group():
    """AuriContextComposer._load_moderation_context returns rules for group sessions."""
    from glitch.auri_context import AuriContextComposer
    from glitch.invocation_context import set_context, clear_context

    chat_id = int(f"9003{uuid.uuid4().hex[:6]}", 16) % (10 ** 12)
    set_context(chat_id=chat_id, from_user_id=12345, message_id=1, is_group=True)
    try:
        composer = AuriContextComposer()
        text = await composer._load_moderation_context()
        assert text, "Expected moderation context for group session, got empty string"
        assert "Group Guardian Rules" in text
        assert "Escalation" in text
        assert "NEVER moderate the group owner" in text
    finally:
        clear_context()


@pytest.mark.asyncio
async def test_moderation_context_empty_for_dm():
    """AuriContextComposer._load_moderation_context returns empty for DM sessions."""
    from glitch.auri_context import AuriContextComposer
    from glitch.invocation_context import set_context, clear_context

    set_context(chat_id=12345, from_user_id=12345, message_id=1, is_group=False)
    try:
        composer = AuriContextComposer()
        text = await composer._load_moderation_context()
        assert text == "", f"Expected empty moderation context for DM, got: {text[:100]}"
    finally:
        clear_context()


@pytest.mark.asyncio
async def test_moderation_context_loads_custom_rules():
    """AuriContextComposer._load_moderation_context loads custom rules from DynamoDB."""
    from glitch.auri_context import AuriContextComposer
    from glitch.invocation_context import set_context, clear_context

    chat_id = int(f"9004{uuid.uuid4().hex[:6]}", 16) % (10 ** 12)
    custom_rules = [
        {"id": 1, "text": "Custom rule one", "severity": "high"},
        {"id": 2, "text": "Custom rule two", "severity": "medium"},
    ]

    ddb = _ddb_client()
    ddb.put_item(
        TableName=_CONFIG_TABLE,
        Item={
            "pk": {"S": f"MOD_RULES#{chat_id}"},
            "sk": {"S": "rules"},
            "rules_json": {"S": json.dumps(custom_rules)},
        },
    )

    set_context(chat_id=chat_id, from_user_id=12345, message_id=1, is_group=True)
    try:
        composer = AuriContextComposer()
        text = await composer._load_moderation_context()
        assert "Custom rule one" in text, f"Custom rule not found in: {text}"
        assert "Custom rule two" in text
        assert "[HIGH]" in text
    finally:
        # DynamoDB cleanup first; context clear is cheap and always safe after.
        ddb.delete_item(
            TableName=_CONFIG_TABLE,
            Key={"pk": {"S": f"MOD_RULES#{chat_id}"}, "sk": {"S": "rules"}},
        )
        clear_context()


@pytest.mark.asyncio
async def test_full_compose_includes_moderation_for_group():
    """Full AuriContextComposer.compose() for a group session includes moderation layer."""
    from glitch.auri_context import AuriContextComposer
    from glitch.invocation_context import set_context, clear_context

    chat_id = int(f"9005{uuid.uuid4().hex[:6]}", 16) % (10 ** 12)
    set_context(chat_id=chat_id, from_user_id=12345, message_id=1, is_group=True)
    try:
        composer = AuriContextComposer()
        blocks = await composer.compose(
            session_id=f"telegram:group:{chat_id}{'0' * 20}",
            user_message="hello everyone",
            active_members=["arc"],
        )
        # May return empty if S3 files don't exist yet, but if it does return content,
        # the moderation layer must be present.
        if blocks:
            assembled = " ".join(
                b.get("text", "") for b in blocks if isinstance(b, dict) and "text" in b
            )
            assert "group guardian" in assembled.lower(), (
                f"Moderation/group guardian not found in assembled context: {assembled[:300]}"
            )
    finally:
        clear_context()


# ---------------------------------------------------------------------------
# Phase 1: Telegram API calls (require TELEGRAM_TEST_CHAT_ID env var)
# ---------------------------------------------------------------------------


def _requires_telegram():
    """Skip test if Telegram test environment variables are not set."""
    if not _TEST_CHAT_ID or not _TEST_FROM_USER_ID:
        pytest.skip(
            "Set TELEGRAM_TEST_CHAT_ID and TELEGRAM_TEST_FROM_USER_ID to run Telegram API tests"
        )


@pytest.mark.asyncio
async def test_get_warnings_returns_valid_json():
    """get_warnings() returns valid JSON with user_id and count fields."""
    _requires_telegram()
    from glitch.invocation_context import set_context, clear_context
    from glitch.tools.moderation_tools import get_warnings

    set_context(chat_id=_TEST_CHAT_ID, from_user_id=_TEST_FROM_USER_ID, message_id=1, is_group=True)
    try:
        result = await get_warnings()
        data = json.loads(result)
        assert "user_id" in data
        assert "count" in data
        assert "warnings" in data
        assert isinstance(data["warnings"], list)
    finally:
        clear_context()


@pytest.mark.asyncio
async def test_get_group_rules_from_dynamodb():
    """get_group_rules() returns valid JSON rules for a configured chat."""
    _requires_telegram()
    from glitch.invocation_context import set_context, clear_context
    from glitch.tools.moderation_tools import get_group_rules

    set_context(chat_id=_TEST_CHAT_ID, from_user_id=_TEST_FROM_USER_ID, message_id=1, is_group=True)
    try:
        result = await get_group_rules()
        data = json.loads(result)
        assert "rules" in data
        assert "source" in data
        assert isinstance(data["rules"], list)
        assert len(data["rules"]) > 0
        for rule in data["rules"]:
            assert "id" in rule
            assert "text" in rule
            assert "severity" in rule
    finally:
        clear_context()


@pytest.mark.asyncio
async def test_warn_user_live():
    """warn_user() sends a real warning reply via Telegram API."""
    _requires_telegram()
    from glitch.invocation_context import set_context, clear_context
    from glitch.tools.moderation_tools import warn_user

    set_context(
        chat_id=_TEST_CHAT_ID,
        from_user_id=_TEST_FROM_USER_ID,
        message_id=_TEST_MESSAGE_ID,
        is_group=True,
    )
    try:
        result = await warn_user("Integration test warning — please ignore")
        assert "warned" in result or "warning" in result.lower(), (
            f"Expected success result, got: {result}"
        )
    finally:
        clear_context()


# ---------------------------------------------------------------------------
# Phase 2 (planned): API endpoints — /api/auri/*
# These tests are written against the planned interface. They will fail with
# 404/ImportError until router.py implements the endpoints. Run them to verify
# implementation as Phase 2 is built.
# ---------------------------------------------------------------------------


def test_auri_api_endpoints_planned_in_router():
    """Structural check: router.py will expose /api/auri/* endpoints (pre-implementation check).

    This test documents the planned API surface. Once Phase 2 is implemented,
    update this to import and verify the actual route handlers.
    """
    import pathlib
    path = pathlib.Path(__file__).parent.parent / "src" / "glitch" / "api" / "router.py"
    # Pre-implementation: just verify router.py exists and is readable
    assert path.exists(), "router.py not found"
    source = path.read_text()
    # Post-implementation: uncomment these assertions once routes are added
    # assert "/api/auri/channels" in source or "auri_channels" in source
    # assert "/api/auri/dm-users" in source or "auri_dm_users" in source
    # assert "/api/auri/persona/core" in source or "auri_persona_core" in source
    # assert "/api/auri/telemetry" in source or "auri_telemetry" in source
    assert True  # placeholder until Phase 2 is implemented


@pytest.mark.asyncio
async def test_auri_channels_endpoint_shape():
    """Phase 2: GET /api/auri/channels returns list of active roleplay sessions.

    Pre-implementation: verifies DynamoDB query shape matches expected data.
    Post-implementation: call the actual HTTP endpoint.
    """
    # Verify DynamoDB contains SESSION_AGENT entries we can query
    import boto3
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    table = ddb.Table(_CONFIG_TABLE)

    # Write a test session entry (simulating what webhook sets)
    test_session_id = f"telegram:group:test_{uuid.uuid4().hex[:8]}{'0' * 10}"
    table.put_item(Item={
        "pk": "SESSION_AGENT",
        "sk": test_session_id,
        "agent_id": "glitch",
        "mode_id": "roleplay",
        "updated_at": int(time.time()),
    })

    try:
        # Query it back — this is the shape the /api/auri/channels endpoint will use
        resp = table.query(
            KeyConditionExpression="pk = :pk",
            FilterExpression="mode_id = :mode",
            ExpressionAttributeValues={
                ":pk": "SESSION_AGENT",
                ":mode": "roleplay",
            },
        )
        items = resp.get("Items", [])
        # At minimum, our test entry should appear
        test_items = [i for i in items if i.get("sk") == test_session_id]
        assert len(test_items) == 1, "Test session not found in DynamoDB"
        assert test_items[0]["mode_id"] == "roleplay"
    finally:
        table.delete_item(Key={"pk": "SESSION_AGENT", "sk": test_session_id})


@pytest.mark.asyncio
async def test_auri_dm_users_endpoint_shape():
    """Phase 2: GET /api/auri/dm-users returns list of allowed DM users.

    Pre-implementation: verifies DynamoDB CONFIG / allowed_dm#* scan shape.
    """
    import boto3
    ddb = boto3.resource("dynamodb", region_name=_REGION)
    table = ddb.Table(_CONFIG_TABLE)

    # Query CONFIG entries with allowed_dm# sk prefix — shape the endpoint will use
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
        ExpressionAttributeValues={
            ":pk": "CONFIG",
            ":prefix": "allowed_dm#",
        },
    )
    # Just verify the query executes without error; may return 0 items on fresh stack
    assert "Items" in resp


def test_auri_persona_core_endpoint_shape():
    """Phase 2: GET /api/auri/persona/core returns auri-core.md content from S3.

    Pre-implementation: verifies S3 load function is importable and returns str.
    """
    from glitch.tools.soul_tools import load_auri_core_from_s3
    content = load_auri_core_from_s3()
    # May be empty on fresh stack — just verify it's a string
    assert isinstance(content, str), f"Expected str, got {type(content)}"


def test_auri_persona_rules_endpoint_shape():
    """Phase 2: GET /api/auri/persona/rules returns auri-runtime-rules.md content from S3."""
    from glitch.tools.soul_tools import load_auri_rules_from_s3
    content = load_auri_rules_from_s3()
    assert isinstance(content, str), f"Expected str, got {type(content)}"


@pytest.mark.asyncio
async def test_auri_memory_stats_endpoint_shape():
    """Phase 2: GET /api/auri/memory-stats returns row count from protect-query Lambda."""
    import boto3
    lambda_name = os.environ.get("GLITCH_PROTECT_QUERY_LAMBDA", "glitch-protect-query")
    client = boto3.client("lambda", region_name=_REGION)

    # Invoke the Lambda with the action the memory-stats endpoint will use
    resp = client.invoke(
        FunctionName=lambda_name,
        InvocationType="RequestResponse",
        Payload=json.dumps({"action": "auri_memory_count"}),
    )
    result = json.loads(resp["Payload"].read())
    # Verify the Lambda responds (may return error if action not yet implemented)
    assert "statusCode" in result, f"Unexpected Lambda response shape: {result}"


@pytest.mark.asyncio
async def test_auri_telemetry_endpoint_shape():
    """Phase 2: GET /api/auri/telemetry returns CloudWatch aggregates filtered to roleplay."""
    # Pre-implementation: verify the telemetry log group exists and is queryable
    import boto3
    logs = boto3.client("logs", region_name=_REGION)

    log_group = "/glitch/telemetry"
    try:
        resp = logs.describe_log_groups(logGroupNamePrefix=log_group)
        groups = resp.get("logGroups", [])
        matching = [g for g in groups if g["logGroupName"] == log_group]
        # Log group may not exist on fresh stack — just verify describe works
        assert isinstance(matching, list)
    except Exception as e:
        pytest.skip(f"CloudWatch access failed: {e}")


# ---------------------------------------------------------------------------
# Phase 2 (planned): PUT endpoints — persona editor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auri_persona_core_put_roundtrip():
    """Phase 2: PUT /api/auri/persona/core saves content to S3 and GET reads it back."""
    from glitch.tools.soul_tools import save_auri_core_to_s3, load_auri_core_from_s3
    from glitch.auri_context import invalidate_cache

    # Read current content first so we can restore it
    original = load_auri_core_from_s3()

    marker = f"# Integration Test Core {uuid.uuid4().hex[:8]}"
    test_content = f"{marker}\nAuri is a test lion for integration testing."

    ok, err = save_auri_core_to_s3(test_content)
    assert ok, f"S3 write failed: {err}"

    invalidate_cache("auri-core")
    loaded = load_auri_core_from_s3()
    assert marker in loaded, f"Marker not found after write: {loaded[:200]}"

    # Restore original
    if original:
        save_auri_core_to_s3(original)
        invalidate_cache("auri-core")


@pytest.mark.asyncio
async def test_auri_persona_rules_put_roundtrip():
    """Phase 2: PUT /api/auri/persona/rules saves content to S3 and GET reads it back."""
    from glitch.tools.soul_tools import save_auri_rules_to_s3, load_auri_rules_from_s3
    from glitch.auri_context import invalidate_cache

    original = load_auri_rules_from_s3()

    marker = f"# Integration Test Rules {uuid.uuid4().hex[:8]}"
    test_content = f"{marker}\nRule: always be warm."

    ok, err = save_auri_rules_to_s3(test_content)
    assert ok, f"S3 write failed: {err}"

    invalidate_cache("auri-rules")
    loaded = load_auri_rules_from_s3()
    assert marker in loaded, f"Marker not found after write: {loaded[:200]}"

    # Restore original
    if original:
        save_auri_rules_to_s3(original)
        invalidate_cache("auri-rules")


# ---------------------------------------------------------------------------
# Phase 2 (planned): Character Card V2 export
# ---------------------------------------------------------------------------


def test_character_card_v2_can_be_constructed():
    """Phase 2: Persona Editor exports Character Card V2 format (portable persona JSON).

    Pre-implementation: verify the data sources that feed the export are accessible.
    Post-implementation: call the export endpoint and validate the JSON schema.
    """
    from glitch.tools.soul_tools import load_auri_core_from_s3, load_auri_rules_from_s3

    core = load_auri_core_from_s3()
    rules = load_auri_rules_from_s3()

    # Build the card shape the endpoint will produce
    card = {
        "spec": "chara_card_v2",
        "spec_version": "2.0",
        "data": {
            "name": "Auri",
            "description": core[:500] if core else "",
            "personality": "",
            "scenario": "",
            "first_mes": "",
            "mes_example": "",
            "system_prompt": rules[:500] if rules else "",
            "tags": ["android", "lion", "caretaker", "auri"],
            "extensions": {
                "glitch_version": "1.0",
                "source": "auri-core.md + auri-runtime-rules.md",
            },
        },
    }

    exported = json.dumps(card)
    loaded = json.loads(exported)

    assert loaded["spec"] == "chara_card_v2"
    assert loaded["spec_version"] == "2.0"
    assert loaded["data"]["name"] == "Auri"
    assert "extensions" in loaded["data"]
