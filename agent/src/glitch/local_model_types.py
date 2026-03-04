"""OpenAI Chat Completions–compatible types for local models (Mistral, LLaVA).

Follows https://platform.openai.com/docs/api-reference/chat (POST /v1/chat/completions).
Host mapping: 10.10.110.202 (mistral-nemo:12b), 10.10.110.137 (llava-v1.6-mistral-7b).
Port: 8080 for OpenAI-compatible server; 11434 for native Ollama.
"""

import os
from typing import Any, Dict, List, Optional, TypedDict, Union

# Host mapping (on-prem via proxy)
# AgentCore runs in PUBLIC network mode; on-prem IPs are not directly routable.
# Set GLITCH_OLLAMA_PROXY_HOST to a proxy that can reach the on-prem Ollama hosts.
MISTRAL_HOST = os.environ.get("GLITCH_OLLAMA_PROXY_HOST", "10.10.110.202")
LLAVA_HOST = os.environ.get("GLITCH_OLLAMA_PROXY_HOST", "10.10.110.137")
DEFAULT_OPENAI_PORT = 8080   # Nginx proxy port for LLaVA
OLLAMA_NATIVE_PORT = 11434   # Nginx proxy port for Mistral


class ImageUrlPart(TypedDict, total=False):
    url: str
    detail: str  # "auto" | "low" | "high"


class ContentPartText(TypedDict):
    type: str  # "text"
    text: str


class ContentPartImageUrl(TypedDict, total=False):
    type: str  # "image_url"
    image_url: ImageUrlPart


ContentPart = Union[ContentPartText, ContentPartImageUrl]

# Message content: string or array of content parts (for vision)
MessageContent = Union[str, List[ContentPart]]


class ChatMessage(TypedDict, total=False):
    role: str  # "system" | "user" | "assistant"
    content: MessageContent
    name: Optional[str]


class ChatCompletionRequest(TypedDict, total=False):
    """Request body for POST /v1/chat/completions (OpenAI spec)."""
    model: str
    messages: List[ChatMessage]
    temperature: float
    top_p: float
    max_tokens: int
    max_completion_tokens: int
    stream: bool
    stop: Union[str, List[str]]
    n: int
    presence_penalty: float
    frequency_penalty: float
    seed: int
    user: str
    prompt_cache_key: str
    response_format: Dict[str, Any]
    stream_options: Dict[str, Any]


class CompletionUsage(TypedDict, total=False):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChoiceMessage(TypedDict, total=False):
    role: str
    content: Optional[str]


class ChatCompletionChoice(TypedDict, total=False):
    index: int
    message: ChoiceMessage
    finish_reason: str  # "stop" | "length" | "tool_calls" | "content_filter" | ...


class ChatCompletionResponse(TypedDict, total=False):
    """Response from POST /v1/chat/completions (OpenAI spec)."""
    id: str
    object: str  # "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionChoice]
    usage: Optional[CompletionUsage]
