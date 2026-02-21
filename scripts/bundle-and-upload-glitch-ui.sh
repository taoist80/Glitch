#!/bin/bash
# Create a tarball of agent + ui and upload to S3 for EC2 user data.
# Run from repo root. EC2 will use this if present (no git clone needed).
# Usage: ./scripts/bundle-and-upload-glitch-ui.sh [s3-uri]
set -e

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

ACCOUNT="${AWS_ACCOUNT_ID:-$(aws sts get-caller-identity --query Account --output text 2>/dev/null)}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-us-west-2}}"
BUCKET="glitch-agent-state-${ACCOUNT}-${REGION}"
S3_URI="${1:-s3://${BUCKET}/deploy/glitch-ui-bundle.tar.gz}"

echo "=== Bundle Glitch UI for EC2 ==="
echo "Repo root: $REPO_ROOT"
echo "Upload target: $S3_URI"

if command -v pnpm &>/dev/null; then
  echo "Building UI..."
  (cd ui && pnpm install && pnpm build)
else
  echo "pnpm not found; bundle will include source only (EC2 will build)."
fi

echo "Creating tarball (agent + ui at top level)..."
TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT
tar -czf "$TMPDIR/glitch-ui-bundle.tar.gz" \
  --exclude='.git' \
  --exclude='agent/.venv' \
  --exclude='ui/node_modules' \
  --exclude='__pycache__' \
  --exclude='.cursor' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  -C "$REPO_ROOT" \
  agent \
  ui

echo "Uploading..."
aws s3 cp "$TMPDIR/glitch-ui-bundle.tar.gz" "$S3_URI"

echo "Done. Next deploy (or new instance) will use this bundle."
echo "S3 URI: $S3_URI"
