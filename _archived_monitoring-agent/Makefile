.PHONY: help deploy deploy-only configure verify check-logs clean

help:
	@echo "Sentinel Deployment Targets:"
	@echo ""
	@echo "  make deploy      - Full deployment workflow (configure from SSM + agentcore deploy)"
	@echo "  make deploy-only - Deploy with existing .env.deploy (skip configure)"
	@echo "  make configure   - Read SSM params and write .env.deploy"
	@echo "  make verify      - Check agent runtime status"
	@echo "  make check-logs  - Tail Sentinel CloudWatch logs"
	@echo "  make clean       - Clean build artifacts"

deploy:
	@echo "Running full Sentinel deployment workflow..."
	python3 scripts/pre-deploy-configure.py
	@ENV_FLAGS=$$(awk '{printf "--env %s ", $$0}' .env.deploy 2>/dev/null); \
	 echo "Deploying Sentinel..."; \
	 agentcore deploy $$ENV_FLAGS

deploy-only:
	@echo "Deploying Sentinel with existing .env.deploy..."
	@ENV_FLAGS=$$(awk '{printf "--env %s ", $$0}' .env.deploy 2>/dev/null); \
	 agentcore deploy $$ENV_FLAGS

configure:
	@echo "Configuring Sentinel from SSM..."
	python3 scripts/pre-deploy-configure.py

verify:
	@echo "Checking Sentinel runtime status..."
	agentcore status

check-logs:
	@echo "Tailing Sentinel CloudWatch logs..."
	aws logs tail /aws/bedrock-agentcore/runtimes/Sentinel-93XJBKBNNx-DEFAULT \
	  --log-stream-name-prefix "$$(date +%Y/%m/%d)/[runtime-logs]" --follow

clean:
	@echo "Cleaning build artifacts..."
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
