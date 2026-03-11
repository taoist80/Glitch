"""Pi-hole DNS management tools.

Provides tools for managing custom DNS records on Pi-hole servers
accessible via the local network.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional, TypedDict

import httpx
from strands import tool

from glitch.aws_utils import get_client

logger = logging.getLogger(__name__)

SECRET_NAME = "glitch/pihole-api"


class PiholeCredentials(TypedDict):
    username: str
    password: str
    hosts: List[str]


@dataclass
class PiholeConfig:
    """Configuration for Pi-hole endpoints."""
    hosts: List[str] = field(default_factory=lambda: ["10.10.100.70", "10.10.100.71"])
    timeout: float = 10.0


DEFAULT_CONFIG = PiholeConfig()

_cached_credentials: Optional[PiholeCredentials] = None


async def _get_credentials() -> PiholeCredentials:
    """Fetch Pi-hole credentials from Secrets Manager (cached)."""
    global _cached_credentials
    if _cached_credentials is not None:
        return _cached_credentials

    try:
        client = get_client("secretsmanager")
        response = client.get_secret_value(SecretId=SECRET_NAME)
        secret = json.loads(response["SecretString"])
        _cached_credentials = PiholeCredentials(
            username=secret["username"],
            password=secret["password"],
            hosts=secret.get("hosts", DEFAULT_CONFIG.hosts),
        )
        logger.info("Loaded Pi-hole credentials from Secrets Manager")
        return _cached_credentials
    except Exception as e:
        logger.error(f"Failed to fetch Pi-hole credentials: {e}")
        raise


async def _get_auth_token(host: str, username: str, password: str) -> Optional[str]:
    """Get session ID (auth token) by logging into Pi-hole web interface."""
    login_url = f"http://{host}/admin/index.php?login"
    async with httpx.AsyncClient(timeout=DEFAULT_CONFIG.timeout, follow_redirects=True) as client:
        try:
            response = await client.post(
                login_url,
                data={"pw": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            cookies = response.cookies
            if "PHPSESSID" in cookies:
                return cookies["PHPSESSID"]
            for cookie in response.headers.get_all("set-cookie"):
                if "PHPSESSID" in cookie:
                    return cookie.split("PHPSESSID=")[1].split(";")[0]
            logger.warning(f"No PHPSESSID in response from {host}")
            return None
        except Exception as e:
            logger.error(f"Failed to authenticate with Pi-hole at {host}: {e}")
            return None


@tool
async def pihole_list_dns_records() -> str:
    """List all custom DNS records from Pi-hole.

    Returns:
        JSON list of DNS records from all Pi-hole hosts, or error message.
    """
    creds = await _get_credentials()
    all_records = []
    errors = []

    for host in creds["hosts"]:
        try:
            session_id = await _get_auth_token(host, creds["username"], creds["password"])
            if not session_id:
                errors.append(f"{host}: authentication failed")
                continue

            url = f"http://{host}/admin/api.php?customdns&action=get"
            async with httpx.AsyncClient(timeout=DEFAULT_CONFIG.timeout) as client:
                response = await client.get(
                    url,
                    cookies={"PHPSESSID": session_id},
                )
                if response.status_code == 200:
                    data = response.json()
                    records = data.get("data", [])
                    for record in records:
                        all_records.append({
                            "ip": record[0],
                            "domain": record[1],
                            "host": host,
                        })
                else:
                    errors.append(f"{host}: HTTP {response.status_code}")
        except Exception as e:
            errors.append(f"{host}: {str(e)}")

    result = {"records": all_records}
    if errors:
        result["errors"] = errors
    return json.dumps(result, indent=2)


@tool
async def pihole_add_dns_record(domain: str, ip: str) -> str:
    """Add a custom DNS record to Pi-hole.

    Args:
        domain: The domain name (e.g., "glitch.awoo.agency")
        ip: The IP address to point to (e.g., "100.64.0.5")

    Returns:
        Success or error message.
    """
    creds = await _get_credentials()
    results = []

    for host in creds["hosts"]:
        try:
            session_id = await _get_auth_token(host, creds["username"], creds["password"])
            if not session_id:
                results.append(f"{host}: authentication failed")
                continue

            url = f"http://{host}/admin/api.php?customdns&action=add&ip={ip}&domain={domain}"
            async with httpx.AsyncClient(timeout=DEFAULT_CONFIG.timeout) as client:
                response = await client.get(
                    url,
                    cookies={"PHPSESSID": session_id},
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        results.append(f"{host}: ✓ Added {domain} -> {ip}")
                    else:
                        results.append(f"{host}: Failed - {data}")
                else:
                    results.append(f"{host}: HTTP {response.status_code}")
        except Exception as e:
            results.append(f"{host}: {str(e)}")

    return "\n".join(results)


@tool
async def pihole_delete_dns_record(domain: str, ip: str) -> str:
    """Delete a custom DNS record from Pi-hole.

    Args:
        domain: The domain name to delete
        ip: The IP address of the record to delete

    Returns:
        Success or error message.
    """
    creds = await _get_credentials()
    results = []

    for host in creds["hosts"]:
        try:
            session_id = await _get_auth_token(host, creds["username"], creds["password"])
            if not session_id:
                results.append(f"{host}: authentication failed")
                continue

            url = f"http://{host}/admin/api.php?customdns&action=delete&ip={ip}&domain={domain}"
            async with httpx.AsyncClient(timeout=DEFAULT_CONFIG.timeout) as client:
                response = await client.get(
                    url,
                    cookies={"PHPSESSID": session_id},
                )
                if response.status_code == 200:
                    data = response.json()
                    if data.get("success"):
                        results.append(f"{host}: ✓ Deleted {domain} -> {ip}")
                    else:
                        results.append(f"{host}: Failed - {data}")
                else:
                    results.append(f"{host}: HTTP {response.status_code}")
        except Exception as e:
            results.append(f"{host}: {str(e)}")

    return "\n".join(results)


@tool
async def pihole_update_dns_record(domain: str, old_ip: str, new_ip: str) -> str:
    """Update a custom DNS record in Pi-hole (delete old, add new).

    Args:
        domain: The domain name to update
        old_ip: The current IP address to remove
        new_ip: The new IP address to set

    Returns:
        Success or error message.
    """
    delete_result = await pihole_delete_dns_record(domain, old_ip)
    add_result = await pihole_add_dns_record(domain, new_ip)
    return f"Delete:\n{delete_result}\n\nAdd:\n{add_result}"
