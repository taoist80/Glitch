#!/bin/bash
#
# New-account deployment: Phase 1 (foundation) → Phase 2 (agent) → Phase 3 (application).
# Run once per new AWS account for a linear deploy with no circular dependencies.
#
# Usage: ./scripts/new-account-deploy.sh [--skip-phase1] [--skip-phase2] [--dry-run]
#
# Prerequisites:
#   - AWS credentials (aws sts get-caller-identity works)
#   - Secrets in AWS Secrets Manager: glitch/tailscale-auth-key, glitch/api-keys,
#     glitch/telegram-bot-token, glitch/porkbun-api (script will warn if missing)
#   - pnpm, cdk, python3, agentcore CLI
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"
AGENT_DIR="$(dirname "$INFRA_DIR")/agent"
PROJECT_ROOT="$(dirname "$INFRA_DIR")"

SKIP_PHASE1=false
SKIP_PHASE2=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --skip-phase1)
      SKIP_PHASE1=true
      shift
      ;;
    --skip-phase2)
      SKIP_PHASE2=true
      shift
      ;;
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--skip-phase1] [--skip-phase2] [--dry-run]"
      exit 1
      ;;
  esac
done

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

run_cmd() {
  if [ "$DRY_RUN" = true ]; then
    echo "[DRY RUN] Would run: $*"
  else
    log "Running: $*"
    "$@"
  fi
}

check_prerequisites() {
  log "Checking prerequisites..."

  if ! command -v aws &>/dev/null; then
    echo "Error: AWS CLI not found. Install it first."
    exit 1
  fi

  if ! command -v cdk &>/dev/null; then
    echo "Error: AWS CDK not found. Install with: npm install -g aws-cdk"
    exit 1
  fi

  if ! command -v pnpm &>/dev/null; then
    echo "Error: pnpm not found."
    exit 1
  fi

  if ! command -v python3 &>/dev/null; then
    echo "Error: Python 3 not found."
    exit 1
  fi

  if ! aws sts get-caller-identity &>/dev/null; then
    echo "Error: AWS credentials not configured. Run 'aws configure' or set AWS_PROFILE."
    exit 1
  fi

  if [ ! -f "$AGENT_DIR/.bedrock_agentcore.yaml" ] && [ ! -f "$AGENT_DIR/.bedrock_agentcore.yaml.template" ]; then
    echo "Error: agent/.bedrock_agentcore.yaml or .template not found."
    exit 1
  fi

  log "Prerequisites OK"
}

warn_secrets() {
  log "Checking for required secrets (optional; deploy may fail later if missing)..."
  local region="${AWS_REGION:-us-west-2}"
  for name in glitch/tailscale-auth-key glitch/api-keys glitch/telegram-bot-token glitch/porkbun-api; do
    if ! aws secretsmanager describe-secret --secret-id "$name" --region "$region" &>/dev/null; then
      log "WARNING: Secret $name not found. Create it before using Tailscale/Telegram/UI."
    fi
  done
}

phase1_foundation() {
  log "=== Phase 1: Foundation (VPC + runtime role + CodeBuild role) ==="
  cd "$INFRA_DIR"
  run_cmd pnpm build
  run_cmd pnpm cdk deploy GlitchVpcStack GlitchAgentCoreIamStack GlitchCodeBuildRoleStack --require-approval never
  log "Phase 1 complete"
}

phase2_agent() {
  log "=== Phase 2: Agent (configure yaml from stack outputs, then agentcore deploy) ==="

  if [ ! -f "$AGENT_DIR/.bedrock_agentcore.yaml" ]; then
    log "Copying agent/.bedrock_agentcore.yaml.template to .bedrock_agentcore.yaml"
    run_cmd cp "$AGENT_DIR/.bedrock_agentcore.yaml.template" "$AGENT_DIR/.bedrock_agentcore.yaml"
  fi

  log "Updating agent config from CloudFormation outputs (execution_role, codebuild role, VPC)..."
  run_cmd bash -c "cd '$AGENT_DIR' && python3 scripts/pre-deploy-configure.py"

  log "Deploying agent (agentcore deploy)..."
  run_cmd bash -c "cd '$AGENT_DIR' && agentcore deploy"

  log "Phase 2 complete"
}

phase3_application() {
  log "=== Phase 3: Application (Gateway, Telegram, Tailscale, UI, etc.) ==="
  cd "$INFRA_DIR"
  run_cmd pnpm cdk deploy --all --require-approval never
  log "Phase 3 complete"
}

main() {
  log "New-account deploy: Phase 1 → Phase 2 → Phase 3"
  check_prerequisites
  warn_secrets

  if [ "$SKIP_PHASE1" = false ]; then
    phase1_foundation
  else
    log "Skipping Phase 1 (--skip-phase1)"
  fi

  if [ "$SKIP_PHASE2" = false ]; then
    phase2_agent
  else
    log "Skipping Phase 2 (--skip-phase2)"
  fi

  phase3_application

  log "Done. Agent and application stacks are deployed."
}

main
