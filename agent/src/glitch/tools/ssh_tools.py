"""SSH tools for the Glitch orchestrator.

Allows the agent to connect to configured remote hosts using a project SSH key,
run commands, and read/write files and directories. Hosts must be registered
and the key must be installed on each host (see scripts/ssh-setup.sh and
scripts/ssh-copy-key.py).

Configuration:
- GLITCH_SSH_HOSTS: JSON array of host entries, e.g.
  [{"alias": "bastion", "host": "10.0.0.1", "user": "ubuntu", "port": 22}]
  Port defaults to 22 if omitted.
- GLITCH_SSH_KEY_PATH: Path to private key file (e.g. agent/glitch_agent_key).
  Used when set; otherwise the agent tries Secrets Manager.
- AWS Secrets Manager: secret id GLITCH_SSH_SECRET_NAME (default glitch/ssh-key)
  with key "private_key" for the PEM body. Grant the runtime secretsmanager:GetSecretValue.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from strands import tool

from glitch.aws_utils import get_client

logger = logging.getLogger(__name__)

ENV_SSH_HOSTS = "GLITCH_SSH_HOSTS"
ENV_SSH_KEY_PATH = "GLITCH_SSH_KEY_PATH"
ENV_SSH_SECRET_NAME = "GLITCH_SSH_SECRET_NAME"
DEFAULT_SSH_SECRET_NAME = "glitch/ssh-key"
SSM_SSH_HOSTS = "/glitch/ssh/hosts"

# Parsed list of {"alias", "host", "user", "port"}
_ssh_hosts_cache: Optional[List[Dict[str, Any]]] = None
_ssh_key_cache: Optional[Any] = None


def _get_ssh_hosts() -> List[Dict[str, Any]]:
    """Return list of configured SSH hosts (alias, host, user, port). Cached."""
    global _ssh_hosts_cache
    if _ssh_hosts_cache is not None:
        return _ssh_hosts_cache

    raw = os.environ.get(ENV_SSH_HOSTS)
    if raw and raw.strip():
        try:
            hosts = json.loads(raw)
            if isinstance(hosts, list):
                out = []
                for h in hosts:
                    if isinstance(h, dict) and h.get("alias") and h.get("host") and h.get("user"):
                        out.append({
                            "alias": str(h["alias"]).strip(),
                            "host": str(h["host"]).strip(),
                            "user": str(h["user"]).strip(),
                            "port": int(h["port"]) if h.get("port") is not None else 22,
                        })
                        out.sort(key=lambda x: x["alias"])
                _ssh_hosts_cache = out
                return _ssh_hosts_cache
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning("Invalid GLITCH_SSH_HOSTS JSON: %s", e)

    try:
        client = get_client("ssm")
        resp = client.get_parameter(Name=SSM_SSH_HOSTS, WithDecryption=False)
        raw = (resp.get("Parameter") or {}).get("Value") or ""
        if raw.strip():
            hosts = json.loads(raw)
            if isinstance(hosts, list):
                out = []
                for h in hosts:
                    if isinstance(h, dict) and h.get("alias") and h.get("host") and h.get("user"):
                        out.append({
                            "alias": str(h["alias"]).strip(),
                            "host": str(h["host"]).strip(),
                            "user": str(h["user"]).strip(),
                            "port": int(h["port"]) if h.get("port") is not None else 22,
                        })
                out.sort(key=lambda x: x["alias"])
                _ssh_hosts_cache = out
                return _ssh_hosts_cache
    except Exception as e:
        logger.debug("Could not load SSH hosts from SSM: %s", e)

    _ssh_hosts_cache = []
    return _ssh_hosts_cache


def _resolve_host(host_alias: str) -> Optional[Dict[str, Any]]:
    """Resolve alias or user@host[:port] to host config dict.

    Accepts either a registered alias (e.g. "bastion") or an ad-hoc
    user@host or user@host:port string. Ad-hoc targets are returned as an
    unregistered host entry so callers can attempt connection without
    requiring pre-registration.
    """
    hosts = _get_ssh_hosts()
    for h in hosts:
        if h["alias"] == host_alias:
            return h
    # Accept ad-hoc user@host[:port] so the agent can connect to new hosts
    # without requiring prior registration.
    parsed = _parse_host_target(host_alias)
    if parsed:
        user, host, port = parsed
        return {"alias": host_alias, "host": host, "user": user, "port": port}
    return None


def _get_ssh_private_key():  # -> Optional[asyncssh.SSHKey]
    """Load private key from file or Secrets Manager. Cached."""
    global _ssh_key_cache
    if _ssh_key_cache is not None:
        return _ssh_key_cache

    import asyncssh

    key_path = os.environ.get(ENV_SSH_KEY_PATH)
    if key_path and os.path.isfile(key_path):
        try:
            _ssh_key_cache = asyncssh.read_private_key(key_path)
            logger.info("Loaded SSH key from %s", key_path)
            return _ssh_key_cache
        except Exception as e:
            logger.warning("Failed to load SSH key from %s: %s", key_path, e)
            return None

    secret_name = os.environ.get(ENV_SSH_SECRET_NAME, DEFAULT_SSH_SECRET_NAME)
    try:
        client = get_client("secretsmanager")
        resp = client.get_secret_value(SecretId=secret_name)
        secret_str = resp.get("SecretString") or ""
        if isinstance(secret_str, dict):
            secret_str = secret_str.get("private_key") or secret_str.get("private_key_pem") or ""
        if secret_str.strip():
            key_data = secret_str.encode("utf-8") if isinstance(secret_str, str) else secret_str
            _ssh_key_cache = asyncssh.import_private_key(key_data)
            logger.info("Loaded SSH key from Secrets Manager %s", secret_name)
            return _ssh_key_cache
    except Exception as e:
        logger.debug("Could not load SSH key from Secrets Manager: %s", e)

    return None


def _get_ssh_public_key_content() -> Optional[str]:
    """Return the project's public key (one line for authorized_keys). From .pub file only."""
    key_path = os.environ.get(ENV_SSH_KEY_PATH)
    if not key_path or not os.path.isfile(key_path):
        return None
    pub_path = key_path if key_path.endswith(".pub") else (key_path + ".pub")
    if not os.path.isfile(pub_path):
        return None
    try:
        return open(pub_path, encoding="utf-8").read().strip()
    except Exception:
        return None


