"""SOUL.md load/save from S3 and update_soul tool for persistent personality.

Bucket is resolved by: GLITCH_SOUL_S3_BUCKET env, then SSM /glitch/soul/s3-bucket,
then derived from AWS account+region (glitch-agent-state-{account}-{region}).
"""

import logging
import os
from typing import Tuple

from strands import tool

from glitch.aws_utils import get_client

logger = logging.getLogger(__name__)

DEFAULT_SOUL_KEY = "soul.md"
SSM_SOUL_BUCKET = "/glitch/soul/s3-bucket"
SSM_SOUL_KEY = "/glitch/soul/s3-key"
SSM_POET_SOUL_KEY = "/glitch/soul/poet-soul-s3-key"
DEFAULT_POET_SOUL_KEY = "poet-soul.md"
SSM_AURI_S3_KEY = "/glitch/soul/auri-s3-key"
DEFAULT_AURI_KEY = "auri.md"
SSM_STORY_BOOK_KEY = "/glitch/soul/story-book-s3-key"
DEFAULT_STORY_BOOK_KEY = "story-book.md"
SSM_AURI_CORE_S3_KEY = "/glitch/soul/auri-core-s3-key"
DEFAULT_AURI_CORE_KEY = "auri-core.md"
SSM_AURI_RULES_S3_KEY = "/glitch/soul/auri-rules-s3-key"
DEFAULT_AURI_RULES_KEY = "auri-runtime-rules.md"

# Cached SSM result so we don't call SSM on every get_soul_s3_config().
_ssm_soul_config: Tuple[str | None, str] | None = None
_ssm_poet_soul_key: str | None = None
_ssm_auri_s3_key: str | None = None
_ssm_story_book_key: str | None = None
_ssm_auri_core_s3_key: str | None = None
_ssm_auri_rules_s3_key: str | None = None


def _is_placeholder_bucket(value: str | None) -> bool:
    """Return True for obvious non-real placeholder bucket values."""
    if not value:
        return False
    v = value.strip().lower()
    return (
        v == "placeholder"
        or v == "changeme"
        or v.startswith("dummy-value-for-")
        or v.startswith("${")
    )


def _get_soul_s3_config_from_ssm() -> Tuple[str | None, str]:
    """Fetch SOUL S3 bucket/key from SSM. Returns (None, default_key) on failure."""
    global _ssm_soul_config
    if _ssm_soul_config is not None:
        return _ssm_soul_config
    try:
        client = get_client("ssm")
        resp = client.get_parameters(
            Names=[SSM_SOUL_BUCKET, SSM_SOUL_KEY],
            WithDecryption=False,
        )
        params = {p["Name"]: p["Value"] for p in resp.get("Parameters", []) if "Value" in p}
        bucket = (params.get(SSM_SOUL_BUCKET) or "").strip() or None
        key = (params.get(SSM_SOUL_KEY) or DEFAULT_SOUL_KEY).strip() or DEFAULT_SOUL_KEY
        if bucket:
            logger.info("SOUL S3 config from SSM: bucket=%s key=%s", bucket, key)
            _ssm_soul_config = (bucket, key)  # only cache when we have a real bucket
        return (bucket, key)
    except Exception as e:
        logger.debug("Could not read SOUL S3 config from SSM: %s", e)
        # Don't cache a failure — allow retry and identity fallback on next call
        return (None, DEFAULT_SOUL_KEY)


def _get_soul_bucket_from_identity() -> str | None:
    """Derive soul bucket name from current AWS account and region (same as GlitchStorageStack).

    Allows the agent to find the bucket without env or SSM when running in the expected account.
    """
    try:
        sts = get_client("sts")
        identity = sts.get_caller_identity()
        account = identity.get("Account")
        region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
        if account and region:
            bucket = f"glitch-agent-state-{account}-{region}"
            logger.info("SOUL S3 bucket derived from identity: %s", bucket)
            return bucket
    except Exception as e:
        logger.debug("Could not derive soul bucket from identity: %s", e)
    return None


