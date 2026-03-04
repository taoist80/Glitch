#!/usr/bin/env bash
#
# Porkbun Dynamic DNS updater.
# Updates an A record (e.g. home.awoo.agency) with your current public IP.
#
# Variables:
#   DOMAIN       - Base domain (e.g. awoo.agency). Pass as first arg or set PORKBUN_DOMAIN.
#   SUBDOMAIN    - Subdomain label only (e.g. home for home.awoo.agency). Pass as second arg or set PORKBUN_SUBDOMAIN.
#   API keys     - Either set PORKBUN_API_KEY + PORKBUN_SECRET_KEY, or PORKBUN_SECRET_ARN (AWS Secrets Manager).
#
# Secrets Manager: secret glitch/porkbun-api must be JSON: {"apikey":"...", "secretapikey":"..."}
#   Optional: PORKBUN_SECRET_ARN (default: glitch/porkbun-api), AWS_REGION (default: us-west-2).
#
# Usage:
#   ./porkbun-ddns-update.sh [DOMAIN] [SUBDOMAIN]
#   # or
#   export PORKBUN_DOMAIN=awoo.agency PORKBUN_SUBDOMAIN=home
#   export PORKBUN_SECRET_ARN=glitch/porkbun-api   # optional if using Secrets Manager
#   ./porkbun-ddns-update.sh
#
# Example (env keys):
#   export PORKBUN_API_KEY="pk1_xxx" PORKBUN_SECRET_KEY="sk1_xxx"
#   ./porkbun-ddns-update.sh awoo.agency home
#
# Example (Secrets Manager; requires aws CLI and jq):
#   ./porkbun-ddns-update.sh awoo.agency home
#   # Script will load keys from glitch/porkbun-api if PORKBUN_API_KEY is not set.
#
# Important: Use a subdomain like "home" for your dynamic IP. Do NOT use "glitch" —
# glitch.awoo.agency must remain a CNAME to CloudFront for the dashboard.
#
# API: https://porkbun.com/api/json/v3/documentation

set -e

DOMAIN="${1:-$PORKBUN_DOMAIN}"
SUBDOMAIN="${2:-$PORKBUN_SUBDOMAIN}"
PORKBUN_SECRET_ARN="${PORKBUN_SECRET_ARN:-glitch/porkbun-api}"
AWS_REGION="${AWS_REGION:-us-west-2}"

[[ -n "$DOMAIN" && -n "$SUBDOMAIN" ]] || { echo "Usage: $0 DOMAIN SUBDOMAIN   or set PORKBUN_DOMAIN and PORKBUN_SUBDOMAIN"; exit 1; }

# Normalize SUBDOMAIN: if user passed FQDN (e.g. glitch.awoo.agency), use first label only (glitch)
if [[ "$SUBDOMAIN" == *.* ]]; then
  SUBDOMAIN="${SUBDOMAIN%%.*}"
fi

# Load API keys: from env, or from AWS Secrets Manager
if [[ -z "$PORKBUN_API_KEY" || -z "$PORKBUN_SECRET_KEY" ]]; then
  if command -v aws >/dev/null 2>&1; then
    secret_json=$(aws secretsmanager get-secret-value --secret-id "$PORKBUN_SECRET_ARN" --region "$AWS_REGION" --query SecretString --output text 2>/dev/null || true)
    if [[ -n "$secret_json" ]]; then
      # Porkbun API expects "apikey" and "secretapikey"; accept common secret key names
      PORKBUN_API_KEY=$(echo "$secret_json" | jq -r '.apikey // .api_key // .apiKey // .API_KEY // .key // empty')
      PORKBUN_SECRET_KEY=$(echo "$secret_json" | jq -r '.secretapikey // .secret_api_key // .secretApiKey // .SECRET_KEY // .secret // empty')
    fi
  fi
fi

if [[ -z "$PORKBUN_API_KEY" || -z "$PORKBUN_SECRET_KEY" ]]; then
  echo "Could not load Porkbun API keys." >&2
  echo "  - Set PORKBUN_API_KEY and PORKBUN_SECRET_KEY, or" >&2
  echo "  - Ensure AWS CLI is configured (e.g. aws sts get-caller-identity) and you have GetSecretValue on $PORKBUN_SECRET_ARN." >&2
  echo "  - Secret must be JSON with keys: apikey and secretapikey (Porkbun names; also accepts api_key/secret_api_key, apiKey/secretApiKey, key/secret)." >&2
  exit 1
fi
API_KEY="$PORKBUN_API_KEY"
SECRET_KEY="$PORKBUN_SECRET_KEY"

BASE_URL="https://api.porkbun.com/api/json/v3"

# Get current public IP (Porkbun ping returns yourIp; fallback to ifconfig.me)
get_public_ip() {
  local ip
  ip=$(curl -sS -X POST "$BASE_URL/ping" \
    -H "Content-Type: application/json" \
    -d "{\"apikey\":\"$API_KEY\",\"secretapikey\":\"$SECRET_KEY\"}" \
    | jq -r '.yourIp // empty')
  if [[ -n "$ip" ]]; then
    echo "$ip"
    return
  fi
  curl -sS ifconfig.me
}

update_a_record() {
  local ip="$1"
  local res
  res=$(curl -sS -X POST "$BASE_URL/dns/editByNameType/$DOMAIN/A/$SUBDOMAIN" \
    -H "Content-Type: application/json" \
    -d "{
      \"apikey\":\"$API_KEY\",
      \"secretapikey\":\"$SECRET_KEY\",
      \"content\":\"$ip\",
      \"ttl\":\"600\"
    }")
  local status
  status=$(echo "$res" | jq -r '.status // "ERROR"')
  if [[ "$status" == "SUCCESS" ]]; then
    echo "Updated $SUBDOMAIN.$DOMAIN A → $ip"
    return 0
  fi
  local msg
  msg=$(echo "$res" | jq -r '.message // .')
  if [[ "$msg" == *"record"* ]] || [[ "$msg" == *"not found"* ]] || [[ "$status" == "ERROR" ]]; then
    create_a_record "$ip"
    return
  fi
  echo "Porkbun API error: $res" >&2
  return 1
}

create_a_record() {
  local ip="$1"
  local res
  res=$(curl -sS -X POST "$BASE_URL/dns/create/$DOMAIN" \
    -H "Content-Type: application/json" \
    -d "{
      \"apikey\":\"$API_KEY\",
      \"secretapikey\":\"$SECRET_KEY\",
      \"name\":\"$SUBDOMAIN\",
      \"type\":\"A\",
      \"content\":\"$ip\",
      \"ttl\":\"600\"
    }")
  local status
  status=$(echo "$res" | jq -r '.status // "ERROR"')
  if [[ "$status" == "SUCCESS" ]]; then
    echo "Created $SUBDOMAIN.$DOMAIN A → $ip"
    return 0
  fi
  echo "Porkbun API create error: $res" >&2
  return 1
}

ip=$(get_public_ip)
if [[ -z "$ip" ]]; then
  echo "Failed to get public IP" >&2
  exit 1
fi
update_a_record "$ip"