def _parse_host_target(host_target: str) -> Optional[Tuple[str, str, int]]:
    """Parse 'user@host' or 'user@host:port' into (user, host, port). Returns None if invalid."""
    host_target = (host_target or "").strip()
    if not host_target or "@" not in host_target:
        return None
    user, rest = host_target.split("@", 1)
    user = user.strip()
    rest = rest.strip()
    if not user or not rest:
        return None
    if ":" in rest:
        host, port_s = rest.rsplit(":", 1)
        try:
            port = int(port_s.strip())
        except ValueError:
            return None
        host = host.strip()
    else:
        host = rest
        port = 22
    return (user, host, port) if host else None


@tool
async def ssh_install_key(host_target: str, password: str) -> str:
    """Install the project's SSH public key on a remote host using password authentication.

    Use this when adding a new host: the remote user must provide their password so the
    Glitch key can be appended to their ~/.ssh/authorized_keys. After this succeeds, the
    agent can use the other SSH tools if you add the host to GLITCH_SSH_HOSTS.

    Args:
        host_target: Remote target as user@hostname or user@hostname:port (e.g. ubuntu@10.10.0.5).
        password: The remote user's password (used only for this connection; not stored or logged).

    Returns:
        Success message or an error (e.g. key not found, connection failed, auth failed).
    """
    pub = _get_ssh_public_key_content()
    if not pub:
        return (
            "Project public key not found. Run scripts/ssh-setup.sh and set GLITCH_SSH_KEY_PATH "
            "to the private key path (the .pub file must exist alongside it)."
        )
    parsed = _parse_host_target(host_target)
    if not parsed:
        return "Invalid host_target. Use user@hostname or user@hostname:port (e.g. ubuntu@10.10.0.5)."

    user, host, port = parsed
    import asyncssh

    try:
        conn = await asyncssh.connect(
            host,
            port=port,
            username=user,
            password=password,
            known_hosts=None,
        )
    except asyncssh.Error as e:
        logger.warning("SSH install_key connect to %s@%s: %s", user, host, e)
        return f"Connection failed to {user}@{host}:{port}: {e}"
    except Exception as e:
        logger.exception("SSH install_key error")
        return f"Connection error: {e}"

    try:
        await conn.run("mkdir -p -m 700 ~/.ssh")
        home_result = await conn.run("echo $HOME")
        home = (home_result.stdout or "").strip() or "/"
        auth_keys = home.rstrip("/") + "/.ssh/authorized_keys"
        sftp = await conn.start_sftp_client()
        try:
            try:
                f = await sftp.open(auth_keys, "r")
                existing = await f.read()
                await f.close()
            except Exception:
                existing = ""
            if pub in existing or pub.rstrip() in existing:
                return f"Key already present in {user}@{host}:{port} ~/.ssh/authorized_keys."
            new_content = (existing.rstrip() + "\n" + pub + "\n").lstrip()
            f = await sftp.open(auth_keys, "w")
            try:
                await f.write(new_content)
            finally:
                await f.close()
        finally:
            sftp.exit()
        return f"Installed Glitch public key on {user}@{host}:{port}. Add this host to GLITCH_SSH_HOSTS to use it."
    except asyncssh.Error as e:
        return f"Error: {e}"
    except Exception as e:
        logger.exception("SSH install_key write failed")
        return f"Error: {e}"
    finally:
        conn.close()


