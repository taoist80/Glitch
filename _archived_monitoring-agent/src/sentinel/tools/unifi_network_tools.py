"""UniFi Network Controller tools for Sentinel.

Provides tools for querying and managing the UniFi Network Controller:
clients, devices, APs, switches, firewall rules, VPN, WiFi, alerts, and topology.

Credentials are read from Secrets Manager: glitch/unifi-controller
Secret format: {"host": "10.10.100.1", "username": "admin", "password": "...", "site": "default"}
"""

import json
import logging
import ssl
from typing import Any, Dict, List, Optional

import httpx
from strands import tool

from sentinel.aws_utils import get_client

logger = logging.getLogger(__name__)

SECRET_NAME = "glitch/unifi-controller"

_unifi_creds: Optional[Dict[str, str]] = None
_unifi_session: Optional[httpx.AsyncClient] = None
_unifi_base_url: Optional[str] = None


def _not_configured() -> str:
    return (
        "UniFi Network credentials not configured. "
        "Store credentials via Glitch: store_secret(name='glitch/unifi-controller', "
        "value={host, username, password, site})."
    )


async def _get_creds() -> Dict[str, str]:
    global _unifi_creds
    if _unifi_creds:
        return _unifi_creds
    try:
        sm = get_client("secretsmanager")
        resp = sm.get_secret_value(SecretId=SECRET_NAME)
        _unifi_creds = json.loads(resp["SecretString"])
        return _unifi_creds
    except Exception as e:
        raise RuntimeError(f"Could not load UniFi credentials: {e}") from e


async def _get_session() -> tuple[httpx.AsyncClient, str]:
    """Return an authenticated httpx session and base URL."""
    global _unifi_session, _unifi_base_url
    creds = await _get_creds()
    host = creds["host"]
    base_url = f"https://{host}"
    site = creds.get("site", "default")

    # Use a new client per invocation (stateless) with SSL verification disabled
    # for self-signed UniFi certs
    client = httpx.AsyncClient(verify=False, timeout=15)

    # Login
    login_resp = await client.post(
        f"{base_url}/api/login",
        json={"username": creds["username"], "password": creds["password"]},
    )
    if login_resp.status_code != 200:
        await client.aclose()
        raise RuntimeError(f"UniFi login failed: {login_resp.status_code}")

    return client, f"{base_url}/api/s/{site}"


async def _api_get(path: str) -> Any:
    client, base = await _get_session()
    try:
        resp = await client.get(f"{base}{path}")
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", data)
    finally:
        await client.aclose()


