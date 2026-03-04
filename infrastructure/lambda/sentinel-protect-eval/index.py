"""Lambda: scheduled invocation of Sentinel for Protect camera evaluation.

Reads Sentinel runtime ARN from SSM /glitch/sentinel/runtime-arn and invokes
with a Protect evaluation prompt. Runs on EventBridge schedule (e.g. every 15 min).
"""
import json
import logging
import time
import urllib.request
from urllib.parse import quote

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

logger = logging.getLogger()
logger.setLevel(logging.INFO)

SSM_PARAM_SENTINEL_ARN = "/glitch/sentinel/runtime-arn"


def get_data_plane_endpoint(region: str) -> str:
    return f"https://bedrock-agentcore.{region}.amazonaws.com"


def parse_runtime_arn(arn: str) -> dict:
    parts = arn.split(":")
    if len(parts) != 6 or not (parts[5] or "").startswith("runtime/"):
        raise ValueError("Invalid runtime ARN: " + str(arn))
    return {
        "region": parts[3],
        "account_id": parts[4],
        "runtime_id": parts[5].split("/", 1)[1],
    }


def handler(event, context):
    try:
        ssm = boto3.client("ssm")
        resp = ssm.get_parameter(Name=SSM_PARAM_SENTINEL_ARN)
        arn = (resp.get("Parameter") or {}).get("Value", "").strip()
    except Exception as e:
        logger.warning("Failed to get Sentinel ARN from SSM: %s", e)
        return

    if not arn:
        logger.warning("Sentinel runtime ARN not set in SSM")
        return

    try:
        parts = parse_runtime_arn(arn)
        region = parts["region"]
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(arn, safe="")
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        session_id = f"system:sentinel-protect-eval-{int(time.time())}"
        payload = {
            "prompt": "Run a scheduled Protect evaluation: check all cameras for recent events, analyze any anomalies, update baselines, and send alerts for anything requiring attention.",
            "session_id": session_id,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
        }
        session = boto3.Session()
        creds = session.get_credentials()
        if creds:
            req = AWSRequest(method="POST", url=url, data=body, headers=headers)
            SigV4Auth(creds, "bedrock-agentcore", region).add_auth(req)
            headers = dict(req.headers)
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            resp.read()
        logger.info("Sentinel Protect eval invocation completed")
    except Exception as e:
        logger.warning("Sentinel Protect eval invoke failed: %s", e)
