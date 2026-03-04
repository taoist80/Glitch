"""Secrets Manager management tools for Glitch.

Allows the owner to store and list credentials via Telegram, enabling
Sentinel and other agents to access new services after deployment.

All operations are restricted to the glitch/* secret prefix.
"""

import json
import logging
from typing import Optional

from strands import tool

from glitch.aws_utils import get_client

logger = logging.getLogger(__name__)

ALLOWED_PREFIX = "glitch/"


def _get_sm_client():
    return get_client("secretsmanager")


@tool
def store_secret(name: str, value: str) -> str:
    """Create or update a secret in AWS Secrets Manager.

    Use this to store credentials for Sentinel and other agents.
    Only secrets under the 'glitch/' prefix are allowed.

    Args:
        name: Secret name. Must start with 'glitch/' (e.g., 'glitch/unifi-controller').
              Common names:
              - 'glitch/unifi-controller' — UniFi Network credentials
                JSON: {"host": "10.10.100.1", "username": "admin", "password": "...", "site": "default"}
              - 'glitch/github-token' — GitHub PAT with repo scope
              - 'glitch/pihole-api' — Pi-hole credentials
                JSON: {"username": "admin", "password": "...", "hosts": ["10.10.100.70", "10.10.100.71"]}
        value: Secret value as a string. For structured credentials, pass JSON.

    Returns:
        Success message with the secret ARN, or error.
    """
    if not name.startswith(ALLOWED_PREFIX):
        return f"Error: secret name must start with '{ALLOWED_PREFIX}'. Got: {name}"

    sm = _get_sm_client()
    try:
        # Try to update existing secret first
        resp = sm.put_secret_value(SecretId=name, SecretString=value)
        return f"Updated secret '{name}' (version: {resp.get('VersionId', 'unknown')})"
    except sm.exceptions.ResourceNotFoundException:
        pass
    except Exception as e:
        if "ResourceNotFoundException" not in str(type(e).__name__):
            return f"Error updating secret '{name}': {e}"

    # Create new secret
    try:
        resp = sm.create_secret(
            Name=name,
            SecretString=value,
            Description=f"Managed by Glitch agent",
        )
        return f"Created secret '{name}' (ARN: {resp.get('ARN', 'unknown')})"
    except Exception as e:
        return f"Error creating secret '{name}': {e}"


@tool
def list_secrets() -> str:
    """List all glitch/* secrets in Secrets Manager (names only, never values).

    Returns:
        JSON list of secret names and metadata under the glitch/ prefix.
    """
    sm = _get_sm_client()
    try:
        paginator = sm.get_paginator("list_secrets")
        secrets = []
        for page in paginator.paginate(
            Filters=[{"Key": "name", "Values": [ALLOWED_PREFIX]}]
        ):
            for s in page.get("SecretList", []):
                secrets.append({
                    "name": s["Name"],
                    "description": s.get("Description", ""),
                    "last_changed": s.get("LastChangedDate", "").isoformat() if hasattr(s.get("LastChangedDate", ""), "isoformat") else str(s.get("LastChangedDate", "")),
                    "last_accessed": s.get("LastAccessedDate", "").isoformat() if hasattr(s.get("LastAccessedDate", ""), "isoformat") else str(s.get("LastAccessedDate", "")),
                })
        return json.dumps({"secret_count": len(secrets), "secrets": secrets}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})
