"""Custom resource Lambda: resolves the current public IP via the Porkbun ping API.

CloudFormation calls this on Create/Update. It reads the Porkbun API credentials from
Secrets Manager (secret name passed as PORKBUN_SECRET_NAME env var or resource property),
calls POST /ping, and returns the IP as a CloudFormation attribute "IpAddress".

The IP is also written to SSM (/glitch/waf/allowed-ipv4) so subsequent CDK synths can
read it via valueFromLookup without calling this Lambda again.
"""

import json
import os
import urllib.request
import urllib.error
import boto3

PORKBUN_PING_URL = "https://api.porkbun.com/api/json/v3/ping"
SSM_IPV4_PARAM = "/glitch/waf/allowed-ipv4"


def _get_porkbun_keys(secret_name: str, region: str) -> tuple[str, str]:
    # The secret lives in us-west-2 regardless of which region this Lambda runs in.
    secret_region = os.environ.get("PORKBUN_SECRET_REGION", region)
    client = boto3.client("secretsmanager", region_name=secret_region)
    resp = client.get_secret_value(SecretId=secret_name)
    secret = json.loads(resp["SecretString"])
    api_key = (
        secret.get("apikey")
        or secret.get("api_key")
        or secret.get("apiKey")
        or secret.get("API_KEY")
        or secret.get("key")
        or ""
    )
    secret_key = (
        secret.get("secretapikey")
        or secret.get("secret_api_key")
        or secret.get("secretApiKey")
        or secret.get("SECRET_KEY")
        or secret.get("secret")
        or ""
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
        secret_name = props.get("PorkbunSecretName") or os.environ.get("PORKBUN_SECRET_NAME", "glitch/porkbun-api")
        region = os.environ.get("AWS_REGION", "us-east-1")

        api_key, secret_key = _get_porkbun_keys(secret_name, region)
        ip = _ping_porkbun(api_key, secret_key)
        ip_cidr = f"{ip}/32"

        _write_ssm(ip_cidr, region)
        print(f"Resolved IP: {ip_cidr}")

        _send_response(event, context, "SUCCESS", {"IpAddress": ip, "IpCidr": ip_cidr})
    except Exception as exc:
        print(f"ERROR: {exc}")
        _send_response(event, context, "FAILED", {}, reason=str(exc))