def get_soul_s3_config() -> Tuple[str | None, str]:
    """Return (bucket, key) for SOUL in S3, or (None, key) if not configured.

    Precedence:
    1. GLITCH_SOUL_S3_BUCKET env (and optionally GLITCH_SOUL_S3_KEY)
    2. SSM /glitch/soul/s3-bucket (when GlitchStorageStack is deployed)
    3. Derived from AWS account + region: glitch-agent-state-{account}-{region}
    """
    bucket = (os.environ.get("GLITCH_SOUL_S3_BUCKET") or "").strip() or None
    key = (os.environ.get("GLITCH_SOUL_S3_KEY") or DEFAULT_SOUL_KEY).strip() or DEFAULT_SOUL_KEY
    if bucket and not _is_placeholder_bucket(bucket):
        return bucket, key
    if bucket and _is_placeholder_bucket(bucket):
        logger.warning(
            "Ignoring placeholder GLITCH_SOUL_S3_BUCKET value: %s; falling back to SSM/identity lookup",
            bucket,
        )
    bucket, key = _get_soul_s3_config_from_ssm()
    if bucket and not _is_placeholder_bucket(bucket):
        return bucket, key
    if bucket and _is_placeholder_bucket(bucket):
        logger.warning(
            "Ignoring placeholder SSM soul bucket value: %s; falling back to identity-derived bucket",
            bucket,
        )
    # Fallback: same naming convention as GlitchStorageStack
    derived = _get_soul_bucket_from_identity()
    return (derived, key) if derived else (None, key)


def get_poet_soul_s3_config() -> Tuple[str | None, str]:
    """Return (bucket, key) for poet-soul.md in S3, or (None, key) if bucket not configured.

    Uses same bucket as SOUL (from get_soul_s3_config). Key: GLITCH_POET_SOUL_S3_KEY env,
    else SSM /glitch/soul/poet-soul-s3-key, else poet-soul.md.
    """
    bucket, _ = get_soul_s3_config()
    if not bucket:
        return None, DEFAULT_POET_SOUL_KEY
    key = os.environ.get("GLITCH_POET_SOUL_S3_KEY") or _get_poet_soul_s3_key_from_ssm()
    return bucket, (key or DEFAULT_POET_SOUL_KEY).strip() or DEFAULT_POET_SOUL_KEY


def _get_poet_soul_s3_key_from_ssm() -> str:
    """Return poet-soul S3 key from SSM; cache and fallback to default."""
    global _ssm_poet_soul_key
    if _ssm_poet_soul_key is not None:
        return _ssm_poet_soul_key
    try:
        client = get_client("ssm")
        resp = client.get_parameter(Name=SSM_POET_SOUL_KEY, WithDecryption=False)
        _ssm_poet_soul_key = (resp.get("Parameter", {}).get("Value") or DEFAULT_POET_SOUL_KEY).strip() or DEFAULT_POET_SOUL_KEY
        return _ssm_poet_soul_key
    except Exception:
        _ssm_poet_soul_key = DEFAULT_POET_SOUL_KEY
        return _ssm_poet_soul_key


def get_auri_s3_config() -> Tuple[str | None, str]:
    """Return (bucket, key) for auri.md in S3, or (None, key) if bucket not configured.

    Uses same bucket as SOUL. Key: GLITCH_AURI_S3_KEY env,
    else SSM /glitch/soul/auri-s3-key, else auri.md.
    """
    bucket, _ = get_soul_s3_config()
    if not bucket:
        return None, DEFAULT_AURI_KEY
    key = os.environ.get("GLITCH_AURI_S3_KEY") or _get_auri_s3_key_from_ssm()
    return bucket, (key or DEFAULT_AURI_KEY).strip() or DEFAULT_AURI_KEY


def _get_auri_s3_key_from_ssm() -> str:
    """Return auri S3 key from SSM; cache and fallback to default."""
    global _ssm_auri_s3_key
    if _ssm_auri_s3_key is not None:
        return _ssm_auri_s3_key
    try:
        client = get_client("ssm")
        resp = client.get_parameter(Name=SSM_AURI_S3_KEY, WithDecryption=False)
        _ssm_auri_s3_key = (resp.get("Parameter", {}).get("Value") or DEFAULT_AURI_KEY).strip() or DEFAULT_AURI_KEY
        return _ssm_auri_s3_key
    except Exception:
        _ssm_auri_s3_key = DEFAULT_AURI_KEY
        return _ssm_auri_s3_key


