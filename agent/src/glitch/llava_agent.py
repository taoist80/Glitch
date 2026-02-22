"""LLaVA vision agent — one per process; image processing (llava-v1.6-mistral-7b).

Backend: 10.10.110.137. Prefer OpenAI-format /v1/chat/completions (port 8080);
fallback Ollama native (port 11434) with /api/generate and images.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Union

import httpx

from glitch.local_model_types import (
    LLAVA_HOST,
    DEFAULT_OPENAI_PORT,
    OLLAMA_NATIVE_PORT,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatMessage,
    ContentPart,
)
from glitch.types import InvocationResponse, create_error_response

logger = logging.getLogger(__name__)

DEFAULT_LLAVA_MODEL = "llava-v1.6-mistral-7b"
ENV_LLAVA_MODEL = "GLITCH_LLAVA_OLLAMA_MODEL"
ENV_USE_OPENAI_FORMAT = "GLITCH_LLAVA_OPENAI_FORMAT"


class LLaVAAgent:
    """Vision agent backed by LLaVA (llava-v1.6-mistral-7b) at 10.10.110.137."""

    def __init__(
        self,
        host: str = LLAVA_HOST,
        port: Optional[int] = None,
        model: Optional[str] = None,
        use_openai_format: Optional[bool] = None,
        timeout: float = 120.0,
    ):
        self.host = host
        self.model = model or os.getenv(ENV_LLAVA_MODEL) or DEFAULT_LLAVA_MODEL
        self.port = port if port is not None else DEFAULT_OPENAI_PORT
        if use_openai_format is not False and os.getenv(ENV_USE_OPENAI_FORMAT, "").lower() in ("1", "true"):
            self.port = DEFAULT_OPENAI_PORT
        self.timeout = timeout
        logger.info(
            "Created agent",
            extra={"agent_id": "llava", "model": self.model, "host": host, "port": self.port},
        )

    def _openai_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1/chat/completions"

    def _build_messages(
        self,
        prompt: str,
        image_urls: Optional[List[str]] = None,
    ) -> List[ChatMessage]:
        if not image_urls or len(image_urls) == 0:
            return [ChatMessage(role="user", content=prompt)]
        parts: List[ContentPart] = []
        for url in image_urls:
            parts.append({"type": "image_url", "image_url": {"url": url, "detail": "auto"}})
        parts.append({"type": "text", "text": prompt})
        return [ChatMessage(role="user", content=parts)]

    async def _call_openai_format(self, messages: List[ChatMessage], session_id: str) -> InvocationResponse:
        payload: ChatCompletionRequest = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 1024,
            "temperature": 0.5,
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(self._openai_url(), json=payload)
                resp.raise_for_status()
            except (httpx.HTTPStatusError, Exception) as e:
                logger.warning("LLaVA OpenAI-format request failed: %s, trying Ollama native", e)
                return await self._call_ollama_native(messages, session_id)
        data: ChatCompletionResponse = resp.json()
        choices = data.get("choices") or []
        if not choices:
            return create_error_response("No choices in LLaVA response", session_id=session_id)
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
        # Extract text and image URLs for Ollama /api/generate
        prompt_text = ""
        images: List[str] = []
        for m in messages:
            content = m.get("content")
            if isinstance(content, str):
                prompt_text = content
                break
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "text":
                            prompt_text = part.get("text", "")
                        elif part.get("type") == "image_url":
                            url = (part.get("image_url") or {}).get("url")
                            if url:
                                images.append(url)
        if not prompt_text:
            prompt_text = "Describe the image(s)."
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt_text,
            "stream": False,
        }
        if images:
            payload["images"] = images
        ollama_url = f"http://{self.host}:{OLLAMA_NATIVE_PORT}/api/generate"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(ollama_url, json=payload)
                resp.raise_for_status()
            except Exception as e:
                logger.error(
                    "LLaVA Ollama native request failed: %s",
                    e,
                    extra={"agent_id": "llava", "session_id": session_id},
                )
                return create_error_response(f"LLaVA request failed: {e}", session_id=session_id)
        data = resp.json()
        content = data.get("response", "")
        return InvocationResponse(
            message=content or "No response from LLaVA",
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
        image_urls: Optional[List[str]] = None,
        system_prompt: Optional[str] = None,
    ) -> InvocationResponse:
        sid = session_id or "default"
        messages = self._build_messages(prompt, image_urls=image_urls)
        if system_prompt and system_prompt.strip():
            messages = [ChatMessage(role="system", content=system_prompt.strip())] + messages
        return await self._call_openai_format(messages, sid)

    def get_status(self) -> Dict[str, Any]:
        return {
            "agent": "llava",
            "model": self.model,
            "session_id": None,
            "host": self.host,
            "port": self.port,
        }
