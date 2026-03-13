#!/usr/bin/env python3
"""Diagnostic: verify Auri tool storage layers are working.

Checks:
  1. S3  — auri-core.md and auri-runtime-rules.md exist and are non-empty
  2. DynamoDB — any AURI_STATE / AURI_SCENE entries exist
  3. auri_memory (RDS) — recent memories via protect-query Lambda search
  4. Participant profiles — recent participant_profile entries via filtered search

Run:
    cd agent && python3 scripts/check-auri-tools.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")


# ── 1. S3 split files ──────────────────────────────────────────────────────────

def check_s3():
    print("\n── S3 Split Files ──────────────────────────────────────────────")
    try:
        from glitch.tools.soul_tools import (
            load_auri_core_from_s3, load_auri_rules_from_s3,
        )
        core = load_auri_core_from_s3()
        rules = load_auri_rules_from_s3()

        if core and core.strip():
            words = len(core.split())
            print(f"  auri-core.md        ✓  {len(core)} chars (~{int(words * 1.3)} tokens)")
            print(f"    preview: {core[:80].strip()!r}...")
        else:
            print("  auri-core.md        ✗  empty or missing")

        if rules and rules.strip():
            words = len(rules.split())
            print(f"  auri-runtime-rules  ✓  {len(rules)} chars (~{int(words * 1.3)} tokens)")
            print(f"    preview: {rules[:80].strip()!r}...")
        else:
            print("  auri-runtime-rules  ✗  empty or missing")
    except Exception as e:
        print(f"  ERROR: {e}")


# ── 2. DynamoDB session state ──────────────────────────────────────────────────

def check_dynamodb():
    print("\n── DynamoDB Session State ──────────────────────────────────────")
    try:
        ddb = boto3.client("dynamodb", region_name=REGION)
        table = "glitch-telegram-config"

        resp = ddb.scan(
            TableName=table,
            FilterExpression="begins_with(pk, :prefix)",
            ExpressionAttributeValues={":prefix": {"S": "AURI_STATE#"}},
            Limit=10,
        )
        items = resp.get("Items", [])
        if items:
            print(f"  AURI_STATE entries  ✓  {len(items)} session(s) found")
            for item in items[:3]:
                pk = item.get("pk", {}).get("S", "?")
                data_raw = item.get("data", {}).get("S", "{}")
                try:
                    data = json.loads(data_raw)
                    print(f"    {pk}: mode={data.get('mode')} mood={data.get('mood')} level={data.get('dynamic_level')}")
                except Exception:
                    print(f"    {pk}: {data_raw[:60]}")
        else:
            print("  AURI_STATE entries  –  none found (no roleplay sessions with state updates yet)")

        resp = ddb.scan(
            TableName=table,
            FilterExpression="begins_with(pk, :prefix)",
            ExpressionAttributeValues={":prefix": {"S": "AURI_SCENE#"}},
            Limit=10,
        )
        items = resp.get("Items", [])
        if items:
            print(f"  AURI_SCENE entries  ✓  {len(items)} session(s) found")
            for item in items[:3]:
                pk = item.get("pk", {}).get("S", "?")
                data_raw = item.get("data", {}).get("S", "{}")
                try:
                    data = json.loads(data_raw)
                    print(f"    {pk}: energy={data.get('energy')} events={len(data.get('recent_events', []))}")
                except Exception:
                    print(f"    {pk}: {data_raw[:60]}")
        else:
            print("  AURI_SCENE entries  –  none found (no scene updates yet)")
    except Exception as e:
        print(f"  ERROR: {e}")


# ── 3. Recent auri_memory entries (RDS via Lambda) ────────────────────────────

def check_auri_memory():
    print("\n── auri_memory (RDS via Lambda) ────────────────────────────────")
    try:
        lambda_client = boto3.client("lambda", region_name=REGION)
        lambda_name = os.environ.get("GLITCH_PROTECT_QUERY_LAMBDA", "glitch-protect-query")

        # Use a broad search with a generic embedding-like query
        # We'll query by fetching the most recent entries via a dummy search
        # The filtered search action lets us filter by memory_type
        from glitch.auri_memory import embed_text

        # Search for any episodic memory
        embedding = embed_text("Arc Auri roleplay memory")
        resp = lambda_client.invoke(
            FunctionName=lambda_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({
                "action": "auri_memory_search",
                "embedding": embedding,
                "k": 5,
            }).encode(),
        )
        result = json.loads(resp["Payload"].read())
        memories = result.get("memories", [])
        if memories:
            print(f"  Episodic memories   ✓  {len(memories)} recent result(s)")
            for m in memories[:3]:
                content = m.get("content", "") if isinstance(m, dict) else str(m)
                print(f"    - {content[:80].strip()!r}...")
        else:
            print("  Episodic memories   –  no results (remember_auri not called yet, or empty DB)")

        # Search for participant profiles
        resp = lambda_client.invoke(
            FunctionName=lambda_name,
            InvocationType="RequestResponse",
            Payload=json.dumps({
                "action": "auri_memory_search_filtered",
                "embedding": embedding,
                "k": 5,
                "memory_type": "participant_profile",
            }).encode(),
        )
        result = json.loads(resp["Payload"].read())
        profiles = result.get("memories", [])
        if profiles:
            print(f"  Participant profiles ✓  {len(profiles)} profile(s)")
            for p in profiles[:3]:
                content = p.get("content", "") if isinstance(p, dict) else str(p)
                pid = p.get("participant_id", "?") if isinstance(p, dict) else "?"
                print(f"    [{pid}] {content[:80].strip()!r}...")
        else:
            print("  Participant profiles –  none found (update_participant_profile not called yet)")

    except Exception as e:
        print(f"  ERROR: {e}")


# ── 4. Trigger a test roleplay invoke and check tool_usage ────────────────────

def check_invoke_tool_usage():
    print("\n── Live Invoke Tool Usage Check ────────────────────────────────")
    print("  Run this to see if tools fire on a memory-worthy prompt:")
    print()
    print("  agentcore invoke '{\"prompt\":\"Auri, I want you to remember — Arc loves warm blankets and being called a good boy.\",\"mode_id\":\"roleplay\"}'")
    print()
    print("  Then look for  \"tool_usage\": {\"remember_auri\": 1}  in the response.")
    print("  If tool_usage is empty {}, the soul tools may not be selected by the skill matcher.")


if __name__ == "__main__":
    check_s3()
    check_dynamodb()
    check_auri_memory()
    check_invoke_tool_usage()
    print()
