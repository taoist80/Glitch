#!/usr/bin/env python3
"""
Check whether AgentCore runtime logs exist in CloudWatch.

For agent runtime, the platform creates a CloudWatch log group by default. If the
group is missing or empty, the cause is usually IAM (runtime role permissions for
/aws/bedrock-agentcore/*) or network (VPC endpoint / NAT).

Usage (from repo root or agent/):
  python3 agent/scripts/check-runtime-logs.py
  cd agent && python3 scripts/check-runtime-logs.py
"""

import sys
from datetime import datetime
from pathlib import Path

try:
    import boto3
    import yaml
except ImportError as e:
    print("Error: need boto3 and pyyaml:", e)
    sys.exit(1)

# Find config relative to script
SCRIPT_DIR = Path(__file__).resolve().parent
AGENT_DIR = SCRIPT_DIR.parent
CONFIG_FILE = AGENT_DIR / ".bedrock_agentcore.yaml"


def load_agent_id_and_region():
    if not CONFIG_FILE.exists():
        print(f"Config not found: {CONFIG_FILE}")
        return None, None
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f)
    agent_name = config.get("default_agent", "Glitch")
    agent_config = config.get("agents", {}).get(agent_name, {})
    agent_id = agent_config.get("bedrock_agentcore", {}).get("agent_id")
    region = agent_config.get("aws", {}).get("region", "us-west-2")
    return agent_id, region


def main():
    agent_id, region = load_agent_id_and_region()
    if not agent_id:
        print("Could not read agent_id from .bedrock_agentcore.yaml")
        sys.exit(1)
    print(f"Agent ID: {agent_id}")
    print(f"Region:   {region}")
    print()

    client = boto3.client("logs", region_name=region)
    prefix = "/aws/bedrock-agentcore/runtimes/"
    # Common pattern: /aws/bedrock-agentcore/runtimes/<agent_id>-DEFAULT
    possible_log_group = f"{prefix}{agent_id}-DEFAULT"

    # List log groups with prefix
    try:
        resp = client.describe_log_groups(
            logGroupNamePrefix=prefix,
            limit=20,
        )
        groups = resp.get("logGroups", [])
    except Exception as e:
        print(f"Failed to list log groups: {e}")
        sys.exit(1)

    matching = [g for g in groups if g["logGroupName"] == possible_log_group or agent_id in g["logGroupName"]]
    if not matching:
        print(f"No runtime log group found for this agent.")
        print(f"Expected name like: {possible_log_group}")
        if groups:
            print(f"Other bedrock-agentcore log groups in account: {[g['logGroupName'] for g in groups[:5]]}")
    else:
        log_group_name = matching[0]["logGroupName"]
        print(f"Log group: {log_group_name}")
        try:
            streams_resp = client.describe_log_streams(
                logGroupName=log_group_name,
                orderBy="LastEventTime",
                descending=True,
                limit=5,
            )
            streams = streams_resp.get("logStreams", [])
            if not streams:
                print("  No log streams yet. Invoke the agent once, then enable log delivery (see below).")
            else:
                for s in streams:
                    ts = s.get("lastEventTimestamp")
                    when = datetime.utcfromtimestamp(ts / 1000).isoformat() + "Z" if ts else "n/a"
                    print(f"  stream: {s['logStreamName'][:60]}...  last: {when}")
        except Exception as e:
            print(f"  Failed to list streams: {e}")

    print()
    print("=" * 60)
    print("IF THE LOG GROUP IS EMPTY OR MISSING")
    print("=" * 60)
    print("""
For agent runtime, the platform creates the log group by default (no "Log delivery"
config required). If logs still don't appear:

1. IAM: Runtime execution role must have logs:CreateLogGroup, CreateLogStream,
   PutLogEvents, DescribeLogStreams on /aws/bedrock-agentcore/*. Redeploy
   GlitchFoundationStack so the role has this (see stack.ts CloudWatchLogs policy).

2. Network: If the runtime is in a VPC, it must reach the CloudWatch Logs
   interface endpoint (or internet via NAT). Check security groups and route tables.

3. Use the "Logs" link in the agent Endpoints table in the console to open
   the runtime log group; confirm the group name matches your runtime ID.
""")


if __name__ == "__main__":
    main()
