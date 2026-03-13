#!/bin/bash
#
# Unified deployment wrapper for AgentCore with auto-configuration.
#
# This script:
# 1. Reads SSM params and writes env vars to .env.deploy (pre-deploy configure)
# 2. Runs `agentcore deploy` passing --env flags from .env.deploy
#
# agentcore deploy rewrites .bedrock_agentcore.yaml on each run and strips
# environment_variables, so env vars must be passed via --env flags.
#
# Usage:
#   ./scripts/deploy.sh [--skip-pre-check] [-- agentcore-deploy-args...]
#
# Options:
#   --skip-pre-check    Skip pre-deploy configuration (reuse existing .env.deploy)
#   --help              Show this help message
#
# Examples:
#   ./scripts/deploy.sh                     # Full workflow (recommended)
#   ./scripts/deploy.sh --skip-pre-check    # Deploy with existing .env.deploy
#   ./scripts/deploy.sh -- --force          # Pass --force to agentcore deploy
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$SCRIPT_DIR")"

SKIP_PRE_CHECK=false
AGENTCORE_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-pre-check)
            SKIP_PRE_CHECK=true
            shift
            ;;
        --help)
            head -n 20 "$0" | tail -n +3 | sed 's/^# //'
            exit 0
            ;;
        --)
            shift
            AGENTCORE_ARGS=("$@")
            break
            ;;
        *)
            AGENTCORE_ARGS+=("$1")
            shift
            ;;
    esac
done

log() {
    echo "[deploy] $*"
}

log_success() {
    echo "[deploy] ✓ $*"
}

log_error() {
    echo "[deploy] ERROR: $*" >&2
}

# Check if agentcore CLI is available
if ! command -v agentcore &> /dev/null; then
    log_error "agentcore CLI not found. Install it first:"
    log_error "  pip install strands-agents"
    exit 1
fi

cd "$AGENT_DIR"

log "Starting AgentCore deployment workflow..."
log "Working directory: $AGENT_DIR"

# Step 1: Pre-deploy configuration
if [ "$SKIP_PRE_CHECK" = false ]; then
    log ""
    log "=== Step 1: Pre-deploy Configuration ==="
    
    if [ -f "$SCRIPT_DIR/pre-deploy-configure.py" ]; then
        python3 "$SCRIPT_DIR/pre-deploy-configure.py"
        PRE_CHECK_EXIT=$?
        
        if [ $PRE_CHECK_EXIT -eq 1 ]; then
            log_error "Pre-deploy configuration failed. Aborting deployment."
            exit 1
        elif [ $PRE_CHECK_EXIT -eq 2 ]; then
            log "Pre-deploy configuration skipped (not applicable)"
        fi
    else
        log "Warning: pre-deploy-configure.py not found. Skipping pre-check."
    fi
else
    log "Skipping pre-deploy configuration (--skip-pre-check)"
fi

# Step 1.5: Upload auri.md to soul bucket (so runtime loads latest Auri persona from S3)
# When run locally, the AWS identity (profile/credentials) must have s3:PutObject and s3:GetObject
# on the soul bucket; when run in CodeBuild, the CodeBuild role has this via GlitchFoundationStack.
# If SSM has "placeholder", derive bucket name: glitch-agent-state-${account}-${region}.
ENV_DEPLOY_FILE="$AGENT_DIR/.env.deploy"
SOUL_BUCKET=""
if [ -f "$ENV_DEPLOY_FILE" ]; then
    SOUL_BUCKET=$(grep -E '^GLITCH_SOUL_S3_BUCKET=' "$ENV_DEPLOY_FILE" | cut -d= -f2- | tr -d '"' | tr -d "'")
fi
if [ -z "$SOUL_BUCKET" ] || [ "$SOUL_BUCKET" = "placeholder" ] || [ "$SOUL_BUCKET" = "changeme" ]; then
    ACCOUNT=$(aws sts get-caller-identity --query Account --output text 2>/dev/null || true)
    # aws configure get region exits non-zero when unset; guard with || true so set -e doesn't abort
    REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-}}"
    if [ -z "$REGION" ]; then
        REGION=$(aws configure get region 2>/dev/null || true)
    fi
    REGION="${REGION:-us-west-2}"
    if [ -n "$ACCOUNT" ]; then
        SOUL_BUCKET="glitch-agent-state-${ACCOUNT}-${REGION}"
        log "Using derived soul bucket: $SOUL_BUCKET"
    fi
fi
if [ -n "$SOUL_BUCKET" ] && [ -f "$AGENT_DIR/auri.md" ]; then
    log ""
    log "=== Uploading auri.md to S3 ==="
    if aws s3 cp "$AGENT_DIR/auri.md" "s3://${SOUL_BUCKET}/auri.md" --content-type "text/markdown"; then
        log_success "auri.md uploaded to s3://${SOUL_BUCKET}/auri.md"
    else
        log_error "Failed to upload auri.md to S3 (check AWS credentials and bucket permissions)"
        exit 1
    fi
elif [ -n "$SOUL_BUCKET" ] && [ ! -f "$AGENT_DIR/auri.md" ]; then
    log "Skipping auri.md upload (file not found)"
else
    log "Skipping auri.md upload (no GLITCH_SOUL_S3_BUCKET in .env.deploy)"
fi

# Step 2: AgentCore deployment
log ""
log "=== Step 2: AgentCore Deployment ==="

# Build --env flags from .env.deploy written by pre-deploy-configure.py.
# agentcore deploy rewrites .bedrock_agentcore.yaml and strips environment_variables,
# so we pass them explicitly via CLI flags which survive the rewrite.
ENV_ARGS=()
ENV_DEPLOY_FILE="$AGENT_DIR/.env.deploy"
if [ -f "$ENV_DEPLOY_FILE" ]; then
    while IFS= read -r line; do
        [[ -z "$line" || "$line" == \#* ]] && continue
        key="${line%%=*}"
        value="${line#*=}"
        [[ -z "$key" ]] && continue
        ENV_ARGS+=(--env "${key}=${value}")
    done < "$ENV_DEPLOY_FILE"
    log "Loaded ${#ENV_ARGS[@]} --env flags from .env.deploy"
else
    log "Warning: .env.deploy not found; environment variables will not be set in runtime"
fi

log "Running: agentcore deploy ${ENV_ARGS[*]} ${AGENTCORE_ARGS[*]}"

if agentcore deploy "${ENV_ARGS[@]}" "${AGENTCORE_ARGS[@]}"; then
    log_success "AgentCore deployment completed"
else
    DEPLOY_EXIT=$?
    log_error "AgentCore deployment failed with exit code $DEPLOY_EXIT"
    exit $DEPLOY_EXIT
fi

log ""
log_success "Deployment workflow completed successfully!"
log ""
log "Agent is now deployed. Next steps:"
log "  • Test invocation: agentcore invoke --message 'Hello'"
log "  • View status: agentcore status"
log "  • Check logs: agentcore logs"
log "  • Monitor: AWS Console → CloudWatch Logs"
