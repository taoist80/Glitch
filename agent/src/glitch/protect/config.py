"""Protect configuration loader.

Loads credentials and config from environment variables (local dev via .env.protect)
with SSM Parameter Store and Secrets Manager fallback for deployed runtime.

Pattern matches ssh_tools.py and pihole_tools.py for consistency.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_protect_config: Optional["ProtectConfig"] = None
_db_config: Optional["ProtectDBConfig"] = None


@dataclass
class ProtectConfig:
    """Configuration for UniFi Protect API access."""
    host: str
    username: str
    password: str
    port: int = 443
    verify_ssl: bool = False


@dataclass
class ProtectDBConfig:
    """Configuration for Protect PostgreSQL database."""
    host: str
    port: int
    dbname: str
    username: str
    password: str

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.username}:{self.password}@{self.host}:{self.port}/{self.dbname}"


def _get_ssm_parameter(name: str) -> Optional[str]:
    """Fetch a single SSM parameter (with decryption)."""
    try:
        import boto3
        client = boto3.client("ssm", region_name="us-west-2")
        response = client.get_parameter(Name=name, WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception as e:
        logger.debug(f"SSM parameter {name} not available: {e}")
        return None


def _get_secret(secret_name: str) -> Optional[dict]:
    """Fetch a Secrets Manager secret as a dict."""
    try:
        import boto3
        client = boto3.client("secretsmanager", region_name="us-west-2")
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except Exception as e:
        logger.debug(f"Secret {secret_name} not available: {e}")
        return None


def get_protect_config() -> ProtectConfig:
    """Load Protect API config (cached). Env vars take priority over SSM."""
    global _protect_config
    if _protect_config is not None:
        return _protect_config

    host = (
        os.environ.get("GLITCH_PROTECT_HOST")
        or _get_ssm_parameter("/glitch/protect/host")
    )
    username = (
        os.environ.get("GLITCH_PROTECT_USERNAME")
        or _get_ssm_parameter("/glitch/protect/username")
    )
    password = (
        os.environ.get("GLITCH_PROTECT_PASSWORD")
        or _get_ssm_parameter("/glitch/protect/password")
    )
    port_str = (
        os.environ.get("GLITCH_PROTECT_PORT")
        or _get_ssm_parameter("/glitch/protect/port")
        or "443"
    )
    verify_ssl_str = (
        os.environ.get("GLITCH_PROTECT_VERIFY_SSL")
        or _get_ssm_parameter("/glitch/protect/verify_ssl")
        or "false"
    )

    if not host or not username or not password:
        raise RuntimeError(
            "Protect credentials not configured. Set GLITCH_PROTECT_HOST, "
            "GLITCH_PROTECT_USERNAME, GLITCH_PROTECT_PASSWORD env vars or "
            "SSM parameters /glitch/protect/{host,username,password}."
        )

    _protect_config = ProtectConfig(
        host=host,
        username=username,
        password=password,
        port=int(port_str),
        verify_ssl=verify_ssl_str.lower() in ("true", "1", "yes"),
    )
    logger.info(f"Loaded Protect config: host={host}, port={port_str}")
    return _protect_config


def get_db_config() -> ProtectDBConfig:
    """Load Protect DB config (cached). Env var DSN takes priority."""
    global _db_config
    if _db_config is not None:
        return _db_config

    # Allow full DSN override for local dev
    full_dsn = os.environ.get("GLITCH_PROTECT_DB_URI")
    if full_dsn:
        # Parse DSN: postgresql://user:pass@host:port/dbname
        from urllib.parse import urlparse
        parsed = urlparse(full_dsn)
        _db_config = ProtectDBConfig(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            dbname=parsed.path.lstrip("/"),
            username=parsed.username or "postgres",
            password=parsed.password or "",
        )
        logger.info(f"Loaded Protect DB config from DSN: host={_db_config.host}")
        return _db_config

    # Build from SSM + Secrets Manager
    host = (
        os.environ.get("GLITCH_PROTECT_DB_HOST")
        or _get_ssm_parameter("/glitch/protect-db/host")
    )
    port_str = (
        os.environ.get("GLITCH_PROTECT_DB_PORT")
        or _get_ssm_parameter("/glitch/protect-db/port")
        or "5432"
    )
    dbname = (
        os.environ.get("GLITCH_PROTECT_DB_NAME")
        or _get_ssm_parameter("/glitch/protect-db/dbname")
        or "glitch_protect"
    )

    # DB credentials from Secrets Manager
    secret = _get_secret("glitch/protect-db")
    if secret:
        db_username = secret.get("username", "postgres")
        db_password = secret.get("password", "")
    else:
        db_username = os.environ.get("GLITCH_PROTECT_DB_USERNAME", "postgres")
        db_password = os.environ.get("GLITCH_PROTECT_DB_PASSWORD", "")

    if not host:
        raise RuntimeError(
            "Protect DB host not configured. Set GLITCH_PROTECT_DB_HOST env var "
            "or SSM parameter /glitch/protect-db/host."
        )

    _db_config = ProtectDBConfig(
        host=host,
        port=int(port_str),
        dbname=dbname,
        username=db_username,
        password=db_password,
    )
    logger.info(f"Loaded Protect DB config: host={host}, dbname={dbname}")
    return _db_config


def is_protect_configured() -> bool:
    """Return True if Protect credentials are available (without raising)."""
    try:
        get_protect_config()
        return True
    except RuntimeError:
        return False


def is_db_configured() -> bool:
    """Return True if Protect DB config is available (without raising)."""
    try:
        get_db_config()
        return True
    except RuntimeError:
        return False


def reset_config_cache() -> None:
    """Clear cached configs (for testing)."""
    global _protect_config, _db_config
    _protect_config = None
    _db_config = None
