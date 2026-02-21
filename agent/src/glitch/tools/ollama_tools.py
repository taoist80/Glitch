"""Ollama integration tools for local model execution via Tailscale.

Dataflow:
    Tool Call -> httpx.AsyncClient -> Ollama API -> Response String

These tools connect to on-premises Ollama instances via Tailscale mesh VPN,
enabling local model execution for cost savings and privacy.
"""

import httpx
from strands import tool
from typing import Optional, TypedDict, List
from dataclasses import dataclass
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OllamaConfig:
    """Configuration for Ollama endpoints.
    
    Attributes:
        chat_host: IP address of chat model host
        vision_host: IP address of vision model host
        port: Ollama API port
        timeout: Request timeout in seconds
    """
    chat_host: str = "10.10.110.202"
    vision_host: str = "10.10.110.137"
    port: int = 11434
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


class OllamaModelInfo(TypedDict):
    """Model information from Ollama /api/tags endpoint."""
    name: str
    modified_at: str
    size: int


class OllamaTagsResponse(TypedDict):
    """Response from Ollama /api/tags endpoint."""
    models: List[OllamaModelInfo]


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
    model: str = "mistral:12b",
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


async def _check_single_host(name: str, host: str, config: OllamaConfig) -> HealthCheckResult:
    """Check health of a single Ollama host.
    
    Args:
        name: Endpoint name for display
        host: IP address to check
        config: OllamaConfig with port and timeout
    
    Returns:
        HealthCheckResult with status
    """
    try:
        endpoint = f"http://{host}:{config.port}/api/tags"
        async with httpx.AsyncClient(timeout=3.0) as client:  # Reduced from 10s to 3s for faster failure
            response = await client.get(endpoint)
            if response.status_code == 200:
                data: OllamaTagsResponse = response.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                return HealthCheckResult(
                    name=name,
                    host=host,
                    healthy=True,
                    models=models,
                )
            return HealthCheckResult(
                name=name,
                host=host,
                healthy=False,
                models=[],
                error=f"HTTP {response.status_code}",
            )
    except Exception as e:
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
    
    # Run checks in parallel for faster results (3s max instead of 6s sequential)
    tasks = [
        _check_single_host("Chat", config.chat_host, config),
        _check_single_host("Vision", config.vision_host, config),
    ]
    results = await asyncio.gather(*tasks)
    
    return "\n".join(r.to_string() for r in results)
