"""REST API module for Glitch Agent UI.

Provides FastAPI router with endpoints for:
- Agent status
- Telegram configuration
- Ollama health
- Memory state
- MCP servers
- Skills management
"""

from glitch.api.router import router, setup_api

__all__ = ["router", "setup_api"]