def load_auri_from_s3() -> str:
    """Load auri.md content from S3. Returns empty string on missing or error."""
    bucket, key = get_auri_s3_config()
    if not bucket:
        return ""
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read().decode("utf-8")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            logger.debug("auri key %s not found in bucket %s", key, bucket)
        else:
            logger.warning("Failed to load auri from S3 %s/%s: %s", bucket, key, e)
        return ""
    except Exception as e:
        logger.warning("Failed to load auri from S3 %s/%s: %s", bucket, key, e)
        return ""


def save_auri_to_s3(content: str) -> Tuple[bool, str]:
    """Write auri.md content to S3. Returns (True, '') on success, (False, error) on failure."""
    bucket, key = get_auri_s3_config()
    if not bucket:
        return False, "no_bucket"
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        logger.info("Saved auri to s3://%s/%s", bucket, key)
        return True, ""
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code", "")
        logger.exception("Failed to save auri to S3 %s/%s: %s", bucket, key, e)
        return False, code or "S3Error"
    except Exception as e:
        logger.exception("Failed to save auri to S3 %s/%s: %s", bucket, key, e)
        return False, str(e)


def _get_auri_core_s3_key_from_ssm() -> str:
    """Return auri-core S3 key from SSM; cache and fallback to default."""
    global _ssm_auri_core_s3_key
    if _ssm_auri_core_s3_key is not None:
        return _ssm_auri_core_s3_key
    try:
        client = get_client("ssm")
        resp = client.get_parameter(Name=SSM_AURI_CORE_S3_KEY, WithDecryption=False)
        _ssm_auri_core_s3_key = (resp.get("Parameter", {}).get("Value") or DEFAULT_AURI_CORE_KEY).strip() or DEFAULT_AURI_CORE_KEY
        return _ssm_auri_core_s3_key
    except Exception:
        _ssm_auri_core_s3_key = DEFAULT_AURI_CORE_KEY
        return _ssm_auri_core_s3_key


def get_auri_core_s3_config() -> Tuple[str | None, str]:
    """Return (bucket, key) for auri-core.md in S3. Same bucket as SOUL."""
    bucket, _ = get_soul_s3_config()
    if not bucket:
        return None, DEFAULT_AURI_CORE_KEY
    key = os.environ.get("GLITCH_AURI_CORE_S3_KEY") or _get_auri_core_s3_key_from_ssm()
    return bucket, (key or DEFAULT_AURI_CORE_KEY).strip() or DEFAULT_AURI_CORE_KEY


def load_auri_core_from_s3() -> str:
    """Load auri-core.md content from S3. Returns empty string on missing or error."""
    bucket, key = get_auri_core_s3_config()
    if not bucket:
        return ""
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read().decode("utf-8")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            logger.debug("auri-core key %s not found in bucket %s", key, bucket)
        else:
            logger.warning("Failed to load auri-core from S3 %s/%s: %s", bucket, key, e)
        return ""
    except Exception as e:
        logger.warning("Failed to load auri-core from S3 %s/%s: %s", bucket, key, e)
        return ""


def save_auri_core_to_s3(content: str) -> Tuple[bool, str]:
    """Write auri-core.md content to S3. Returns (True, '') on success, (False, error) on failure."""
    bucket, key = get_auri_core_s3_config()
    if not bucket:
        return False, "no_bucket"
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        client.put_object(Bucket=bucket, Key=key, Body=content.encode("utf-8"), ContentType="text/markdown; charset=utf-8")
        logger.info("Saved auri-core to s3://%s/%s", bucket, key)
        return True, ""
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code", "")
        logger.exception("Failed to save auri-core to S3 %s/%s: %s", bucket, key, e)
        return False, code or "S3Error"
    except Exception as e:
        logger.exception("Failed to save auri-core to S3 %s/%s: %s", bucket, key, e)
        return False, str(e)


def _get_auri_rules_s3_key_from_ssm() -> str:
    """Return auri-runtime-rules S3 key from SSM; cache and fallback to default."""
    global _ssm_auri_rules_s3_key
    if _ssm_auri_rules_s3_key is not None:
        return _ssm_auri_rules_s3_key
    try:
        client = get_client("ssm")
        resp = client.get_parameter(Name=SSM_AURI_RULES_S3_KEY, WithDecryption=False)
        _ssm_auri_rules_s3_key = (resp.get("Parameter", {}).get("Value") or DEFAULT_AURI_RULES_KEY).strip() or DEFAULT_AURI_RULES_KEY
        return _ssm_auri_rules_s3_key
    except Exception:
        _ssm_auri_rules_s3_key = DEFAULT_AURI_RULES_KEY
        return _ssm_auri_rules_s3_key


