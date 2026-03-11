"""DDNS Updater webhook Lambda.

Called by the home network (HTTP POST to the Function URL) to:
  1. Update home.awoo.agency A record in Cloudflare DNS to the caller's public IP
  2. Update the WAF IP set (GlitchAllowedIPs) with the new CIDR
  3. Write the new CIDR to SSM /glitch/waf/allowed-ipv4

Authentication: Bearer token stored in Secrets Manager (DDNS_TOKEN_SECRET_ARN).
If DDNS_TOKEN_SECRET_ARN is not set, auth is skipped (not recommended for production).

Usage from home network (run every 5 minutes via cron/task scheduler):
  TOKEN=$(aws secretsmanager get-secret-value \\
    --secret-id glitch/ddns-token --region us-east-1 \\
    --query SecretString --output text)
  curl -s -X POST https://<DDNS_UPDATER_URL> \\
    -H "Authorization: Bearer $TOKEN"

UDM-Pro: add a Task under System > Scheduled Tasks that runs the curl command above.
"""

import ipaddress
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Optional

import boto3

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

CLOUDFLARE_API_BASE = "https://api.cloudflare.com/client/v4"

DDNS_SUBDOMAIN = os.environ.get("DDNS_SUBDOMAIN", "home")
DDNS_DOMAIN = os.environ.get("DDNS_DOMAIN", "awoo.agency")

WAF_IP_SET_ID = os.environ.get("WAF_IP_SET_ID", "")
WAF_IP_SET_NAME = os.environ.get("WAF_IP_SET_NAME", "GlitchAllowedIPs")
WAF_REGION = os.environ.get("WAF_REGION", "us-east-1")

SSM_PARAM = os.environ.get("SSM_PARAM", "/glitch/waf/allowed-ipv4")
SSM_REGION = os.environ.get("SSM_REGION", "us-east-1")

CLOUDFLARE_SECRET_NAME = os.environ.get("CLOUDFLARE_SECRET_NAME", "glitch/cloudflare-api")
DDNS_TOKEN_SECRET_ARN = os.environ.get("DDNS_TOKEN_SECRET_ARN", "")

CLOUDFLARE_SECRET_REGION = os.environ.get("CLOUDFLARE_SECRET_REGION", "us-east-1")
TOKEN_SECRET_REGION = os.environ.get("TOKEN_SECRET_REGION", "us-east-1")

# Module-level boto3 clients — reused across warm Lambda invocations.
_sm_cloudflare = boto3.client("secretsmanager", region_name=CLOUDFLARE_SECRET_REGION)
_sm_token = boto3.client("secretsmanager", region_name=TOKEN_SECRET_REGION)
_wafv2 = boto3.client("wafv2", region_name=WAF_REGION)
_ssm = boto3.client("ssm", region_name=SSM_REGION)


def _json_response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _get_secret(client, secret_id: str) -> str:
    return client.get_secret_value(SecretId=secret_id)["SecretString"]


def _get_cloudflare_creds() -> tuple[str, str]:
    """Return (api_token, zone_id) from Secrets Manager."""
    raw = _get_secret(_sm_cloudflare, CLOUDFLARE_SECRET_NAME)
    secret = json.loads(raw)
    api_token = secret.get("api_token") or secret.get("apiToken") or secret.get("token") or ""
    zone_id = secret.get("zone_id") or secret.get("zoneId") or os.environ.get("CLOUDFLARE_ZONE_ID", "")
    if not api_token:
        raise ValueError("Cloudflare API token not found in secret")
    if not zone_id:
        raise ValueError("Cloudflare zone_id not found in secret or env")
    return api_token, zone_id


def _get_caller_ip(event: dict) -> str:
    """Extract and validate the caller's public IP from the Lambda Function URL event."""
    ip = (
        (event.get("requestContext") or {}).get("http", {}).get("sourceIp")
        or ((event.get("headers") or {}).get("x-forwarded-for", "")).split(",")[0].strip()
    )
    if not ip:
        raise ValueError("Could not determine caller IP from request")
    # Validate it's a well-formed IP address before using it in DNS/WAF writes.
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"Invalid IP address in request: {ip!r}")
    return ip


