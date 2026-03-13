import base64
import json
import logging
import os
import uuid
from decimal import Decimal
from urllib.parse import parse_qs, quote

import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
import urllib.error
import urllib.request

from agentcore_utils import get_data_plane_endpoint, parse_runtime_arn

logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource('dynamodb')
lambda_client = boto3.client('lambda')
session = boto3.Session()

CONFIG_TABLE_NAME = os.environ['CONFIG_TABLE_NAME']
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')
PROTECT_QUERY_FUNCTION_NAME = os.environ.get('PROTECT_QUERY_FUNCTION_NAME', '')

table = dynamodb.Table(CONFIG_TABLE_NAME)


def get_or_create_session(client_id: str) -> str:
    """Get existing session_id for client or create new one. AgentCore requires length >= 33."""
    try:
        response = table.get_item(Key={'pk': f'UI_SESSION#{client_id}', 'sk': 'session'})
        if 'Item' in response:
            session_id = response['Item']['session_id']
            if len(session_id) >= 33:
                return session_id
            # Existing short session_id; replace with valid one and update DB
    except Exception as e:
        logger.warning(f"Failed to get session: {e}")

    session_id = f"ui-{client_id}-{uuid.uuid4().hex}"
    try:
        table.put_item(Item={
            'pk': f'UI_SESSION#{client_id}',
            'sk': 'session',
            'session_id': session_id,
            'created_at': str(int(__import__('time').time())),
        })
    except Exception as e:
        logger.warning(f"Failed to save session: {e}")

    return session_id


def get_session_agent_mode(session_id: str) -> tuple:
    """Load agent_id and mode_id for session from DynamoDB. Returns (agent_id, mode_id)."""
    if not table:
        return (None, None)
    try:
        r = table.get_item(Key={"pk": "SESSION_AGENT", "sk": session_id})
        if "Item" not in r:
            return (None, None)
        item = r["Item"]
        return (item.get("agent_id"), item.get("mode_id"))
    except Exception as e:
        logger.debug("get_session_agent_mode: %s", e)
        return (None, None)


def invoke_agent(prompt: str, session_id: str, stream: bool = False, agent_id: str = None, mode_id: str = None) -> dict:
    """Invoke AgentCore Runtime via signed HTTP request. Forwards agent_id and mode_id when set."""
    if not AGENTCORE_RUNTIME_ARN:
        return {"error": "Agent runtime not configured"}

    if agent_id is None and mode_id is None:
        agent_id, mode_id = get_session_agent_mode(session_id)

    try:
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        payload = {"prompt": prompt, "session_id": session_id}
        if stream:
            payload["stream"] = True
        if agent_id:
            payload["agent_id"] = agent_id
        if mode_id:
            payload["mode_id"] = mode_id
        body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
        }
        aws_request = AWSRequest(method='POST', url=url, data=body, headers=headers)
        credentials = session.get_credentials()
        if credentials:
            SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
        req = urllib.request.Request(
            url, data=body, headers=dict(aws_request.headers), method='POST'
        )
        with urllib.request.urlopen(req, timeout=280) as response:
            result = json.loads(response.read().decode())
            logger.info(f"Agent response keys: {list(result.keys()) if isinstance(result, dict) else 'not-dict'}")
            if isinstance(result, dict) and result.get('error'):
                logger.warning(f"Agent returned error: {result.get('error')}")
            return result if isinstance(result, dict) else {"message": str(result)}
    except urllib.error.HTTPError as he:
        resp_body = ""
        try:
            if he.fp:
                resp_body = he.fp.read().decode('utf-8', errors='replace')
        except Exception:
            pass
        logger.error(
            "AgentCore HTTP %s %s response_body: %s",
            he.code, he.reason, resp_body[:2000] if resp_body else "(empty)",
        )
        return {"error": f"HTTP Error {he.code}: {he.reason}"}
    except Exception as e:
        logger.error(f"Failed to invoke agent: {e}", exc_info=True)
        return {"error": f"gateway_invoke_agent: {e}"}


