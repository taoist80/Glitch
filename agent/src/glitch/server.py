"""HTTP server for AgentCore Runtime integration."""

import json
import logging
from typing import Any, Dict

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route
import uvicorn

logger = logging.getLogger(__name__)

# Global agent instance
_agent = None


async def ping(request: Request) -> Response:
    """Health check endpoint required by AgentCore."""
    return JSONResponse({"status": "healthy"})


async def invocations(request: Request) -> JSONResponse:
    """
    Main invocation endpoint for AgentCore Runtime.
    
    Receives:
        - POST /invocations
        - Body: {"prompt": "user message", ...}
    
    Returns:
        - {"message": "agent response", ...}
    """
    try:
        body = await request.json()
        user_message = body.get("prompt", "")
        
        if not user_message:
            return JSONResponse(
                {"error": "No prompt provided"},
                status_code=400
            )
        
        response = await _agent.process_message(user_message)
        
        return JSONResponse({
            "message": response,
            "session_id": _agent.session_id,
            "memory_id": _agent.memory_id
        })
        
    except Exception as e:
        logger.error(f"Error processing invocation: {e}", exc_info=True)
        return JSONResponse(
            {"error": str(e)},
            status_code=500
        )


async def run_server(agent: Any, host: str = "0.0.0.0", port: int = 8080):
    """
    Run Glitch agent as an HTTP server for AgentCore Runtime.
    
    Args:
        agent: GlitchAgent instance
        host: Host to bind to
        port: Port to bind to
    """
    global _agent
    _agent = agent
    
    app = Starlette(
        debug=False,
        routes=[
            Route("/ping", ping, methods=["GET"]),
            Route("/invocations", invocations, methods=["POST"]),
        ],
    )
    
    logger.info(f"Starting AgentCore HTTP server on {host}:{port}")
    logger.info(f"Session ID: {agent.session_id}")
    logger.info(f"Memory ID: {agent.memory_id}")
    
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()
