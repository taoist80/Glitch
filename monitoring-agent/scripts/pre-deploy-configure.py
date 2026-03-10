#!/usr/bin/env python3
"""
Pre-deploy hook: Auto-configure environment variables before Sentinel deployment.

Reads runtime configuration from SSM Parameters and writes .env.deploy
for agentcore deploy to consume via --env flags.

SSM Parameters:
  /glitch/protect/host         - UniFi Protect host (home.awoo.agency:13443)
  /glitch/protect/username     - Protect API username (SecureString)
  /glitch/protect/password     - Protect API password (SecureString)
  /glitch/protect-db/host      - Protect Postgres host
  /glitch/protect-db/port      - Protect Postgres port (default 5432)
  /glitch/protect-db/dbname    - Protect Postgres database name
  /glitch/ollama/proxy-host    - Ollama nginx proxy hostname
  /glitch/ollama/api-key       - Ollama nginx API key (SecureString)

Exit codes:
  0 - Success
  1 - Error (missing required parameters)
"""

import os
import sys
from pathlib import Path

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:
    print("Warning: boto3 not available. Skipping pre-deploy configuration.")
    sys.exit(0)

REGION = os.environ.get("AWS_REGION", "us-west-2")

AGENT_DIR = Path(__file__).parent.parent
ENV_DEPLOY_FILE = AGENT_DIR / ".env.deploy"


def log(message: str, level: str = "INFO"):
    prefix = {
        "INFO": "[pre-deploy]",
        "WARN": "[pre-deploy] WARNING:",
        "ERROR": "[pre-deploy] ERROR:",
        "SUCCESS": "[pre-deploy] ✓",
    }.get(level, "[pre-deploy]")
    print(f"{prefix} {message}")


def get_ssm_parameter(ssm_client, name: str) -> str | None:
    try:
        response = ssm_client.get_parameter(Name=name, WithDecryption=True)
        return response["Parameter"]["Value"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ParameterNotFound":
            return None
        raise


def main():
    log("Configuring Sentinel pre-deploy environment variables...")

    try:
        ssm = boto3.client("ssm", region_name=REGION)
        env_vars: dict[str, str] = {}

        # UniFi Protect API
        protect_host = get_ssm_parameter(ssm, "/glitch/protect/host")
        if protect_host:
            env_vars["GLITCH_PROTECT_HOST"] = protect_host
            log(f"Protect host set to {protect_host}", "SUCCESS")
        else:
            log("SSM /glitch/protect/host not found; Protect integration will be disabled", "WARN")

        protect_user = get_ssm_parameter(ssm, "/glitch/protect/username")
        if protect_user:
            env_vars["GLITCH_PROTECT_USERNAME"] = protect_user
            log("Protect username loaded from SSM", "SUCCESS")
        else:
            log("SSM /glitch/protect/username not found", "WARN")

        protect_pass = get_ssm_parameter(ssm, "/glitch/protect/password")
        if protect_pass:
            env_vars["GLITCH_PROTECT_PASSWORD"] = protect_pass
            log("Protect password loaded from SSM", "SUCCESS")
        else:
            log("SSM /glitch/protect/password not found", "WARN")

        # Protect database (host/port/dbname + IAM username for Sentinel)
        protect_db_host = get_ssm_parameter(ssm, "/glitch/protect-db/host")
        if protect_db_host:
            env_vars["GLITCH_PROTECT_DB_HOST"] = protect_db_host
            log(f"Protect DB host set to {protect_db_host}", "SUCCESS")
        else:
            log("SSM /glitch/protect-db/host not found; DB writes will be disabled", "WARN")

        protect_db_port = get_ssm_parameter(ssm, "/glitch/protect-db/port")
        if protect_db_port:
            env_vars["GLITCH_PROTECT_DB_PORT"] = protect_db_port

        protect_db_name = get_ssm_parameter(ssm, "/glitch/protect-db/dbname")
        if protect_db_name:
            env_vars["GLITCH_PROTECT_DB_NAME"] = protect_db_name

        protect_db_iam_user = get_ssm_parameter(ssm, "/glitch/protect-db/sentinel-iam-user")
        if protect_db_iam_user:
            env_vars["GLITCH_PROTECT_DB_IAM_USER"] = protect_db_iam_user
            log(f"Protect DB IAM user set to {protect_db_iam_user}", "SUCCESS")
        else:
            log("SSM /glitch/protect-db/sentinel-iam-user not found; will fall back to password auth", "WARN")

        # Ollama proxy (for vision analysis)
        ollama_host = get_ssm_parameter(ssm, "/glitch/ollama/proxy-host")
        if ollama_host:
            env_vars["GLITCH_OLLAMA_PROXY_HOST"] = ollama_host
            log(f"Ollama proxy host set to {ollama_host}", "SUCCESS")
        else:
            log("SSM /glitch/ollama/proxy-host not found; vision analysis will be disabled", "WARN")

        ollama_key = get_ssm_parameter(ssm, "/glitch/ollama/api-key")
        if ollama_key:
            env_vars["GLITCH_OLLAMA_API_KEY"] = ollama_key
            log("Ollama API key loaded from SSM", "SUCCESS")
        else:
            log("SSM /glitch/ollama/api-key not set; Ollama proxy unauthenticated", "WARN")

        # Write .env.deploy
        with open(ENV_DEPLOY_FILE, "w") as f:
            for key, value in env_vars.items():
                f.write(f"{key}={value}\n")
            f.flush()
            os.fsync(f.fileno())
        log(f"Wrote {len(env_vars)} env vars to {ENV_DEPLOY_FILE.name}", "SUCCESS")
        log("Pre-deploy configuration completed successfully", "SUCCESS")

    except ClientError as e:
        log(f"AWS API error: {e}", "ERROR")
        sys.exit(1)
    except Exception as e:
        log(f"Unexpected error: {e}", "ERROR")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