def _normalize_query_params(event_params) -> dict:
    """Ensure query params are a dict. Lambda Function URL gives dict; some triggers give a string."""
    if not event_params:
        return {}
    if isinstance(event_params, dict):
        return event_params
    if isinstance(event_params, str):
        parsed = parse_qs(event_params, keep_blank_values=True)
        return {k: (v[0] if v else "") for k, v in parsed.items()}
    return {}


def invoke_api(path: str, method: str, body: dict, session_id: str, query_params: dict = None) -> dict:
    """Invoke AgentCore Runtime with _ui_api_request payload."""
    if not AGENTCORE_RUNTIME_ARN:
        return {"error": "Agent runtime not configured"}

    try:
        arn_parts = parse_runtime_arn(AGENTCORE_RUNTIME_ARN)
        region = arn_parts['region']
        endpoint = get_data_plane_endpoint(region)
        encoded_arn = quote(AGENTCORE_RUNTIME_ARN, safe='')
        url = f"{endpoint}/runtimes/{encoded_arn}/invocations"
        ui_request = {
            "path": path,
            "method": method,
            "body": body,
        }
        if query_params:
            ui_request["query_params"] = query_params
        payload = {"_ui_api_request": ui_request}
        req_body = json.dumps(payload).encode('utf-8')
        headers = {
            'Content-Type': 'application/json',
            'X-Amzn-Bedrock-AgentCore-Runtime-Session-Id': session_id,
        }
        aws_request = AWSRequest(method='POST', url=url, data=req_body, headers=headers)
        credentials = session.get_credentials()
        if credentials:
            SigV4Auth(credentials, 'bedrock-agentcore', region).add_auth(aws_request)
        req = urllib.request.Request(
            url, data=req_body, headers=dict(aws_request.headers), method='POST'
        )
        # 25s timeout: UI API calls (status, agents, protect, etc.) must be fast.
        # This ensures the Lambda returns an error response well within CloudFront's
        # readTimeout, preventing 504s during container startup/scaling events.
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.loads(response.read().decode())
            return result if isinstance(result, dict) else {"data": result}
    except urllib.error.HTTPError as e:
        err_body = ""
        try:
            if e.fp:
                err_body = e.fp.read().decode("utf-8", errors="replace")
        finally:
            try:
                if e.fp:
                    e.fp.close()
            except Exception:
                pass
        logger.error("AgentCore HTTP %s %s body=%s", e.code, e.reason, err_body[:500])
        return {"error": f"gateway_invoke_api: AgentCore HTTP {e.code}: {e.reason}. {err_body[:500]}"}
    except Exception as e:
        logger.error(f"Failed to invoke API: {e}", exc_info=True)
        return {"error": f"gateway_invoke_api: {e}"}


def invoke_protect_query(path: str, query_params: dict) -> dict:
    """Invoke protect-query Lambda directly — bypasses AgentCore/LLM entirely."""
    if not PROTECT_QUERY_FUNCTION_NAME:
        return {"error": "protect-query function not configured"}
    try:
        payload = json.dumps({
            "path": path,
            "queryStringParameters": query_params or {},
        }).encode("utf-8")
        response = lambda_client.invoke(
            FunctionName=PROTECT_QUERY_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=payload,
        )
        result = json.loads(response["Payload"].read())
        body = result.get("body", "{}")
        return json.loads(body) if isinstance(body, str) else body
    except Exception as e:
        logger.error(f"protect-query Lambda invoke failed: {e}", exc_info=True)
        return {"error": f"protect_query: {e}"}


