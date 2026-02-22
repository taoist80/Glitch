"""Mistral chat agent — one per process, session-keyed conversation buffer.

Backend: 10.10.110.202, model mistral-nemo-12b.
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

DEFAULT_MISTRAL_MODEL = "mistral-nemo-12b"
ENV_MISTRAL_MODEL = "GLITCH_MISTRAL_OLLAMA_MODEL"
ENV_USE_OPENAI_FORMAT = "GLITCH_MISTRAL_OPENAI_FORMAT"  # "1" or "true" to use port 8080
DEFAULT_SYSTEM_PROMPT = "You are a helpful assistant. Be concise and accurate."


class MistralAgent:
    """Chat agent backed by Mistral (mistral-nemo-12b) at 10.10.110.202.

    Option A: one agent per process; conversation history keyed by session_id.
    """

    def __init__(
        self,
        host: str = MISTRAL_HOST,
        port: Optional[int] = None,
        model: Optional[str] = None,
        use_openai_format: Optional[bool] = None,
        timeout: float = 120.0,
    ):
        self.host = host
        self.model = model or os.getenv(ENV_MISTRAL_MODEL) or DEFAULT_MISTRAL_MODEL
        if port is not None:
            self.port = port
        elif use_openai_format is not False and os.getenv(ENV_USE_OPENAI_FORMAT, "").lower() in ("1", "true"):
            self.port = DEFAULT_OPENAI_PORT
        else:
            # Default: try OpenAI format first (8080); caller can override port to 11434 for Ollama native
            self.port = DEFAULT_OPENAI_PORT
        self.timeout = timeout
        self._buffer: Dict[str, List[ChatMessage]] = {}
        logger.info(
            "Created agent",
            extra={"agent_id": "mistral", "model": self.model, "host": host, "port": self.port},
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
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(self._openai_url(), json=payload)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                logger.warning("OpenAI-format request failed (status %s), trying Ollama native", e.response.status_code)
                return await self._call_ollama_native(messages, session_id)
            except Exception as e:
                logger.warning("OpenAI-format request failed: %s, trying Ollama native", e)
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
        # Build a single prompt from messages for /api/generate
        parts: List[str] = []
        for m in messages:
            role = m.get("role", "user")
            content = m.get("content")
            if isinstance(content, str):
                parts.append(f"({role})\n{content}")
            else:
                parts.append(f"({role})\n[non-text content omitted]")
        prompt = "\n\n".join(parts)
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
        }
        ollama_url = f"http://{self.host}:{OLLAMA_NATIVE_PORT}/api/generate"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(ollama_url, json=payload)
                resp.raise_for_status()
            except Exception as e:
                logger.error("Mistral Ollama native request failed: %s", e, extra={"agent_id": "mistral", "session_id": session_id})
                return create_error_response(f"Mistral request failed: {e}", session_id=session_id)
        data = resp.json()
        content = data.get("response", "")
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
    ) -> InvocationResponse:
        sid = session_id or "default"
        messages = self._get_messages(sid, prompt, system_prompt=system_prompt or DEFAULT_SYSTEM_PROMPT)
        result = await self._call_openai_format(messages, sid)
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