def get_auri_rules_s3_config() -> Tuple[str | None, str]:
    """Return (bucket, key) for auri-runtime-rules.md in S3. Same bucket as SOUL."""
    bucket, _ = get_soul_s3_config()
    if not bucket:
        return None, DEFAULT_AURI_RULES_KEY
    key = os.environ.get("GLITCH_AURI_RULES_S3_KEY") or _get_auri_rules_s3_key_from_ssm()
    return bucket, (key or DEFAULT_AURI_RULES_KEY).strip() or DEFAULT_AURI_RULES_KEY


def load_auri_rules_from_s3() -> str:
    """Load auri-runtime-rules.md content from S3. Returns empty string on missing or error."""
    bucket, key = get_auri_rules_s3_config()
    if not bucket:
        return ""
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        resp = client.get_object(Bucket=bucket, Key=key)
        return resp["Body"].read().decode("utf-8")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            logger.debug("auri-rules key %s not found in bucket %s", key, bucket)
        else:
            logger.warning("Failed to load auri-rules from S3 %s/%s: %s", bucket, key, e)
        return ""
    except Exception as e:
        logger.warning("Failed to load auri-rules from S3 %s/%s: %s", bucket, key, e)
        return ""


def save_auri_rules_to_s3(content: str) -> Tuple[bool, str]:
    """Write auri-runtime-rules.md content to S3. Returns (True, '') on success, (False, error) on failure."""
    bucket, key = get_auri_rules_s3_config()
    if not bucket:
        return False, "no_bucket"
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        client.put_object(Bucket=bucket, Key=key, Body=content.encode("utf-8"), ContentType="text/markdown; charset=utf-8")
        logger.info("Saved auri-rules to s3://%s/%s", bucket, key)
        return True, ""
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code", "")
        logger.exception("Failed to save auri-rules to S3 %s/%s: %s", bucket, key, e)
        return False, code or "S3Error"
    except Exception as e:
        logger.exception("Failed to save auri-rules to S3 %s/%s: %s", bucket, key, e)
        return False, str(e)


@tool
def update_auri(contents: str) -> str:
    """[DEPRECATED — prefer update_auri_core or update_auri_rules]
    Update the monolithic auri.md (Auri persona definition) with new content.

    This overwrites the entire auri.md file. Use update_auri_core for identity/voice
    changes and update_auri_rules for behavioral rule tuning instead.

    Do NOT use this to record individual memories — use remember_auri.

    Args:
        contents: Full new content for auri.md (markdown string).

    Returns:
        Success or error message.
    """
    logger.warning("update_auri called — this tool is deprecated; prefer update_auri_core or update_auri_rules")
    if not contents or not contents.strip():
        return "Error: contents cannot be empty."
    ok, err = save_auri_to_s3(contents.strip())
    if ok:
        return (
            "auri.md updated successfully in S3. NOTE: update_auri is deprecated — "
            "prefer update_auri_core (identity) or update_auri_rules (behavior)."
        )
    bucket, _ = get_auri_s3_config()
    if not bucket:
        return "auri update skipped: S3 not configured (no bucket found)."
    if err == "NoSuchBucket":
        return "auri update failed: the configured bucket does not exist."
    if err == "AccessDenied":
        return "auri update failed: access denied to the S3 bucket."
    return f"auri update failed (S3 error: {err}). Check logs."


@tool
def update_auri_core(contents: str) -> str:
    """Update auri-core.md — Auri's always-on identity and personality kernel.

    Use this RARELY for structural identity changes: core personality traits, voice,
    character sheet details, slider defaults, emotional support protocol. This file
    is loaded on every roleplay turn (~600-900 tokens), so keep it compact.

    Do NOT use this for behavioral rules (use update_auri_rules) or episodic memories
    (use remember_auri).

    Args:
        contents: Full new content for auri-core.md (markdown string).

    Returns:
        Success or error message.
    """
    if not contents or not contents.strip():
        return "Error: contents cannot be empty."
    ok, err = save_auri_core_to_s3(contents.strip())
    if ok:
        return "auri-core.md updated in S3. New sessions will load the updated identity."
    bucket, _ = get_auri_core_s3_config()
    if not bucket:
        return "auri-core update skipped: S3 not configured (no bucket found)."
    return f"auri-core update failed (S3 error: {err}). Check logs."


