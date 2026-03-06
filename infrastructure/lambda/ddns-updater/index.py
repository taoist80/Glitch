"""DDNS Updater webhook Lambda.

Called by the home network (HTTP POST to the Function URL) to:
  1. Update home.awoo.agency A record in Porkbun DNS to the caller's public IP
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

UDM-Pro: add a Task under System → Scheduled Tasks that runs the curl command above.
"""

import json
import os
import urllib.request

import boto3

PORKBUN_API_BASE = "https://api.porkbun.com/api/json/v3"

DDNS_SUBDOMAIN = os.environ.get("DDNS_SUBDOMAIN", "home")
DDNS_DOMAIN = os.environ.get("DDNS_DOMAIN", "awoo.agency")

WAF_IP_SET_ID = os.environ.get("WAF_IP_SET_ID", "")
WAF_IP_SET_NAME = os.environ.get("WAF_IP_SET_NAME", "GlitchAllowedIPs")

SSM_PARAM = os.environ.get("SSM_PARAM", "/glitch/waf/allowed-ipv4")
PORKBUN_SECRET_NAME = os.environ.get("PORKBUN_SECRET_NAME", "glitch/porkbun-api")
DDNS_TOKEN_SECRET_ARN = os.environ.get("DDNS_TOKEN_SECRET_ARN", "")

# Porkbun secret lives in us-west-2; token secret lives in us-east-1 (this stack's region)
PORKBUN_SECRET_REGION = os.environ.get("PORKBUN_SECRET_REGION", "us-west-2")
TOKEN_SECRET_REGION = os.environ.get("TOKEN_SECRET_REGION", "us-east-1")


def _json_response(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _get_secret(secret_id: str, region: str) -> str:
    client = boto3.client("secretsmanager", region_name=region)
    return client.get_secret_value(SecretId=secret_id)["SecretString"]


def _get_porkbun_keys() -> tuple[str, str]:
    raw = _get_secret(PORKBUN_SECRET_NAME, PORKBUN_SECRET_REGION)
    secret = json.loads(raw)
    api_key = (
        secret.get("apikey") or secret.get("api_key") or secret.get("apiKey")
        or secret.get("API_KEY") or secret.get("key") or ""
    )
    secret_key = (
        secret.get("secretapikey") or secret.get("secret_api_key") or secret.get("secretApiKey")
        or secret.get("SECRET_KEY") or secret.get("secret") or ""
    )
    if not api_key or not secret_key:
        raise ValueError("Porkbun API keys not found in secret")
    return api_key, secret_key


def _get_caller_ip(event: dict) -> str:
    """Extract the caller's public IP from the Lambda Function URL event."""
    ip = (
        (event.get("requestContext") or {}).get("http", {}).get("sourceIp")
        or ((event.get("headers") or {}).get("x-forwarded-for", "")).split(",")[0].strip()
    )
    if not ip:
        raise ValueError("Could not determine caller IP from request")
    return ip


def _validate_token(event: dict) -> bool:
    """Validate Authorization: Bearer <token> header against Secrets Manager."""
    if not DDNS_TOKEN_SECRET_ARN:
        return True  # auth not configured — skip
    auth = ((event.get("headers") or {}).get("authorization") or "")
    if not auth.lower().startswith("bearer "):
        return False
    provided = auth[7:].strip()
    try:
        expected = _get_secret(DDNS_TOKEN_SECRET_ARN, TOKEN_SECRET_REGION).strip()
    except Exception as e:
        print(f"Token secret read failed: {e}")
        return False
    return provided == expected


def _porkbun_request(path: str, body: dict) -> dict:
    api_key, secret_key = _get_porkbun_keys()
    body = {**body, "apikey": api_key, "secretapikey": secret_key}
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{PORKBUN_API_BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def _update_porkbun_dns(ip: str) -> None:
    """Update (or create) the DDNS_SUBDOMAIN.DDNS_DOMAIN A record."""
    result = _porkbun_request(
        f"/dns/editByNameType/{DDNS_DOMAIN}/A/{DDNS_SUBDOMAIN}",
        {"content": ip, "ttl": "600"},
    )
    if result.get("status") == "SUCCESS":
        print(f"Porkbun: updated {DDNS_SUBDOMAIN}.{DDNS_DOMAIN} → {ip}")
        return
    # editByNameType may fail if the record doesn't exist yet — try create
    result2 = _porkbun_request(
        f"/dns/create/{DDNS_DOMAIN}",
        {"name": DDNS_SUBDOMAIN, "type": "A", "content": ip, "ttl": "600"},
    )
    if result2.get("status") == "SUCCESS":
        print(f"Porkbun: created {DDNS_SUBDOMAIN}.{DDNS_DOMAIN} → {ip}")
    else:
        raise RuntimeError(f"Porkbun DNS update failed: {result2}")


def _update_waf_ip_set(ip_cidr: str) -> None:
    """Update the WAF IP set to the new home IP CIDR."""
    if not WAF_IP_SET_ID:
        print("WAF_IP_SET_ID not configured; skipping WAF update")
        return
    client = boto3.client("wafv2", region_name="us-east-1")
    resp = client.get_ip_set(Name=WAF_IP_SET_NAME, Scope="CLOUDFRONT", Id=WAF_IP_SET_ID)
    client.update_ip_set(
        Name=WAF_IP_SET_NAME,
        Scope="CLOUDFRONT",
        Id=WAF_IP_SET_ID,
        Addresses=[ip_cidr],
        LockToken=resp["LockToken"],
    )
    print(f"WAF IP set updated: {ip_cidr}")


def _update_ssm(ip_cidr: str) -> None:
    client = boto3.client("ssm", region_name="us-east-1")
    client.put_parameter(Name=SSM_PARAM, Value=ip_cidr, Type="String", Overwrite=True)
    print(f"SSM {SSM_PARAM} = {ip_cidr}")


def handler(event: dict, context) -> dict:
    method = (event.get("requestContext") or {}).get("http", {}).get("method", "?")
    print(json.dumps({"method": method}))

    if not _validate_token(event):
        return _json_response(401, {"error": "Unauthorized"})

    try:
        ip = _get_caller_ip(event)
        ip_cidr = f"{ip}/32"
        print(f"Caller IP: {ip}")

        _update_porkbun_dns(ip)
        _update_waf_ip_set(ip_cidr)
        _update_ssm(ip_cidr)

        return _json_response(200, {"status": "ok", "ip": ip, "cidr": ip_cidr})
    except Exception as exc:
        print(f"ERROR: {exc}")
        return _json_response(500, {"error": str(exc)})
