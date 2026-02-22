#!/bin/bash
#
# Unified deployment wrapper for AgentCore with auto-configuration and verification.
#
# This script:
# 1. Auto-configures VPC settings from CloudFormation (pre-deploy)
# 2. Runs `agentcore deploy`
# 3. Verifies deployment and connectivity (post-deploy)
#
# Usage:
#   ./scripts/deploy.sh [--skip-pre-check] [--skip-post-check] [agentcore-deploy-args...]
#
# Options:
#   --skip-pre-check    Skip pre-deploy configuration check
#   --skip-post-check   Skip post-deploy verification
#   --help              Show this help message
#
# Examples:
#   ./scripts/deploy.sh                        # Full workflow
#   ./scripts/deploy.sh --skip-post-check      # Skip verification
#   ./scripts/deploy.sh -- --force             # Pass --force to agentcore deploy
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$SCRIPT_DIR")"

SKIP_PRE_CHECK=false
SKIP_POST_CHECK=false
AGENTCORE_ARGS=()

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-pre-check)
            SKIP_PRE_CHECK=true
            shift
            ;;
        --skip-post-check)
            SKIP_POST_CHECK=true
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
log "Running: agentcore deploy ${AGENTCORE_ARGS[*]}"

if agentcore deploy "${AGENTCORE_ARGS[@]}"; then
    log_success "AgentCore deployment completed"
else
    DEPLOY_EXIT=$?
    log_error "AgentCore deployment failed with exit code $DEPLOY_EXIT"
    exit $DEPLOY_EXIT
fi

# Step 3: Post-deploy verification
if [ "$SKIP_POST_CHECK" = false ]; then
    log ""
    log "=== Step 3: Post-deploy Verification ==="
    
    if [ -f "$SCRIPT_DIR/post-deploy-verify.py" ]; then
        python3 "$SCRIPT_DIR/post-deploy-verify.py"
        POST_CHECK_EXIT=$?
        
        if [ $POST_CHECK_EXIT -eq 1 ]; then
            log_error "Post-deploy verification failed"
            log_error "Deployment completed but issues detected"
            exit 1
        elif [ $POST_CHECK_EXIT -eq 2 ]; then
            log "Post-deploy verification completed with warnings"
        fi
    else
        log "Warning: post-deploy-verify.py not found. Skipping post-check."
    fi
else
    log "Skipping post-deploy verification (--skip-post-check)"
fi

log ""
log_success "Deployment workflow completed successfully!"
log ""
log "Agent is now deployed. Next steps:"
log "  • Test invocation: agentcore invoke --message 'Hello'"
log "  • View status: agentcore status"
log "  • Check logs: agentcore logs"
log "  • Monitor: AWS Console → CloudWatch Logs"
