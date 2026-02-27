"""Tailscale/infrastructure tools for the Glitch agent.

Allows the orchestration agent to trigger SSL cert generation on the Tailscale EC2
proxy (e.g. on deploy) via SSM Run Command.
"""

import asyncio
import logging
import os
import time
from typing import List, Optional

import boto3
from strands import tool

logger = logging.getLogger(__name__)

REGION = os.environ.get("AWS_REGION", "us-west-2")
SSM_INSTANCE_ID_PARAM = "/glitch/tailscale/instance-id"
SCRIPT_PATH = "/usr/local/bin/ensure-glitch-tls.sh"
POLL_INTERVAL = 5
MAX_WAIT_SECONDS = 180


def _get_instance_id() -> Optional[str]:
    """Read Tailscale EC2 instance ID from SSM Parameter Store."""
    try:
        client = boto3.client("ssm", region_name=REGION)
        resp = client.get_parameter(Name=SSM_INSTANCE_ID_PARAM)
        return resp["Parameter"]["Value"].strip()
    except Exception as e:
        logger.warning("Failed to get %s: %s", SSM_INSTANCE_ID_PARAM, e)
        return None


def _run_ensure_tls_sync() -> str:
    """Synchronously send SSM command and optionally wait for completion."""
    instance_id = _get_instance_id()
    if not instance_id:
        return (
            f"Could not read Tailscale instance ID from SSM parameter {SSM_INSTANCE_ID_PARAM}. "
            "Ensure the Tailscale stack has been deployed and the instance ID is written to SSM."
        )

    ssm = boto3.client("ssm", region_name=REGION)
    try:
        cmd = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={
                "commands": [f"sudo {SCRIPT_PATH}"],
            },
            TimeoutSeconds=120,
        )
        command_id = cmd["Command"]["CommandId"]
    except Exception as e:
        return f"SSM SendCommand failed: {e}"

    # Poll for completion
    for _ in range(MAX_WAIT_SECONDS // POLL_INTERVAL):
        try:
            inv = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
            status = inv["Status"]
            if status in ("Success", "Failed", "TimedOut", "Cancelled"):
                out = (inv.get("StandardOutputContent") or "").strip()
                err = (inv.get("StandardErrorContent") or "").strip()
                if status == "Success":
                    return f"SSL cert generation completed. CommandId={command_id}. Output: {out[:500]}" + ("..." if len(out) > 500 else "")
                return f"SSL cert generation ended with status={status}. CommandId={command_id}. Stderr: {err[:500]}"
        except Exception as e:
            logger.warning("GetCommandInvocation failed: %s", e)
        time.sleep(POLL_INTERVAL)

    return (
        f"Command {command_id} was sent and is still running (waited up to {MAX_WAIT_SECONDS}s). "
        "Check SSM Run Command in the AWS Console for final status."
    )


def _run_ssm_commands_sync(commands: List[str]) -> str:
    """Run shell commands on the Tailscale EC2 via SSM and return combined output.

    Commands are prefixed with 'sudo' automatically so they run with root privileges
    (AWS-RunShellScript runs as ssm-user on Amazon Linux 2023, not root).
    """
    instance_id = _get_instance_id()
    if not instance_id:
        return (
            f"Could not read Tailscale instance ID from SSM parameter {SSM_INSTANCE_ID_PARAM}. "
            "Ensure the Tailscale stack has been deployed."
        )
    if not commands:
        return "No commands provided."

    # Prefix each command with sudo so they run with root privileges.
    # ssm-user on Amazon Linux 2023 is not root; most nginx/certbot/systemctl
    # commands require elevated privileges.
    sudoed = [
        cmd if cmd.startswith("sudo ") or cmd.startswith("#") or not cmd.strip()
        else f"sudo {cmd}"
        for cmd in commands
    ]

    ssm = boto3.client("ssm", region_name=REGION)
    try:
        cmd = ssm.send_command(
            InstanceIds=[instance_id],
            DocumentName="AWS-RunShellScript",
            Parameters={"commands": sudoed},
            TimeoutSeconds=60,
        )
        command_id = cmd["Command"]["CommandId"]
    except Exception as e:
        return f"SSM SendCommand failed: {e}"
    for _ in range(MAX_WAIT_SECONDS // POLL_INTERVAL):
        try:
            inv = ssm.get_command_invocation(
                CommandId=command_id,
                InstanceId=instance_id,
            )
            status = inv["Status"]
            if status in ("Success", "Failed", "TimedOut", "Cancelled"):
                out = (inv.get("StandardOutputContent") or "").strip()
                err = (inv.get("StandardErrorContent") or "").strip()
                return f"Status: {status}\nStdout:\n{out}\nStderr:\n{err}"
        except Exception as e:
            logger.warning("GetCommandInvocation failed: %s", e)
        time.sleep(POLL_INTERVAL)
    return f"Command {command_id} timed out (waited {MAX_WAIT_SECONDS}s)."


@tool
async def run_tailscale_ssm_command(commands: List[str]) -> str:
    """Run one or more shell commands on the Tailscale EC2 instance via SSM Run Command.

    Use for troubleshooting (e.g. nginx status, listeners, config test, logs). Instance ID
    is read from SSM parameter /glitch/tailscale/instance-id. Commands are automatically
    prefixed with sudo — do NOT add sudo yourself. Avoid interactive or long-running commands.

    Args:
        commands: List of shell command strings to run in order on the instance.
                  Do not prefix with sudo; it is added automatically.

    Returns:
        Combined status, stdout, and stderr from the SSM command invocation.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_ssm_commands_sync, commands)


RENEW_SCRIPT = "/usr/local/bin/renew-glitch-tls.sh"

# Python patch that bypasses Tailscale's DNS interception for certbot renewal.
# Installed on the instance by userData as renew-glitch-tls.sh; also embedded here
# so the agent can install it on-demand if the script is missing.
_RENEW_SCRIPT_CONTENT = r"""#!/bin/bash
# Renew Let's Encrypt cert via Porkbun DNS-01, bypassing Tailscale DNS interception.
set -e
python3 - << 'PYEOF'
import dns.resolver
_orig = dns.resolver.Resolver.__init__
def _p(self, filename=None, configure=True):
    _orig(self, filename=filename, configure=configure)
    self.nameservers = ["8.8.8.8", "8.8.4.4"]
    self.timeout = 10
    self.lifetime = 30
dns.resolver.Resolver.__init__ = _p
dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
dns.resolver.default_resolver.nameservers = ["8.8.8.8", "8.8.4.4"]
dns.resolver.default_resolver.timeout = 10
dns.resolver.default_resolver.lifetime = 30
import certbot.main, sys
sys.argv = ["certbot", "renew", "--quiet",
    "--authenticator", "dns-porkbun",
    "--dns-porkbun-credentials", "/etc/letsencrypt/porkbun.ini",
    "--dns-porkbun-propagation-seconds", "600",
    "--post-hook", "systemctl reload nginx"]
certbot.main.main()
PYEOF
"""


def _run_renew_tls_sync() -> str:
    """Install renew script if missing, then run it via SSM."""
    instance_id = _get_instance_id()
    if not instance_id:
        return (
            f"Could not read Tailscale instance ID from SSM parameter {SSM_INSTANCE_ID_PARAM}."
        )
    # Build commands: install script if missing, then run it
    install_cmd = (
        f"if [ ! -f {RENEW_SCRIPT} ]; then "
        f"cat > {RENEW_SCRIPT} << 'RENEWEOF'\n{_RENEW_SCRIPT_CONTENT}\nRENEWEOF\n"
        f"chmod +x {RENEW_SCRIPT}; fi"
    )
    return _run_ssm_commands_sync([
        install_cmd,
        f"{RENEW_SCRIPT}",
    ])


@tool
async def run_tailscale_renew_tls() -> str:
    """Renew the Let's Encrypt SSL certificate for glitch.awoo.agency on the Tailscale EC2.

    Runs /usr/local/bin/renew-glitch-tls.sh via SSM Run Command. The script uses a
    dnspython patch to bypass Tailscale's DNS interception so certbot can verify the
    Porkbun DNS-01 challenge. Installs the script on-demand if it is missing.
    Call this when the cert is near expiry (< 30 days) or has expired.

    Returns:
        Status, stdout, and stderr from the renewal run.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_renew_tls_sync)


@tool
async def run_tailscale_ensure_tls() -> str:
    """Run the ensure-glitch-tls script on the Tailscale EC2 instance to obtain or refresh the SSL certificate for glitch.awoo.agency.

    Uses SSM Run Command. The instance ID is read from SSM parameter /glitch/tailscale/instance-id (written by the Tailscale stack on deploy).
    Call this after deploying or replacing the Tailscale EC2 so that HTTPS is enabled without waiting for the 5-minute bootstrap delay.

    Returns:
        A short status message (success, failure, or still running).
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_ensure_tls_sync)
