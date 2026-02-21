#!/bin/bash
# Start Glitch UI server with automatic SSO login if needed
set -e

cd "$(dirname "$0")/agent"

AWS_PROFILE="${AWS_PROFILE:-default}"

# Check if AWS credentials are valid
echo "Checking AWS credentials (profile: $AWS_PROFILE)..."
if ! aws sts get-caller-identity &>/dev/null; then
    echo "⚠️  AWS credentials expired. Attempting SSO login..."
    aws sso login --profile "$AWS_PROFILE"
    
    if ! aws sts get-caller-identity &>/dev/null; then
        echo "❌ SSO login failed. Please login manually."
        exit 1
    fi
fi

echo "✓ AWS credentials valid"

# Export credentials to environment so Python inherits them
# This handles SSO credentials that aren't in ~/.aws/credentials
eval "$(aws configure export-credentials --profile "$AWS_PROFILE" --format env 2>/dev/null || true)"

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
