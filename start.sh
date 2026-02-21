#!/usr/bin/env bash
# Start Glitch agent with automatic UI build
# Usage: ./start.sh

set -e
cd "$(dirname "$0")/agent"
exec python3 -m glitch "$@"
