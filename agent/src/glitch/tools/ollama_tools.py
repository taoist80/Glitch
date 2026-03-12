"""Ollama integration tools for local model execution via on-prem hosts.

Dataflow:
    Tool Call -> httpx.AsyncClient -> Ollama API -> Response String

These tools connect to on-premises Ollama instances (via GLITCH_OLLAMA_PROXY_HOST
when set, or direct IP when reachable), enabling local model execution for cost
savings and privacy.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict, cast

import httpx
from strands import tool

logger = logging.getLogger(__name__)

# CloudWatch Logs stream for ollama health debugging (reuses telemetry log group)
_OLLAMA_CW_SEQUENCE_TOKENS: Dict[str, str] = {}
_OLLAMA_CW_LOG_GROUP = os.environ.get("GLITCH_TELEMETRY_LOG_GROUP", "/glitch/telemetry")


def _ollama_timeout() -> float:
    """Timeout for Ollama requests (connect + read). Env GLITCH_OLLAMA_TIMEOUT, default 180."""
    v = os.environ.get("GLITCH_OLLAMA_TIMEOUT", "").strip()
    if v:
        try:
            return float(v)
        except ValueError:
            pass
    return 180.0


def _ollama_proxy_host() -> Optional[str]:
    """When set, route Ollama requests through this proxy to reach on-prem hosts."""
    v = os.environ.get("GLITCH_OLLAMA_PROXY_HOST", "").strip()
    return v or None


def _ollama_api_key() -> Optional[str]:
    """API key for nginx proxy auth. Set via GLITCH_OLLAMA_API_KEY env var."""
    v = os.environ.get("GLITCH_OLLAMA_API_KEY", "").strip()
    return v or None


def _ollama_headers() -> dict:
    """Base headers for all Ollama requests. Includes X-Api-Key when proxy auth is configured."""
    headers: dict = {"Content-Type": "application/json"}
    key = _ollama_api_key()
    if key:
        headers["X-Api-Key"] = key
    return headers


def _ollama_chat_host() -> str:
    """Chat endpoint: proxy host (port 11434) or direct 10.10.110.202."""
    return _ollama_proxy_host() or "10.10.110.202"


def _ollama_vision_host() -> str:
    """Vision endpoint: proxy host (port 18080) or direct 10.10.110.137."""
    return _ollama_proxy_host() or "10.10.110.137"


@dataclass(frozen=True)
class OllamaConfig:
    """Configuration for Ollama / local model endpoints.

    When GLITCH_OLLAMA_PROXY_HOST is set, chat_host and vision_host both use the proxy;
    the proxy listens on 11434 (Mistral/Chat) and 18080 (LLaVA/Vision, WAN-safe port).
    When unset, direct on-prem IPs are used (requires network reachability).
    """
    chat_host: str = "10.10.110.202"
    vision_host: str = "10.10.110.137"
    port: int = 11434
    vision_port: int = 18080
    timeout: float = 180.0


def _get_config() -> OllamaConfig:
    """Build OllamaConfig at call time so env var changes after import are respected."""
    return OllamaConfig(
        chat_host=_ollama_chat_host(),
        vision_host=_ollama_vision_host(),
        timeout=_ollama_timeout(),
    )


class OllamaGeneratePayload(TypedDict, total=False):
    """Payload for Ollama /api/generate endpoint."""
    model: str
    prompt: str
    images: List[str]
    stream: bool
    options: dict


class OllamaGenerateResponse(TypedDict, total=False):
    """Response from Ollama /api/generate endpoint."""
    model: str
    response: str
    done: bool
    context: List[int]
    total_duration: int
    load_duration: int
    prompt_eval_count: int
    eval_count: int


class OllamaModelInfo(TypedDict, total=False):
    """Model information from Ollama /api/tags endpoint."""
    name: str
    modified_at: str
    size: int


class OllamaTagsResponse(TypedDict, total=False):
    """Response from Ollama /api/tags endpoint."""
    models: List[OllamaModelInfo]


class OpenAIModelEntry(TypedDict, total=False):
    """One model entry in OpenAI-compatible GET /v1/models response."""
    id: str
    name: str
    object: str
    created: int
    owned_by: str


class OpenAIModelsResponse(TypedDict, total=False):
    """Response from OpenAI-compatible GET /v1/models endpoint (e.g. vision host on 8080)."""
    object: str
    data: List[OpenAIModelEntry]
    models: List[OpenAIModelEntry]


@dataclass
class HealthCheckResult:
    """Result of an Ollama health check.

    Attributes:
        name: Endpoint name (Chat, Vision)
        host: IP address
        healthy: Whether endpoint is reachable
        models: List of available models (if healthy)
        missing_models: Expected models not found in the model list
        latency_ms: Round-trip latency in milliseconds (None if check failed)
        error: Error message (if unhealthy)
    """
    name: str
    host: str
    healthy: bool
    models: List[str]
    missing_models: List[str] = field(default_factory=list)
    latency_ms: Optional[float] = None
    error: Optional[str] = None

    def to_string(self) -> str:
        """Format as human-readable string."""
        if not self.healthy:
            return f"{self.name} ({self.host}): ✗ {self.error}"
        latency = f" [{self.latency_ms:.0f}ms]" if self.latency_ms is not None else ""
        models_str = ", ".join(self.models) if self.models else "(none)"
        base = f"{self.name} ({self.host}){latency}: ✓ Available models: {models_str}"
        if self.missing_models:
            base += f" | WARNING: expected model(s) not found: {', '.join(self.missing_models)}"
        return base


def _vision_model_name() -> str:
    """Return the configured LLaVA model name, matching llava_agent.py."""
    return os.environ.get("GLITCH_LLAVA_OLLAMA_MODEL", "llava-v1.6-mistral-7b")


@tool
async def vision_agent(
    image_url: str,
    prompt: str,
    model: str = "",
) -> str:
    """Process an image with the local LLaVA vision model.
    
    Dataflow:
        (image_url, prompt) -> Ollama Vision Host -> Response String
    
    Args:
        image_url: URL or base64-encoded image to analyze
        prompt: Question or instruction about the image
        model: Ollama vision model to use (default: llava)
    
    Returns:
        Model's analysis or response about the image
    """
    config = _get_config()
    resolved_model = model or _vision_model_name()

    # Use OpenAI-compatible format on the vision port (18080) — same path as llava_agent.py.
    # Port 11434 (native Ollama) requires different auth and doesn't support images the same way.
    endpoint = f"http://{config.vision_host}:{config.vision_port}/v1/chat/completions"

    # Accept raw base64, data URI, or http/https URL
    if image_url.startswith("data:"):
        image_data_url = image_url  # already a data URI
    elif image_url.startswith("http://") or image_url.startswith("https://"):
        image_data_url = image_url  # pass URL directly
    else:
        image_data_url = f"data:image/jpeg;base64,{image_url}"

    payload = {
        "model": resolved_model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_data_url, "detail": "auto"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        "max_tokens": 1024,
        "temperature": 0.3,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            logger.info("Sending vision request to %s with model %s", endpoint, resolved_model)
            response = await client.post(endpoint, json=payload, headers=_ollama_headers())
            response.raise_for_status()

            result = response.json()
            choices = result.get("choices", [])
            if choices:
                return choices[0].get("message", {}).get("content", "No response from vision model")
            return "No response from vision model"

    except httpx.HTTPError as e:
        logger.error("HTTP error calling vision model: %s", e)
        return f"Error connecting to vision model: {str(e)}"
    except Exception as e:
        logger.error("Unexpected error in vision_agent: %s", e)
        return f"Vision processing failed: {str(e)}"


@tool
async def local_chat(
    prompt: str,
    model: str = "mistral-nemo:12b",
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    """Execute a chat completion with a local Ollama model.
    
    Use this for lightweight tasks, tool execution, or when local processing is preferred.
    
    Dataflow:
        (prompt, system_prompt) -> Ollama Chat Host -> Response String
    
    Args:
        prompt: The user's message or query
        model: Ollama model to use (default: mistral:12b)
        system_prompt: Optional system instructions for the model
        temperature: Sampling temperature (0.0 to 1.0)
    
    Returns:
        Model's response to the prompt
    """
    config = _get_config()
    
    try:
        endpoint = f"http://{config.chat_host}:{config.port}/api/generate"
        
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        payload: OllamaGeneratePayload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            logger.info(f"Sending chat request to {endpoint} with model {model}")
            response = await client.post(endpoint, json=payload, headers=_ollama_headers())
            response.raise_for_status()
            
            result: OllamaGenerateResponse = response.json()
            return result.get("response", "No response from chat model")
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error calling chat model: {e}")
        return f"Error connecting to chat model: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in local_chat: {e}")
        return f"Chat processing failed: {str(e)}"


@tool
def test_ollama_model(
    model: str = "mistral-nemo:12b",
    prompt: str = "Reply with exactly one word: hello",
    endpoint: str = "chat",
) -> str:
    """Send a test prompt to a local Ollama model and measure end-to-end inference latency.

    Unlike check_ollama_health (which only checks reachability and model lists), this
    actually sends a prompt and validates the model produces a response.

    Args:
        model: Model name to test (e.g. "mistral-nemo:12b", "llava")
        prompt: Test prompt — keep short for speed
        endpoint: "chat" uses port 11434 (Ollama native); "vision" uses port 18080 (OpenAI-compat)
    """
    import time
    import urllib.request
    config = _get_config()

    if endpoint == "vision":
        url = f"http://{config.vision_host}:{config.vision_port}/api/generate"
    else:
        url = f"http://{config.chat_host}:{config.port}/api/generate"

    payload = json.dumps({"model": model, "prompt": prompt, "stream": False}).encode()
    req = urllib.request.Request(url, data=payload, headers=_ollama_headers())
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=config.timeout) as resp:
            latency_ms = int((time.monotonic() - t0) * 1000)
            data = json.loads(resp.read().decode())
            response_text = (data.get("response") or "").strip()
            return (
                f"✓ {model} ({endpoint}) responded in {latency_ms}ms\n"
                f"Prompt:   {prompt}\n"
                f"Response: {response_text}"
            )
    except Exception as e:
        latency_ms = int((time.monotonic() - t0) * 1000)
        return f"✗ {model} ({endpoint}) failed after {latency_ms}ms: {e}"


def _debug_ollama_log(message: str, data: dict, hypothesis_id: str = "") -> None:
    """Write ollama health debug payload to CloudWatch Logs and to logger (stdout)."""
    # #region agent log
    payload = {
        "event_type": "ollama_health_debug",
        "timestamp": time.time(),
        "location": "ollama_tools._check_single_host",
        "message": message,
        "data": data,
        "hypothesisId": hypothesis_id,
    }
    logger.info("OLLAMA_HEALTH_DEBUG %s", message, extra={"ollama_debug": payload})
    stream_name = "ollama-health/" + datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ts_ms = int(payload["timestamp"] * 1000)
    msg = json.dumps(payload)
    try:
        try:
            from glitch.aws_utils import get_client
            client = get_client("logs")
        except Exception:
            return
        kwargs = {
            "logGroupName": _OLLAMA_CW_LOG_GROUP,
            "logStreamName": stream_name,
            "logEvents": [{"timestamp": ts_ms, "message": msg}],
        }
        token = _OLLAMA_CW_SEQUENCE_TOKENS.get(stream_name)
        if token:
            kwargs["sequenceToken"] = token
        resp = client.put_log_events(**kwargs)
        if resp.get("nextSequenceToken"):
            _OLLAMA_CW_SEQUENCE_TOKENS[stream_name] = resp["nextSequenceToken"]
    except Exception as e:
        err_code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
        if err_code == "ResourceNotFoundException" and client is not None:
            try:
                client.create_log_group(logGroupName=_OLLAMA_CW_LOG_GROUP)
            except Exception:
                pass
            try:
                client.create_log_stream(logGroupName=_OLLAMA_CW_LOG_GROUP, logStreamName=stream_name)
                client.put_log_events(
                    logGroupName=_OLLAMA_CW_LOG_GROUP,
                    logStreamName=stream_name,
                    logEvents=[{"timestamp": ts_ms, "message": msg}],
                )
            except Exception as e2:
                logger.debug("Ollama debug CloudWatch write failed: %s", e2)
        else:
            logger.debug("Ollama debug CloudWatch write failed: %s", e)
    # #endregion


def _parse_ollama_models(data: OllamaTagsResponse) -> List[str]:
    """Extract model names from Ollama /api/tags response."""
    return [m.get("name", "") for m in data.get("models", [])]


def _parse_openai_models(data: OpenAIModelsResponse) -> List[str]:
    """Extract model names from OpenAI-compatible /v1/models response."""
    models = data.get("models") or data.get("data") or []
    return [m.get("name") or m.get("id") or "" for m in models if m.get("name") or m.get("id")]


async def _check_single_host(
    name: str,
    host: str,
    config: OllamaConfig,
    *,
    port_override: Optional[int] = None,
    use_openai_format: bool = False,
    expected_models: Optional[List[str]] = None,
) -> HealthCheckResult:
    """Check health of a single host (Ollama native or OpenAI-compatible).

    Args:
        name: Endpoint name for display (Chat, Vision)
        host: IP address to check
        config: OllamaConfig with port, vision_port, timeout
        port_override: If set, use this port instead of config.port
        use_openai_format: If True, GET /v1/models (port 8080); else GET /api/tags (port 11434)
        expected_models: Model names that must be present for the check to be fully healthy

    Returns:
        HealthCheckResult with status, latency, and any missing expected models
    """
    port = port_override if port_override is not None else config.port
    path = "/v1/models" if use_openai_format else "/api/tags"
    _debug_ollama_log("check_single_host entry", {"name": name, "host": host, "port": port, "path": path}, "A")
    t0 = time.monotonic()
    try:
        endpoint = f"http://{host}:{port}{path}"
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(endpoint, headers=_ollama_headers())
            latency_ms = (time.monotonic() - t0) * 1000
            if response.status_code == 200:
                raw = response.json()
                if use_openai_format:
                    models = _parse_openai_models(cast(OpenAIModelsResponse, raw))
                else:
                    models = _parse_ollama_models(cast(OllamaTagsResponse, raw))
                missing = [m for m in (expected_models or []) if m not in models]
                _debug_ollama_log("check_single_host success", {"name": name, "host": host, "healthy": True, "latency_ms": latency_ms, "models_count": len(models), "models": models, "missing_models": missing}, "D")
                return HealthCheckResult(
                    name=name,
                    host=host,
                    healthy=True,
                    models=models,
                    missing_models=missing,
                    latency_ms=latency_ms,
                )
            _debug_ollama_log("check_single_host non-200", {"name": name, "host": host, "status_code": response.status_code, "latency_ms": latency_ms}, "C")
            return HealthCheckResult(
                name=name,
                host=host,
                healthy=False,
                models=[],
                latency_ms=latency_ms,
                error=f"HTTP {response.status_code}",
            )
    except httpx.TimeoutException:
        latency_ms = (time.monotonic() - t0) * 1000
        error = "timed out after 3s (host unreachable or overloaded)"
        _debug_ollama_log("check_single_host timeout", {"name": name, "host": host, "latency_ms": latency_ms}, "B")
        return HealthCheckResult(name=name, host=host, healthy=False, models=[], latency_ms=latency_ms, error=error)
    except httpx.ConnectError:
        latency_ms = (time.monotonic() - t0) * 1000
        error = "connection refused (host down or port not open)"
        _debug_ollama_log("check_single_host connect_error", {"name": name, "host": host, "latency_ms": latency_ms}, "B")
        return HealthCheckResult(name=name, host=host, healthy=False, models=[], latency_ms=latency_ms, error=error)
    except Exception as e:
        latency_ms = (time.monotonic() - t0) * 1000
        _debug_ollama_log("check_single_host exception", {"name": name, "host": host, "error": str(e), "error_type": type(e).__name__, "latency_ms": latency_ms}, "B")
        return HealthCheckResult(name=name, host=host, healthy=False, models=[], latency_ms=latency_ms, error=str(e))


@tool
async def check_ollama_health() -> str:
    """Check connectivity and health status of Ollama hosts.
    
    Runs health checks in parallel for faster results.
    
    Dataflow:
        () -> [Chat Host, Vision Host] -> HealthCheckResult[] -> Status String
    
    Returns:
        Status report of both Ollama endpoints
    """
    import asyncio
    
    config = _get_config()
    
    # Chat: Ollama native (11434, /api/tags). Vision: OpenAI-compatible (8080, /v1/models).
    # Expected models match the defaults used by local_chat and vision_agent respectively.
    tasks = [
        _check_single_host("Chat", config.chat_host, config, expected_models=["mistral-nemo:12b"]),
        _check_single_host("Vision", config.vision_host, config, port_override=config.vision_port, use_openai_format=True, expected_models=[_vision_model_name()]),
    ]
    results = await asyncio.gather(*tasks)
    lines = [r.to_string() for r in results]
    if not all(r.healthy for r in results):
        lines.append(
            "Note: These hosts are only reachable when the runtime has network access to the on-prem network. "
            "Set GLITCH_OLLAMA_PROXY_HOST to a proxy that can reach on-prem IPs, or ensure direct connectivity."
        )
    return "\n".join(lines)
