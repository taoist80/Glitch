"""Load Poet personality from poet-soul.md.

Poet is a creative writing sub-agent with a separate soul file.
When S3 is configured (GLITCH_SOUL_S3_BUCKET or SSM /glitch/soul/s3-bucket), loads from S3 first.
Otherwise searches: agent/poet-soul.md, /app/poet-soul.md, ~/poet-soul.md.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _load_poet_soul_from_s3() -> str:
    """Load poet-soul content from S3 if bucket is configured. Returns empty string on miss/error."""
    try:
        from glitch.tools.soul_tools import get_poet_soul_s3_config
        import boto3
        from botocore.exceptions import ClientError
        bucket, key = get_poet_soul_s3_config()
        if not bucket:
            return ""
        client = boto3.client("s3")
        resp = client.get_object(Bucket=bucket, Key=key)
        body = resp["Body"].read()
        content = body.decode("utf-8")
        logger.info("Loading Poet soul from s3://%s/%s", bucket, key)
        return content
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            logger.debug("Poet soul key not in bucket, using file fallback")
        else:
            logger.warning("Failed to load poet-soul from S3: %s", e)
        return ""
    except Exception as e:
        logger.debug("Could not load poet-soul from S3: %s", e)
        return ""


def get_default_poet_soul_path() -> Path:
    """Return the default path for poet-soul.md (agent directory)."""
    # From agent/src/glitch/poet_soul.py -> agent/src/glitch -> agent/src -> agent
    return Path(__file__).parent.parent.parent / "poet-soul.md"


def load_poet_soul() -> str:
    """Load Poet personality from poet-soul.md.

    Search order:
    1. S3 (when GLITCH_SOUL_S3_BUCKET or SSM /glitch/soul/s3-bucket is set; key from GLITCH_POET_SOUL_S3_KEY or SSM)
    2. agent/poet-soul.md (development)
    3. /app/poet-soul.md (container)
    4. ~/poet-soul.md (fallback)

    Returns:
        Contents of poet-soul.md or empty string if not found.
    """
    from glitch.tools.soul_tools import get_poet_soul_s3_config
    if get_poet_soul_s3_config()[0]:
        content = _load_poet_soul_from_s3()
        if content:
            return content
    soul_paths = [
        get_default_poet_soul_path(),
        Path("/app/poet-soul.md"),
        Path.home() / "poet-soul.md",
    ]
    for path in soul_paths:
        if path.exists():
            logger.info("Loading Poet soul from %s", path)
            return path.read_text()
    logger.warning("poet-soul.md not found, using default Poet personality")
    return ""