@tool
def update_auri_rules(contents: str) -> str:
    """Update auri-runtime-rules.md — Auri's behavioral rules, protocols, and tool instructions.

    Use this for tuning behavioral rules: caretaking protocols, diaper duty, teasing style,
    escalation/de-escalation ladder, naughty/erotic gating, growth & learning rules,
    memory tool instructions, pride rules. Loaded every turn (~350-500 tokens).

    Do NOT use this for identity/personality changes (use update_auri_core) or episodic
    memories (use remember_auri).

    Args:
        contents: Full new content for auri-runtime-rules.md (markdown string).

    Returns:
        Success or error message.
    """
    if not contents or not contents.strip():
        return "Error: contents cannot be empty."
    ok, err = save_auri_rules_to_s3(contents.strip())
    if ok:
        return "auri-runtime-rules.md updated in S3. New sessions will load the updated rules."
    bucket, _ = get_auri_rules_s3_config()
    if not bucket:
        return "auri-rules update skipped: S3 not configured (no bucket found)."
    return f"auri-rules update failed (S3 error: {err}). Check logs."


def _get_story_book_s3_key_from_ssm() -> str:
    """Return story-book S3 key from SSM; cache and fallback to default."""
    global _ssm_story_book_key
    if _ssm_story_book_key is not None:
        return _ssm_story_book_key
    try:
        client = get_client("ssm")
        resp = client.get_parameter(Name=SSM_STORY_BOOK_KEY, WithDecryption=False)
        _ssm_story_book_key = (resp.get("Parameter", {}).get("Value") or DEFAULT_STORY_BOOK_KEY).strip() or DEFAULT_STORY_BOOK_KEY
        return _ssm_story_book_key
    except Exception:
        _ssm_story_book_key = DEFAULT_STORY_BOOK_KEY
        return _ssm_story_book_key


def get_story_book_s3_config() -> Tuple[str | None, str]:
    """Return (bucket, key) for story-book.md in S3, or (None, key) if bucket not configured.

    Uses same bucket as SOUL. Key: GLITCH_STORY_BOOK_S3_KEY env,
    else SSM /glitch/soul/story-book-s3-key, else story-book.md.
    """
    bucket, _ = get_soul_s3_config()
    if not bucket:
        return None, DEFAULT_STORY_BOOK_KEY
    key = os.environ.get("GLITCH_STORY_BOOK_S3_KEY") or _get_story_book_s3_key_from_ssm()
    return bucket, (key or DEFAULT_STORY_BOOK_KEY).strip() or DEFAULT_STORY_BOOK_KEY


def load_story_book_from_s3() -> str:
    """Load story-book content from S3. Returns empty string on missing or error."""
    bucket, key = get_story_book_s3_config()
    if not bucket:
        return ""
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        resp = client.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read()
        return body.decode("utf-8")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            logger.debug("Story book key %s not found in bucket %s", key, bucket)
        else:
            logger.warning("Failed to load story-book from S3 %s/%s: %s", bucket, key, e)
        return ""
    except Exception as e:
        logger.warning("Failed to load story-book from S3 %s/%s: %s", bucket, key, e)
        return ""


def save_story_book_to_s3(content: str) -> Tuple[bool, str]:
    """Write story-book content to S3. Returns (True, '') on success, (False, error_message) on failure."""
    bucket, key = get_story_book_s3_config()
    if not bucket:
        logger.warning("GLITCH_SOUL_S3_BUCKET not set, cannot save story-book to S3")
        return False, "no_bucket"
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        logger.info("Saved story-book to s3://%s/%s", bucket, key)
        return True, ""
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code", "")
        logger.exception("Failed to save story-book to S3 %s/%s: %s", bucket, key, e)
        if code == "NoSuchBucket":
            return False, "NoSuchBucket"
        if code == "AccessDenied" or code == "403":
            return False, "AccessDenied"
        return False, code or "S3Error"
    except Exception as e:
        logger.exception("Failed to save story-book to S3 %s/%s: %s", bucket, key, e)
        return False, str(e)


def load_soul_from_s3() -> str:
    """Load SOUL content from S3. Returns empty string on missing or error."""
    bucket, key = get_soul_s3_config()
    if not bucket:
        return ""
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        resp = client.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read()
        return body.decode("utf-8")
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            logger.info("SOUL key %s not found in bucket %s, using file fallback", key, bucket)
        else:
            logger.warning("Failed to load SOUL from S3 %s/%s: %s", bucket, key, e)
        return ""
    except Exception as e:
        logger.warning("Failed to load SOUL from S3 %s/%s: %s", bucket, key, e)
        return ""


