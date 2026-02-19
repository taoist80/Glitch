"""Main entry point for Glitch agent.

Dataflow:
    Environment Variables -> TelemetryConfig, AgentConfig, ServerConfig
                                    |
                                    v
                            setup_telemetry()
                                    |
                                    v
                            create_glitch_agent()
                                    |
                                    v
                    Telegram Channel (if bot token present)
                                    |
                                    v
                            run_server_async() or interactive_mode()
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

from glitch.agent import create_glitch_agent, GlitchAgent
from glitch.telemetry import setup_telemetry
from glitch.types import (
    TelemetryConfig,
    ServerConfig,
    InvocationResponse,
)
from glitch.channels import (
    ConfigManager,
    OwnerBootstrap,
    TelegramChannel,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def get_telemetry_config() -> TelemetryConfig:
    """Build TelemetryConfig from environment variables.
    
    Environment Variables:
        OTEL_CONSOLE_ENABLED: Enable console exporter (default: false)
        OTEL_OTLP_ENABLED: Enable OTLP exporter (default: true)
        OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint URL
    
    Returns:
        TelemetryConfig instance
    """
    return TelemetryConfig(
        service_name="glitch-agent",
        enable_console=os.getenv("OTEL_CONSOLE_ENABLED", "false").lower() == "true",
        enable_otlp=os.getenv("OTEL_OTLP_ENABLED", "true").lower() == "true",
    )


def get_server_config() -> ServerConfig:
    """Build ServerConfig from environment variables.
    
    Environment Variables:
        GLITCH_HOST: Host to bind to (default: 0.0.0.0)
        GLITCH_PORT: Port to bind to (default: 8080)
        GLITCH_DEBUG: Enable debug mode (default: false)
    
    Returns:
        ServerConfig instance
    """
    return ServerConfig(
        host=os.getenv("GLITCH_HOST", "0.0.0.0"),
        port=int(os.getenv("GLITCH_PORT", "8080")),
        debug=os.getenv("GLITCH_DEBUG", "false").lower() == "true",
    )


async def main() -> None:
    """Main execution function.
    
    Initializes telemetry, creates agent, and starts server or interactive mode.
    Optionally starts Telegram channel if bot token is provided.
    """
    print("=" * 60)
    print("GLITCH AGENT STARTUP")
    print("=" * 60)
    print(f"GLITCH_MODE env var: {os.getenv('GLITCH_MODE', 'NOT_SET')}")
    print(f"Python version: {sys.version}")
    print(f"Current working directory: {os.getcwd()}")
    print("=" * 60)
    
    logger.info("Starting Glitch agent...")
    logger.info(f"GLITCH_MODE environment variable: {os.getenv('GLITCH_MODE', 'NOT_SET')}")
    
    telemetry_config = get_telemetry_config()
    setup_telemetry(telemetry_config)
    
    agent = create_glitch_agent()
    
    logger.info(f"Glitch agent initialized for session: {agent.session_id}")
    
    connectivity = await agent.check_connectivity()
    logger.info(f"Connectivity check: {connectivity}")
    
    # Initialize Telegram channel if bot token is provided
    telegram_channel = None
    telegram_token = os.getenv("GLITCH_TELEGRAM_BOT_TOKEN")
    
    if telegram_token:
        try:
            logger.info("Telegram bot token found, initializing Telegram channel...")
            
            # Get config directory (allow override)
            config_dir = os.getenv("GLITCH_CONFIG_DIR")
            config_path = Path(config_dir) if config_dir else None
            
            # Initialize config manager
            config_manager = ConfigManager(config_dir=config_path)
            config = config_manager.load(bot_token=telegram_token)
            
            # Initialize bootstrap system
            bootstrap = OwnerBootstrap(config_manager)
            
            # Create Telegram channel
            telegram_channel = TelegramChannel(
                config_manager=config_manager,
                bootstrap=bootstrap,
                agent=agent,
            )
            
            # Start Telegram channel in background
            await telegram_channel.start()
            
            logger.info("Telegram channel started successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram channel: {e}", exc_info=True)
            # Continue without Telegram if it fails
    else:
        logger.info("No Telegram bot token found (GLITCH_TELEGRAM_BOT_TOKEN), skipping Telegram channel")
    
    mode = os.getenv("GLITCH_MODE", "server")
    logger.info(f"Mode determined: {mode}")
    print(f"Starting in {mode} mode")
    
    try:
        if mode == "interactive":
            logger.warning("INTERACTIVE MODE - This will fail in containers without stdin!")
            print("ERROR: Interactive mode requested but container has no stdin")
            await interactive_mode(agent)
        else:
            logger.info("Starting HTTP server")
            server_config = get_server_config()
            print(f"Starting HTTP server on {server_config.host}:{server_config.port}")
            
            from glitch.server import run_server_async
            await run_server_async(agent, server_config)
    finally:
        # Clean up Telegram channel on shutdown
        if telegram_channel:
            logger.info("Shutting down Telegram channel...")
            try:
                await telegram_channel.stop()
            except Exception as e:
                logger.error(f"Error stopping Telegram channel: {e}")


async def interactive_mode(agent: GlitchAgent) -> None:
    """Run agent in interactive CLI mode.
    
    Args:
        agent: GlitchAgent instance to interact with
    """
    print("\n" + "=" * 60)
    print("Glitch Agent - Interactive Mode")
    print("=" * 60)
    print(f"Session ID: {agent.session_id}")
    print(f"Memory ID: {agent.memory_id}")
    print("\nType 'quit' or 'exit' to stop, 'status' for agent status.")
    print("=" * 60 + "\n")
    
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
            
            response: InvocationResponse = await agent.process_message(user_input)
            print(f"\nGlitch: {response.get('message', '')}")
            
            metrics = response.get("metrics")
            if metrics:
                token_usage = metrics.get("token_usage", {})
                print(
                    f"\n[Tokens: {token_usage.get('input_tokens', 0)}in/"
                    f"{token_usage.get('output_tokens', 0)}out]"
                )
            
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
