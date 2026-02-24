#!/bin/bash
# Enable HTTPS (port 443) for glitch-proxy on the Tailscale EC2.
# Run on the EC2: sudo bash enable-https-glitch-proxy.sh
# Prereqs: Porkbun creds in /etc/letsencrypt/porkbun.ini
# S3/Lambda: from /etc/nginx/conf.d/glitch-proxy.conf if present, else set S3_WEBSITE_HOST and LAMBDA_HOST (e.g. from CloudFormation outputs).

set -e

CONF=/etc/nginx/conf.d/glitch-proxy.conf
DOMAIN=glitch.awoo.agency

# 1. Get S3 website host and Lambda host: from existing config or from environment
if [ -f "$CONF" ]; then
  S3_WEBSITE_HOST=$(grep -E 'proxy_pass http://.*s3-website' "$CONF" | head -1 | sed -n 's/.*http:\/\/\([^/;]*\).*/\1/p')
  LAMBDA_HOST=$(grep -E 'proxy_pass https://.*lambda-url' "$CONF" | head -1 | sed -n 's/.*https:\/\/\([^/]*\).*/\1/p')
fi

if [ -z "$S3_WEBSITE_HOST" ] || [ -z "$LAMBDA_HOST" ]; then
  if [ -z "$S3_WEBSITE_HOST" ] && [ -z "$LAMBDA_HOST" ] && [ ! -f "$CONF" ]; then
    echo "Missing $CONF and S3_WEBSITE_HOST/LAMBDA_HOST not set."
    echo "Set them from your stack outputs and re-run, e.g.:"
    echo "  export S3_WEBSITE_HOST=\$(aws cloudformation describe-stacks --stack-name GlitchUiHostingStack --region us-west-2 --query \"Stacks[0].Outputs[?OutputKey=='UiBucketName'].OutputValue\" --output text).s3-website-us-west-2.amazonaws.com"
    echo "  export LAMBDA_HOST=<your-gateway-lambda-url-host from GlitchGatewayStack>"
    echo "  sudo -E bash $0"
    exit 1
  fi
  echo "Could not get S3_WEBSITE_HOST or LAMBDA_HOST (from config or env)."
  echo "S3_WEBSITE_HOST=$S3_WEBSITE_HOST LAMBDA_HOST=$LAMBDA_HOST"
  exit 1
fi

echo "S3_WEBSITE_HOST=$S3_WEBSITE_HOST"
echo "LAMBDA_HOST=$LAMBDA_HOST"

GATEWAY_URL="https://${LAMBDA_HOST}"

# 2. Obtain certs if not present
if [ ! -f "/etc/letsencrypt/live/${DOMAIN}/fullchain.pem" ]; then
  echo "Obtaining certificate for ${DOMAIN}..."
  certbot certonly --non-interactive --agree-tos --email admin@awoo.agency \
    --authenticator dns-porkbun \
    --dns-porkbun-credentials /etc/letsencrypt/porkbun.ini \
    -d "$DOMAIN"
else
  echo "Certificate already exists for ${DOMAIN}"
fi

# 3. Write TLS nginx config
echo "Writing TLS config to $CONF ..."
cat > "$CONF" << EOF
# Redirect HTTP to HTTPS
server {
    listen 80;
    server_name ${DOMAIN} _;
    return 301 https://${DOMAIN}\$request_uri;
}

server {
    listen 443 ssl;
    http2 on;
    server_name ${DOMAIN} _;

    ssl_certificate /etc/letsencrypt/live/${DOMAIN}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/${DOMAIN}/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    location / {
        proxy_pass http://${S3_WEBSITE_HOST};
        proxy_set_header Host ${S3_WEBSITE_HOST};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    location /api/ {
        proxy_pass ${GATEWAY_URL}/api/;
        proxy_set_header Host ${LAMBDA_HOST};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_ssl_server_name on;
    }

    location /invocations {
        proxy_pass ${GATEWAY_URL}/invocations;
        proxy_set_header Host ${LAMBDA_HOST};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_ssl_server_name on;
        proxy_read_timeout 300s;
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
    }

    location /health {
        proxy_pass ${GATEWAY_URL}/health;
        proxy_set_header Host ${LAMBDA_HOST};
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
        proxy_ssl_server_name on;
    }
}
EOF

# 4. Test and reload nginx
nginx -t && systemctl reload nginx
echo "Nginx reloaded. Checking listeners..."
ss -lntp | grep -E ':80|:443' || true
echo "Done. Test from your machine: curl -vI https://${DOMAIN}/"