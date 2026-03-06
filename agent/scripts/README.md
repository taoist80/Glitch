# Agent Deployment Scripts

Scripts in this directory are invoked via `agent/Makefile` targets. Do not call them directly unless you have a specific reason.

## Quick reference

```bash
# From agent/
make deploy                # Configure from SSM + agentcore deploy (recommended)
make deploy-only           # Deploy using existing .env.deploy (skip configure)
make configure             # Update .bedrock_agentcore.yaml from SSM only
make verify                # Check agent runtime status (agentcore status)
make check-logs            # Check AgentCore runtime logs in CloudWatch
make telegram-troubleshoot # Run Telegram webhook/runtime diagnostics
make test                  # Run unit tests
```

## Scripts

### `deploy.sh`

Orchestrates the two-step deploy:
1. Runs `pre-deploy-configure.py` to read SSM params and write `.env.deploy`
2. Calls `agentcore deploy --env KEY=VALUE ...` with every var from `.env.deploy`

**Why this matters:** `agentcore deploy` rewrites `.bedrock_agentcore.yaml` on each run and strips `environment_variables`. The `--env` flags survive that rewrite. Never call `agentcore deploy` directly.

### `pre-deploy-configure.py`

Reads SSM params (`/glitch/iam/*`, `/glitch/telegram/*`, `/glitch/ssh/*`, `/glitch/soul/s3-bucket`) and:
- Updates `.bedrock_agentcore.yaml` with `execution_role` and `codebuild.execution_role`
- Writes all runtime env vars to `.env.deploy` for `deploy.sh` to consume

### `check-runtime-logs.py`

Reads `agent_id` from `.bedrock_agentcore.yaml` and lists recent CloudWatch log streams under `/aws/bedrock-agentcore/runtimes/<agent_id>-DEFAULT`. Prints troubleshooting guidance if the log group is missing.

### `ssh-setup.sh`

One-time bootstrap: generates `glitch_agent_key` (ed25519) and writes `agent/.env.ssh` with `GLITCH_SSH_KEY_PATH` and `GLITCH_SSH_HOSTS`. Run once per project. Interactive — prompts to add an initial host.

### `ssh-copy-key.py`

Installs the project public key on a remote host using `ssh-copy-id`. Run after `ssh-setup.sh` for each new host.

```bash
python scripts/ssh-copy-key.py user@hostname [port]
```