async def _run_on_host(
    host_alias: str,
    fn,
    *args,
    **kwargs,
) -> Tuple[bool, str]:
    """Run an async callback with an open SSH connection. Returns (success, message).

    Accepts either a registered alias or an ad-hoc user@host[:port] string.
    Tries key-based auth first. If auth fails and a password is supplied via
    the 'password' kwarg, falls back to password auth and installs the public
    key so future connections are key-only.
    """
    resolved = _resolve_host(host_alias)
    if not resolved:
        return False, (
            f"Cannot resolve host '{host_alias}'. "
            "Pass user@hostname or user@hostname:port directly, or check ssh_list_hosts."
        )

    key = _get_ssh_private_key()
    password = kwargs.pop("password", None)

    import asyncssh

    conn = None

    # Try key auth first (works for registered hosts and new hosts where key was already installed).
    if key:
        try:
            conn = await asyncssh.connect(
                resolved["host"],
                port=resolved["port"],
                username=resolved["user"],
                client_keys=[key],
                known_hosts=None,
            )
        except asyncssh.PermissionDenied:
            logger.info("Key auth denied for %s, will try password if provided", resolved["host"])
            conn = None
        except asyncssh.Error as e:
            logger.warning("SSH connect to %s (%s): %s", host_alias, resolved["host"], e)
            return False, f"SSH connection failed to {resolved['user']}@{resolved['host']}:{resolved['port']}: {e}"
        except Exception as e:
            logger.exception("SSH connect error to %s", host_alias)
            return False, f"SSH connection error: {e}"

    # Fall back to password auth if key auth didn't work and a password was supplied.
    if conn is None and password:
        try:
            conn = await asyncssh.connect(
                resolved["host"],
                port=resolved["port"],
                username=resolved["user"],
                password=password,
                known_hosts=None,
            )
            # Auto-install the public key so future connections don't need a password.
            pub = _get_ssh_public_key_content()
            if pub:
                try:
                    await conn.run("mkdir -p -m 700 ~/.ssh")
                    home_res = await conn.run("echo $HOME")
                    home = (home_res.stdout or "").strip() or "~"
                    auth_keys = home.rstrip("/") + "/.ssh/authorized_keys"
                    sftp = await conn.start_sftp_client()
                    try:
                        try:
                            f = await sftp.open(auth_keys, "r")
                            existing = await f.read()
                            await f.close()
                        except Exception:
                            existing = ""
                        if pub not in existing:
                            new_content = (existing.rstrip() + "\n" + pub + "\n").lstrip()
                            f = await sftp.open(auth_keys, "w")
                            try:
                                await f.write(new_content)
                            finally:
                                await f.close()
                            logger.info("Auto-installed public key on %s", resolved["host"])
                    finally:
                        sftp.exit()
                except Exception as e:
                    logger.warning("Auto key install on %s failed: %s", resolved["host"], e)
        except asyncssh.Error as e:
            return False, (
                f"SSH auth failed for {resolved['user']}@{resolved['host']}:{resolved['port']}: {e}. "
                "Provide the correct password so the agent can install its public key."
            )
        except Exception as e:
            return False, f"SSH connection error: {e}"

    if conn is None:
        return False, (
            f"Cannot authenticate to {resolved['user']}@{resolved['host']}:{resolved['port']}. "
            "Key auth failed and no password was provided. "
            "Call ssh_run_command with password='<password>' to install the key automatically."
        )

    try:
        result = await fn(conn, *args, **kwargs)
        return True, result
    except asyncssh.Error as e:
        return False, str(e)
    except Exception as e:
        logger.exception("SSH operation on %s failed", host_alias)
        return False, f"{type(e).__name__}: {e}"
    finally:
        conn.close()


@tool
async def ssh_list_hosts() -> str:
    """List the SSH hosts the agent is configured to connect to.

    Returns a list of host aliases and connection details (user@host:port).
    These aliases (or user@host strings directly) can be used with ssh_run_command,
    ssh_read_file, ssh_write_file, and ssh_mkdir.
    """
    hosts = _get_ssh_hosts()
    if not hosts:
        return (
            "No pre-registered SSH hosts.\n\n"
            "Pass user@hostname or user@hostname:port directly to "
            "ssh_run_command. Key auth is tried first; if it fails, pass password='<password>' "
            "to install the key automatically."
        )
    lines = [
        f"- {h['alias']}: {h['user']}@{h['host']}:{h['port']}"
        for h in hosts
    ]
    return "Configured SSH hosts:\n" + "\n".join(lines)