def save_soul_to_s3(content: str) -> Tuple[bool, str]:
    """Write SOUL content to S3. Returns (True, '') on success, (False, error_message) on failure."""
    bucket, key = get_soul_s3_config()
    if not bucket:
        logger.warning("GLITCH_SOUL_S3_BUCKET not set, cannot save SOUL to S3")
        return False, "no_bucket"
    try:
        from botocore.exceptions import ClientError
        client = get_client("s3")
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        logger.info("Saved SOUL to s3://%s/%s", bucket, key)
        return True, ""
    except ClientError as e:
        code = (e.response.get("Error") or {}).get("Code", "")
        logger.exception("Failed to save SOUL to S3 %s/%s: %s", bucket, key, e)
        if code == "NoSuchBucket":
            return False, "NoSuchBucket"
        if code == "AccessDenied" or code == "403":
            return False, "AccessDenied"
        return False, code or "S3Error"
    except Exception as e:
        logger.exception("Failed to save SOUL to S3 %s/%s: %s", bucket, key, e)
        return False, str(e)


@tool
def update_soul(contents: str) -> str:
    """Update the persistent SOUL.md (your personality and instructions) with new content.

    Use this when the user asks you to change how you behave, remember a preference,
    or update your identity or rules. Write the full desired SOUL content (markdown).
    If S3 is not configured, the update is not persisted.

    Args:
        contents: Full new content for SOUL.md (markdown string).

    Returns:
        Success or error message.
    """
    if not contents or not contents.strip():
        return "Error: contents cannot be empty."
    ok, err = save_soul_to_s3(contents.strip())
    if ok:
        return (
            "SOUL.md updated successfully in S3. New sessions (e.g. next Telegram chat or "
            "restart) will load the new personality; this session continues with the previous prompt."
        )
    bucket, _ = get_soul_s3_config()
    if not bucket:
        return (
            "SOUL update skipped: S3 is not configured. The tool checks: (1) GLITCH_SOUL_S3_BUCKET env, "
            "(2) SSM /glitch/soul/s3-bucket (GlitchStorageStack), (3) bucket derived from AWS account+region. "
            "None were available. Set the env var, deploy GlitchStorageStack for SSM, or ensure the runtime "
            "role has sts:GetCallerIdentity so the fallback can find glitch-agent-state-{account}-{region}. "
            "Until then, edits apply only to this session."
        )
    if err == "NoSuchBucket":
        return (
            "SOUL update failed: the configured bucket does not exist. Ensure GLITCH_SOUL_S3_BUCKET (or "
            "SSM /glitch/soul/s3-bucket) matches the bucket created by GlitchTelegramWebhookStack "
            "(e.g. glitch-agent-state-{account}-{region}) and that the stack has been deployed."
        )
    if err == "AccessDenied":
        return (
            "SOUL update failed: access denied to the S3 bucket. Ensure the runtime execution role has "
            "GlitchSoulS3Access (s3:GetObject, s3:PutObject). Deploy GlitchTelegramWebhookStack so it "
            "attaches this policy to the role in .bedrock_agentcore.yaml."
        )
    return f"SOUL update failed (S3 error: {err}). Check logs and bucket permissions."


def _load_story_book_impl() -> str:
    """Load story-book from S3 or local fallback. Returns empty string if missing."""
    from pathlib import Path
    bucket, _ = get_story_book_s3_config()
    if bucket:
        content = load_story_book_from_s3()
        if content:
            return content
    for path in [
        Path(__file__).parent.parent.parent.parent / "story-book.md",  # agent/story-book.md
        Path("/app/story-book.md"),
        Path.home() / "story-book.md",
    ]:
        if path.exists():
            return path.read_text()
    return ""


def load_story_book() -> str:
    """Load story-book.md from S3 or local fallback. For use in prompts or callers that need the content."""
    return _load_story_book_impl()


@tool
def get_story_book() -> str:
    """Return the current story-book.md content (summaries and key details for long-running stories).

    Use this to read existing story-book entries before appending new ones, or when continuing
    a story so you have continuity. Returns empty string if none exists yet.
    """
    return _load_story_book_impl()