def decimal_default(obj):
    if isinstance(obj, Decimal):
        return float(obj) if obj % 1 else int(obj)
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def handler(event, context):
    """Lambda handler for gateway. Routes requests to AgentCore Runtime."""
    # Handle CloudWatch Events keepalive
    if event.get('source') == 'aws.events':
        return {'statusCode': 200, 'body': json.dumps({'status': 'healthy'})}

    # Parse request (Function URL uses payload 2.0: rawPath or requestContext.http.path)
    http_method = event.get('requestContext', {}).get('http', {}).get('method', 'GET')
    path = (event.get('rawPath') or event.get('requestContext', {}).get('http', {}).get('path') or '/')
    headers = event.get('headers', {})
    logger.info("Gateway request: %s path=%s", http_method, path)

    # CORS preflight: return 204 with CORS headers so browsers can send actual request
    cors_headers = {
        'Content-Type': 'application/json',
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': 'Content-Type, X-Client-Id, X-Session-Id',
        'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    }
    if http_method == 'OPTIONS':
        return {'statusCode': 204, 'headers': cors_headers, 'body': ''}

    # Get or create client session
    client_id = headers.get('x-client-id') or headers.get('X-Client-Id') or 'anonymous'
    session_id = get_or_create_session(client_id)

    # Parse body
    body = {}
    if event.get('body'):
        try:
            raw_body = event['body']
            if event.get('isBase64Encoded'):
                raw_body = base64.b64decode(raw_body).decode('utf-8')
            body = json.loads(raw_body)
        except Exception as e:
            logger.warning(f"Failed to parse body: {e}")

    # Route requests
    response_body = {}
    status_code = 200

    try:
        # Health check
        if path == '/health' or path == '/':
            response_body = {'status': 'healthy', 'session_id': session_id}

        # Chat invocation
        elif path == '/invocations' and http_method == 'POST':
            prompt = body.get('prompt', '')
            stream = body.get('stream', False)
            agent_id = body.get('agent_id') or None
            mode_id = body.get('mode_id') or None
            if not prompt:
                response_body = {'error': 'No prompt provided'}
                status_code = 400
            else:
                response_body = invoke_agent(prompt, session_id, stream=stream, agent_id=agent_id, mode_id=mode_id)

        # Protect API: bypass LLM — query Postgres directly via protect-query Lambda.
        # scan/backfill are runtime actions and must be forwarded to AgentCore instead.
        elif path.startswith('/api/protect/'):
            if path in ('/api/protect/scan', '/api/protect/backfill'):
                api_path = '/' + path[5:]
                query_params = _normalize_query_params(event.get('queryStringParameters'))
                logger.info(f"Gateway forwarding protect action to AgentCore: {http_method} {api_path}")
                response_body = invoke_api(api_path, http_method, body, session_id, query_params)
            else:
                query_params = _normalize_query_params(event.get('queryStringParameters'))
                logger.info(f"Gateway routing to protect-query: {http_method} {path} query={query_params}")
                response_body = invoke_protect_query(path, query_params)

        # API proxy routes: /api/* (from nginx) or direct paths (from UI with Lambda base URL)
        elif path.startswith('/api/'):
            api_path = '/' + path[5:]
            query_params = _normalize_query_params(event.get('queryStringParameters'))
            logger.info(f"Gateway forwarding to AgentCore: {http_method} {api_path} query={query_params}")
            response_body = invoke_api(api_path, http_method, body, session_id, query_params)
        elif (path in ('/status', '/telegram/config', '/ollama/health', '/memory/summary', '/telemetry', '/streaming-info', '/mcp/servers', '/agents', '/modes') or
              path.startswith('/skills') or path.startswith('/sessions/') or path.startswith('/protect/')):
            query_params = _normalize_query_params(event.get('queryStringParameters'))
            logger.info(f"Gateway forwarding to AgentCore: {http_method} {path} query={query_params}")
            response_body = invoke_api(path, http_method, body, session_id, query_params)
            # So the UI uses the same session_id for /sessions/{id}/agent and /sessions/{id}/mode as we use for
            # /invocations, overwrite session_id in /status with the gateway's session_id (per client).
            if path == '/status' and isinstance(response_body, dict) and 'error' not in response_body:
                response_body = {**response_body, 'session_id': session_id}
        else:
            response_body = {'error': f'Unknown path: {path}'}
            status_code = 404

    except Exception as e:
        logger.error(f"Handler error: {e}", exc_info=True)
        response_body = {'error': f'gateway_handler: {e}'}
        status_code = 500

    return {
        'statusCode': status_code,
        'headers': cors_headers,
        'body': json.dumps(response_body, default=decimal_default),
    }
