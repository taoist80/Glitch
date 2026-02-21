#!/usr/bin/env python3
"""Run Glitch agent with automatic setup.

Usage (from anywhere):
    python -m glitch

Or create a shell alias:
    alias glitch='cd /path/to/AgentCore-Glitch/agent && python -m glitch'

This module:
1. Ensures PYTHONPATH includes src/
2. Auto-builds the UI if ui/dist is missing
3. Starts the agent server
"""

import os
import sys
from pathlib import Path


def _ensure_pythonpath() -> None:
    """Add agent/src and agent/ to sys.path if not already present."""
    # __file__ is agent/src/glitch/__main__.py
    src_dir = Path(__file__).resolve().parent.parent  # agent/src
    agent_dir = src_dir.parent  # agent/
    for d in (src_dir, agent_dir):
        d_str = str(d)
        if d_str not in sys.path:
            sys.path.insert(0, d_str)


def _auto_build_ui_if_needed() -> None:
    """Build UI if dist doesn't exist and pnpm is available."""
    from glitch.ui_build import auto_build_ui
    auto_build_ui(verbose=True)


def main() -> None:
    """Entry point: setup and run the agent."""
    _ensure_pythonpath()
    _auto_build_ui_if_needed()

    # Now import and run the actual main
    import asyncio
    from main import main as agent_main

    try:
        asyncio.run(agent_main())
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
