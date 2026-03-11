"""Local network diagnostic tools for Glitch.

Runs directly inside the AgentCore container — no SSH required.
Use these for self-diagnosis (e.g. "can I reach home.awoo.agency:32443?")
before escalating to SSH-based tools on remote hosts.
"""

import asyncio
import json
import logging
import shlex
import socket
import subprocess
import time
from typing import Optional

import httpx
from strands import tool

logger = logging.getLogger(__name__)

_BODY_LIMIT = 2000  # max response body chars returned to the agent


@tool
def net_tcp_check(host: str, port: int, timeout: float = 10.0) -> str:
    """Test raw TCP connectivity to a host:port from this container.

    The most direct way to verify whether an endpoint is reachable from the
    agent's own runtime — useful for diagnosing port-forward and firewall issues
    before any application-layer protocols are attempted.

    Args:
        host: Hostname or IP address to connect to.
        port: TCP port number (1–65535).
        timeout: Connection timeout in seconds (capped at 30).

    Returns:
        JSON with reachable (bool), elapsed_ms, and error if any.
    """
    timeout = max(0.5, min(timeout, 30.0))

    async def _check() -> dict:
        t0 = time.monotonic()
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port), timeout=timeout
            )
            elapsed = (time.monotonic() - t0) * 1000
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            return {"reachable": True, "elapsed_ms": round(elapsed, 1), "host": host, "port": port}
        except asyncio.TimeoutError:
            elapsed = (time.monotonic() - t0) * 1000
            return {
                "reachable": False,
                "elapsed_ms": round(elapsed, 1),
                "host": host,
                "port": port,
                "error": f"Connection timed out after {timeout}s",
            }
        except OSError as exc:
            elapsed = (time.monotonic() - t0) * 1000
            return {
                "reachable": False,
                "elapsed_ms": round(elapsed, 1),
                "host": host,
                "port": port,
                "error": str(exc),
            }

    try:
        result = asyncio.run(_check())
    except RuntimeError:
        # Already inside an event loop — use a new thread
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _check())
            result = future.result()

    return json.dumps(result, indent=2)


@tool
def net_resolve(hostname: str, record_type: str = "A") -> str:
    """Resolve a hostname to IP addresses from this container.

    Uses the container's DNS resolver (getaddrinfo). For A/AAAA queries this
    is authoritative from the container's perspective. MX/TXT/CNAME queries
    fall back to 'dig' if available, otherwise return an error.

    Args:
        hostname: Hostname or domain to resolve (e.g. "home.awoo.agency").
        record_type: DNS record type — A, AAAA, or ANY (default A).

    Returns:
        JSON with the resolved addresses/records, query time, and resolver used.
    """
    record_type = record_type.upper()
    t0 = time.monotonic()

    if record_type in ("A", "AAAA", "ANY"):
        family = (
            socket.AF_INET if record_type == "A"
            else socket.AF_INET6 if record_type == "AAAA"
            else socket.AF_UNSPEC
        )
        try:
            results = socket.getaddrinfo(hostname, None, family=family, type=socket.SOCK_STREAM)
            ips = sorted({r[4][0] for r in results})
            elapsed = (time.monotonic() - t0) * 1000
            return json.dumps({
                "hostname": hostname,
                "record_type": record_type,
                "addresses": ips,
                "elapsed_ms": round(elapsed, 1),
                "resolver": "getaddrinfo",
            }, indent=2)
        except socket.gaierror as exc:
            elapsed = (time.monotonic() - t0) * 1000
            return json.dumps({
                "hostname": hostname,
                "record_type": record_type,
                "addresses": [],
                "elapsed_ms": round(elapsed, 1),
                "error": str(exc),
            }, indent=2)
    else:
        # Fall back to dig for MX, TXT, CNAME, NS, SOA, PTR
        try:
            result = subprocess.run(
                ["dig", "+noall", "+answer", "+stats", record_type, hostname],
                capture_output=True, text=True, timeout=15,
            )
            elapsed = (time.monotonic() - t0) * 1000
            output = (result.stdout + result.stderr).strip()
            return json.dumps({
                "hostname": hostname,
                "record_type": record_type,
                "output": output or "(no answer)",
                "elapsed_ms": round(elapsed, 1),
                "resolver": "dig",
            }, indent=2)
        except FileNotFoundError:
            return json.dumps({
                "hostname": hostname,
                "record_type": record_type,
                "error": f"dig not available in container for {record_type} queries; use A/AAAA instead",
            }, indent=2)
        except subprocess.TimeoutExpired:
            return json.dumps({
                "hostname": hostname,
                "record_type": record_type,
                "error": "dig timed out",
            }, indent=2)


