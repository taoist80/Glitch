"""Glitch agent invocation tool for Sentinel.

Allows Sentinel to call the Glitch agent via InvokeAgentRuntime for tasks that
require SSH/SSM access, Ollama, or other Glitch-owned tools.

Glitch runs the HTTP protocol (port 8080 / /invocations), so the payload is a
plain JSON prompt — not A2A JSON-RPC 2.0.

Uses the boto3 bedrock-agentcore client per:
https://docs.aws.amazon.com/boto3/latest/reference/services/bedrock-agentcore/client/invoke_agent_runtime.html
"""

import json
import logging
import os
import time
import uuid
from typing import Optional

from strands import tool

from sentinel.aws_utils import REGION, get_client

logger = logging.getLogger(__name__)

SSM_PARAM_GLITCH_ARN = "/glitch/sentinel/glitch-runtime-arn"
ARN_CACHE_TTL_SECONDS = 300  # 5 min — self-heals after agent redeploy

_glitch_runtime_arn: Optional[str] = None
_glitch_arn_fetched_at: float = 0.0


def _get_ssm_client():
    return get_client("ssm")


def _get_agentcore_client():
    return get_client("bedrock-agentcore")


def _get_glitch_arn(force_refresh: bool = False) -> str:
    """Return Glitch runtime ARN, refreshing from SSM if TTL has expired."""
    global _glitch_runtime_arn, _glitch_arn_fetched_at
    now = time.monotonic()
    if not force_refresh and _glitch_runtime_arn and (now - _glitch_arn_fetched_at) < ARN_CACHE_TTL_SECONDS:
        return _glitch_runtime_arn
    arn = os.environ.get("GLITCH_RUNTIME_ARN")
    if not arn:
        try:
            resp = _get_ssm_client().get_parameter(Name=SSM_PARAM_GLITCH_ARN)
            arn = resp["Parameter"]["Value"].strip()
        except Exception as e:
            raise RuntimeError(f"Could not determine Glitch runtime ARN: {e}") from e
    _glitch_runtime_arn = arn
    _glitch_arn_fetched_at = now
    return arn


def _invoke_via_boto3(arn: str, payload: bytes, session_id: str) -> str:
    """Invoke AgentRuntime using the boto3 bedrock-agentcore client.

    Per AWS docs, the response is a streaming EventStream. We collect all chunks
    and decode. The runtimeSessionId parameter maintains conversation context.
    """
    client = _get_agentcore_client()
    response = client.invoke_agent_runtime(
        agentRuntimeArn=arn,
        runtimeSessionId=session_id,
        payload=payload,
        contentType="application/json",
        accept="application/json",
    )
    chunks = []
    for chunk in response.get("response", []):
        if isinstance(chunk, (bytes, bytearray)):
            chunks.append(chunk.decode("utf-8"))
        else:
            chunks.append(str(chunk))
    return "".join(chunks)


def _invoke_with_retry(payload: bytes, session_id: str) -> str:
    """Invoke Glitch with automatic cache-bust on stale ARN.

    On ResourceNotFoundException the cached ARN is cleared and re-resolved from
    SSM before one retry — this covers the rare case where Glitch's runtime ARN
    changes (ARNs are stable across UpdateAgentRuntime, but this adds resilience).
    """
    arn = _get_glitch_arn()
    try:
        return _invoke_via_boto3(arn, payload, session_id)
    except Exception as e:
        err_str = str(e)
        if "ResourceNotFoundException" in err_str or "ResourceNotFound" in err_str:
            logger.warning("Glitch ARN may be stale (%s); refreshing and retrying once", err_str)
            arn = _get_glitch_arn(force_refresh=True)
            return _invoke_via_boto3(arn, payload, session_id)
        raise


@tool
async def invoke_glitch_agent(prompt: str, session_id: Optional[str] = None) -> str:
    """Send a task to the Glitch agent and return its response.

    Use this when a remediation task requires Glitch's capabilities: SSH access
    to remote hosts, Ollama vision analysis, or other tools Glitch owns.

    Args:
        prompt: The task description for Glitch. Be specific about what you need done
                and what output format you expect back.
        session_id: Optional session ID for conversation continuity. If omitted,
                    a unique UUID session is created for this request.

    Returns:
        Glitch's response as a string.
    """
    import asyncio

    sid = session_id if session_id else f"sentinel-glitch-{uuid.uuid4()}"

    try:
        # Glitch runs HTTP protocol — payload is a plain JSON prompt object.
        payload = json.dumps({"prompt": prompt}).encode("utf-8")

        loop = asyncio.get_event_loop()
        response_text = await asyncio.wait_for(
            loop.run_in_executor(None, _invoke_with_retry, payload, sid),
            timeout=115,
        )

        try:
            data = json.loads(response_text)
            if isinstance(data, dict):
                return data.get("output", data.get("content", response_text))
        except json.JSONDecodeError:
            return response_text

    except RuntimeError as e:
        return f"Glitch agent ARN not configured. Error: {e}"
    except Exception as e:
        logger.error("invoke_glitch_agent failed: %s", e)
        return f"Error invoking Glitch agent: {e}"
