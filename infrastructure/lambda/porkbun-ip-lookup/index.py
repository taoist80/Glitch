"""Custom resource Lambda: resolves the current public IP for the WAF allowlist.

Strategy (in order):
1. If DdnsHostname is provided as a resource property, resolve it via DNS.
   This is the preferred path: your DDNS record (e.g. home.awoo.agency) always
   reflects your current home IP and is maintained by porkbun-ddns-update.sh.
2. Fall back to calling the Porkbun ping API with your API keys.
   Note: when running inside AWS Lambda the ping API returns an AWS egress IP,
   not your home IP — only use this fallback if DDNS is not configured.

The resolved IP is written to SSM (/glitch/waf/allowed-ipv4) and returned as
the CloudFormation attribute "IpCidr" so the WAF IP set stays current on every deploy.
"""

import json
import os
import socket
import urllib.request
import urllib.error
import boto3

SSM_IPV4_PARAM = "/glitch/waf/allowed-ipv4"
PORKBUN_PING_URL = "https://api.porkbun.com/api/json/v3/ping"


def _resolve_ddns(hostname: str) -> str:
    """Resolve a DDNS hostname to its current IPv4 address via DNS."""
    results = socket.getaddrinfo(hostname, None, socket.AF_INET)
    if not results:
        raise RuntimeError(f"DNS resolution returned no results for {hostname!r}")
    return results[0][4][0]


def _get_porkbun_keys(secret_name: str, region: str) -> tuple[str, str]:
    secret_region = os.environ.get("PORKBUN_SECRET_REGION", region)
    client = boto3.client("secretsmanager", region_name=secret_region)
    resp = client.get_secret_value(SecretId=secret_name)
    secret = json.loads(resp["SecretString"])
    api_key = (
        secret.get("apikey") or secret.get("api_key") or secret.get("apiKey")
        or secret.get("API_KEY") or secret.get("key") or ""
    )
    secret_key = (
        secret.get("secretapikey") or secret.get("secret_api_key") or secret.get("secretApiKey")
        or secret.get("SECRET_KEY") or secret.get("secret") or ""
    )
    if not api_key or not secret_key:
        raise ValueError(f"Porkbun API keys not found in secret {secret_name!r}")
    return api_key, secret_key


def _ping_porkbun(api_key: str, secret_key: str) -> str:
    payload = json.dumps({"apikey": api_key, "secretapikey": secret_key}).encode()
    req = urllib.request.Request(
        PORKBUN_PING_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        body = json.loads(resp.read())
    if body.get("status") != "SUCCESS":
        raise RuntimeError(f"Porkbun ping failed: {body}")
    ip = body.get("yourIp", "").strip()
    if not ip:
        raise RuntimeError(f"Porkbun ping returned no IP: {body}")
    return ip


def _write_ssm(ip_cidr: str, region: str) -> None:
    client = boto3.client("ssm", region_name=region)
    client.put_parameter(
        Name=SSM_IPV4_PARAM,
        Value=ip_cidr,
        Type="String",
        Description="Allowed IPv4 CIDRs for Glitch WAF (auto-updated by Porkbun IP lookup)",
        Overwrite=True,
    )


def _send_response(event: dict, context, status: str, data: dict, reason: str = "") -> None:
    body = json.dumps({
        "Status": status,
        "Reason": reason or f"See CloudWatch log stream: {context.log_stream_name}",
        "PhysicalResourceId": event.get("PhysicalResourceId") or context.log_stream_name,
        "StackId": event["StackId"],
        "RequestId": event["RequestId"],
        "LogicalResourceId": event["LogicalResourceId"],
        "Data": data,
    }).encode()
    req = urllib.request.Request(
        event["ResponseURL"],
        data=body,
        headers={"Content-Type": "application/json", "Content-Length": str(len(body))},
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=10):
        pass


def handler(event: dict, context) -> None:
    print(json.dumps({"event_type": event["RequestType"], "logical_id": event["LogicalResourceId"]}))

    if event["RequestType"] == "Delete":
        _send_response(event, context, "SUCCESS", {})
        return

    try:
        props = event.get("ResourceProperties", {})
        region = os.environ.get("AWS_REGION", "us-east-1")
        ddns_hostname = props.get("DdnsHostname") or os.environ.get("DDNS_HOSTNAME", "")

        if ddns_hostname:
            # Preferred: resolve DDNS hostname — always reflects current home IP
            print(f"Resolving DDNS hostname: {ddns_hostname}")
            ip = _resolve_ddns(ddns_hostname)
            print(f"DDNS resolved: {ddns_hostname} -> {ip}")
        else:
            # Fallback: Porkbun ping API (returns Lambda's AWS IP when run inside AWS)
            print("No DDNS hostname; falling back to Porkbun ping API")
            secret_name = props.get("PorkbunSecretName") or os.environ.get("PORKBUN_SECRET_NAME", "glitch/porkbun-api")
            api_key, secret_key = _get_porkbun_keys(secret_name, region)
            ip = _ping_porkbun(api_key, secret_key)

        ip_cidr = f"{ip}/32"
        _write_ssm(ip_cidr, region)
        print(f"IP written to SSM: {ip_cidr}")

        _send_response(event, context, "SUCCESS", {"IpAddress": ip, "IpCidr": ip_cidr})
    except Exception as exc:
        print(f"ERROR: {exc}")
        _send_response(event, context, "FAILED", {}, reason=str(exc))
