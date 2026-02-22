.PHONY: help deploy deploy-only configure verify test clean

help:
	@echo "AgentCore Deployment Targets:"
	@echo ""
	@echo "  make deploy         - Full deployment workflow (configure + deploy + verify)"
	@echo "  make deploy-only    - Deploy without pre/post checks"
	@echo "  make configure      - Configure VPC settings from CloudFormation"
	@echo "  make verify         - Run post-deployment verification"
	@echo "  make test           - Run agent tests"
	@echo "  make clean          - Clean build artifacts"
	@echo ""
	@echo "Note: If deploy fails with 'VPC mode requires both subnets and security groups':"
	@echo "      Just run 'agentcore deploy' directly - config is correct, it's a CLI bug"

deploy:
	@echo "Running full deployment workflow..."
	./scripts/deploy.sh

deploy-only:
	@echo "Running deployment without checks..."
	./scripts/deploy.sh --skip-pre-check --skip-post-check

configure:
	@echo "Configuring VPC settings..."
	python3 scripts/pre-deploy-configure.py

verify:
	@echo "Running post-deployment verification..."
	python3 scripts/post-deploy-verify.py

test:
	@echo "Running agent tests..."
	pytest tests/ -v

clean:
	@echo "Cleaning build artifacts..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
