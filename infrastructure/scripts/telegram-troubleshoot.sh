#!/usr/bin/env bash
# Telegram troubleshooting: webhook Lambda, gateway, runtime logs, and DynamoDB.
# Run from repo root or infrastructure/scripts. Uses AWS CLI and agent/.bedrock_agentcore.yaml for runtime.
set -euo pipefail

REGION="${AWS_REGION:-us-west-2}"
REPO_ROOT="${REPO_ROOT:-$(cd -P "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
AGENT_CONFIG="${REPO_ROOT}/agent/.bedrock_agentcore.yaml"
START_MS=$(($(date +%s) - 7200))000   # last 2 hours

# Resolve runtime log group from agent config
RUNTIME_LOG_GROUP=""
if [[ -f "$AGENT_CONFIG" ]]; then
  ARN=$(grep -E '^\s+agent_arn:' "$AGENT_CONFIG" | sed -E 's/.*runtime\/([^[:space:]]+).*/\1/')
  if [[ -n "${ARN:-}" ]]; then
    RUNTIME_LOG_GROUP="/aws/bedrock-agentcore/runtimes/${ARN}-DEFAULT"
  fi
fi
RUNTIME_LOG_GROUP="${RUNTIME_LOG_GROUP:-/aws/bedrock-agentcore/runtimes/Glitch-tC207UDZC5-DEFAULT}"

echo "=== Telegram troubleshooting (region=$REGION, last 2h) ==="
echo "Runtime log group: $RUNTIME_LOG_GROUP"
echo ""

# --- Webhook Lambda ---
echo "--- 1. Webhook Lambda (glitch-telegram-webhook) ---"
WEBHOOK_URL=""
if WEBHOOK_URL=$(aws lambda get-function-url-config --function-name glitch-telegram-webhook --region "$REGION" --query 'FunctionUrl' --output text 2>/dev/null); then
  echo "Function URL: $WEBHOOK_URL"
else
  echo "Could not get Function URL (Lambda missing or no URL config)."
fi

echo "Recent webhook log events (errors + last 20 events):"
err=$(aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-telegram-webhook" \
  --start-time "$START_MS" \
  --region "$REGION" \
  --filter-pattern "?ERROR ?Failed ?timed ?out ?error ?Error" \
  --limit 30 \
  --query 'events[*].message' --output text 2>/dev/null) || true
echo "${err:- (no matching errors) }" | head -50
echo "(--- end errors ---)"
rec=$(aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-telegram-webhook" \
  --start-time "$START_MS" \
  --region "$REGION" \
  --limit 20 \
  --query 'events[*].message' --output text 2>/dev/null) || true
echo "${rec:- (no recent events) }" | head -40
echo ""

# --- Gateway (Telegram tab: GET /api/telegram/config) ---
echo "--- 2. Gateway (glitch-gateway) – Telegram tab requests ---"
aws logs filter-log-events \
  --log-group-name "/aws/lambda/glitch-gateway" \
  --start-time "$START_MS" \
  --region "$REGION" \
  --filter-pattern "telegram" \
  --limit 25 \
  --query 'events[*].message' --output text 2>/dev/null | head -40
echo "(--- end gateway telegram ---)"
echo ""

# --- Runtime: Telegram config API and Telegram invocations ---
echo "--- 3. Runtime ($RUNTIME_LOG_GROUP) – Telegram config + invocations ---"
aws logs filter-log-events \
  --log-group-name "$RUNTIME_LOG_GROUP" \
  --start-time "$START_MS" \
  --region "$REGION" \
  --filter-pattern "telegram" \
  --limit 30 \
  --query 'events[*].message' --output text 2>/dev/null | head -50
echo "(--- end runtime telegram ---)"
echo ""

# --- DynamoDB CONFIG (optional) ---
echo "--- 4. DynamoDB glitch-telegram-config (CONFIG item) ---"
aws dynamodb get-item \
  --table-name glitch-telegram-config \
  --key '{"pk":{"S":"CONFIG"},"sk":{"S":"telegram"}}' \
  --region "$REGION" \
  --output json 2>/dev/null | head -30 || echo "DynamoDB get-item failed (table or key may differ; check CONFIG/sk=telegram in console)."
echo ""

echo "=== Next steps ==="
echo "1. If webhook has no recent events when you send a Telegram message: set webhook with Telegram to $WEBHOOK_URL (e.g. getWebhookInfo: https://api.telegram.org/bot<TOKEN>/getWebhookInfo)."
echo "2. If webhook logs show 'Failed to invoke agent' or timeout: runtime may be cold or overloaded; webhook Lambda timeout was increased to 280s (redeploy TelegramWebhookStack to apply)."
echo "3. If Telegram tab times out: check gateway logs above for GET /api/telegram/config; if absent, request may be failing at nginx or gateway. Runtime logs above should show 'UI API request: GET /telegram/config' when the tab loads."
