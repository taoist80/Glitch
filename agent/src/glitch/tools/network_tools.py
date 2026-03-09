"""Network diagnostic tools — run via SSH on remote on-prem hosts.

Provides packet capture, ping, and traceroute capabilities for Glitch.
All tools require a configured SSH host (alias or user@host[:port]).
Reuses _run_on_host from ssh_tools for all connection management.
"""
import asyncio
import shlex

from strands import tool
from glitch.tools.ssh_tools import _run_on_host


@tool
def run_packet_capture(
    host: str,
    interface: str = "eth0",
    filter: str = "",
    duration_seconds: int = 10,
    packet_count: int = 100,
    password: str = None,
) -> str:
    """Run a packet capture (tcpdump) on a remote host via SSH.

    Requires tcpdump and sudo (or CAP_NET_RAW) on the remote host.

    Args:
        host: SSH host alias or user@host[:port]
        interface: Network interface (e.g. "eth0", "br0", "any")
        filter: BPF filter expression (e.g. "port 5432", "host 10.0.0.1")
        duration_seconds: Stop after N seconds (capped at 60)
        packet_count: Stop after N packets (capped at 500)
        password: SSH password if key auth not configured
    """
    duration_seconds = max(1, min(duration_seconds, 60))
    packet_count = max(1, min(packet_count, 500))

    parts = ["sudo", "tcpdump", "-l", "-n",
             "-i", shlex.quote(interface),
             "-c", str(packet_count)]
    if filter:
        parts.append(shlex.quote(filter))
    cmd = f"timeout {duration_seconds} {' '.join(parts)} 2>&1 || true"

    async def _capture(conn):
        result = await conn.run(cmd, timeout=duration_seconds + 10)
        return ((result.stdout or "") + (result.stderr or "")).strip() or "(no output)"

    success, output = asyncio.run(_run_on_host(host, _capture, password=password))
    return output if success else f"Packet capture failed: {output}"


@tool
def ping_host(
    source_host: str,
    target: str,
    count: int = 4,
    password: str = None,
) -> str:
    """Ping a target from a remote SSH host to test reachability and latency.

    Args:
        source_host: SSH host alias or user@host[:port]
        target: IP address or hostname to ping
        count: Number of ICMP packets (capped at 20)
        password: SSH password if key auth not configured
    """
    count = max(1, min(count, 20))
    cmd = f"ping -c {count} -W 2 {shlex.quote(target)} 2>&1"

    async def _ping(conn):
        result = await conn.run(cmd, timeout=count * 3 + 5)
        return ((result.stdout or "") + (result.stderr or "")).strip()

    success, output = asyncio.run(_run_on_host(source_host, _ping, password=password))
    return output if success else f"ping failed: {output}"


@tool
def traceroute_host(
    source_host: str,
    target: str,
    max_hops: int = 20,
    password: str = None,
) -> str:
    """Run traceroute from a remote SSH host to map the network path to a target.

    Falls back to tracepath if traceroute is not available (no root required).

    Args:
        source_host: SSH host alias or user@host[:port]
        target: IP address or hostname to trace
        max_hops: Maximum TTL / hop count (capped at 30)
        password: SSH password if key auth not configured
    """
    max_hops = max(1, min(max_hops, 30))
    cmd = (
        f"command -v traceroute >/dev/null 2>&1 "
        f"&& traceroute -m {max_hops} -w 2 {shlex.quote(target)} 2>&1 "
        f"|| tracepath -m {max_hops} {shlex.quote(target)} 2>&1"
    )

    async def _trace(conn):
        result = await conn.run(cmd, timeout=max_hops * 3 + 10)
        return ((result.stdout or "") + (result.stderr or "")).strip()

    success, output = asyncio.run(_run_on_host(source_host, _trace, password=password))
    return output if success else f"traceroute failed: {output}"
