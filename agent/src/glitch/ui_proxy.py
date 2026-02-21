"""UI proxy for invoking deployed AgentCore runtime via boto3.

Allows the dashboard UI to communicate with a deployed agent when running
in proxy mode (GLITCH_UI_MODE=proxy) by calling the Bedrock AgentCore
Data Plane API instead of the agentcore CLI.
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Short-lived cache so we pick up new runtime ARN shortly after redeploy (TTL 60s).
_runtime_arn_cache: dict[str, tuple[str, float]] = {}
_RUNTIME_ARN_CACHE_TTL = 60.0


def get_runtime_arn(agent_name: str, region: str) -> Optional[str]:
    """Resolve agent runtime ARN by name using the Control Plane API.

    Args:
        agent_name: Agent name (e.g. 'Glitch').
        region: AWS region.

    Returns:
        Runtime ARN if found, None otherwise.
    """
    cache_key = f"{region}:{agent_name}"
    now = time.time()
    if cache_key in _runtime_arn_cache:
        arn, cached_at = _runtime_arn_cache[cache_key]
        if now - cached_at < _RUNTIME_ARN_CACHE_TTL:
            return arn
        del _runtime_arn_cache[cache_key]
    try:
        import boto3
        control = boto3.client("bedrock-agentcore-control", region_name=region)
        response = control.list_agent_runtimes(maxResults=50)
        for runtime in response.get("agentRuntimes", []):
            name = runtime.get("agentRuntimeName") or ""
            rid = runtime.get("agentRuntimeId") or ""
            arn = runtime.get("agentRuntimeArn") or ""
            if name == agent_name or rid.startswith(agent_name):
                _runtime_arn_cache[cache_key] = (arn, now)
                logger.info("Resolved runtime ARN for %s: %s", agent_name, arn[:80] + "..." if len(arn) > 80 else arn)
                return arn
        logger.warning("No agent runtime found for name=%s in region=%s", agent_name, region)
        return None
    except Exception as e:
        logger.warning("Failed to list agent runtimes: %s", e)
        return None


def invoke_deployed_agent(
    agent_name: str,
    region: str,
    payload: dict,
    session_id: Optional[str] = None,
    runtime_arn: Optional[str] = None,
) -> dict:
    """Invoke the deployed agent via boto3 and return the parsed response.

    Args:
        agent_name: Agent name (used to resolve ARN if runtime_arn not set).
        region: AWS region.
        payload: Invocation payload (e.g. {"prompt": "..."} or {"_ui_api_request": {...}}).
        session_id: Optional runtime session ID for conversation continuity.
        runtime_arn: Optional explicit runtime ARN; if not set, resolved from agent_name or env.

    Returns:
        Parsed response dict (e.g. {"message": "...", "metrics": {...}} or API response).
    """
    import os
    import boto3

    arn = runtime_arn or os.environ.get("GLITCH_AGENT_RUNTIME_ARN") or get_runtime_arn(agent_name, region)
    if not arn:
        return {"error": "Could not resolve agent runtime ARN"}

    payload_bytes = json.dumps(payload).encode("utf-8")
    client = boto3.client("bedrock-agentcore", region_name=region)

    kwargs = {
        "agentRuntimeArn": arn,
        "payload": payload_bytes,
        "contentType": "application/json",
        "accept": "application/json",
    }
    if session_id:
        kwargs["runtimeSessionId"] = session_id

    try:
        response = client.invoke_agent_runtime(**kwargs)
    except Exception as e:
        logger.exception("invoke_agent_runtime failed: %s", e)
        # Clear cache so next request re-resolves (e.g. after redeploy)
        cache_key = f"{region}:{agent_name}"
        _runtime_arn_cache.pop(cache_key, None)
        return {"error": str(e)}

    status = response.get("statusCode", 0)
    if status != 200:
        return {"error": f"Agent returned status {status}"}

    body = response.get("response")
    if body is None:
        return {"error": "Empty response from agent"}

    try:
        raw = body.read()
    finally:
        if hasattr(body, "close"):
            body.close()
    if not raw:
        return {"error": "Empty response body"}

    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        text = raw.decode("utf-8", errors="replace")
        # Fallback: try to extract JSON from CLI-style "Response: {...}"
        match = re.search(r"Response:\s*(\{[\s\S]*\})\s*$", text)
        if match:
            try:
                return json.loads(match.group(1))
            except json.JSONDecodeError:
                pass
        return {"error": "Invalid JSON response", "raw": text[:500]}


def create_api_proxy_payload(path: str, method: str, body: Any = None) -> dict:
    """Build the _ui_api_request payload for proxy API calls."""
    return {
        "_ui_api_request": {
            "path": path,
            "method": method.upper(),
            "body": body,
        }
    }


async def invoke_deployed_agent_async(
    agent_name: str,
    region: str,
    payload: dict,
    session_id: Optional[str] = None,
    runtime_arn: Optional[str] = None,
) -> dict:
    """Async wrapper for invoke_deployed_agent (runs sync boto3 call in executor)."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: invoke_deployed_agent(
            agent_name=agent_name,
            region=region,
            payload=payload,
            session_id=session_id,
            runtime_arn=runtime_arn,
        ),
    )