async def _api_post(path: str, payload: dict) -> Any:
    client, base = await _get_session()
    try:
        resp = await client.post(f"{base}{path}", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", data)
    finally:
        await client.aclose()


@tool
async def unifi_list_clients(active_only: bool = True) -> str:
    """List all clients connected to the UniFi network.

    Args:
        active_only: If True (default), return only currently connected clients.

    Returns:
        JSON list of clients with hostname, IP, MAC, signal strength, and data usage.
    """
    try:
        endpoint = "/stat/sta" if active_only else "/stat/alluser"
        data = await _api_get(endpoint)
        clients = []
        for c in data:
            clients.append({
                "hostname": c.get("hostname", c.get("name", "unknown")),
                "ip": c.get("ip", ""),
                "mac": c.get("mac", ""),
                "oui": c.get("oui", ""),
                "network": c.get("network", ""),
                "signal_dbm": c.get("signal", None),
                "tx_bytes": c.get("tx_bytes", 0),
                "rx_bytes": c.get("rx_bytes", 0),
                "uptime_s": c.get("uptime", 0),
                "is_wired": c.get("is_wired", False),
            })
        return json.dumps({"client_count": len(clients), "clients": clients}, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_device_status(device_mac: Optional[str] = None) -> str:
    """Get the status of UniFi network devices (APs, switches, gateways).

    Args:
        device_mac: Specific device MAC address to query. If omitted, returns all devices.

    Returns:
        JSON list of devices with name, model, state, firmware, uptime, and load.
    """
    try:
        data = await _api_get("/stat/device")
        devices = []
        for d in data:
            if device_mac and d.get("mac", "").lower() != device_mac.lower():
                continue
            devices.append({
                "name": d.get("name", d.get("mac", "unknown")),
                "mac": d.get("mac", ""),
                "model": d.get("model", ""),
                "type": d.get("type", ""),
                "state": d.get("state", 0),
                "state_label": {0: "disconnected", 1: "connected", 4: "upgrading"}.get(d.get("state", 0), "unknown"),
                "firmware": d.get("version", ""),
                "uptime_s": d.get("uptime", 0),
                "load_1m": d.get("sys_stats", {}).get("loadavg_1", None),
                "mem_pct": d.get("sys_stats", {}).get("mem_used", 0),
                "ip": d.get("ip", ""),
            })
        return json.dumps({"device_count": len(devices), "devices": devices}, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_ap_stats() -> str:
    """Get access point performance statistics.

    Returns:
        JSON with each AP's channel, interference score, client count, and throughput.
    """
    try:
        data = await _api_get("/stat/device")
        aps = []
        for d in data:
            if d.get("type") not in ("uap", "ugw"):
                continue
            radio_table = d.get("radio_table", [])
            radio_stats = d.get("radio_table_stats", [])
            for i, radio in enumerate(radio_table):
                stats = radio_stats[i] if i < len(radio_stats) else {}
                aps.append({
                    "ap_name": d.get("name", d.get("mac")),
                    "ap_mac": d.get("mac"),
                    "radio": radio.get("name"),
                    "channel": radio.get("channel"),
                    "bandwidth": radio.get("ht"),
                    "clients": stats.get("num_sta", 0),
                    "tx_packets": stats.get("tx_packets", 0),
                    "rx_packets": stats.get("rx_packets", 0),
                    "satisfaction": d.get("satisfaction", None),
                })
        return json.dumps({"ap_count": len(aps), "aps": aps}, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_switch_ports(device_mac: Optional[str] = None) -> str:
    """Get switch port status including PoE, link speed, and traffic.

    Args:
        device_mac: MAC address of a specific switch. If omitted, returns ports for all switches.

    Returns:
        JSON with port details per switch.
    """
    try:
        data = await _api_get("/stat/device")
        result = []
        for d in data:
            if d.get("type") != "usw":
                continue
            if device_mac and d.get("mac", "").lower() != device_mac.lower():
                continue
            ports = []
            for p in d.get("port_table", []):
                ports.append({
                    "port_idx": p.get("port_idx"),
                    "name": p.get("name", f"Port {p.get('port_idx')}"),
                    "enabled": p.get("enable", False),
                    "up": p.get("up", False),
                    "speed": p.get("speed", 0),
                    "full_duplex": p.get("full_duplex", False),
                    "poe_enable": p.get("poe_enable", False),
                    "poe_power_w": p.get("poe_power", None),
                    "tx_bytes": p.get("tx_bytes", 0),
                    "rx_bytes": p.get("rx_bytes", 0),
                })
            result.append({
                "switch_name": d.get("name", d.get("mac")),
                "switch_mac": d.get("mac"),
                "ports": ports,
            })
        return json.dumps(result, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_firewall_rules() -> str:
    """List all active firewall and traffic rules.

    Returns:
        JSON list of firewall rules with name, action, protocol, source, and destination.
    """
    try:
        rules = await _api_get("/rest/firewallrule")
        return json.dumps({
            "rule_count": len(rules),
            "rules": [
                {
                    "name": r.get("name"),
                    "enabled": r.get("enabled"),
                    "action": r.get("action"),
                    "ruleset": r.get("ruleset"),
                    "protocol": r.get("protocol"),
                    "src_address": r.get("src_address"),
                    "dst_address": r.get("dst_address"),
                    "src_port": r.get("src_port"),
                    "dst_port": r.get("dst_port"),
                }
                for r in rules
            ],
        }, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_block_client(mac_address: str) -> str:
    """Block a client from the network by MAC address.

    Args:
        mac_address: The client MAC address to block (e.g., "aa:bb:cc:dd:ee:ff").

    Returns:
        Success or error message.
    """
    try:
        result = await _api_post("/cmd/stamgr", {"cmd": "block-sta", "mac": mac_address})
        return json.dumps({"blocked": mac_address, "result": result})
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_traffic_stats(hours: int = 24) -> str:
    """Get aggregate network traffic statistics.

    Args:
        hours: Time period in hours (default 24).

    Returns:
        JSON with total bytes transmitted/received and top clients by usage.
    """
    try:
        data = await _api_get("/stat/sta")
        total_tx = sum(c.get("tx_bytes", 0) for c in data)
        total_rx = sum(c.get("rx_bytes", 0) for c in data)
        top = sorted(data, key=lambda c: c.get("tx_bytes", 0) + c.get("rx_bytes", 0), reverse=True)[:10]
        return json.dumps({
            "total_tx_bytes": total_tx,
            "total_rx_bytes": total_rx,
            "top_clients": [
                {
                    "hostname": c.get("hostname", c.get("mac", "unknown")),
                    "mac": c.get("mac"),
                    "tx_bytes": c.get("tx_bytes", 0),
                    "rx_bytes": c.get("rx_bytes", 0),
                }
                for c in top
            ],
        }, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_network_health() -> str:
    """Get overall network health status and subsystem scores.

    Returns:
        JSON with health scores for WAN, LAN, WLAN subsystems and active alerts.
    """
    try:
        data = await _api_get("/stat/health")
        return json.dumps({"subsystems": data}, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_vpn_status() -> str:
    """Get VPN connection status (site-to-site and client VPN).

    Returns:
        JSON with active VPN tunnels, connected clients, and throughput.
    """
    try:
        # Check for VPN clients (remote access)
        vpn_clients = await _api_get("/stat/remoteuserstat")
        # Check site-to-site VPN status via device stats
        devices = await _api_get("/stat/device")
        gateways = [d for d in devices if d.get("type") == "ugw"]
        vpn_tunnels = []
        for gw in gateways:
            for iface in gw.get("if_table", []):
                if "vpn" in iface.get("name", "").lower() or "tun" in iface.get("name", "").lower():
                    vpn_tunnels.append({
                        "gateway": gw.get("name"),
                        "interface": iface.get("name"),
                        "up": iface.get("up", False),
                        "rx_bytes": iface.get("rx_bytes", 0),
                        "tx_bytes": iface.get("tx_bytes", 0),
                    })
        return json.dumps({
            "vpn_client_count": len(vpn_clients),
            "vpn_clients": vpn_clients[:10],
            "vpn_tunnels": vpn_tunnels,
        }, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_wifi_networks() -> str:
    """List all WiFi SSIDs with channel, radio settings, and client counts.

    Returns:
        JSON with each WLAN's SSID, band, channel, security, and connected client count.
    """
    try:
        wlans = await _api_get("/rest/wlanconf")
        clients = await _api_get("/stat/sta")

        # Count clients per SSID
        ssid_counts: Dict[str, int] = {}
        for c in clients:
            ssid = c.get("essid", "")
            ssid_counts[ssid] = ssid_counts.get(ssid, 0) + 1

        networks = []
        for w in wlans:
            ssid = w.get("name", "")
            networks.append({
                "ssid": ssid,
                "enabled": w.get("enabled", False),
                "security": w.get("security", "open"),
                "band": w.get("wlan_band", "both"),
                "vlan": w.get("vlan", None),
                "hide_ssid": w.get("hide_ssid", False),
                "client_count": ssid_counts.get(ssid, 0),
                "schedule_enabled": w.get("schedule_enabled", False),
            })
        return json.dumps({"network_count": len(networks), "networks": networks}, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_alerts_events(limit: int = 50, archived: bool = False) -> str:
    """Retrieve recent UniFi alerts and events.

    Args:
        limit: Maximum number of events to return (default 50).
        archived: If True, include archived/acknowledged alerts (default False).

    Returns:
        JSON list of recent alerts with type, message, device, and timestamp.
    """
    try:
        endpoint = "/stat/alarm" if not archived else "/stat/alarm?archived=true"
        data = await _api_get(endpoint)
        events = []
        for e in data[:limit]:
            events.append({
                "key": e.get("key", ""),
                "message": e.get("msg", ""),
                "device_name": e.get("ap_displayName", e.get("sw_displayName", e.get("gw_displayName", ""))),
                "device_mac": e.get("ap", e.get("sw", e.get("gw", ""))),
                "datetime": e.get("datetime", ""),
                "archived": e.get("archived", False),
                "count": e.get("count", 1),
            })
        return json.dumps({"event_count": len(events), "events": events}, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def unifi_get_network_topology() -> str:
    """Get the network topology showing device interconnections and uplink paths.

    Returns:
        JSON tree showing gateway -> switches -> APs -> clients with link speeds.
    """
    try:
        devices = await _api_get("/stat/device")
        clients = await _api_get("/stat/sta")

        device_map = {d["mac"]: d for d in devices}

        # Build uplink tree
        topology = []
        roots = [d for d in devices if not d.get("uplink", {}).get("uplink_mac")]

        def build_node(device: dict) -> dict:
            mac = device.get("mac")
            children_devices = [
                d for d in devices
                if d.get("uplink", {}).get("uplink_mac") == mac
            ]
            client_list = [
                {"hostname": c.get("hostname", c.get("mac")), "mac": c.get("mac"), "ip": c.get("ip")}
                for c in clients
                if c.get("ap_mac") == mac or c.get("sw_mac") == mac
            ]
            return {
                "name": device.get("name", mac),
                "mac": mac,
                "type": device.get("type"),
                "model": device.get("model"),
                "uplink_speed": device.get("uplink", {}).get("speed"),
                "state": device.get("state"),
                "children_devices": [build_node(child) for child in children_devices],
                "clients": client_list,
            }

        topology = [build_node(r) for r in roots]
        return json.dumps({"topology": topology}, indent=2)
    except RuntimeError as e:
        return _not_configured() if "credentials" in str(e) else str(e)
    except Exception as e:
        return json.dumps({"error": str(e)})
