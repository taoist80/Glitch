"""Command-line interface for Glitch agent management.

Provides CLI commands for:
- Viewing channel status
- Managing pairing requests (future)
- Configuration management
"""

import sys
import json
import argparse
import logging
from pathlib import Path
from typing import Optional

from glitch.channels.config_manager import ConfigManager

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
)

logger = logging.getLogger(__name__)


def cmd_status(args: argparse.Namespace) -> int:
    """Show Glitch agent status and configuration.
    
    Args:
        args: Parsed command arguments
        
    Returns:
        Exit code (0 for success)
    """
    config_dir = Path(args.config_dir) if args.config_dir else None
    config_manager = ConfigManager(config_dir=config_dir)
    
    try:
        config = config_manager.load()
        
        print("=" * 60)
        print("GLITCH AGENT STATUS")
        print("=" * 60)
        
        # Configuration status
        status_emoji = "🔒" if config.locked else "🔓"
        print(f"\nConfiguration: {status_emoji} {'Locked' if config.locked else 'Unlocked'}")
        print(f"Config file: {config_manager.config_path}")
        
        # Owner information
        if config.owner and config.owner.telegram_id:
            print(f"\nOwner:")
            print(f"  Telegram ID: {config.owner.telegram_id}")
            if config.owner.claimed_at:
                print(f"  Claimed: {config.owner.claimed_at}")
        else:
            print("\n⚠️  No owner configured (bot unclaimed)")
        
        # Telegram configuration
        if config.telegram:
            print(f"\nTelegram Channel:")
            print(f"  Mode: {config.telegram.mode}")
            print(f"  DM Policy: {config.telegram.dm_policy}")
            print(f"  DM Allowlist: {len(config.telegram.dm_allowlist)} users")
            print(f"  Group Policy: {config.telegram.group_policy}")
            print(f"  Group Allowlist: {len(config.telegram.group_allowlist)} groups")
            print(f"  Require Mention: {config.telegram.require_mention}")
            print(f"  Chunk Limit: {config.telegram.text_chunk_limit} chars")
            print(f"  Media Limit: {config.telegram.media_max_mb} MB")
            
            if args.verbose and config.telegram.dm_allowlist:
                print(f"\n  DM Allowlist:")
                for user_id in config.telegram.dm_allowlist:
                    print(f"    - {user_id}")
            
            if args.verbose and config.telegram.group_allowlist:
                print(f"\n  Group Allowlist:")
                for chat_id in config.telegram.group_allowlist:
                    print(f"    - {chat_id}")
        else:
            print("\nTelegram Channel: Not configured")
        
        print("\n" + "=" * 60)
        return 0
        
    except Exception as e:
        logger.error(f"Failed to load status: {e}")
        return 1


def cmd_config(args: argparse.Namespace) -> int:
    """Display raw configuration file.
    
    Args:
        args: Parsed command arguments
        
    Returns:
        Exit code (0 for success)
    """
    config_dir = Path(args.config_dir) if args.config_dir else None
    config_manager = ConfigManager(config_dir=config_dir)
    
    if not config_manager.config_path.exists():
        print(f"No configuration file found at: {config_manager.config_path}")
        return 1
    
    try:
        with open(config_manager.config_path, "r") as f:
            config_data = json.load(f)
        
        print(json.dumps(config_data, indent=2))
        return 0
        
    except Exception as e:
        logger.error(f"Failed to read config: {e}")
        return 1


def main() -> int:
    """Main CLI entry point.
    
    Returns:
        Exit code
    """
    parser = argparse.ArgumentParser(
        description="Glitch Agent CLI - Manage your Glitch agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    parser.add_argument(
        "--config-dir",
        type=str,
        help="Config directory (default: ~/.glitch)",
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show agent status and configuration",
    )
    status_parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show detailed information",
    )
    
    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Display raw configuration file",
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Route to command handler
    if args.command == "status":
        return cmd_status(args)
    elif args.command == "config":
        return cmd_config(args)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