@tool
def net_curl(
    url: str,
    method: str = "GET",
    headers: str = "",
    data: str = "",
    timeout: float = 15.0,
    verify_ssl: bool = False,
) -> str:
    """Make an HTTP/HTTPS request from this container using httpx.

    Useful for testing API reachability and diagnosing endpoint issues directly
    from the agent's runtime — no SSH hop required.

    Args:
        url: Full URL including scheme (e.g. "https://home.awoo.agency:32443/").
        method: HTTP method — GET, POST, PUT, DELETE, HEAD, OPTIONS (default GET).
        headers: Extra request headers, one per line in "Key: Value" format.
        data: Request body string (for POST/PUT). Sent as-is.
        timeout: Total request timeout in seconds (capped at 60).
        verify_ssl: Verify TLS certificate (default False — UDM-Pro uses self-signed).

    Returns:
        JSON with status_code, elapsed_ms, response_headers, and body (truncated to 2000 chars).
    """
    timeout = max(1.0, min(timeout, 60.0))
    method = method.upper()

    parsed_headers: dict = {}
    for line in (headers or "").splitlines():
        line = line.strip()
        if ": " in line:
            k, _, v = line.partition(": ")
            parsed_headers[k.strip()] = v.strip()

    async def _request() -> dict:
        t0 = time.monotonic()
        try:
            async with httpx.AsyncClient(verify=verify_ssl, timeout=timeout, follow_redirects=True) as client:
                response = await client.request(
                    method,
                    url,
                    headers=parsed_headers,
                    content=data.encode() if data else None,
                )
            elapsed = (time.monotonic() - t0) * 1000
            body = response.text
            truncated = len(body) > _BODY_LIMIT
            return {
                "url": url,
                "method": method,
                "status_code": response.status_code,
                "elapsed_ms": round(elapsed, 1),
                "response_headers": dict(response.headers),
                "body": body[:_BODY_LIMIT],
                "body_truncated": truncated,
            }
        except httpx.ConnectTimeout:
            elapsed = (time.monotonic() - t0) * 1000
            return {"url": url, "method": method, "error": "ConnectTimeout", "elapsed_ms": round(elapsed, 1)}
        except httpx.ReadTimeout:
            elapsed = (time.monotonic() - t0) * 1000
            return {"url": url, "method": method, "error": "ReadTimeout", "elapsed_ms": round(elapsed, 1)}
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            return {"url": url, "method": method, "error": str(exc), "elapsed_ms": round(elapsed, 1)}

    try:
        result = asyncio.run(_request())
    except RuntimeError:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, _request())
            result = future.result()

    return json.dumps(result, indent=2, default=str)


@tool
def net_ping(target: str, count: int = 4) -> str:
    """Ping a host from this container using ICMP.

    Requires the 'ping' binary to be available in the container (standard on
    most Linux base images). Uses a 2-second per-packet wait timeout.

    Args:
        target: IP address or hostname to ping.
        count: Number of ICMP echo requests (capped at 10).

    Returns:
        Raw ping output including round-trip statistics, or an error message.
    """
    count = max(1, min(count, 10))
    cmd = ["ping", "-c", str(count), "-W", "2", target]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=count * 4 + 5,
        )
        output = (result.stdout + result.stderr).strip()
        return output or "(no output from ping)"
    except FileNotFoundError:
        return "Error: ping binary not found in container"
    except subprocess.TimeoutExpired:
        return f"Error: ping timed out after {count * 4 + 5}s"
    except Exception as exc:
        return f"Error: {exc}"


@tool
def net_traceroute(target: str, max_hops: int = 20) -> str:
    """Trace the network path from this container to a target host.

    Tries traceroute first, falls back to tracepath (no root required).
    Returns "not available" if neither binary exists in the container.

    Args:
        target: IP address or hostname to trace.
        max_hops: Maximum TTL / hop count (capped at 30).

    Returns:
        Raw traceroute/tracepath output, or an error message.
    """
    max_hops = max(1, min(max_hops, 30))

    for binary, args in [
        ("traceroute", ["-m", str(max_hops), "-w", "2", target]),
        ("tracepath", ["-m", str(max_hops), target]),
    ]:
        try:
            result = subprocess.run(
                [binary] + args,
                capture_output=True,
                text=True,
                timeout=max_hops * 3 + 10,
            )
            output = (result.stdout + result.stderr).strip()
            return output or f"(no output from {binary})"
        except FileNotFoundError:
            continue
        except subprocess.TimeoutExpired:
            return f"Error: {binary} timed out after {max_hops * 3 + 10}s"
        except Exception as exc:
            return f"Error running {binary}: {exc}"

    return "Error: neither traceroute nor tracepath found in container"
