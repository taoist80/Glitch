---
name: pihole-dns
description: Manage Pi-hole DNS records via API. Use when updating local DNS entries, adding/removing custom DNS records, or when the user mentions Pi-hole, local DNS, or needs to point a domain to an IP address on the local network.
---

# Pi-hole DNS Management

Manage custom DNS records on Pi-hole for local network name resolution.

## Available Tools

Use these tools to manage Pi-hole DNS records:

- `pihole_list_dns_records`: List all custom DNS records from both Pi-hole hosts
- `pihole_add_dns_record(domain, ip)`: Add a DNS record to both hosts
- `pihole_delete_dns_record(domain, ip)`: Delete a DNS record from both hosts
- `pihole_update_dns_record(domain, old_ip, new_ip)`: Update a record (delete + add)

## Pi-hole Hosts

Records are managed on both Pi-hole servers:
- 10.10.100.70
- 10.10.100.71

Credentials are fetched from AWS Secrets Manager (`glitch/pihole-api`).

## Common Workflows

### List Current Records

```
pihole_list_dns_records()
```

Returns JSON with all records from both hosts.

### Add a New DNS Record

```
pihole_add_dns_record(domain="myservice.local", ip="10.10.100.50")
```

### Update Glitch DNS After Redeploy

When the Tailscale EC2 instance is redeployed and gets a new IP:

1. Get the new Tailscale IP (user will provide)
2. List current records to find old IP:
   ```
   pihole_list_dns_records()
   ```
3. Update the record:
   ```
   pihole_update_dns_record(
       domain="glitch.awoo.agency",
       old_ip="100.x.x.x",  # from step 2
       new_ip="100.y.y.y"   # new IP from user
   )
   ```

### Delete a Record

```
pihole_delete_dns_record(domain="old.local", ip="10.10.100.99")
```

## Response Format

Tools return status for each Pi-hole host:
```
10.10.100.70: ✓ Added example.local -> 10.10.100.50
10.10.100.71: ✓ Added example.local -> 10.10.100.50
```

## Troubleshooting

- **Authentication failed**: Check credentials in Secrets Manager
- **Connection refused**: Verify Pi-hole hosts are reachable via Tailscale
- **Record not resolving**: DNS cache may need time to expire (or restart Pi-hole DNS)
