#!/usr/bin/env bash
# Full system diagnostics: Lambda env vars, DynamoDB tables/items, recent errors from all log groups.
# Run from repo root with AWS CLI configured.
set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
REPO_ROOT="${REPO_ROOT:-$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
AGENT_CONFIG="${REPO_ROOT}/agent/.bedrock_agentcore.yaml"
START_MS=$(($(date +%s) - 7200))000   # last 2 hours

# Resolve runtime log group
RUNTIME_LOG_GROUP=""
if [[ -f "$AGENT_CONFIG" ]]; then
  ARN=$(grep -E '^\s+agent_arn:' "$AGENT_CONFIG" | sed -E 's/.*runtime\/([^[:space:]]+).*/\1/')
  [[ -n "${ARN:-}" ]] && RUNTIME_LOG_GROUP="/aws/bedrock-agentcore/runtimes/${ARN}-DEFAULT"
fi
RUNTIME_LOG_GROUP="${RUNTIME_LOG_GROUP:-/aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT}"

echo "======================================================================"
echo "GLITCH FULL DIAGNOSTICS  region=$REGION  runtime=$RUNTIME_LOG_GROUP"
echo "======================================================================"
echo ""

# ── 1. Lambda environment variables ───────────────────────────────────────
echo "=== 1. Lambda env vars: glitch-gateway ==="
aws lambda get-function-configuration --function-name glitch-gateway \
  --region "$REGION" --query 'Environment.Variables' --output json 2>/dev/null \
  || echo "(failed to get glitch-gateway config)"
echo ""

echo "=== 1b. Lambda env vars: glitch-telegram-webhook ==="
aws lambda get-function-configuration --function-name glitch-telegram-webhook \
  --region "$REGION" --query 'Environment.Variables' --output json 2>/dev/null \
  || echo "(failed to get glitch-telegram-webhook config)"
echo ""

# ── 2. DynamoDB tables ─────────────────────────────────────────────────────
echo "=== 2. DynamoDB tables ==="
aws dynamodb list-tables --region "$REGION" --query 'TableNames' --output json 2>/dev/null \
  || echo "(failed to list DynamoDB tables)"
echo ""

echo "=== 2b. glitch-telegram-config: CONFIG/main item ==="
aws dynamodb get-item --table-name glitch-telegram-config \
  --key '{"pk":{"S":"CONFIG"},"sk":{"S":"main"}}' \
  --region "$REGION" --output json 2>/dev/null | head -30 \
  || echo "(table missing or access denied)"
echo ""

echo "=== 2c. glitch-telegram-config: CONFIG/telegram item ==="
aws dynamodb get-item --table-name glitch-telegram-config \
  --key '{"pk":{"S":"CONFIG"},"sk":{"S":"telegram"}}' \
  --region "$REGION" --output json 2>/dev/null | head -30 \
  || echo "(table missing or access denied)"
echo ""

# ── 2d. SSM Telegram params ───────────────────────────────────────────────
echo "=== 2d. SSM /glitch/telegram/* params ==="
aws ssm get-parameters \
  --names "/glitch/telegram/webhook-url" "/glitch/telegram/config-table" \
  --region "$REGION" \
  --query 'Parameters[*].{Name:Name,Value:Value}' --output json 2>/dev/null \
  || echo "(SSM params not found — deploy GlitchTelegramWebhookStack)"
echo ""

# ── 3. Secrets Manager ─────────────────────────────────────────────────────
echo "=== 3. Secrets Manager: glitch/telegram-bot-token (exists?) ==="
aws secretsmanager describe-secret --secret-id glitch/telegram-bot-token \
  --region "$REGION" --query '{Name:Name,ARN:ARN,LastChangedDate:LastChangedDate}' --output json 2>/dev/null \
  || echo "(secret not found or access denied)"
echo ""

# ── 4. Gateway Lambda errors ───────────────────────────────────────────────
echo "=== 4. Gateway errors (last 2h) ==="
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-gateway" \
  --start-time "$START_MS" --region "$REGION" \
  --filter-pattern "?ERROR ?error ?Error ?failed ?Failed ?exception ?Exception ?timeout ?Timeout" \
  --limit 40 --query 'events[*].message' --output text 2>/dev/null \
  | head -80 || echo "(no matching events or log group missing)"
echo ""

echo "=== 4b. Gateway last 20 events (any) ==="
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-gateway" \
  --start-time "$START_MS" --region "$REGION" \
  --limit 20 --query 'events[*].message' --output text 2>/dev/null \
  | head -60 || echo "(no events)"
echo ""

# ── 5. Runtime errors ──────────────────────────────────────────────────────
echo "=== 5. Runtime errors (last 2h) ==="
aws logs filter-log-events \
  --log-group-name "$RUNTIME_LOG_GROUP" \
  --start-time "$START_MS" --region "$REGION" \
  --filter-pattern "?ERROR ?WARN ?error ?failed ?Failed ?timeout ?Timeout ?exception ?ConnectTimeout ?AccessDenied" \
  --limit 40 --query 'events[*].message' --output text 2>/dev/null \
  | head -100 || echo "(no matching events or log group missing)"
echo ""

# ── 6. Webhook Lambda errors ───────────────────────────────────────────────
echo "=== 6. Telegram webhook errors (last 2h) ==="
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-telegram-webhook" \
  --start-time "$START_MS" --region "$REGION" \
  --filter-pattern "?ERROR ?error ?Error ?failed ?Failed ?timeout ?Timeout ?exception" \
  --limit 30 --query 'events[*].message' --output text 2>/dev/null \
  | head -60 || echo "(no matching events)"
echo ""

echo "=== 6b. Webhook last 20 events (any) ==="
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-telegram-webhook" \
  --start-time "$START_MS" --region "$REGION" \
  --limit 20 --query 'events[*].message' --output text 2>/dev/null \
  | head -40 || echo "(no events)"
echo ""

# ── 7. Runtime: all recent events (last 30) ────────────────────────────────
echo "=== 7. Runtime: last 30 events (any) ==="
aws logs filter-log-events \
  --log-group-name "$RUNTIME_LOG_GROUP" \
  --start-time "$START_MS" --region "$REGION" \
  --limit 30 --query 'events[*].message' --output text 2>/dev/null \
  | head -80 || echo "(no events)"
echo ""

# ── 8. VPC endpoints ──────────────────────────────────────────────────────
echo "=== 8. VPC endpoints in account ==="
aws ec2 describe-vpc-endpoints --region "$REGION" \
  --query 'VpcEndpoints[*].{Service:ServiceName,State:State,Type:VpcEndpointType}' \
  --output table 2>/dev/null || echo "(failed to list endpoints)"
echo ""

echo "======================================================================"
echo "DIAGNOSTICS COMPLETE"
echo "======================================================================"
