# Incident Response Skill

## Decision Tree

```
Detect signal (log error / network alert / DNS anomaly / camera event)
  ↓
Correlate: check other domains for related signals (3 minutes window)
  ↓
Classify severity (HIGH / MEDIUM / LOW)
  ↓
Can auto-remediate?
  ├── YES → Attempt fix → Verify → Report resolved via Telegram
  ├── NEEDS CODE CHANGE → Create GitHub PR → Alert via Telegram
  └── NO → Alert via Telegram with full context
```

## Auto-Remediation Capabilities

### Via SSH (ssh_run_command)
- Nginx config issues → run `write-glitch-proxy-conf.sh` via SSH
- TLS cert issues → run `ensure-glitch-tls.sh` or `renew-glitch-tls.sh` via SSH
- EC2 service restart → systemctl commands via SSH
- File system issues → write/fix files via ssh_write_file

### Via tools directly
- DNS anomaly → `dns_manage_blocklists(action="blacklist_domain", target=domain)`
- Suspicious network client → `unifi_block_client(mac_address)`
- Stack drift → `rollback_stack(stack_name)` if in recoverable state

### Via GitHub PR
- Code bugs in Lambda, agent tools, infrastructure CDK
- Pattern: `github_get_file` → analyze → `github_create_branch` → `github_commit_file` → `github_create_pr`

## Cross-Domain Correlation Examples

**Network security incident:**
1. `protect_get_events` → unknown person at 2am
2. `unifi_list_clients` → new unrecognized device appeared
3. `dns_detect_suspicious_domains` → that device queried C2 domain
4. → `unifi_block_client` + HIGH alert via Telegram

**Deployment failure cascade:**
1. `scan_log_groups_for_errors` → spike in Lambda errors at timestamp X
2. `list_cfn_stacks_status` → stack in UPDATE_FAILED at same time
3. `check_cfn_drift` → drift on compute resources
4. → `rollback_stack` if recoverable, else MEDIUM alert

**DNS-based threat:**
1. `dns_monitor_live_queries` → sudden spike in queries from single client
2. `dns_detect_suspicious_domains` → DGA-like domains being queried
3. `unifi_get_device_status` → identify device
4. → `unifi_block_client` + `dns_manage_blocklists` + HIGH alert

## Telegram Alert Template

```
🔴/🟡/🔵 Glitch Alert [Component]

What happened: [concise description]
When: [timestamp]
Affected: [systems/services]

Investigation:
- [what you checked]
- [what you found]

Action taken: [what you did or could not do]
Next steps: [what human needs to do, if anything]
```

## GitHub PR Template

Title: `fix: [brief description] (Glitch auto-diagnosis)`

Body:
```
## Root Cause
[What the error was and why]

## Fix
[What was changed and why it fixes the issue]

## Diagnosed From
- Log group: [name]
- Error pattern: [pattern]
- First seen: [timestamp]

## Testing Notes
[What to verify after merging]

---
*Auto-diagnosed by Glitch*
```
