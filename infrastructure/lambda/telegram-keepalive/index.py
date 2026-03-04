import json
import os
import urllib.request
from urllib.parse import quote
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest


def get_data_plane_endpoint(region):
    return "https://bedrock-agentcore." + region + ".amazonaws.com"


def parse_runtime_arn(arn):
    parts = arn.split(':')
    if len(parts) != 6 or not (parts[5] or '').startswith('runtime/'):
        raise ValueError("Invalid runtime ARN: " + str(arn))
    return {'region': parts[3], 'account_id': parts[4], 'runtime_id': parts[5].split('/', 1)[1]}


def handler(event, context):
    arn = os.environ.get('AGENTCORE_RUNTIME_ARN', '')
    if not arn:
        return
    try:
        parts = parse_runtime_arn(arn)
        region = parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(arn, safe='')
        url = endpoint + "/runtimes/" + encoded_arn + "/invocations"
        keepalive_session_id = "system:keepalive" + "0" * 17
        payload = {"prompt": "ping", "session_id": keepalive_session_id}
        body = json.dumps(payload).encode('utf-8')
        headers = {'Content-Type': 'application/json', 'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': keepalive_session_id}
        session = boto3.Session()
        creds = session.get_credentials()
        if creds:
            req = AWSRequest(method='POST', url=url, data=body, headers=headers)
            SigV4Auth(creds, 'bedrock-agentcore', region).add_auth(req)
            headers = dict(req.headers)
        req = urllib.request.Request(url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()
    except Exception as e:
        import logging
        logging.getLogger().warning("Keepalive invoke failed: %s", e)
