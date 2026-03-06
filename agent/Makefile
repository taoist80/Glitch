.PHONY: help deploy deploy-only configure verify check-logs telegram-troubleshoot test clean

help:
	@echo "AgentCore Deployment Targets:"
	@echo ""
	@echo "  make deploy                - Full deployment workflow (configure + deploy)"
	@echo "  make deploy-only           - Deploy without pre-configure"
	@echo "  make configure             - Configure environment from SSM and update .bedrock_agentcore.yaml"
	@echo "  make verify                - Check agent runtime status"
	@echo "  make check-logs            - Check AgentCore runtime logs in CloudWatch"
	@echo "  make telegram-troubleshoot - Run Telegram webhook/runtime diagnostics"
	@echo "  make test                  - Run agent tests"
	@echo "  make clean                 - Clean build artifacts"

deploy:
	@echo "Running full deployment workflow..."
	./scripts/deploy.sh

deploy-only:
	@echo "Running deployment without pre-configure..."
	./scripts/deploy.sh --skip-pre-check

configure:
	@echo "Configuring environment from SSM..."
	python3 scripts/pre-deploy-configure.py

verify:
	@echo "Checking agent runtime status..."
	agentcore status

check-logs:
	@echo "Checking AgentCore runtime logs..."
	python3 scripts/check-runtime-logs.py

telegram-troubleshoot:
	@echo "Running Telegram diagnostics..."
	bash ../infrastructure/scripts/telegram-troubleshoot.sh

test:
	@echo "Running agent tests..."
	pytest tests/ -v

clean:
	@echo "Cleaning build artifacts..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
