"""Mistral chat agent — one per process, session-keyed conversation buffer.

Backend: 10.10.110.202, model mistral-nemo:12b.
Prefer OpenAI-format /v1/chat/completions (port 8080); fallback Ollama native (port 11434).
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from glitch.local_model_types import (
    MISTRAL_HOST,
    DEFAULT_OPENAI_PORT,
    OLLAMA_NATIVE_PORT,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
)
from glitch.types import InvocationResponse, create_error_response

logger = logging.getLogger(__name__)

DEFAULT_MISTRAL_MODEL = "mistral-nemo:12b"
ENV_MISTRAL_MODEL = "GLITCH_MISTRAL_OLLAMA_MODEL"
ENV_USE_OPENAI_FORMAT = "GLITCH_MISTRAL_OPENAI_FORMAT"  # "1" or "true" to use port 8080
ENV_MISTRAL_TIMEOUT = "GLITCH_MISTRAL_TIMEOUT"  # seconds for request (connect + read); default 180
DEFAULT_MISTRAL_TIMEOUT = 180.0
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Be concise and accurate."

_SOUL_CACHE: Optional[str] = None


def _load_soul_system_prompt() -> str:
    """Load SOUL.md as the system prompt for Mistral, cached after first load.

    Tries S3 (if GLITCH_SOUL_S3_BUCKET is set), then /app/SOUL.md (container),
    then the local source-tree SOUL.md. Falls back to DEFAULT_SYSTEM_PROMPT.
    """
    global _SOUL_CACHE
    if _SOUL_CACHE is not None:
        return _SOUL_CACHE

    # Try the canonical load_soul() helper first (handles S3 + all local paths)
    try:
        from glitch.agent import load_soul
        soul = load_soul()
        if soul and soul.strip():
            logger.info("Mistral: loaded SOUL.md via load_soul() (%d chars)", len(soul))
            _SOUL_CACHE = soul.strip()
            return _SOUL_CACHE
    except Exception as e:
        logger.warning("Mistral: load_soul() failed (%s: %s), trying direct file paths", type(e).__name__, e)

    # Direct fallback: try known container and source-tree paths
    from pathlib import Path
    candidates = [
        Path("/app/SOUL.md"),
        Path(__file__).parent.parent.parent / "SOUL.md",
        Path.home() / "SOUL.md",
    ]
    for p in candidates:
        try:
            if p.exists():
                soul = p.read_text(encoding="utf-8").strip()
                if soul:
                    logger.info("Mistral: loaded SOUL.md from %s (%d chars)", p, len(soul))
                    _SOUL_CACHE = soul
                    return _SOUL_CACHE
        except Exception as e:
            logger.warning("Mistral: could not read %s: %s", p, e)

    logger.warning("Mistral: SOUL.md not found on any path, using DEFAULT_SYSTEM_PROMPT")
    _SOUL_CACHE = DEFAULT_SYSTEM_PROMPT
    return _SOUL_CACHE


class MistralAgent:
    """Chat agent backed by Mistral (mistral-nemo:12b) at 10.10.110.202.

    Option A: one agent per process; conversation history keyed by session_id.
    """

    def __init__(
        self,
        host: str = MISTRAL_HOST,
        port: Optional[int] = None,
        model: Optional[str] = None,
        use_openai_format: Optional[bool] = None,
        timeout: Optional[float] = None,
    ):
        self.host = host
        self.model = model or os.getenv(ENV_MISTRAL_MODEL) or DEFAULT_MISTRAL_MODEL
        # Mistral host (10.10.110.202) only has Ollama native API on port 11434
        # (no OpenAI-compatible endpoint on port 8080 like LLaVA has)
        self.port = port if port is not None else OLLAMA_NATIVE_PORT
        _t = os.getenv(ENV_MISTRAL_TIMEOUT)
        self.timeout = float(_t) if _t is not None and _t.strip() else (timeout if timeout is not None else DEFAULT_MISTRAL_TIMEOUT)
        self._buffer: Dict[str, List[ChatMessage]] = {}
        base_url = f"http://{self.host}:{self.port}"
        proxy_env = os.environ.get("GLITCH_OLLAMA_PROXY_HOST", "")
        logger.info(
            "Mistral endpoint: %s (GLITCH_OLLAMA_PROXY_HOST=%s)",
            base_url,
            proxy_env if proxy_env else "(not set, using default)",
            extra={"agent_id": "mistral", "model": self.model, "host": self.host, "port": self.port, "url": base_url},
        )

    def _base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def _openai_url(self) -> str:
        return f"{self._base_url()}/v1/chat/completions"

    def _get_messages(self, session_id: str, user_message: str, system_prompt: Optional[str] = None) -> List[ChatMessage]:
        turns = self._buffer.get(session_id, [])
        messages: List[ChatMessage] = []
        if system_prompt and system_prompt.strip():
            messages.append(ChatMessage(role="system", content=system_prompt.strip()))
        for t in turns:
            messages.append(t)
        messages.append(ChatMessage(role="user", content=user_message))
        return messages

    def _append_turn(self, session_id: str, user_message: str, assistant_message: str) -> None:
        if session_id not in self._buffer:
            self._buffer[session_id] = []
        self._buffer[session_id].append(ChatMessage(role="user", content=user_message))
        self._buffer[session_id].append(ChatMessage(role="assistant", content=assistant_message))

    async def _call_openai_format(
        self,
        messages: List[ChatMessage],
        session_id: str,
    ) -> InvocationResponse:
        payload: ChatCompletionRequest = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2048,
            "temperature": 0.7,
        }
        url = self._openai_url()
        logger.info("Mistral OpenAI-format request starting: %s", url)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                logger.info("Mistral OpenAI-format request succeeded")
            except httpx.HTTPStatusError as e:
                logger.warning("OpenAI-format request failed (status %s), trying Ollama native", e.response.status_code)
                return await self._call_ollama_native(messages, session_id)
            except httpx.TimeoutException as e:
                logger.error("Mistral OpenAI-format TIMEOUT after %ss connecting to %s: %s", self.timeout, url, e, exc_info=True)
                return await self._call_ollama_native(messages, session_id)
            except httpx.ConnectError as e:
                logger.error("Mistral OpenAI-format CONNECT ERROR to %s: %s", url, e, exc_info=True)
                return await self._call_ollama_native(messages, session_id)
            except Exception as e:
                logger.error("Mistral OpenAI-format request failed: %s (type: %s)", e, type(e).__name__, exc_info=True)
                return await self._call_ollama_native(messages, session_id)
        data: ChatCompletionResponse = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return create_error_response("No choices in Mistral response", session_id=session_id)
        content = (choices[0].get("message") or {}).get("content") or ""
        usage = data.get("usage")
        return InvocationResponse(
            message=content,
            session_id=session_id,
            memory_id="",
            metrics={
                "duration_seconds": 0,
                "token_usage": {
                    "input_tokens": (usage or {}).get("prompt_tokens", 0),
                    "output_tokens": (usage or {}).get("completion_tokens", 0),
                    "total_tokens": (usage or {}).get("total_tokens", 0),
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "cycle_count": 1,
                "latency_ms": 0,
                "stop_reason": (choices[0].get("finish_reason") or "stop"),
                "tool_usage": {},
            },
        )

    async def _call_ollama_native(
        self,
        messages: List[ChatMessage],
        session_id: str,
    ) -> InvocationResponse:
        # Use Ollama's native /api/chat endpoint which accepts messages array
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        ollama_url = f"http://{self.host}:{OLLAMA_NATIVE_PORT}/api/chat"
        logger.info("Mistral Ollama native request starting: %s (model: %s)", ollama_url, self.model)
        # Set explicit timeouts: 30s to establish connection, 120s total for response
        timeout = httpx.Timeout(timeout=self.timeout, connect=30.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            try:
                resp = await client.post(ollama_url, json=payload)
                resp.raise_for_status()
                logger.info("Mistral Ollama native request succeeded")
            except httpx.TimeoutException as e:
                logger.error("Mistral Ollama native TIMEOUT after %ss connecting to %s: %s", self.timeout, ollama_url, str(e), exc_info=True)
                return create_error_response(f"Mistral request timed out after {self.timeout}s: {e}", session_id=session_id)
            except httpx.ConnectError as e:
                logger.error("Mistral Ollama native CONNECT ERROR to %s: %s", ollama_url, str(e), exc_info=True)
                return create_error_response(f"Cannot connect to Mistral at {ollama_url}: {e}", session_id=session_id)
            except httpx.HTTPStatusError as e:
                logger.error("Mistral Ollama native HTTP ERROR %s: %s", e.response.status_code, str(e), exc_info=True)
                return create_error_response(f"Mistral HTTP error {e.response.status_code}: {e.response.text[:200]}", session_id=session_id)
            except Exception as e:
                logger.error("Mistral Ollama native request failed: %s (type: %s)", str(e), type(e).__name__, exc_info=True)
                return create_error_response(f"Mistral request failed: {type(e).__name__}: {e}", session_id=session_id)
        data = resp.json()
        message = data.get("message", {})
        content = message.get("content", "")
        return InvocationResponse(
            message=content or "No response from Mistral",
            session_id=session_id,
            memory_id="",
            metrics={
                "duration_seconds": 0,
                "token_usage": {
                    "input_tokens": data.get("prompt_eval_count", 0),
                    "output_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                },
                "cycle_count": 1,
                "latency_ms": 0,
                "stop_reason": "stop",
                "tool_usage": {},
            },
        )

    async def process_message(
        self,
        prompt: str,
        session_id: Optional[str] = None,
        system_prompt: Optional[str] = None,
        **kwargs: Any,
    ) -> InvocationResponse:
        sid = session_id or "default"
        # Use caller-supplied system_prompt, then SOUL.md, then hardcoded default
        effective_system = system_prompt or _load_soul_system_prompt()
        messages = self._get_messages(sid, prompt, system_prompt=effective_system)
        # Use Ollama's native /api/chat endpoint (port 11434)
        result = await self._call_ollama_native(messages, sid)
        if "error" not in result and result.get("message"):
            self._append_turn(sid, prompt, result["message"])
        return result

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "mistral",
            "model": self.model,
            "session_id": None,
            "host": self.host,
            "port": self.port,
        }
