"""Protect configuration loader.

Loads credentials and config from environment variables (local dev via .env.protect)
with SSM Parameter Store and Secrets Manager fallback for deployed runtime.

Pattern matches ssh_tools.py and pihole_tools.py for consistency.

API authentication strategy
---------------------------
Two modes are supported (checked in order):

1. **API key** (recommended) — set ``GLITCH_PROTECT_API_KEY`` env var or
   Secrets Manager ``glitch/protect-api-key``.  Passed as ``X-API-KEY`` header;
   no login endpoint, no session cookies, no rate-limit risk.  Requires a
   Super Admin local account to generate via UDM-Pro web UI →
   Settings → Control Plane → Integrations.

2. **Username/password cookie auth** (legacy fallback) — ``GLITCH_PROTECT_USERNAME``
   / ``GLITCH_PROTECT_PASSWORD`` env vars or SSM.  Calls ``/api/auth/login`` and
   maintains session cookies.  Subject to 429 rate limits.

Both modes require ``GLITCH_PROTECT_HOST``.

DB authentication strategy
--------------------------
Two modes are supported (checked in order):

1. **Full DSN override** — set ``GLITCH_PROTECT_DB_URI`` to a complete
   ``postgresql://user:pass@host:port/dbname`` URI.  Useful for local dev.

2. **RDS IAM authentication** (production default) — the runtime role calls
   ``boto3 rds.generate_db_auth_token`` to obtain a short-lived token used
   as the Postgres password.  The DB username is read from
   ``GLITCH_PROTECT_DB_IAM_USER`` or SSM ``/glitch/protect-db/sentinel-iam-user``
   (default ``sentinel_iam``).  The host and dbname are read from
   ``GLITCH_PROTECT_DB_HOST`` / SSM, and ``GLITCH_PROTECT_DB_NAME`` / SSM.
   IAM auth requires SSL; ``asyncpg`` is called with ``ssl='require'``.

3. **Explicit username/password fallback** — ``GLITCH_PROTECT_DB_USERNAME`` and
   ``GLITCH_PROTECT_DB_PASSWORD`` env vars (or Secrets Manager ``glitch/protect-db``).
   Kept for local dev and emergency break-glass; not used on the deployed runtime.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

_protect_config: Optional["ProtectConfig"] = None
_db_config: Optional["ProtectDBConfig"] = None


def _normalize_site_label(label: str) -> str:
    """Map legacy generic labels to human-readable site names."""
    normalized = (label or "").strip().lower()
    if normalized == "site1":
        return "ringtail"
    if normalized == "site2":
        return "starbase80"
    return label


@dataclass
class ProtectConfig:
    """Configuration for UniFi Protect API access."""
    host: str
    port: int = 443
    verify_ssl: bool = False
    api_key: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    @property
    def use_api_key(self) -> bool:
        return self.api_key is not None


@dataclass
class ProtectDBConfig:
    """Configuration for Protect PostgreSQL database."""
    host: str
    port: int
    dbname: str
    username: str
    password: str
    use_iam_auth: bool = False

    def get_iam_token(self) -> str:
        """Generate a fresh RDS IAM auth token valid for 15 minutes."""
        import boto3
        rds = boto3.client("rds", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        token = rds.generate_db_auth_token(
            DBHostname=self.host,
            Port=self.port,
            DBUsername=self.username,
        )
        logger.debug("Generated RDS IAM auth token for %s@%s", self.username, self.host)
        return token


def parse_host_port(raw_host: str, default_port: int) -> tuple[str, int]:
    """Split 'hostname:port' into (hostname, port), falling back to default_port."""
    if ":" in raw_host:
        hostname, port_str = raw_host.rsplit(":", 1)
        return hostname, int(port_str)
    return raw_host, default_port


def _get_ssm_parameter(name: str) -> Optional[str]:
    """Fetch a single SSM parameter (with decryption)."""
    try:
        from glitch.aws_utils import get_client
        client = get_client("ssm")
        response = client.get_parameter(Name=name, WithDecryption=True)
        return response["Parameter"]["Value"]
    except Exception as e:
        logger.debug(f"SSM parameter {name} not available: {e}")
        return None


def _get_secret(secret_name: str) -> Optional[dict]:
    """Fetch a Secrets Manager secret as a dict."""
    try:
        from glitch.aws_utils import get_client
        client = get_client("secretsmanager")
        response = client.get_secret_value(SecretId=secret_name)
        return json.loads(response["SecretString"])
    except Exception as e:
        logger.debug(f"Secret {secret_name} not available: {e}")
        return None


def _get_protect_api_key() -> Optional[str]:
    """Resolve API key from env, Secrets Manager, or SSM (in that order)."""
    key = os.environ.get("GLITCH_PROTECT_API_KEY")
    if key:
        return key

    secret = _get_secret("glitch/protect-api-key")
    if secret:
        return secret.get("api_key") or secret.get("key")

    return _get_ssm_parameter("/glitch/protect/api_key")


def get_protect_config() -> ProtectConfig:
    """Load Protect API config (cached).

    Resolution order for auth:
    1. API key (GLITCH_PROTECT_API_KEY / Secrets Manager / SSM)
    2. Username + password (env / SSM) — legacy fallback
    Host is always required.
    """
    global _protect_config
    if _protect_config is not None:
        return _protect_config

    host = (
        os.environ.get("GLITCH_PROTECT_HOST")
        or _get_ssm_parameter("/glitch/protect/host")
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

    if not host:
        raise RuntimeError(
            "Protect host not configured. Set GLITCH_PROTECT_HOST env var "
            "or SSM parameter /glitch/protect/host."
        )

    api_key = _get_protect_api_key()

    username = (
        os.environ.get("GLITCH_PROTECT_USERNAME")
        or _get_ssm_parameter("/glitch/protect/username")
    )
    password = (
        os.environ.get("GLITCH_PROTECT_PASSWORD")
        or _get_ssm_parameter("/glitch/protect/password")
    )

    if not api_key and (not username or not password):
        raise RuntimeError(
            "Protect credentials not configured. Set GLITCH_PROTECT_API_KEY "
            "(recommended) or GLITCH_PROTECT_USERNAME + GLITCH_PROTECT_PASSWORD."
        )

    _protect_config = ProtectConfig(
        host=host,
        port=int(port_str),
        verify_ssl=verify_ssl_str.lower() in ("true", "1", "yes"),
        api_key=api_key,
        username=username,
        password=password,
    )
    auth_mode = "API key" if api_key else "cookie (legacy)"
    logger.info("Loaded Protect config: host=%s, port=%s, auth=%s", host, port_str, auth_mode)
    return _protect_config


def get_db_config() -> ProtectDBConfig:
    """Load Protect DB config (cached).

    Resolution order:
    1. GLITCH_PROTECT_DB_URI — full DSN override (local dev).
    2. RDS IAM auth — host/port/dbname from env/SSM; username from
       GLITCH_PROTECT_DB_IAM_USER or SSM /glitch/protect-db/sentinel-iam-user.
       This is the default for the deployed runtime.
    3. Explicit password — Secrets Manager glitch/protect-db, then env vars
       GLITCH_PROTECT_DB_USERNAME / GLITCH_PROTECT_DB_PASSWORD.
    """
    global _db_config
    if _db_config is not None:
        return _db_config

    # 1. Full DSN override (local dev)
    full_dsn = os.environ.get("GLITCH_PROTECT_DB_URI")
    if full_dsn:
        from urllib.parse import urlparse
        parsed = urlparse(full_dsn)
        _db_config = ProtectDBConfig(
            host=parsed.hostname or "localhost",
            port=parsed.port or 5432,
            dbname=parsed.path.lstrip("/"),
            username=parsed.username or "postgres",
            password=parsed.password or "",
            use_iam_auth=False,
        )
        logger.info("Loaded Protect DB config from DSN: host=%s", _db_config.host)
        return _db_config

    # Common: host / port / dbname from env or SSM.
    # Prefer SSM host when both are present but differ so DB instance replacements
    # (which update /glitch/protect-db/host) do not require an immediate runtime redeploy.
    env_host = (os.environ.get("GLITCH_PROTECT_DB_HOST") or "").strip()
    ssm_host = (_get_ssm_parameter("/glitch/protect-db/host") or "").strip()
    if env_host and ssm_host and env_host != ssm_host:
        logger.warning(
            "GLITCH_PROTECT_DB_HOST (%s) differs from SSM /glitch/protect-db/host (%s); preferring SSM",
            env_host,
            ssm_host,
        )
        host = ssm_host
    else:
        host = env_host or ssm_host
    env_port = (os.environ.get("GLITCH_PROTECT_DB_PORT") or "").strip()
    ssm_port = (_get_ssm_parameter("/glitch/protect-db/port") or "").strip()
    port_str = env_port or ssm_port or "5432"
    dbname = (
        os.environ.get("GLITCH_PROTECT_DB_NAME")
        or _get_ssm_parameter("/glitch/protect-db/dbname")
        or "glitch_protect"
    )

    # Defensive: if host was provided as "hostname:port", split it safely.
    # This prevents DNS lookup failures caused by passing "host:port" as host.
    if host and ":" in host:
        parsed_host, parsed_port = parse_host_port(host, int(port_str))
        if not env_port and not ssm_port:
            port_str = str(parsed_port)
        elif int(port_str) != parsed_port:
            logger.warning(
                "Protect DB host includes port (%s) but GLITCH_PROTECT_DB_PORT/SSM port is %s; using explicit port",
                host,
                port_str,
            )
        host = parsed_host

    if not host:
        raise RuntimeError(
            "Protect DB host not configured. Set GLITCH_PROTECT_DB_HOST env var "
            "or SSM parameter /glitch/protect-db/host."
        )

    # 2. RDS IAM auth (preferred on the deployed runtime)
    iam_user = (
        os.environ.get("GLITCH_PROTECT_DB_IAM_USER")
        or _get_ssm_parameter("/glitch/protect-db/sentinel-iam-user")
    )
    if iam_user:
        _db_config = ProtectDBConfig(
            host=host,
            port=int(port_str),
            dbname=dbname,
            username=iam_user,
            password="",
            use_iam_auth=True,
        )
        logger.info(
            "Loaded Protect DB config (IAM auth): host=%s, user=%s, dbname=%s",
            host, iam_user, dbname,
        )
        return _db_config

    # 3. Explicit username/password (local dev / break-glass)
    secret = _get_secret("glitch/protect-db")
    if secret:
        db_username = secret.get("username", "postgres")
        db_password = secret.get("password", "")
    else:
        db_username = os.environ.get("GLITCH_PROTECT_DB_USERNAME", "postgres")
        db_password = os.environ.get("GLITCH_PROTECT_DB_PASSWORD", "")

    _db_config = ProtectDBConfig(
        host=host,
        port=int(port_str),
        dbname=dbname,
        username=db_username,
        password=db_password,
        use_iam_auth=False,
    )
    logger.info("Loaded Protect DB config (password auth): host=%s, dbname=%s", host, dbname)
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


# Minimum anomaly score (0.0–1.0) required to send a Telegram alert.
PROTECT_ALERT_THRESHOLD = float(os.environ.get("GLITCH_PROTECT_ALERT_THRESHOLD", "0.7"))


@dataclass
class SiteConfig:
    """Configuration bundle for a single Protect site."""
    site_id: str  # e.g. "site1", "starbase80" — used as site label in DB
    protect: ProtectConfig


def get_all_site_configs() -> "list[SiteConfig]":
    """Return a SiteConfig for every configured Protect site.

    Site 1 always uses the existing env vars / SSM (GLITCH_PROTECT_HOST etc.).
    Site 2 is opt-in: only included when GLITCH_PROTECT_2_HOST is set.
    """
    sites: "list[SiteConfig]" = []

    # Site 1 — existing config path, no changes to get_protect_config()
    try:
        site1_label = _normalize_site_label(os.environ.get("GLITCH_PROTECT_LABEL", "ringtail"))
        sites.append(SiteConfig(
            site_id=site1_label,
            protect=get_protect_config(),
        ))
    except RuntimeError as exc:
        logger.warning("Site 1 Protect config unavailable: %s", exc)

    # Site 2 — opt-in via GLITCH_PROTECT_2_HOST
    host2 = os.environ.get("GLITCH_PROTECT_2_HOST", "").strip()
    if host2:
        api_key2 = os.environ.get("GLITCH_PROTECT_2_API_KEY", "").strip() or None
        port_str2 = os.environ.get("GLITCH_PROTECT_2_PORT", "443")
        site_id2 = _normalize_site_label(os.environ.get("GLITCH_PROTECT_2_LABEL", "starbase80"))
        if api_key2:
            host2_parsed, port2 = parse_host_port(host2, int(port_str2))
            sites.append(SiteConfig(
                site_id=site_id2,
                protect=ProtectConfig(
                    host=host2_parsed,
                    port=port2,
                    verify_ssl=False,
                    api_key=api_key2,
                ),
            ))
            logger.info("Site 2 (%s) configured: host=%s, port=%d", site_id2, host2_parsed, port2)
        else:
            logger.warning(
                "GLITCH_PROTECT_2_HOST set but GLITCH_PROTECT_2_API_KEY missing — skipping site2"
            )

    return sites
