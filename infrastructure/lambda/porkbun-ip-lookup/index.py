"""Custom resource Lambda: provides the current home IP CIDR for the WAF allowlist.

Strategy:
  1. Read /glitch/waf/allowed-ipv4 from SSM (kept current by the ddns-updater webhook Lambda).
  2. If SSM has no value, use the FallbackIpCidr resource property (baked into cdk.context.json).

The resolved CIDR is written back to SSM (idempotent) and returned as the CloudFormation
attribute "IpCidr" so the WAF IP set stays current on every deploy.

The ddns-updater Lambda handles the actual DNS update and WAF IP set update at runtime
whenever the home IP changes. This custom resource only runs at deploy time.
"""

import json
import os
import urllib.request

import boto3

SSM_IPV4_PARAM = "/glitch/waf/allowed-ipv4"


def _read_ssm(region: str) -> str | None:
    try:
        client = boto3.client("ssm", region_name=region)
        return client.get_parameter(Name=SSM_IPV4_PARAM)["Parameter"]["Value"]
    except client.exceptions.ParameterNotFound:
        return None
    except Exception as e:
        print(f"SSM read failed: {e}")
        return None


def _write_ssm(ip_cidr: str, region: str) -> None:
    client = boto3.client("ssm", region_name=region)
    client.put_parameter(
        Name=SSM_IPV4_PARAM,
        Value=ip_cidr,
        Type="String",
        Description="Allowed IPv4 CIDRs for Glitch WAF (managed by ddns-updater webhook)",
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

        # 1. Try SSM — the ddns-updater webhook keeps this current at runtime.
        ip_cidr = _read_ssm(region)
        if ip_cidr:
            print(f"Using SSM value: {ip_cidr}")
        else:
            # 2. Fall back to the value baked into CDK context (cdk.context.json).
            #    Update context.json manually if the fallback IP is stale.
            fallback = props.get("FallbackIpCidr", "")
            if not fallback:
                raise RuntimeError(
                    "SSM parameter not found and no FallbackIpCidr provided. "
                    "Call the ddns-updater webhook from your home network first, "
                    "or set allowedIpAddresses context override."
                )
            ip_cidr = fallback
            print(f"SSM empty; using FallbackIpCidr: {ip_cidr}")

        _write_ssm(ip_cidr, region)
        ip = ip_cidr.split("/")[0]
        _send_response(event, context, "SUCCESS", {"IpAddress": ip, "IpCidr": ip_cidr})
    except Exception as exc:
        print(f"ERROR: {exc}")
        _send_response(event, context, "FAILED", {}, reason=str(exc))
