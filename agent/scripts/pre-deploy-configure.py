#!/usr/bin/env python3
"""
Pre-deploy hook: Auto-configure environment variables before AgentCore deployment.

This script runs automatically before `agentcore deploy` to:
1. Fetch runtime configuration from SSM Parameters
2. Update .bedrock_agentcore.yaml and .env.deploy with correct env vars
3. Validate configuration before proceeding

SSM Parameters (set by GlitchFoundationStack and deployment stacks):
  /glitch/iam/runtime-role-arn      - Runtime role ARN
  /glitch/iam/codebuild-role-arn    - CodeBuild role ARN
  /glitch/telegram/webhook-url      - Lambda Function URL for Telegram webhook
  /glitch/telegram/config-table     - DynamoDB table for Telegram config
  /glitch/ssh/hosts                 - SSH hosts configuration (JSON)

Environment Variables set automatically:
  GLITCH_OLLAMA_TIMEOUT             - Timeout for Ollama requests (default: 180s)
  GLITCH_MISTRAL_TIMEOUT            - Timeout for Mistral requests (default: 180s)
  GLITCH_TELEGRAM_WEBHOOK_URL       - Lambda Function URL for Telegram webhook
  GLITCH_CONFIG_TABLE               - DynamoDB table for Telegram config
  GLITCH_TELEGRAM_SECRET_NAME       - Secrets Manager secret name for Telegram bot token
  GLITCH_TELEMETRY_LOG_GROUP        - CloudWatch log group for telemetry
  GLITCH_DEFAULT_CHAT_AGENT         - Default chat agent (glitch = Sonnet brainstem)
  GLITCH_SSH_HOSTS                  - JSON-encoded SSH host list (from .env.ssh or SSM)
  GLITCH_SSH_SECRET_NAME            - Secrets Manager secret name for SSH key
  GLITCH_SOUL_S3_BUCKET             - S3 bucket for SOUL.md (from SSM /glitch/soul/s3-bucket)

Exit codes:
  0 - Success (configuration updated or already correct)
  1 - Error (missing required SSM parameters or invalid configuration)
"""

import os
import sys
from pathlib import Path

try:
    import boto3
    import yaml
    from botocore.exceptions import ClientError
except ImportError:
    print("Warning: boto3 or pyyaml not available. Skipping pre-deploy configuration.")
    print("To enable auto-configuration, install: pip install boto3 pyyaml")
    sys.exit(0)

REGION = os.environ.get('AWS_REGION', 'us-west-2')

SSM_RUNTIME_ROLE_ARN = '/glitch/iam/runtime-role-arn'
SSM_CODEBUILD_ROLE_ARN = '/glitch/iam/codebuild-role-arn'
SSM_TELEGRAM_WEBHOOK_URL = '/glitch/telegram/webhook-url'
SSM_TELEGRAM_CONFIG_TABLE = '/glitch/telegram/config-table'
SSM_SSH_HOSTS = '/glitch/ssh/hosts'
SSM_SOUL_S3_BUCKET = '/glitch/soul/s3-bucket'
SSM_OLLAMA_PROXY_HOST = '/glitch/ollama/proxy-host'
SSM_OLLAMA_API_KEY = '/glitch/ollama/api-key'
# Protect subsystem SSM params (previously only in monitoring-agent)
SSM_PROTECT_HOST = '/glitch/protect/host'
SSM_PROTECT_2_HOST = '/glitch/protect/site2/host'
SSM_PROTECT_2_API_KEY = '/glitch/protect/site2/api_key'
SSM_PROTECT_DB_HOST = '/glitch/protect-db/host'
SSM_PROTECT_DB_PORT = '/glitch/protect-db/port'
SSM_PROTECT_DB_NAME = '/glitch/protect-db/dbname'
SSM_PROTECT_DB_IAM_USER = '/glitch/protect-db/sentinel-iam-user'

AGENT_DIR = Path(__file__).parent.parent
CONFIG_FILE = AGENT_DIR / '.bedrock_agentcore.yaml'


def log(message: str, level: str = 'INFO'):
    """Log message with prefix."""
    prefix = {
        'INFO': '[pre-deploy]',
        'WARN': '[pre-deploy] WARNING:',
        'ERROR': '[pre-deploy] ERROR:',
        'SUCCESS': '[pre-deploy] ✓',
    }.get(level, '[pre-deploy]')
    print(f"{prefix} {message}")


def get_ssm_parameter(ssm_client, name: str) -> str | None:
    """Get a parameter value from SSM Parameter Store."""
    try:
        response = ssm_client.get_parameter(Name=name, WithDecryption=True)
        return response['Parameter']['Value']
    except ClientError as e:
        if e.response['Error']['Code'] == 'ParameterNotFound':
            return None
        raise


def load_config() -> dict:
    """Load AgentCore configuration."""
    if not CONFIG_FILE.exists():
        log(f"Config file not found: {CONFIG_FILE}", 'ERROR')
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        return yaml.safe_load(f)