@tool
async def ssh_run_command(host: str, command: str, password: Optional[str] = None) -> str:
    """Run a shell command on a remote host over SSH.

    Accepts a registered host
    alias OR an ad-hoc user@host or user@host:port string. Key auth is tried first;
    if it fails and a password is provided, the key is installed automatically.

    Args:
        host: Host alias (e.g. "bastion") or user@hostname[:port] (e.g. "ubuntu@10.0.0.5").
        command: Shell command to run.
        password: Optional password for first-time key installation. Only needed if key
                  auth fails (i.e. the public key hasn't been installed on this host yet).

    Returns:
        Combined stdout and stderr, or an error message if connection or command failed.
    """
    async def _run(conn):
        result = await conn.run(command)
        out = (result.stdout or "").strip()
        err = (result.stderr or "").strip()
        if result.exit_status != 0:
            return f"exit_code={result.exit_status}\nstdout:\n{out}\nstderr:\n{err}"
        return out or "(no output)"

    ok, msg = await _run_on_host(host, _run, password=password)
    return msg


@tool
async def ssh_read_file(host: str, remote_path: str, password: Optional[str] = None) -> str:
    """Read the contents of a file on a remote host.

    Args:
        host: Host alias or user@hostname[:port].
        remote_path: Absolute or relative path on the remote host (e.g. /etc/hostname, ~/config.yaml).
        password: Optional password for first-time key installation.

    Returns:
        File contents as text, or an error message.
    """
    async def _read(conn):
        result = await conn.run(f"cat -- {remote_path!r}")
        if result.exit_status != 0:
            return f"exit_code={result.exit_status}\nstderr: {result.stderr or 'unknown'}"
        return (result.stdout or "")

    ok, msg = await _run_on_host(host, _read, password=password)
    return msg


@tool
async def ssh_write_file(host: str, remote_path: str, content: str, password: Optional[str] = None) -> str:
    """Write content to a file on a remote host. Creates parent directories if needed.

    Args:
        host: Host alias or user@hostname[:port].
        remote_path: Path on the remote host (e.g. /tmp/out.txt, ~/mcp_servers.yaml).
        content: Full file content to write (text).
        password: Optional password for first-time key installation.

    Returns:
        Success message or error.
    """
    async def _write(conn):
        import posixpath
        parent = posixpath.dirname(remote_path)
        if parent and parent != "/":
            await conn.run(f"mkdir -p -- {parent!r}")
        sftp = await conn.start_sftp_client()
        try:
            f = await sftp.open(remote_path, "w")
            try:
                await f.write(content)
            finally:
                await f.close()
            return f"Wrote {len(content)} bytes to {remote_path}"
        finally:
            sftp.exit()

    ok, msg = await _run_on_host(host, _write, password=password)
    return msg if ok else f"Error: {msg}"


@tool
async def ssh_mkdir(host: str, remote_path: str, password: Optional[str] = None) -> str:
    """Create a directory on a remote host (like mkdir -p).

    Args:
        host: Host alias or user@hostname[:port].
        remote_path: Directory path on the remote host (e.g. /tmp/glitch, ~/config/mcp).
        password: Optional password for first-time key installation.

    Returns:
        Success message or error.
    """
    async def _mkdir(conn):
        await conn.run(f"mkdir -p -- {remote_path!r}")
        return f"Created directory {remote_path}"

    ok, msg = await _run_on_host(host, _mkdir, password=password)
    return msg if ok else f"Error: {msg}"


@tool
async def ssh_file_exists(host: str, remote_path: str, password: Optional[str] = None) -> str:
    """Check whether a path on a remote host exists (file or directory).

    Args:
        host: Host alias or user@hostname[:port].
        remote_path: Path on the remote host.
        password: Optional password for first-time key installation.

    Returns:
        'yes' or 'no', or an error message if the host is unknown or connection failed.
    """
    async def _exists(conn):
        result = await conn.run(f"test -e {remote_path!r} && echo yes || echo no")
        return (result.stdout or "").strip() or "no"

    ok, msg = await _run_on_host(host, _exists, password=password)
    if not ok:
        return f"Error: {msg}"
    return msg


@tool
async def ssh_list_dir(host: str, remote_path: str, password: Optional[str] = None) -> str:
    """List entries in a directory on a remote host (names only, one per line).

    Args:
        host: Host alias or user@hostname[:port].
        remote_path: Directory path on the remote host (e.g. /tmp, ~/.cursor).
        password: Optional password for first-time key installation.

    Returns:
        Newline-separated list of entry names, or an error message.
    """
    async def _listdir(conn):
        sftp = await conn.start_sftp_client()
        try:
            entries = await sftp.readdir(remote_path)
            return "\n".join(e.filename for e in entries) if entries else "(empty)"
        finally:
            sftp.exit()

    ok, msg = await _run_on_host(host, _listdir, password=password)
    return msg if ok else f"Error: {msg}"