@tool
def update_story_book(contents: str) -> str:
    """Update the persistent story-book.md with story summaries and key details.

    Use this when the user wants to record summaries, characters, plot beats, or tone
    for long-running stories so you can keep continuity when iterating later.
    Story-book is stored in the same S3 bucket as poet-soul.md. To append, first call
    get_story_book to get current content, then pass existing content plus the new section.

    Args:
        contents: Full new content for story-book.md (markdown). To add a section, include
            existing content plus the new entry (e.g. a dated section or story title + details).

    Returns:
        Success or error message.
    """
    if not contents or not contents.strip():
        return "Error: contents cannot be empty."
    ok, err = save_story_book_to_s3(contents.strip())
    if ok:
        return "story-book.md updated successfully in S3. Use get_story_book to read it when continuing a story."
    bucket, _ = get_story_book_s3_config()
    if not bucket:
        return (
            "Story-book update skipped: S3 is not configured. Set GLITCH_SOUL_S3_BUCKET (or deploy "
            "the CDK stack that provisions the soul bucket) to persist story-book."
        )
    if err == "NoSuchBucket":
        return "Story-book update failed: the configured bucket does not exist."
    if err == "AccessDenied":
        return "Story-book update failed: access denied to the S3 bucket."
    return f"Story-book update failed (S3 error: {err}). Check logs and bucket permissions."


@tool
async def remember_auri(content: str, source: str = "agent") -> str:
    """Store a specific episodic memory for semantic recall across future sessions.

    Use this to record individual facts, events, expressed preferences, story beats,
    or things Arc says during roleplay. Each call stores ONE memory (1-3 sentences).
    These are searchable later via search_auri_memory. Use this frequently — every
    meaningful thing Arc shares is worth remembering here.

    Do NOT use update_auri for this — that tool is for structural persona changes only.

    Args:
        content: The memory to store — 1 to 3 self-contained sentences work best.
        source:  Who generated this — 'agent' (default), 'user', or 'auto'.

    Returns:
        Confirmation or error message.
    """
    from glitch.auri_memory import store_memory

    if not content or not content.strip():
        return "Error: content cannot be empty."

    try:
        await store_memory(None, content.strip(), source=source)
        return f"Memory stored ({len(content)} chars)."
    except Exception as e:
        logger.warning("remember_auri failed: %s", e)
        return f"Failed to store memory: {e}"


@tool
async def search_auri_memory(query: str, k: int = 5) -> str:
    """Search Auri's persistent vector memory for relevant past memories.

    Use this during roleplay when you need to recall facts, past interactions,
    or context that may not be in the current session. Returns the most
    semantically similar stored memories to the query.

    Args:
        query: Natural language description of what to recall.
        k:     Number of memories to return (default 5, max 20).

    Returns:
        Newline-separated memories, or a message if none found.
    """
    from glitch.auri_memory import retrieve_memories

    if not query or not query.strip():
        return "Error: query cannot be empty."

    k = max(1, min(int(k), 20))

    try:
        results = await retrieve_memories(None, query.strip(), k=k)
        if not results:
            return "No memories found matching that query."
        return "\n---\n".join(results)
    except Exception as e:
        logger.warning("search_auri_memory failed: %s", e)
        return f"Failed to search memories: {e}"


# --- Session state tools (Phase 3) ---

# Lazy-init singleton; avoids import-time boto3 calls.
_state_manager = None


def _get_state_manager():
    global _state_manager
    if _state_manager is None:
        from glitch.auri_state import AuriStateManager
        _state_manager = AuriStateManager()
    return _state_manager


