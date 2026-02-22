#!/usr/bin/env python3
"""
Diagnostic script to check what AgentCore CLI will see in the configuration.
"""

import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    print("Error: pyyaml not installed")
    sys.exit(1)

CONFIG_FILE = Path(__file__).parent.parent / '.bedrock_agentcore.yaml'

print(f"Reading: {CONFIG_FILE}")
print(f"File exists: {CONFIG_FILE.exists()}")
print(f"File size: {CONFIG_FILE.stat().st_size} bytes")
print()

with open(CONFIG_FILE) as f:
    config = yaml.safe_load(f)

agent_name = config.get('default_agent', 'Glitch')
print(f"Default agent: {agent_name}")

if agent_name not in config.get('agents', {}):
    print(f"ERROR: Agent '{agent_name}' not found in config")
    sys.exit(1)

agent_config = config['agents'][agent_name]
aws_config = agent_config.get('aws', {})
network_config = aws_config.get('network_configuration', {})

print(f"\nAWS Configuration:")
print(f"  region: {aws_config.get('region')}")
print(f"  account: {aws_config.get('account')}")
print(f"  execution_role: {aws_config.get('execution_role')}")

print(f"\nNetwork Configuration:")
print(f"  network_mode: {network_config.get('network_mode')}")

mode_config = network_config.get('network_mode_config')
print(f"  network_mode_config type: {type(mode_config)}")
print(f"  network_mode_config value: {mode_config}")

if mode_config:
    subnet_ids = mode_config.get('subnet_ids')
    sg_ids = mode_config.get('security_group_ids')
    
    print(f"\n  subnet_ids:")
    print(f"    type: {type(subnet_ids)}")
    print(f"    value: {subnet_ids}")
    print(f"    length: {len(subnet_ids) if subnet_ids else 0}")
    if subnet_ids:
        for i, subnet in enumerate(subnet_ids):
            print(f"    [{i}]: {subnet} (type: {type(subnet)})")
    
    print(f"\n  security_group_ids:")
    print(f"    type: {type(sg_ids)}")
    print(f"    value: {sg_ids}")
    print(f"    length: {len(sg_ids) if sg_ids else 0}")
    if sg_ids:
        for i, sg in enumerate(sg_ids):
            print(f"    [{i}]: {sg} (type: {type(sg)})")
    
    # Check validation logic
    print(f"\nValidation Checks:")
    print(f"  mode_config exists: {mode_config is not None}")
    print(f"  mode_config is dict: {isinstance(mode_config, dict)}")
    print(f"  subnet_ids exists: {subnet_ids is not None}")
    print(f"  subnet_ids is list: {isinstance(subnet_ids, list)}")
    print(f"  subnet_ids is truthy: {bool(subnet_ids)}")
    print(f"  subnet_ids has items: {len(subnet_ids) > 0 if subnet_ids else False}")
    print(f"  sg_ids exists: {sg_ids is not None}")
    print(f"  sg_ids is list: {isinstance(sg_ids, list)}")
    print(f"  sg_ids is truthy: {bool(sg_ids)}")
    print(f"  sg_ids has items: {len(sg_ids) > 0 if sg_ids else False}")
    
    # Final verdict
    is_valid = (
        mode_config is not None and
        isinstance(mode_config, dict) and
        subnet_ids is not None and
        isinstance(subnet_ids, list) and
        len(subnet_ids) > 0 and
        sg_ids is not None and
        isinstance(sg_ids, list) and
        len(sg_ids) > 0
    )
    print(f"\n  ✅ Configuration is VALID: {is_valid}")
else:
    print("\n  ❌ network_mode_config is None or empty")

print(f"\nRaw YAML (network_configuration section):")
print("---")
import yaml as yaml2
print(yaml2.dump(network_config, default_flow_style=False, sort_keys=False))
print("---")
