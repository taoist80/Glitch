"""Main entry point for Glitch agent."""

import asyncio
import logging
import os
import sys
from typing import Optional

from glitch.agent import create_glitch_agent
from glitch.telemetry import setup_telemetry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


async def main():
    """Main execution function."""
    logger.info("Starting Glitch agent...")
    
    telemetry = setup_telemetry(
        service_name="glitch-agent",
        enable_console=os.getenv("OTEL_CONSOLE_ENABLED", "false").lower() == "true",
    )
    
    agent = create_glitch_agent()
    
    logger.info(f"Glitch agent initialized for session: {agent.session_id}")
    
    connectivity = await agent.check_connectivity()
    logger.info(f"Connectivity check: {connectivity}")
    
    if os.getenv("GLITCH_MODE", "interactive") == "server":
        logger.info("Starting in server mode (HTTP endpoint)")
        from glitch.server import run_server
        await run_server(agent)
    else:
        logger.info("Starting in interactive mode")
        await interactive_mode(agent)


async def interactive_mode(agent):
    """Run agent in interactive CLI mode."""
    print("\n" + "="*60)
    print("Glitch Agent - Interactive Mode")
    print("="*60)
    print(f"Session ID: {agent.session_id}")
    print(f"Memory ID: {agent.memory_id}")
    print("\nType 'quit' or 'exit' to stop, 'status' for agent status.")
    print("="*60 + "\n")
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() in ["quit", "exit"]:
                print("\nShutting down Glitch agent...")
                break
            
            if user_input.lower() == "status":
                status = agent.get_status()
                print(f"\n{status}")
                continue
            
            response = await agent.process_message(user_input)
            print(f"\nGlitch: {response}")
            
        except KeyboardInterrupt:
            print("\n\nInterrupted. Shutting down...")
            break
        except Exception as e:
            logger.error(f"Error in interactive mode: {e}")
            print(f"\nError: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        sys.exit(1)
