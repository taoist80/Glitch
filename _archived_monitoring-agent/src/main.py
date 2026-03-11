"""Main entry point for Sentinel A2A server.

Imported by the AgentCore runtime entrypoint mechanism.
"""
import uvicorn
from sentinel.server import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=9000)
