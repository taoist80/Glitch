"""Ollama integration tools for local model execution via Tailscale."""

import httpx
from strands import tool
from typing import Optional
import base64
import logging

logger = logging.getLogger(__name__)

OLLAMA_CHAT_HOST = "10.10.110.202"
OLLAMA_VISION_HOST = "10.10.110.137"
OLLAMA_PORT = 11434
REQUEST_TIMEOUT = 120.0


@tool
async def vision_agent(image_url: str, prompt: str, model: str = "llava") -> str:
    """
    Process an image with the local LLaVA vision model via Tailscale.
    
    Args:
        image_url: URL or base64-encoded image to analyze
        prompt: Question or instruction about the image
        model: Ollama vision model to use (default: llava)
    
    Returns:
        Model's analysis or response about the image
    """
    try:
        endpoint = f"http://{OLLAMA_VISION_HOST}:{OLLAMA_PORT}/api/generate"
        
        payload = {
            "model": model,
            "prompt": prompt,
            "images": [image_url] if image_url.startswith("http") else [image_url],
            "stream": False,
        }
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            logger.info(f"Sending vision request to {endpoint} with model {model}")
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            
            result = response.json()
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
    model: str = "llama3.2",
    system_prompt: Optional[str] = None,
    temperature: float = 0.7,
) -> str:
    """
    Execute a chat completion with a local Ollama model via Tailscale.
    
    Use this for lightweight tasks, tool execution, or when local processing is preferred.
    
    Args:
        prompt: The user's message or query
        model: Ollama model to use (default: llama3.2)
        system_prompt: Optional system instructions for the model
        temperature: Sampling temperature (0.0 to 1.0)
    
    Returns:
        Model's response to the prompt
    """
    try:
        endpoint = f"http://{OLLAMA_CHAT_HOST}:{OLLAMA_PORT}/api/generate"
        
        full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
        
        payload = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            logger.info(f"Sending chat request to {endpoint} with model {model}")
            response = await client.post(endpoint, json=payload)
            response.raise_for_status()
            
            result = response.json()
            return result.get("response", "No response from chat model")
            
    except httpx.HTTPError as e:
        logger.error(f"HTTP error calling chat model: {e}")
        return f"Error connecting to chat model: {str(e)}"
    except Exception as e:
        logger.error(f"Unexpected error in local_chat: {e}")
        return f"Chat processing failed: {str(e)}"


@tool
async def check_ollama_health() -> str:
    """
    Check connectivity and health status of Ollama hosts.
    
    Returns:
        Status report of both Ollama endpoints
    """
    results = []
    
    for name, host in [("Chat", OLLAMA_CHAT_HOST), ("Vision", OLLAMA_VISION_HOST)]:
        try:
            endpoint = f"http://{host}:{OLLAMA_PORT}/api/tags"
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(endpoint)
                if response.status_code == 200:
                    data = response.json()
                    models = [m.get("name") for m in data.get("models", [])]
                    results.append(f"{name} ({host}): ✓ Available models: {', '.join(models)}")
                else:
                    results.append(f"{name} ({host}): ✗ HTTP {response.status_code}")
        except Exception as e:
            results.append(f"{name} ({host}): ✗ {str(e)}")
    
    return "\n".join(results)
