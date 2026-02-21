#!/bin/bash
# Start Glitch UI server with AWS credential validation
set -e

cd "$(dirname "$0")/agent"

# Check if AWS credentials are valid
echo "Checking AWS credentials..."
if ! aws sts get-caller-identity &>/dev/null; then
    echo "❌ AWS credentials are invalid or expired."
    echo ""
    echo "Please refresh your credentials first:"
    echo "  aws sso login"
    echo ""
    echo "Then run this script again."
    exit 1
fi

echo "✓ AWS credentials valid"

# Kill any existing server on port 8080
if lsof -ti :8080 &>/dev/null; then
    echo "Stopping existing server on port 8080..."
    lsof -ti :8080 | xargs kill -9 2>/dev/null || true
    sleep 2
fi

echo "Starting Glitch UI server..."
echo "UI will be available at: http://localhost:8080/"
echo ""

PYTHONPATH=src GLITCH_UI_MODE=proxy GLITCH_MODE=server .venv/bin/python -m glitch