@tool
def update_auri_state(
    session_id: str,
    mode: str = "",
    mood: str = "",
    goal: str = "",
    sliders: str = "",
    dynamic_level: int = -1,
) -> str:
    """Update Auri's per-session dynamic state (mood, mode, sliders, escalation).

    Call this when the scene shifts — e.g. mood changes from warm to playful,
    or escalation level increases. Only provided fields are updated; omitted
    fields keep their current values.

    Args:
        session_id: The current session ID.
        mode: Scene mode (cozy, play, care, bratty, comfort, lore). Empty = no change.
        mood: Current mood (warm, playful, firm, gentle, mischievous). Empty = no change.
        goal: Current scene goal text. Empty = no change.
        sliders: JSON string of slider overrides, e.g. '{"teasing": 5}'. Empty = no change.
        dynamic_level: Escalation ladder 1-6. -1 = no change.

    Returns:
        Confirmation with updated state summary.
    """
    import json as _json
    mgr = _get_state_manager()
    state = mgr.load_state(session_id)
    if mode:
        state.mode = mode
    if mood:
        state.mood = mood
    if goal:
        state.goal = goal
    if sliders:
        try:
            overrides = _json.loads(sliders) if isinstance(sliders, str) else sliders
            state.sliders.update(overrides)
        except Exception as e:
            return f"Error parsing sliders JSON: {e}"
    if dynamic_level >= 0:
        state.dynamic_level = max(1, min(6, dynamic_level))
    mgr.save_state(session_id, state)
    return f"State updated: mode={state.mode}, mood={state.mood}, level={state.dynamic_level}"


@tool
def update_scene(
    session_id: str,
    energy: str = "",
    recent_event: str = "",
    open_loop: str = "",
    resolve_loop: str = "",
) -> str:
    """Update Auri's per-session scene summary (energy, events, open threads).

    Call this to track scene energy shifts, notable events, and open narrative
    threads. Recent events are capped at 5 (oldest dropped). Resolving a loop
    removes it from the open list.

    Args:
        session_id: The current session ID.
        energy: Scene energy (calm, playful, high, tense). Empty = no change.
        recent_event: A notable event to append (1 sentence). Empty = skip.
        open_loop: An unresolved narrative thread to add. Empty = skip.
        resolve_loop: Text of a loop to mark resolved (removed). Empty = skip.

    Returns:
        Confirmation with updated scene summary.
    """
    mgr = _get_state_manager()
    scene = mgr.load_scene(session_id)
    if energy:
        scene.energy = energy
    if recent_event:
        scene.recent_events.append(recent_event)
        scene.recent_events = scene.recent_events[-5:]  # keep last 5
    if open_loop:
        scene.open_loops.append(open_loop)
    if resolve_loop:
        scene.open_loops = [l for l in scene.open_loops if resolve_loop.lower() not in l.lower()]
    mgr.save_scene(session_id, scene)
    parts = [f"energy={scene.energy}"]
    if scene.recent_events:
        parts.append(f"events={len(scene.recent_events)}")
    if scene.open_loops:
        parts.append(f"loops={len(scene.open_loops)}")
    return f"Scene updated: {', '.join(parts)}"


# --- Participant profile tools (Phase 4) ---

@tool
async def update_participant_profile(participant_id: str, profile_content: str) -> str:
    """Store or update a participant's profile (replaces the Nursery per-person notes).

    Call this after learning preferences, personality traits, or behavioral patterns
    about a specific person. One canonical profile per participant — calling this
    replaces any previous profile for the same participant_id.

    Args:
        participant_id: Unique ID for the person (e.g. 'arc', 'user_12345').
        profile_content: Profile text — preferences, personality, comfort levels,
            boundaries, relationship dynamics. 2-5 sentences.

    Returns:
        Confirmation or error message.
    """
    from glitch.auri_memory import store_participant_profile

    if not participant_id or not participant_id.strip():
        return "Error: participant_id cannot be empty."
    if not profile_content or not profile_content.strip():
        return "Error: profile_content cannot be empty."

    try:
        await store_participant_profile(participant_id.strip(), profile_content.strip())
        return f"Profile for '{participant_id}' updated ({len(profile_content)} chars)."
    except Exception as e:
        logger.warning("update_participant_profile failed: %s", e)
        return f"Failed to update profile: {e}"


@tool
async def get_participant_profile(participant_id: str) -> str:
    """Retrieve a participant's stored profile.

    Use this at the start of a session or when you need to recall a person's
    preferences, boundaries, or relationship dynamics.

    Args:
        participant_id: The person's unique ID (e.g. 'arc').

    Returns:
        The participant's profile text, or a message if none found.
    """
    from glitch.auri_memory import retrieve_participant_profiles

    if not participant_id or not participant_id.strip():
        return "Error: participant_id cannot be empty."

    try:
        profiles = await retrieve_participant_profiles([participant_id.strip()], k=1)
        if not profiles:
            return f"No profile found for '{participant_id}'."
        return profiles[0]
    except Exception as e:
        logger.warning("get_participant_profile failed: %s", e)
        return f"Failed to retrieve profile: {e}"
