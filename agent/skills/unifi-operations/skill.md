# UniFi Operations Skill

## Protect (Surveillance)

### Routine Checks
- `protect_get_cameras()` — verify all cameras online and recording
- `protect_get_events(hours=24)` — review recent motion/person/vehicle events
- `protect_get_monitoring_status()` — check if monitoring workflow is active

### Security Response
- `protect_analyze_event(event_id)` — deep analysis of a specific event
- `protect_should_alert(event_id)` — determine if alert is warranted
- `protect_classify_snapshot(camera_id)` — get vision classification of current view
- `protect_detect_anomalies(camera_id)` — check for unusual activity
- `protect_send_telegram_alert(message, snapshot_url)` — alert with visual

### Entity Management
- `protect_register_entity(name, category)` — register known people/vehicles
- `protect_search_entities(query)` — search entity database
- `protect_get_entity_dossier(entity_id)` — full history of entity sightings

## Network

### Health Monitoring
- `unifi_get_network_health()` — subsystem health scores (WAN, LAN, WLAN)
- `unifi_get_alerts_events(limit=20)` — recent UniFi alerts
- `unifi_get_device_status()` — all device states
- `unifi_get_ap_stats()` — radio performance, client density

### Client Investigation
- `unifi_list_clients(active_only=True)` — all active clients
- `unifi_get_network_topology()` — full device tree with uplink paths
- `unifi_block_client(mac_address)` — block suspicious device (irreversible without manual unblock)

### Infrastructure
- `unifi_get_switch_ports()` — port status, PoE, link speeds
- `unifi_get_wifi_networks()` — SSID config, channel assignment, client density
- `unifi_get_vpn_status()` — VPN tunnel health
- `unifi_get_traffic_stats()` — bandwidth usage

## DNS / Pi-hole

- `pihole_list_dns_records()` — custom DNS entries
- `dns_analyze_query_patterns(hours=6)` — query volume analysis
- `dns_detect_suspicious_domains(hours=3)` — threat detection
- `dns_get_top_blocked(limit=25)` — most blocked domains
- `dns_manage_blocklists(action="list_sources")` — blocklist management

## Security Correlation Workflow

When an unknown device appears on the network:
1. `unifi_list_clients()` → find the device details
2. `dns_analyze_query_patterns()` → check what domains it's querying
3. `dns_detect_suspicious_domains()` → flag if querying C2/malware domains
4. `protect_get_events()` → check if camera events correlate with device arrival time
5. Decision: block + alert, or just alert for human review

When a camera event triggers:
1. `protect_should_alert(event_id)` → determine if worth alerting
2. `protect_classify_snapshot(camera_id)` → get visual classification
3. `unifi_list_clients()` → check if new devices appeared at same time
4. Compose alert with context using `send_telegram_alert`
