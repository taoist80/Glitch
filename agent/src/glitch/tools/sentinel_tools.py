"""Sentinel agent invocation tool for Glitch.

Allows Glitch to call the Sentinel agent via InvokeAgentRuntime for operational
queries: log analysis, network status, security events, infrastructure health,
and incident response delegation.

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

from glitch.aws_utils import REGION, get_client
from glitch.tools.a2a_types import build_a2a_request, extract_a2a_text

logger = logging.getLogger(__name__)

SSM_PARAM_SENTINEL_ARN = "/glitch/sentinel/runtime-arn"
ARN_CACHE_TTL_SECONDS = 300  # 5 min — self-heals after agent redeploy

_sentinel_runtime_arn: Optional[str] = None
_sentinel_arn_fetched_at: float = 0.0


def _get_ssm_client():
    return get_client("ssm")


def _get_agentcore_client():
    return get_client("bedrock-agentcore")


def _get_sentinel_arn(force_refresh: bool = False) -> str:
    """Return Sentinel runtime ARN, refreshing from SSM if TTL has expired."""
    global _sentinel_runtime_arn, _sentinel_arn_fetched_at
    now = time.monotonic()
    if not force_refresh and _sentinel_runtime_arn and (now - _sentinel_arn_fetched_at) < ARN_CACHE_TTL_SECONDS:
        return _sentinel_runtime_arn
    arn = os.environ.get("SENTINEL_RUNTIME_ARN")
    if not arn:
        try:
            resp = _get_ssm_client().get_parameter(Name=SSM_PARAM_SENTINEL_ARN)
            arn = resp["Parameter"]["Value"].strip()
        except Exception as e:
            raise RuntimeError(f"Could not determine Sentinel runtime ARN: {e}") from e
    _sentinel_runtime_arn = arn
    _sentinel_arn_fetched_at = now
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


_COLD_START_DELAYS = [5, 10, 20, 30]  # seconds; 424 = runtime is starting up


def _invoke_with_retry(payload: bytes, session_id: str) -> str:
    """Invoke Sentinel with automatic cache-bust on stale ARN and cold-start retry.

    On ResourceNotFoundException the cached ARN is cleared and re-resolved from
    SSM before one retry — this covers the case where Sentinel is redeployed and
    gets a new runtime ARN (though ARNs are stable across UpdateAgentRuntime).

    On HTTP 424 (runtime is cold-starting) we wait with backoff and retry up to
    len(_COLD_START_DELAYS) times before giving up.
    """
    arn = _get_sentinel_arn()
    for attempt, delay in enumerate([0] + _COLD_START_DELAYS):
        if delay:
            logger.info(
                "Sentinel cold-start detected — waiting %ds before retry (attempt %d)",
                delay, attempt,
            )
            time.sleep(delay)
        try:
            return _invoke_via_boto3(arn, payload, session_id)
        except Exception as e:
            err_str = str(e)
            if "ResourceNotFoundException" in err_str or "ResourceNotFound" in err_str:
                logger.warning("Sentinel ARN may be stale (%s); refreshing and retrying once", err_str)
                arn = _get_sentinel_arn(force_refresh=True)
                return _invoke_via_boto3(arn, payload, session_id)
            # RuntimeClientError (HTTP 424) = runtime is cold-starting — retry
            if "RuntimeClientError" in err_str or (
                hasattr(e, "response")
                and e.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 424
            ):
                if attempt < len(_COLD_START_DELAYS):
                    continue
            raise


@tool
async def invoke_sentinel(query: str, session_id: Optional[str] = None) -> str:
    """Send an operational query to the Sentinel agent and return its response.

    Use this to delegate operational tasks to Sentinel: log analysis, security
    monitoring, network status, infrastructure health, incident response, and
    anything Sentinel owns (UniFi Protect/Network, Pi-hole, CloudWatch, GitHub).

    Args:
        query: What you need Sentinel to do or investigate. Be specific.
               Examples:
               - "Scan all log groups for errors in the last 3 hours"
               - "Check if there are any UniFi alerts or network anomalies"
               - "What is the current CloudFormation stack status?"
               - "Is there suspicious DNS activity on the network?"
        session_id: Optional session ID for continuity. If omitted, defaults to
                    a stable shared ID so all calls route to the same container
                    (prevents multi-container auth stampedes on the UDM-Pro).

    Returns:
        JSON with keys: status ("ok" | "error"), response (Sentinel's answer),
        session_id (for follow-up calls), and latency_ms.
    """
    import asyncio
    import time as _time

    # Stable session ID routes all calls to the same Sentinel container.
    # Must be >= 33 characters per InvokeAgentRuntime API contract.
    sid = session_id if session_id else "glitch-sentinel-main-session-fixed"
    t0 = _time.monotonic()

    try:
        a2a_payload = build_a2a_request(
            query=query,
            request_id=str(uuid.uuid4()),
            message_id=str(uuid.uuid4()),
        )
        payload = json.dumps(a2a_payload).encode("utf-8")

        loop = asyncio.get_event_loop()
        response_text = await asyncio.wait_for(
            loop.run_in_executor(None, _invoke_with_retry, payload, sid),
            timeout=115,
        )

        latency_ms = int((_time.monotonic() - t0) * 1000)

        try:
            data = json.loads(response_text)
            text = extract_a2a_text(data)
            response_str = text if text is not None else response_text
        except json.JSONDecodeError:
            response_str = response_text

        return json.dumps({
            "status": "ok",
            "response": response_str,
            "session_id": sid,
            "latency_ms": latency_ms,
        })

    except RuntimeError as e:
        return json.dumps({
            "status": "error",
            "error": f"Sentinel ARN not configured: {e}",
            "session_id": sid,
        })
    except Exception as e:
        logger.error("invoke_sentinel failed: %s", e)
        return json.dumps({
            "status": "error",
            "error": str(e),
            "session_id": sid,
        })
