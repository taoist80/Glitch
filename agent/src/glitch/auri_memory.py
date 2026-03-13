"""Auri vector memory — Bedrock Titan Embed + protect-query Lambda bridge.

The AgentCore runtime runs in PUBLIC mode (no VPC), so it cannot reach the private
RDS subnet directly. Instead:
  1. Embeddings are generated here via Bedrock (public endpoint, works fine).
  2. The pre-computed embedding is sent to the protect-query Lambda via
     lambda:InvokeFunction (AWS API — not VPC-restricted). That Lambda lives in the
     VPC and handles the actual INSERT/SELECT against RDS.

Usage:
    # Store a memory (async):
    await store_memory(None, "Arc prefers gentle teasing in the morning.", source="agent")

    # Retrieve relevant memories (async):
    memories = await retrieve_memories(None, "What time of day does Arc like teasing?", k=8)

The `pool` parameter is kept in signatures for API compatibility but is unused.
"""

import asyncio
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

EMBED_MODEL = "amazon.titan-embed-text-v2:0"
EMBED_DIMS = 1024

# Name of the Lambda that has VPC access to RDS (protect-query is already in the VPC).
_AURI_LAMBDA = os.environ.get("GLITCH_PROTECT_QUERY_LAMBDA", "glitch-protect-query")


def embed_text(text: str) -> list:
    """Synchronous. Call Bedrock Titan Embed Text v2, return 1024-dim unit vector."""
    from glitch.aws_utils import get_client

    client = get_client("bedrock-runtime")
    body = json.dumps({"inputText": text, "dimensions": EMBED_DIMS, "normalize": True})
    resp = client.invoke_model(
        modelId=EMBED_MODEL,
        body=body,
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(resp["body"].read())["embedding"]


def _invoke_auri_lambda(action: str, payload: dict) -> dict:
    """Synchronous. Invoke protect-query Lambda with an action payload."""
    from glitch.aws_utils import get_client

    client = get_client("lambda")
    event = {"action": action, **payload}
    resp = client.invoke(
        FunctionName=_AURI_LAMBDA,
        InvocationType="RequestResponse",
        Payload=json.dumps(event).encode(),
    )
    return json.loads(resp["Payload"].read())


async def store_memory(
    pool,
    content: str,
    session_id: str = "",
    source: str = "agent",
    metadata: Optional[dict] = None,
) -> None:
    """Embed content via Bedrock, then store via protect-query Lambda (VPC bridge).

    Args:
        pool:       Unused (kept for API compatibility). Pass None.
        content:    The text to remember (1-3 self-contained sentences work best).
        session_id: Optional session tag (e.g. 'telegram:dm:123').
        source:     'agent' | 'user' | 'auto'
        metadata:   Optional JSON metadata dict.
    """
    embedding = await asyncio.to_thread(embed_text, content)
    result = await asyncio.to_thread(
        _invoke_auri_lambda,
        "auri_memory_store",
        {
            "content": content,
            "embedding": embedding,
            "session_id": session_id or "",
            "source": source,
            "metadata": metadata or {},
        },
    )
    if result.get("statusCode", 200) >= 400:
        raise RuntimeError(f"auri_memory_store error: {result.get('error', result)}")
    logger.info("auri_memory: stored memory (source=%s, len=%d)", source, len(content))


async def retrieve_memories(pool, query_text: str, k: int = 8) -> list:
    """Embed query via Bedrock, then search via protect-query Lambda (VPC bridge).

    Args:
        pool:       Unused (kept for API compatibility). Pass None.
        query_text: Natural-language query to embed and search.
        k:          Number of results to return.

    Returns:
        List of content strings ordered by cosine similarity (closest first).
    """
    embedding = await asyncio.to_thread(embed_text, query_text)
    result = await asyncio.to_thread(
        _invoke_auri_lambda,
        "auri_memory_search",
        {"embedding": embedding, "k": k},
    )
    if result.get("statusCode", 200) >= 400:
        raise RuntimeError(f"auri_memory_search error: {result.get('error', result)}")
    return result.get("memories", [])


async def store_participant_profile(participant_id: str, content: str) -> None:
    """Upsert a participant profile (replaces any existing profile for this participant).

    Args:
        participant_id: Unique ID for the participant (e.g. 'arc', 'user123').
        content:        Profile text describing preferences, personality, etc.
    """
    participant_id = participant_id.strip().lower()
    embedding = await asyncio.to_thread(embed_text, content)
    result = await asyncio.to_thread(
        _invoke_auri_lambda,
        "auri_participant_upsert",
        {
            "participant_id": participant_id,
            "content": content,
            "embedding": embedding,
        },
    )
    if result.get("statusCode", 200) >= 400:
        raise RuntimeError(f"auri_participant_upsert error: {result.get('error', result)}")
    logger.info("auri_memory: upserted participant profile for %s", participant_id)


async def retrieve_participant_profiles(
    participant_ids: list, query_text: str = "", k: int = 3
) -> list:
    """Retrieve participant profiles by ID using filtered vector search.

    Args:
        participant_ids: List of participant IDs to retrieve profiles for.
        query_text:      Optional query for relevance ranking (defaults to participant_ids joined).
        k:               Max results per participant.

    Returns:
        List of profile content strings.
    """
    if not participant_ids:
        return []
    participant_ids = [p.strip().lower() for p in participant_ids]
    search_text = query_text or " ".join(participant_ids)
    embedding = await asyncio.to_thread(embed_text, search_text)
    profiles = []
    for pid in participant_ids:
        result = await asyncio.to_thread(
            _invoke_auri_lambda,
            "auri_memory_search_filtered",
            {
                "embedding": embedding,
                "k": k,
                "memory_type": "participant_profile",
                "participant_id": pid,
            },
        )
        if result.get("statusCode", 200) >= 400:
            logger.warning("auri_memory: filtered search error for %s: %s", pid, result.get("error"))
            continue
        for mem in result.get("memories", []):
            content = mem.get("content", mem) if isinstance(mem, dict) else mem
            if content:
                profiles.append(content)
    return profiles
