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
                    Telegram Channel (if bot token in Secrets Manager)
                                    |
                                    v
                            run_server_async() or interactive_mode()
"""

import asyncio
import json
import logging
import os

# Strands SDK: allow non-interactive tool execution (required for AgentCore/serverless).
# Set before any Strands/glitch.agent imports.
os.environ.setdefault("BYPASS_TOOL_CONSENT", "true")
import sys
import time
import boto3
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional

from glitch.agent import create_glitch_agent, GlitchAgent
from glitch.poet_agent import create_poet_agent
from glitch.telemetry import setup_telemetry
from glitch.types import (
    TelemetryConfig,
    ServerConfig,
    InvocationResponse,
)
from glitch.channels import (
    ConfigManager,
    DynamoDBConfigManager,
    OwnerBootstrap,
    TelegramChannel,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def get_telegram_bot_token() -> Optional[str]:
    """Retrieve Telegram bot token from AWS Secrets Manager.
    
    Returns:
        Bot token string if available, None otherwise
    """
    secret_name = os.getenv("GLITCH_TELEGRAM_SECRET_NAME", "glitch/telegram-bot-token")
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-west-2"))
    
    try:
        session = boto3.session.Session()
        client = session.client(service_name="secretsmanager", region_name=region)
        
        response = client.get_secret_value(SecretId=secret_name)
        
        if "SecretString" in response:
            return response["SecretString"]
        else:
            logger.warning(f"Secret {secret_name} does not contain a string value")
            return None
    except client.exceptions.ResourceNotFoundException:
        logger.info(f"Telegram bot token secret not found: {secret_name}")
        return None
    except Exception as e:
        logger.warning(f"Failed to retrieve Telegram bot token from Secrets Manager: {e}")
        return None


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
    port_str = os.getenv("GLITCH_PORT", "8080")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning("Invalid GLITCH_PORT '%s', using default 8080", port_str)
        port = 8080
    return ServerConfig(
        host=os.getenv("GLITCH_HOST", "0.0.0.0"),
        port=port,
        debug=os.getenv("GLITCH_DEBUG", "false").lower() == "true",
    )


def get_current_telegram_webhook(bot_token: str) -> Optional[str]:
    """Get current webhook URL from Telegram (getWebhookInfo). Returns None on error."""
    info_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    try:
        with urllib.request.urlopen(info_url, timeout=10) as response:
            result = json.loads(response.read().decode())
            if result.get("ok"):
                return (result.get("result") or {}).get("url") or ""
            return None
    except Exception:
        return None


def register_telegram_webhook(bot_token: str, webhook_url: str, secret_token: str) -> bool:
    """Register webhook URL with Telegram API.
    
    If getWebhookInfo shows the URL is already set to webhook_url, skips setWebhook to avoid
    rate limits when multiple runtime instances start. Retries on 429 with exponential backoff.
    
    Args:
        bot_token: Telegram bot token
        webhook_url: URL for Telegram to send updates to
        secret_token: Secret token for webhook validation
        
    Returns:
        True if registration succeeded or webhook already set to this URL
    """
    current = get_current_telegram_webhook(bot_token)
    if current is not None and current.rstrip("/") == webhook_url.rstrip("/"):
        logger.info("Telegram webhook already set to %s, skipping setWebhook", webhook_url)
        return True

    url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    payload = {
        "url": webhook_url,
        "secret_token": secret_token,
        "allowed_updates": ["message", "edited_message", "callback_query"],
        "drop_pending_updates": True,
    }
    data = json.dumps(payload).encode()
    max_attempts = 4
    base_delay = 5.0

    for attempt in range(max_attempts):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                if result.get("ok"):
                    logger.info(f"Telegram webhook registered: {webhook_url}")
                    return True
                logger.error(f"Failed to register webhook: {result}")
                return False
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_attempts - 1:
                delay = base_delay * (2**attempt)
                logger.warning(
                    "Telegram rate limit (429) when registering webhook, retrying in %.0fs (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    max_attempts,
                )
                time.sleep(delay)
                continue
            logger.error(f"Error registering webhook: {e}")
            return False
        except Exception as e:
            logger.error(f"Error registering webhook: {e}")
            return False
    return False


def get_webhook_url() -> Optional[str]:
    """Resolve webhook URL: env GLITCH_TELEGRAM_WEBHOOK_URL, else Lambda function URL by name.
    
    Returns:
        Webhook URL if found, None otherwise
    """
    url = os.getenv("GLITCH_TELEGRAM_WEBHOOK_URL")
    if url:
        return url
    region = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-west-2"))
    function_name = os.getenv("GLITCH_TELEGRAM_WEBHOOK_FUNCTION_NAME", "glitch-telegram-webhook")
    try:
        lambda_client = boto3.client("lambda", region_name=region)
        resp = lambda_client.get_function_url_config(FunctionName=function_name)
        return resp.get("FunctionUrl")
    except Exception as e:
        logger.warning(f"Failed to get webhook URL from Lambda {function_name}: {e}")
    return None


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
    
    # Skip blocking connectivity check on startup - run on-demand via /status command instead
    # connectivity = await agent.check_connectivity()
    # logger.info(f"Connectivity check: {connectivity}")
    
    # Initialize Telegram channel if bot token is in Secrets Manager
    telegram_channel = None
    telegram_token = get_telegram_bot_token()
    
    if telegram_token:
        try:
            logger.info("Telegram bot token retrieved from Secrets Manager, initializing Telegram channel...")
            
            # Determine config backend: DynamoDB (webhook mode) or local file (polling mode)
            use_dynamodb = os.getenv("GLITCH_CONFIG_BACKEND", "dynamodb").lower() == "dynamodb"
            config_table = os.getenv("GLITCH_CONFIG_TABLE", "glitch-telegram-config")
            
            if use_dynamodb:
                logger.info(f"Using DynamoDB config backend (table: {config_table})")
                config_manager = DynamoDBConfigManager(table_name=config_table)
                config = config_manager.load(bot_token=telegram_token)
                
                # Register webhook if URL is available
                webhook_url = get_webhook_url()
                if webhook_url:
                    webhook_secret = config_manager.get_webhook_secret()
                    if register_telegram_webhook(telegram_token, webhook_url, webhook_secret):
                        config_manager.set_webhook_url(webhook_url)
                        logger.info("Telegram webhook mode enabled - Lambda handles incoming messages")
                    else:
                        logger.warning("Failed to register webhook, falling back to polling")
                else:
                    logger.info("No webhook URL configured, using polling mode")
            else:
                # Local file config (original behavior)
                config_dir = os.getenv("GLITCH_CONFIG_DIR")
                config_path = Path(config_dir) if config_dir else None
                config_manager = ConfigManager(config_dir=config_path)
                config = config_manager.load(bot_token=telegram_token)
            
            # Initialize bootstrap system
            bootstrap = OwnerBootstrap(config_manager)
            
            # Create Poet sub-agent for Telegram routing
            poet_agent = create_poet_agent()
            
            # Create Telegram channel
            telegram_channel = TelegramChannel(
                config_manager=config_manager,
                bootstrap=bootstrap,
                agent=agent,
                poet_agent=poet_agent,
            )
            
            # Start Telegram channel in background
            await telegram_channel.start()
            
            logger.info("Telegram channel started successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram channel: {e}", exc_info=True)
            # Continue without Telegram if it fails
    else:
        logger.info("No Telegram bot token found in Secrets Manager (glitch/telegram-bot-token), skipping Telegram channel")
    
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