ENV_DEPLOY_FILE = AGENT_DIR / '.env.deploy'


def save_config(config: dict):
    """Save AgentCore configuration with explicit flush."""
    with open(CONFIG_FILE, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        f.flush()
        os.fsync(f.fileno())


def save_env_deploy(env_vars: dict):
    """Write env vars to .env.deploy for deploy.sh to pass as --env flags.

    agentcore deploy strips environment_variables from the YAML on each run,
    so we pass them explicitly via --env KEY=VALUE CLI flags instead.
    """
    with open(ENV_DEPLOY_FILE, 'w') as f:
        for key, value in env_vars.items():
            f.write(f"{key}={value}\n")
        f.flush()
        os.fsync(f.fileno())
    log(f"Wrote {len(env_vars)} env vars to {ENV_DEPLOY_FILE.name} for deploy.sh", 'SUCCESS')


def main():
    log("Configuring pre-deploy environment variables...")

    config = load_config()
    agent_name = config.get('default_agent', 'Glitch')

    if agent_name not in config.get('agents', {}):
        log(f"Agent '{agent_name}' not found in config", 'ERROR')
        sys.exit(1)

    agent_config = config['agents'][agent_name]

    try:
        ssm_client = boto3.client('ssm', region_name=REGION)

        execution_role_arn = get_ssm_parameter(ssm_client, SSM_RUNTIME_ROLE_ARN)
        codebuild_role_arn = get_ssm_parameter(ssm_client, SSM_CODEBUILD_ROLE_ARN)

        if execution_role_arn:
            if 'aws' not in agent_config:
                agent_config['aws'] = {}
            agent_config['aws']['execution_role'] = execution_role_arn
            log(f"Execution role set from SSM", 'SUCCESS')

        if codebuild_role_arn:
            if 'codebuild' not in agent_config:
                agent_config['codebuild'] = {}
            agent_config['codebuild']['execution_role'] = codebuild_role_arn
            log("CodeBuild execution_role set from SSM", 'SUCCESS')

        if 'aws' not in agent_config:
            agent_config['aws'] = {}
        if 'environment_variables' not in agent_config['aws']:
            agent_config['aws']['environment_variables'] = {}
        env_vars = agent_config['aws']['environment_variables']

        # Ollama proxy host — DDNS hostname that forwards to on-prem model servers.
        # Port-forwards required on UDM-Pro: WAN:11434→10.10.110.202:11434 (Chat), WAN:18080→10.10.110.137:8080 (Vision).
        ollama_proxy_host = get_ssm_parameter(ssm_client, SSM_OLLAMA_PROXY_HOST)
        if ollama_proxy_host:
            env_vars['GLITCH_OLLAMA_PROXY_HOST'] = ollama_proxy_host
            log(f"Ollama proxy host set to {ollama_proxy_host} (from SSM)", 'SUCCESS')
        else:
            log("SSM /glitch/ollama/proxy-host not found; deploy GlitchFoundationStack first", 'WARN')

        ollama_api_key = get_ssm_parameter(ssm_client, SSM_OLLAMA_API_KEY)
        if ollama_api_key:
            env_vars['GLITCH_OLLAMA_API_KEY'] = ollama_api_key
            log("Ollama API key loaded from SSM", 'SUCCESS')
        else:
            log("SSM /glitch/ollama/api-key not set; Ollama proxy will be unauthenticated", 'WARN')

        # Set default timeouts for Ollama requests
        if 'GLITCH_OLLAMA_TIMEOUT' not in env_vars:
            env_vars['GLITCH_OLLAMA_TIMEOUT'] = '180'
            log("Ollama timeout set to 180s (default)", 'SUCCESS')
        if 'GLITCH_MISTRAL_TIMEOUT' not in env_vars:
            env_vars['GLITCH_MISTRAL_TIMEOUT'] = '180'
            log("Mistral timeout set to 180s (default)", 'SUCCESS')

        # Telegram configuration
        telegram_webhook_url = get_ssm_parameter(ssm_client, SSM_TELEGRAM_WEBHOOK_URL)
        telegram_config_table = get_ssm_parameter(ssm_client, SSM_TELEGRAM_CONFIG_TABLE)

        if telegram_webhook_url:
            env_vars['GLITCH_TELEGRAM_WEBHOOK_URL'] = telegram_webhook_url
            log(f"Telegram webhook URL set to {telegram_webhook_url}", 'SUCCESS')
        else:
            log("SSM /glitch/telegram/webhook-url not found; deploy GlitchTelegramWebhookStack first", 'WARN')

        if telegram_config_table:
            env_vars['GLITCH_CONFIG_TABLE'] = telegram_config_table
            log(f"Telegram config table set to {telegram_config_table}", 'SUCCESS')
        else:
            env_vars['GLITCH_CONFIG_TABLE'] = 'glitch-telegram-config'
            log("SSM /glitch/telegram/config-table not found; using default 'glitch-telegram-config'", 'WARN')

        env_vars['GLITCH_TELEGRAM_SECRET_NAME'] = 'glitch/telegram-bot-token'
        log("Telegram secret name set to glitch/telegram-bot-token", 'SUCCESS')

        # Telemetry
        env_vars['GLITCH_TELEMETRY_LOG_GROUP'] = '/glitch/telemetry'
        log("Telemetry log group set to /glitch/telemetry", 'SUCCESS')

        # Default chat agent
        env_vars['GLITCH_DEFAULT_CHAT_AGENT'] = 'glitch'
        log("Default chat agent set to 'glitch' (Sonnet brainstem)", 'SUCCESS')

        # SSH hosts: merge from .env.ssh if present; else fall back to SSM
        env_ssh = AGENT_DIR / '.env.ssh'
        ssh_hosts_set = False
        if env_ssh.exists():
            try:
                with open(env_ssh) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, _, value = line.partition('=')
                            key, value = key.strip(), value.strip()
                            if key == 'GLITCH_SSH_HOSTS' and value:
                                env_vars['GLITCH_SSH_HOSTS'] = value
                                log("SSH hosts merged from .env.ssh", 'SUCCESS')
                                ssh_hosts_set = True
                                break
            except Exception as e:
                log(f"Could not read .env.ssh: {e}", 'WARN')
        if not ssh_hosts_set:
            try:
                ssh_hosts_value = get_ssm_parameter(ssm_client, SSM_SSH_HOSTS)
                if ssh_hosts_value and ssh_hosts_value.strip():
                    env_vars['GLITCH_SSH_HOSTS'] = ssh_hosts_value.strip()
                    log("SSH hosts set from SSM /glitch/ssh/hosts", 'SUCCESS')
            except Exception:
                pass
        if 'GLITCH_SSH_SECRET_NAME' not in env_vars:
            env_vars['GLITCH_SSH_SECRET_NAME'] = 'glitch/ssh-key'
            log("SSH secret name set to glitch/ssh-key", 'SUCCESS')

        # Soul bucket (SOUL.md, poet-soul, story-book) — runtime needs this to read/write soul
        soul_bucket = get_ssm_parameter(ssm_client, SSM_SOUL_S3_BUCKET)
        if soul_bucket and soul_bucket.strip():
            env_vars['GLITCH_SOUL_S3_BUCKET'] = soul_bucket.strip()
            log(f"Soul S3 bucket set to {soul_bucket.strip()} (from SSM)", 'SUCCESS')
        else:
            log("SSM /glitch/soul/s3-bucket not found; deploy GlitchStorageStack so agent can write SOUL.md", 'WARN')

        # Protect subsystem env vars (merged from monitoring-agent)
        protect_host = get_ssm_parameter(ssm_client, SSM_PROTECT_HOST)
        if protect_host:
            env_vars['GLITCH_PROTECT_HOST'] = protect_host
            log(f"Protect host set to {protect_host}", 'SUCCESS')
        else:
            log("SSM /glitch/protect/host not found; Protect subsystem will be disabled", 'WARN')

        # Site 2 — opt-in; only set env vars if SSM params exist
        protect_2_host = get_ssm_parameter(ssm_client, SSM_PROTECT_2_HOST)
        if protect_2_host:
            env_vars['GLITCH_PROTECT_2_HOST'] = protect_2_host
            log(f"Protect site 2 host set to {protect_2_host}", 'SUCCESS')
        protect_2_api_key = get_ssm_parameter(ssm_client, SSM_PROTECT_2_API_KEY)
        if protect_2_api_key:
            env_vars['GLITCH_PROTECT_2_API_KEY'] = protect_2_api_key
            log("Protect site 2 API key loaded from SSM", 'SUCCESS')

        protect_db_host = get_ssm_parameter(ssm_client, SSM_PROTECT_DB_HOST)
        if protect_db_host:
            env_vars['GLITCH_PROTECT_DB_HOST'] = protect_db_host
            log(f"Protect DB host set from SSM", 'SUCCESS')

        protect_db_port = get_ssm_parameter(ssm_client, SSM_PROTECT_DB_PORT)
        if protect_db_port:
            env_vars['GLITCH_PROTECT_DB_PORT'] = protect_db_port

        protect_db_name = get_ssm_parameter(ssm_client, SSM_PROTECT_DB_NAME)
        if protect_db_name:
            env_vars['GLITCH_PROTECT_DB_NAME'] = protect_db_name

        protect_db_iam_user = get_ssm_parameter(ssm_client, SSM_PROTECT_DB_IAM_USER)
        if protect_db_iam_user:
            env_vars['GLITCH_PROTECT_DB_IAM_USER'] = protect_db_iam_user

        save_config(config)
        save_env_deploy(env_vars)
        log("Pre-deploy configuration completed successfully", 'SUCCESS')

    except ClientError as e:
        log(f"AWS API error: {e}", 'ERROR')
        sys.exit(1)
    except Exception as e:
        log(f"Unexpected error: {e}", 'ERROR')
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
