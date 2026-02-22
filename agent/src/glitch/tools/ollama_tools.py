"""Ollama integration tools for local model execution via Tailscale.

Dataflow:
    Tool Call -> httpx.AsyncClient -> Ollama API -> Response String

These tools connect to on-premises Ollama instances via Tailscale mesh VPN,
enabling local model execution for cost savings and privacy.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, TypedDict, cast

import httpx
from strands import tool

logger = logging.getLogger(__name__)

# CloudWatch Logs stream for ollama health debugging (reuses telemetry log group)
_OLLAMA_CW_SEQUENCE_TOKENS: Dict[str, str] = {}
_OLLAMA_CW_LOG_GROUP = os.environ.get("GLITCH_TELEMETRY_LOG_GROUP", "/glitch/telemetry")


@dataclass(frozen=True)
class OllamaConfig:
    """Configuration for Ollama / local model endpoints.

    Chat host (10.10.110.202): Ollama native on port 11434 (/api/tags, /api/generate).
    Vision host (10.10.110.137): OpenAI-compatible on port 8080 (/v1/models, /v1/chat/completions).
    """
    chat_host: str = "10.10.110.202"
    vision_host: str = "10.10.110.137"
    port: int = 11434
    vision_port: int = 8080
    timeout: float = 120.0


DEFAULT_CONFIG = OllamaConfig()


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
        error: Error message (if unhealthy)
    """
    name: str
    host: str
    healthy: bool
    models: List[str]
    error: Optional[str] = None
    
    def to_string(self) -> str:
        """Format as human-readable string."""
        if self.healthy:
            return f"{self.name} ({self.host}): ✓ Available models: {', '.join(self.models)}"
        return f"{self.name} ({self.host}): ✗ {self.error}"


@tool
async def vision_agent(
    image_url: str,
    prompt: str,
    model: str = "llava",
) -> str:
    """Process an image with the local LLaVA vision model via Tailscale.
    
    Dataflow:
        (image_url, prompt) -> Ollama Vision Host -> Response String
    
    Args:
        image_url: URL or base64-encoded image to analyze
        prompt: Question or instruction about the image
        model: Ollama vision model to use (default: llava)
    
    Returns:
        Model's analysis or response about the image
    """
    config = DEFAULT_CONFIG
    
    try:
        endpoint = f"http://{config.vision_host}:{config.port}/api/generate"
        
        payload: OllamaGeneratePayload = {
            "model": model,
            "prompt": prompt,
            "images": [image_url],
            "stream": False,
        }
        
        async with httpx.AsyncClient(timeout=config.timeout) as client:
            logger.info(f"Sending vision request to {endpoint} with model {model}")
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            
            result: OllamaGenerateResponse = response.json()
            return result.get("response", "No response from vision model")
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error calling vision model: {e}")
        return f"Error connecting to vision model: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in vision_agent: {e}")
        return f"Vision processing failed: {str(e)}"


@tool
async def local_chat(
    prompt: str,
    model: str = "mistral-nemo:12b",
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    """Execute a chat completion with a local Ollama model via Tailscale.
    
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
    config = DEFAULT_CONFIG
    
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
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            
            result: OllamaGenerateResponse = response.json()
            return result.get("response", "No response from chat model")
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error calling chat model: {e}")
        return f"Error connecting to chat model: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in local_chat: {e}")
        return f"Chat processing failed: {str(e)}"


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
        client = None
        try:
            import boto3
            client = boto3.client("logs")
        except Exception:
            pass
        if not client:
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
) -> HealthCheckResult:
    """Check health of a single host (Ollama native or OpenAI-compatible).

    Args:
        name: Endpoint name for display (Chat, Vision)
        host: IP address to check
        config: OllamaConfig with port, vision_port, timeout
        port_override: If set, use this port instead of config.port
        use_openai_format: If True, GET /v1/models (port 8080); else GET /api/tags (port 11434)

    Returns:
        HealthCheckResult with status
    """
    port = port_override if port_override is not None else config.port
    path = "/v1/models" if use_openai_format else "/api/tags"
    _debug_ollama_log("check_single_host entry", {"name": name, "host": host, "port": port, "path": path}, "A")
    try:
        endpoint = f"http://{host}:{port}{path}"
        async with httpx.AsyncClient(timeout=3.0) as client:
            response = await client.get(endpoint)
            if response.status_code == 200:
                raw = response.json()
                if use_openai_format:
                    models = _parse_openai_models(cast(OpenAIModelsResponse, raw))
                else:
                    models = _parse_ollama_models(cast(OllamaTagsResponse, raw))
                _debug_ollama_log("check_single_host success", {"name": name, "host": host, "healthy": True, "models_count": len(models), "models": models}, "D")
                return HealthCheckResult(
                    name=name,
                    host=host,
                    healthy=True,
                    models=models,
                )
            _debug_ollama_log("check_single_host non-200", {"name": name, "host": host, "status_code": response.status_code}, "C")
            return HealthCheckResult(
                name=name,
                host=host,
                healthy=False,
                models=[],
                error=f"HTTP {response.status_code}",
            )
    except Exception as e:
        _debug_ollama_log("check_single_host exception", {"name": name, "host": host, "error": str(e), "error_type": type(e).__name__}, "B")
        return HealthCheckResult(
            name=name,
            host=host,
            healthy=False,
            models=[],
            error=str(e),
        )


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
    
    config = DEFAULT_CONFIG
    
    # Chat: Ollama native (11434, /api/tags). Vision: OpenAI-compatible (8080, /v1/models).
    tasks = [
        _check_single_host("Chat", config.chat_host, config),
        _check_single_host("Vision", config.vision_host, config, port_override=config.vision_port, use_openai_format=True),
    ]
    results = await asyncio.gather(*tasks)
    lines = [r.to_string() for r in results]
    if not all(r.healthy for r in results):
        lines.append(
            "Note: These hosts are only reachable when the runtime is on your Tailscale/on-prem network. "
            "When running in AWS or off-network, unreachable is expected; Mistral and LLaVA sub-agents are still registered but cannot reach the hosts until the runtime has network access."
        )
    return "\n".join(lines)
