"""SOUL.md load/save from S3 and update_soul tool for persistent personality.

When GLITCH_SOUL_S3_BUCKET is set, the agent loads SOUL from S3 and can update it
via the update_soul tool so Telegram and chat agents can evolve the personality over time.
"""

import logging
import os
from typing import Tuple

from strands import tool

logger = logging.getLogger(__name__)

DEFAULT_SOUL_KEY = "soul.md"


def get_soul_s3_config() -> Tuple[str | None, str]:
    """Return (bucket, key) for SOUL in S3, or (None, key) if not configured."""
    bucket = os.environ.get("GLITCH_SOUL_S3_BUCKET") or None
    key = os.environ.get("GLITCH_SOUL_S3_KEY", DEFAULT_SOUL_KEY).strip() or DEFAULT_SOUL_KEY
    return bucket, key


def load_soul_from_s3() -> str:
    """Load SOUL content from S3. Returns empty string on missing or error."""
    bucket, key = get_soul_s3_config()
    if not bucket:
        return ""
    try:
        import boto3
        from botocore.exceptions import ClientError
        client = boto3.client("s3")
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


def save_soul_to_s3(content: str) -> bool:
    """Write SOUL content to S3. Returns True on success."""
    bucket, key = get_soul_s3_config()
    if not bucket:
        logger.warning("GLITCH_SOUL_S3_BUCKET not set, cannot save SOUL to S3")
        return False
    try:
        import boto3
        client = boto3.client("s3")
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=content.encode("utf-8"),
            ContentType="text/markdown; charset=utf-8",
        )
        logger.info("Saved SOUL to s3://%s/%s", bucket, key)
        return True
    except Exception as e:
        logger.exception("Failed to save SOUL to S3 %s/%s: %s", bucket, key, e)
        return False


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
    if save_soul_to_s3(contents.strip()):
        return (
            "SOUL.md updated successfully in S3. New sessions (e.g. next Telegram chat or "
            "restart) will load the new personality; this session continues with the previous prompt."
        )
    bucket, _ = get_soul_s3_config()
    if not bucket:
        return (
            "SOUL update skipped: S3 is not configured. Set GLITCH_SOUL_S3_BUCKET (and optional "
            "GLITCH_SOUL_S3_KEY) to persist SOUL changes. Until then, edits apply only to this session."
        )
    return "SOUL update failed (S3 write error). Check logs and bucket permissions."
