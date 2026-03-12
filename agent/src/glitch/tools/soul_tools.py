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
SSM_STORY_BOOK_KEY = "/glitch/soul/story-book-s3-key"
DEFAULT_STORY_BOOK_KEY = "story-book.md"

# Cached SSM result so we don't call SSM on every get_soul_s3_config().
_ssm_soul_config: Tuple[str | None, str] | None = None
_ssm_poet_soul_key: str | None = None
_ssm_story_book_key: str | None = None


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
