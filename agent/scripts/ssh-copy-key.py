#!/usr/bin/env python3
"""
Install the Glitch project SSH public key on a remote host.

Prompts for the remote user's password (required to add the key to
~/.ssh/authorized_keys on the host). Use after running ssh-setup.sh.

Usage:
  python scripts/ssh-copy-key.py user@hostname [port]

Example:
  python scripts/ssh-copy-key.py ubuntu@10.10.0.5
  python scripts/ssh-copy-key.py ubuntu@10.10.0.5 22
"""

import os
import subprocess
import sys
from pathlib import Path


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    agent_dir = script_dir.parent
    key_path = os.environ.get("GLITCH_SSH_KEY_PATH")
    if not key_path or not os.path.isfile(key_path):
        key_path = agent_dir / "glitch_agent_key"
    else:
        key_path = Path(key_path)
    pub = key_path.with_suffix(key_path.suffix + ".pub")
    if not pub.exists():
        print(f"Public key not found: {pub}", file=sys.stderr)
        print("Run scripts/ssh-setup.sh first to generate the key.", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        print("Usage: python scripts/ssh-copy-key.py user@hostname [port]", file=sys.stderr)
        return 1
    target = sys.argv[1]
    port = sys.argv[2] if len(sys.argv) > 2 else None

    cmd = ["ssh-copy-id", "-i", str(pub)]
    if port:
        cmd.extend(["-p", port])
    cmd.append(target)

    print(f"Installing key {pub} to {target} (you will be prompted for the remote password).")
    result = subprocess.run(cmd)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
