#!/usr/bin/env bash
#
# Generate the project SSH key for Glitch agent remote host access.
# Run once per project; then use ssh-copy-key.py to install the public key
# on each host (you will be prompted for the remote user's password).
#
# Usage:
#   ./scripts/ssh-setup.sh
#
# Configuration is written to agent/.env.ssh and loaded automatically by the agent.
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$SCRIPT_DIR")"
KEY_PATH="${AGENT_DIR}/glitch_agent_key"
ENV_SSH="${AGENT_DIR}/.env.ssh"

if [[ -f "${KEY_PATH}" ]]; then
  echo "SSH key already exists: ${KEY_PATH}"
  echo "Public key (add this to remote ~/.ssh/authorized_keys if not using ssh-copy-key.py):"
  cat "${KEY_PATH}.pub"
  echo ""
  echo "To (re)install on a host, run: python scripts/ssh-copy-key.py user@hostname"
  echo "Config: ${ENV_SSH}"
  exit 0
fi

echo "Generating new SSH key at ${KEY_PATH} (ed25519, no passphrase for agent use)."
ssh-keygen -t ed25519 -f "${KEY_PATH}" -N "" -C "glitch-agent"

# Write configuration: key path (absolute) and empty hosts by default
{
  echo "# Written by scripts/ssh-setup.sh — do not commit (gitignored)"
  echo "GLITCH_SSH_KEY_PATH=${KEY_PATH}"
  echo "GLITCH_SSH_HOSTS=[]"
} > "${ENV_SSH}"

# Optionally add one host interactively
echo ""
read -r -p "Add a host now? (y/n) " ADD_HOST
ADD_HOST="${ADD_HOST,,}"
if [[ "${ADD_HOST}" == "y" || "${ADD_HOST}" == "yes" ]]; then
  read -r -p "Host alias (e.g. myserver): " ALIAS
  read -r -p "Hostname or IP: " HOST
  read -r -p "SSH user: " USER
  read -r -p "Port [22]: " PORT
  PORT="${PORT:-22}"
  if [[ -n "${ALIAS}" && -n "${HOST}" && -n "${USER}" ]]; then
    HOSTS_JSON="[{\"alias\":\"${ALIAS}\",\"host\":\"${HOST}\",\"user\":\"${USER}\",\"port\":${PORT}}]"
    {
      echo "# Written by scripts/ssh-setup.sh — do not commit (gitignored)"
      echo "GLITCH_SSH_KEY_PATH=${KEY_PATH}"
      echo "GLITCH_SSH_HOSTS=${HOSTS_JSON}"
    } > "${ENV_SSH}"
    echo "Added host: ${ALIAS} (${USER}@${HOST}:${PORT})"
  else
    echo "Skipped (alias, host, and user are required)."
  fi
fi

echo ""
echo "Configuration written to ${ENV_SSH}"
echo "The agent loads this file automatically when run. For the current shell: source ${ENV_SSH}"
echo ""
echo "Next: install the key on each host (password prompt):"
echo "  cd ${AGENT_DIR} && python scripts/ssh-copy-key.py user@hostname [port]"
echo ""
echo "Public key (for manual install):"
cat "${KEY_PATH}.pub"