def _validate_token(event: dict) -> bool:
    """Validate Authorization: Bearer <token> header against Secrets Manager."""
    if not DDNS_TOKEN_SECRET_ARN:
        return True
    auth = ((event.get("headers") or {}).get("authorization") or "")
    if not auth.lower().startswith("bearer "):
        return False
    provided = auth[7:].strip()
    try:
        expected = _get_secret(_sm_token, DDNS_TOKEN_SECRET_ARN).strip()
    except Exception as e:
        logger.error("Token secret read failed: %s", e)
        return False
    return provided == expected


def _cloudflare_request(method: str, path: str, api_token: str, body: Optional[dict] = None) -> dict:
    """Make an authenticated request to the Cloudflare API.

    Raises ValueError on HTTP errors or when the Cloudflare response indicates failure.
    """
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(
        f"{CLOUDFLARE_API_BASE}{path}",
        data=data,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result: dict = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode(errors="replace")
        raise ValueError(f"Cloudflare API {method} {path} returned {exc.code}: {body_text}") from exc

    if not result.get("success", True):
        errors = result.get("errors", [])
        raise ValueError(f"Cloudflare API error on {method} {path}: {errors}")

    return result


def _update_cloudflare_dns(ip: str) -> None:
    """Update (or create) the DDNS_SUBDOMAIN.DDNS_DOMAIN A record in Cloudflare."""
    api_token, zone_id = _get_cloudflare_creds()
    fqdn = f"{DDNS_SUBDOMAIN}.{DDNS_DOMAIN}"

    # List existing A records for this FQDN
    result = _cloudflare_request(
        "GET",
        f"/zones/{zone_id}/dns_records?type=A&name={fqdn}",
        api_token,
    )
    records = result.get("result", [])

    if records:
        record_id = records[0]["id"]
        current_ip = records[0].get("content", "")
        if current_ip == ip:
            logger.info("Cloudflare: %s already points to %s, no update needed", fqdn, ip)
            return
        _cloudflare_request(
            "PATCH",
            f"/zones/{zone_id}/dns_records/{record_id}",
            api_token,
            {"content": ip, "ttl": 600, "proxied": False},
        )
        logger.info("Cloudflare: updated %s → %s", fqdn, ip)
    else:
        _cloudflare_request(
            "POST",
            f"/zones/{zone_id}/dns_records",
            api_token,
            {"type": "A", "name": DDNS_SUBDOMAIN, "content": ip, "ttl": 600, "proxied": False},
        )
        logger.info("Cloudflare: created %s → %s", fqdn, ip)


def _update_waf_ip_set(ip_cidr: str) -> None:
    """Update the WAF IP set to the new home IP CIDR."""
    if not WAF_IP_SET_ID:
        logger.warning("WAF_IP_SET_ID not configured; skipping WAF update")
        return
    resp = _wafv2.get_ip_set(Name=WAF_IP_SET_NAME, Scope="CLOUDFRONT", Id=WAF_IP_SET_ID)
    _wafv2.update_ip_set(
        Name=WAF_IP_SET_NAME,
        Scope="CLOUDFRONT",
        Id=WAF_IP_SET_ID,
        Addresses=[ip_cidr],
        LockToken=resp["LockToken"],
    )
    logger.info("WAF IP set updated: %s", ip_cidr)


def _update_ssm(ip_cidr: str) -> None:
    _ssm.put_parameter(Name=SSM_PARAM, Value=ip_cidr, Type="String", Overwrite=True)
    logger.info("SSM %s = %s", SSM_PARAM, ip_cidr)


def handler(event: dict, context) -> dict:
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "GET")
    logger.info(json.dumps({"method": method}))

    # Health / preflight — return 200 without performing any updates.
    if method in ("GET", "HEAD", "OPTIONS"):
        return _json_response(200, {"status": "ok"})

    if method != "POST":
        return _json_response(405, {"error": f"Method {method} not allowed"})

    if not _validate_token(event):
        return _json_response(401, {"error": "Unauthorized"})

    try:
        ip = _get_caller_ip(event)
        ip_cidr = f"{ip}/32"
        logger.info("Caller IP: %s", ip)

        _update_cloudflare_dns(ip)
        _update_waf_ip_set(ip_cidr)
        _update_ssm(ip_cidr)

        return _json_response(200, {"status": "ok", "ip": ip, "cidr": ip_cidr})
    except Exception as exc:
        logger.error("DDNS update failed: %s", exc, exc_info=True)
        return _json_response(500, {"error": str(exc)})
