"""SOUL.md load/save from S3 and update_soul tool for persistent personality.

When GLITCH_SOUL_S3_BUCKET is set (or SSM /glitch/soul/s3-bucket when using CDK stack),
the agent loads SOUL from S3 and can update it via the update_soul tool.
"""

import logging
import os
from typing import Tuple

from strands import tool

logger = logging.getLogger(__name__)

DEFAULT_SOUL_KEY = "soul.md"
SSM_SOUL_BUCKET = "/glitch/soul/s3-bucket"
SSM_SOUL_KEY = "/glitch/soul/s3-key"
SSM_POET_SOUL_KEY = "/glitch/soul/poet-soul-s3-key"
DEFAULT_POET_SOUL_KEY = "poet-soul.md"

# Cached SSM result so we don't call SSM on every get_soul_s3_config().
_ssm_soul_config: Tuple[str | None, str] | None = None
_ssm_poet_soul_key: str | None = None


def _get_soul_s3_config_from_ssm() -> Tuple[str | None, str]:
    """Fetch SOUL S3 bucket/key from SSM. Returns (None, default_key) on failure."""
    global _ssm_soul_config
    if _ssm_soul_config is not None:
        return _ssm_soul_config
    try:
        import boto3
        client = boto3.client("ssm")
        resp = client.get_parameters(
            Names=[SSM_SOUL_BUCKET, SSM_SOUL_KEY],
            WithDecryption=False,
        )
        params = {p["Name"]: p["Value"] for p in resp.get("Parameters", []) if "Value" in p}
        bucket = (params.get(SSM_SOUL_BUCKET) or "").strip() or None
        key = (params.get(SSM_SOUL_KEY) or DEFAULT_SOUL_KEY).strip() or DEFAULT_SOUL_KEY
        _ssm_soul_config = (bucket, key)
        if bucket:
            logger.info("SOUL S3 config from SSM: bucket=%s key=%s", bucket, key)
        return _ssm_soul_config
    except Exception as e:
        logger.debug("Could not read SOUL S3 config from SSM: %s", e)
        _ssm_soul_config = (None, DEFAULT_SOUL_KEY)
        return _ssm_soul_config


def get_soul_s3_config() -> Tuple[str | None, str]:
    """Return (bucket, key) for SOUL in S3, or (None, key) if not configured.

    Precedence: GLITCH_SOUL_S3_BUCKET env, then SSM /glitch/soul/s3-bucket (when CDK stack is used).
    """
    bucket = os.environ.get("GLITCH_SOUL_S3_BUCKET") or None
    key = os.environ.get("GLITCH_SOUL_S3_KEY", DEFAULT_SOUL_KEY).strip() or DEFAULT_SOUL_KEY
    if bucket:
        return bucket, key
    return _get_soul_s3_config_from_ssm()


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
        import boto3
        client = boto3.client("ssm")
        resp = client.get_parameter(Name=SSM_POET_SOUL_KEY, WithDecryption=False)
        _ssm_poet_soul_key = (resp.get("Parameter", {}).get("Value") or DEFAULT_POET_SOUL_KEY).strip() or DEFAULT_POET_SOUL_KEY
        return _ssm_poet_soul_key
    except Exception:
        _ssm_poet_soul_key = DEFAULT_POET_SOUL_KEY
        return _ssm_poet_soul_key


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


def save_soul_to_s3(content: str) -> Tuple[bool, str]:
    """Write SOUL content to S3. Returns (True, '') on success, (False, error_message) on failure."""
    bucket, key = get_soul_s3_config()
    if not bucket:
        logger.warning("GLITCH_SOUL_S3_BUCKET not set, cannot save SOUL to S3")
        return False, "no_bucket"
    try:
        import boto3
        from botocore.exceptions import ClientError
        client = boto3.client("s3")
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
            "SOUL update skipped: S3 is not configured. Set GLITCH_SOUL_S3_BUCKET (and optional "
            "GLITCH_SOUL_S3_KEY) to persist SOUL changes, or deploy the CDK TelegramWebhookStack so "
            "the runtime can read bucket/key from SSM (/glitch/soul/s3-bucket). Until then, edits apply only to this session."
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
