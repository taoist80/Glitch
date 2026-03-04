# Glitch Protect Surveillance (Delegated to Sentinel)

All UniFi Protect, UniFi Network, Pi-hole DNS, and security operations live in the **Sentinel agent**.

When surveillance, network, or security questions arise, delegate using `invoke_sentinel`.

## Delegation Examples

```python
invoke_sentinel("Check recent UniFi Protect events — any motion or person detections in the last 6 hours?")
invoke_sentinel("Check for suspicious DNS activity and unknown devices on the network")
invoke_sentinel("Is there anything unusual on the network or cameras right now?")
invoke_sentinel("Search entities for [name/description] and return their sighting history")
invoke_sentinel("Are all cameras online and recording?")
invoke_sentinel("Run a security correlation scan for the last 30 minutes")
```

## What Sentinel Handles

- All `protect_*` tools (13 core always active + 35 extended for deep investigations)
- All `unifi_*` tools (clients, APs, switches, VPN, WiFi, firewall, topology)
- All `pihole_*` and `dns_*` tools (DNS records, analytics, threat detection)
- `security_correlation_scan` — protect events + network clients + DNS in one call
- `analyze_and_alert` — full pipeline: fetch events → analyze → decide → alert
- Automatic Telegram alerts for security events
