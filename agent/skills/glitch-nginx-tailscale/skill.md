# Glitch Nginx (Tailscale proxy) troubleshooting and cert management

You are managing the nginx proxy and SSL certificate on the Tailscale EC2 that serves the Glitch UI. Use this skill for connection issues, nginx problems, and SSL cert generation or renewal.

## CRITICAL: Do NOT use SSH

**Never ask for SSH credentials. Never use `ssh_*` tools for this task.**
The Tailscale EC2 has AWS SSM Agent installed. All remote access is via SSM — no SSH keys, no passwords, no Tailscale IP needed.

## Context

- **Target**: Tailscale EC2. The instance ID is stored in SSM at `/glitch/tailscale/instance-id` — the tailscale tools read it automatically.
- **Tools** (use these, not SSH):
  - `run_tailscale_ssm_command(commands)` — run shell commands on the instance via AWS SSM Run Command. Commands are automatically prefixed with `sudo` (SSM runs as `ssm-user`, not root). No SSH needed.
  - `run_tailscale_ensure_tls` — obtain a new cert (first-time or after instance replace) and switch nginx to HTTPS.
  - `run_tailscale_renew_tls` — renew an existing cert (uses dnspython patch to bypass Tailscale DNS interception).
  - `protect_send_telegram_alert` — send a report to the owner via Telegram.

- **Interactive terminal** — share this with the user when they need a shell on the instance:
  ```bash
  aws ssm start-session --target $(aws cloudformation describe-stacks --stack-name GlitchTailscaleStack --query 'Stacks[0].Outputs[?OutputKey==`InstanceId`].OutputValue' --output text)
  ```
  Once connected, use `sudo` for most commands (e.g. `sudo systemctl status nginx`, `sudo nginx -t`, `sudo cat /var/log/nginx/error.log`).

## Workflow 1: Nginx health check

1. Run standard checks in one SSM call:
   ```python
   run_tailscale_ssm_command(commands=[
       "systemctl status nginx --no-pager",
       "ss -tlnp | grep -E ':80|:443'",
       "nginx -t",
       "tail -20 /var/log/nginx/error.log",
   ])
   ```

2. Interpret:
   - **nginx inactive/failed** → nginx not running; check error.log for config or cert path issues.
   - **No listener on 80** → nginx failed to bind or config is broken.
   - **No listener on 443** → TLS not enabled yet; run `run_tailscale_ensure_tls`.
   - **nginx -t failed** → config syntax error or missing cert files.
   - **Connection refused** → user likely using `https://` before certs exist; advise `http://` first. Confirm DNS points to current Tailscale IP (`tailscale ip -4`).

3. Report issues via Telegram:
   - `protect_send_telegram_alert(event_id="nginx-troubleshoot", alert_priority="high"|"medium", message=<summary + fix>)`
   - If Telegram unavailable, include the summary in your reply.

## Workflow 2: Check cert expiry

```python
run_tailscale_ssm_command(commands=[
    "certbot certificates 2>/dev/null || echo 'certbot not installed'",
    "openssl x509 -in /etc/letsencrypt/live/glitch.awoo.agency/fullchain.pem -noout -dates 2>/dev/null || echo 'cert not found'",
])
```

- If expiry is **< 30 days** or cert is missing → run `run_tailscale_renew_tls`.
- If cert is healthy → report expiry date to user.

## Workflow 3: Renew cert (on demand or near expiry)

1. Call `run_tailscale_renew_tls` — this installs the renewal script if missing and runs it.
   - The script patches `dnspython` to use 8.8.8.8/8.8.4.4 so Tailscale's DNS interception is bypassed.
   - Uses Porkbun DNS-01 challenge with 600s propagation wait.
   - On success, nginx is reloaded automatically.
2. If renewal fails, report via Telegram with `alert_priority="high"` and include the error output.

## Workflow 4: Obtain cert for the first time (new instance)

1. Call `run_tailscale_ensure_tls` — runs `/usr/local/bin/ensure-glitch-tls.sh` which runs certbot and switches nginx to TLS.
2. If the script is missing (old instance), use `run_tailscale_ssm_command` to install and run the renew script directly.

## Automatic renewal

New instances get `/etc/cron.d/certbot-renew` which runs `/usr/local/bin/renew-glitch-tls.sh` at 3am daily. For the current instance, install it manually:

```python
run_tailscale_ssm_command(commands=[
    "echo '0 3 * * * root /usr/local/bin/renew-glitch-tls.sh >> /var/log/glitch-tls-renew.log 2>&1' > /etc/cron.d/certbot-renew",
    "ls -la /etc/cron.d/certbot-renew",
])
```

## Output

- Always summarize findings in your reply.
- When you send a Telegram alert, say "I've reported the issue via Telegram to the owner."
