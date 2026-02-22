#!/bin/bash
#
# Full deployment and verification script for VPC/Tailscale/AgentCore infrastructure.
# This script automates the deployment order and runs verification tests.
#
# Usage:
#   ./scripts/deploy-and-verify.sh [--skip-deploy] [--skip-tests]
#
# Options:
#   --skip-deploy   Skip CDK deployment (only run verification)
#   --skip-tests    Skip verification tests (only deploy)
#   --dry-run       Show what would be done without executing
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(dirname "$SCRIPT_DIR")"
AGENT_DIR="$(dirname "$INFRA_DIR")/agent"
PROJECT_ROOT="$(dirname "$INFRA_DIR")"

SKIP_DEPLOY=false
SKIP_TESTS=false
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-deploy)
            SKIP_DEPLOY=true
            shift
            ;;
        --skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            echo "Unknown option: $1"
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
    
    if ! command -v aws &> /dev/null; then
        echo "Error: AWS CLI not found. Install it first."
        exit 1
    fi
    
    if ! command -v cdk &> /dev/null; then
        echo "Error: AWS CDK not found. Install it with: npm install -g aws-cdk"
        exit 1
    fi
    
    if ! command -v python3 &> /dev/null; then
        echo "Error: Python 3 not found."
        exit 1
    fi
    
    if ! aws sts get-caller-identity &> /dev/null; then
        echo "Error: AWS credentials not configured. Run 'aws configure' or set AWS_PROFILE."
        exit 1
    fi
    
    log "Prerequisites OK"
}

deploy_stacks() {
    log "Starting CDK deployment..."
    
    cd "$INFRA_DIR"
    
    log "Building TypeScript..."
    run_cmd pnpm build
    
    log "Deploying VPC stack..."
    run_cmd cdk deploy GlitchVpcStack --require-approval never
    
    log "Deploying Secrets stack..."
    run_cmd cdk deploy GlitchSecretsStack --require-approval never
    
    log "Deploying Tailscale stack..."
    run_cmd cdk deploy GlitchTailscaleStack --require-approval never
    
    log "Deploying AgentCore stack..."
    run_cmd cdk deploy GlitchAgentCoreStack --require-approval never
    
    log "CDK deployment complete"
}

configure_agentcore() {
    log "Configuring AgentCore VPC settings..."
    
    cd "$INFRA_DIR"
    
    run_cmd python3 scripts/configure_agentcore_vpc.py
    
    log "AgentCore configuration complete"
}

run_unit_tests() {
    log "Running CDK unit tests..."
    
    cd "$INFRA_DIR"
    
    run_cmd pnpm test
    
    log "Unit tests complete"
}

run_integration_tests() {
    log "Running integration tests..."
    
    cd "$INFRA_DIR"
    
    if ! command -v pytest &> /dev/null; then
        log "Installing pytest..."
        pip3 install pytest boto3 pyyaml
    fi
    
    run_cmd pytest test/test_integration.py -v --tb=short
    
    log "Integration tests complete"
}

print_next_steps() {
    echo ""
    echo "=========================================="
    echo "Deployment and verification complete!"
    echo "=========================================="
    echo ""
    echo "Manual steps required:"
    echo ""
    echo "1. TAILSCALE ROUTE APPROVAL:"
    echo "   - Open https://admin.tailscale.com"
    echo "   - Find the 'glitch-tailscale' node"
    echo "   - Approve the 10.10.110.0/24 subnet route"
    echo ""
    echo "2. DEPLOY AGENTCORE RUNTIME:"
    echo "   cd $AGENT_DIR"
    echo "   agentcore deploy"
    echo ""
    echo "3. VERIFY CONNECTIVITY:"
    echo "   - Test Ollama: curl http://10.10.110.202:11434/api/tags"
    echo "   - Test Bedrock: Send a message via UI or Telegram"
    echo "   - Check Memory: View CloudWatch logs"
    echo ""
}

main() {
    log "Starting deployment and verification..."
    
    check_prerequisites
    
    if [ "$SKIP_DEPLOY" = false ]; then
        deploy_stacks
        configure_agentcore
    else
        log "Skipping deployment (--skip-deploy)"
    fi
    
    if [ "$SKIP_TESTS" = false ]; then
        run_unit_tests
        run_integration_tests
    else
        log "Skipping tests (--skip-tests)"
    fi
    
    print_next_steps
}

main
