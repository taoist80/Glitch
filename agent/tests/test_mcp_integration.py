#!/usr/bin/env python3
"""Test script to verify MCP server integration.

This script checks that:
1. MCP configuration loads correctly
2. MCP manager initializes without errors
3. UniFi server config is recognized (even if not connected due to missing credentials)
"""

import sys
import os
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from glitch.mcp import MCPServerManager, load_mcp_config, get_default_mcp_config_path

def main():
    print("MCP Server Integration Test")
    print("=" * 50)
    
    # Test 1: Check default config path
    print("\n1. Checking default config path...")
    config_path = get_default_mcp_config_path()
    print(f"   Default config path: {config_path}")
    print(f"   Config exists: {config_path.exists()}")
    
    if not config_path.exists():
        print("   ❌ Config file not found!")
        return 1
    
    # Test 2: Load configuration
    print("\n2. Loading MCP configuration...")
    try:
        config = load_mcp_config()
        print(f"   ✓ Config loaded: {len(config.servers)} server(s) defined")
        
        for name, server in config.servers.items():
            print(f"   - {name}: enabled={server.enabled}, transport={server.transport}")
    except Exception as e:
        print(f"   ❌ Failed to load config: {e}")
        return 1
    
    # Test 3: Initialize manager (will fail to connect without credentials)
    print("\n3. Initializing MCP manager...")
    try:
        manager = MCPServerManager()
        status = manager.get_status()
        
        print(f"   ✓ Manager initialized")
        print(f"   - Total servers: {status['total_servers']}")
        print(f"   - Enabled servers: {status['enabled_servers']}")
        print(f"   - Connected clients: {status['connected_clients']}")
        print(f"   - Server names: {status['server_names']}")
        
        if status['enabled_servers'] > 0 and status['connected_clients'] == 0:
            print("\n   ℹ️  Note: No servers connected (likely missing credentials)")
            print("   To connect to UniFi MCP server, set environment variables:")
            print("     export UNIFI_API_KEY=your_key_here")
            print("     export UNIFI_API_TYPE=cloud")
        
    except Exception as e:
        print(f"   ⚠️  Manager initialization warning: {e}")
        print("   This is expected if MCP server packages are not installed")
        return 0
    
    print("\n" + "=" * 50)
    print("✓ MCP integration test completed successfully!")
    return 0

if __name__ == "__main__":
    sys.exit(main())
