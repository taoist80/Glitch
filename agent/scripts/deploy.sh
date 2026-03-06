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
