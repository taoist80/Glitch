#!/bin/bash
# Run on the Tailscale EC2 instance to install and start the Glitch UI server.
# Usage: curl -sSL https://raw.githubusercontent.com/taoist80/Glitch/main/scripts/ec2-setup-glitch-ui.sh | sudo bash
#    or: sudo bash ec2-setup-glitch-ui.sh
set -e

REGION="${AWS_REGION:-$(curl -s http://169.254.169.254/latest/meta-data/placement/region)}"
REPO="${GLITCH_REPO:-https://github.com/taoist80/Glitch.git}"
BRANCH="${GLITCH_BRANCH:-main}"

echo "=== Glitch UI server setup (region=$REGION) ==="

echo "Installing Python 3.12, Node, git..."
yum install -y python3.12 python3.12-pip git nodejs npm 2>/dev/null || {
  yum install -y python3.12 python3.12-pip git
  curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
  yum install -y nodejs
}

echo "Cloning Glitch repository..."
cd /opt
if [ -d glitch ]; then
  cd glitch && git fetch && git checkout "$BRANCH" && git pull && cd /opt
else
  git clone -b "$BRANCH" "$REPO" glitch
fi

echo "Setting up Python virtual environment..."
cd /opt/glitch/agent
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install bedrock-agentcore 'fastapi>=0.115.0' "python-telegram-bot[webhooks]"

echo "Building UI..."
cd /opt/glitch/ui
npm install -g pnpm
CI=true pnpm install
pnpm build

echo "Creating systemd service..."
cat > /etc/systemd/system/glitch-ui.service << EOF
[Unit]
Description=Glitch UI Server
After=network.target tailscaled.service
Wants=tailscaled.service

[Service]
Type=simple
User=root
WorkingDirectory=/opt/glitch/agent
Environment=PYTHONPATH=/opt/glitch/agent/src
Environment=GLITCH_UI_MODE=proxy
Environment=GLITCH_MODE=server
Environment=GLITCH_AGENT_NAME=Glitch
Environment=AWS_DEFAULT_REGION=$REGION
ExecStart=/opt/glitch/agent/.venv/bin/python -m glitch
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

echo "Enabling and starting glitch-ui..."
systemctl daemon-reload
systemctl enable glitch-ui
systemctl restart glitch-ui

echo "=== Done ==="
echo "UI should be at: http://$(tailscale ip -4 2>/dev/null || echo '<tailscale-ip>'):8080/"
systemctl status glitch-ui --no-pager
