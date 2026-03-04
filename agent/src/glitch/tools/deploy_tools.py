"""Agent deployment management tools for Glitch.

Provides tools to:
- Read the current deployed ARNs for Glitch and Sentinel from SSM
- Update cross-agent SSM parameters after a fresh agentcore deploy
- Check CodeBuild project status for in-progress agentcore deploys

NOTE: Container image builds (agentcore deploy) require Docker and must be
run locally on a machine with the source tree.
"""

import json
import logging

from strands import tool

from glitch.aws_utils import get_client

logger = logging.getLogger(__name__)

# SSM parameter names for cross-agent ARN wiring
SSM_GLITCH_ARN = "/glitch/sentinel/glitch-runtime-arn"
SSM_SENTINEL_ARN = "/glitch/sentinel/runtime-arn"

# CodeBuild project names used by agentcore deploy
CODEBUILD_GLITCH = "bedrock-agentcore-glitch-builder"
CODEBUILD_SENTINEL = "bedrock-agentcore-sentinel-builder"


def _get_ssm():
    return get_client("ssm")


def _get_cb():
    return get_client("codebuild")


@tool
def get_deployed_arns() -> str:
    """Read the currently deployed runtime ARNs for Glitch and Sentinel from SSM.

    Also reads the live ARNs from .bedrock_agentcore.yaml files (if present) and
    compares them to the SSM values so you can see at a glance whether the SSM
    parameters are stale and need updating.

    Returns:
        JSON with SSM values, live YAML values, and a stale flag for each agent.
        If stale=true, call update_glitch_arn_in_ssm / update_sentinel_arn_in_ssm.
    """
    import os
    import yaml  # pyyaml is a project dependency

    ssm = _get_ssm()
    result = {}
    for label, param in [("glitch_arn_in_sentinel_ssm", SSM_GLITCH_ARN), ("sentinel_arn_in_glitch_ssm", SSM_SENTINEL_ARN)]:
        try:
            resp = ssm.get_parameter(Name=param)
            result[label] = {"value": resp["Parameter"]["Value"], "param": param, "status": "ok"}
        except ssm.exceptions.ParameterNotFound:
            result[label] = {"value": None, "param": param, "status": "missing"}
        except Exception as e:
            result[label] = {"value": None, "param": param, "status": f"error: {e}"}

    # Read live ARNs from .bedrock_agentcore.yaml files for staleness comparison.
    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))
    yaml_paths = {
        "glitch": os.path.join(repo_root, "agent", ".bedrock_agentcore.yaml"),
        "sentinel": os.path.join(repo_root, "monitoring-agent", ".bedrock_agentcore.yaml"),
    }
    live_arns: dict = {}
    for agent_name, yaml_path in yaml_paths.items():
        try:
            with open(yaml_path) as f:
                cfg = yaml.safe_load(f)
            agents_cfg = cfg.get("agents", {})
            agent_cfg = agents_cfg.get(agent_name.capitalize(), agents_cfg.get(agent_name, {}))
            live_arns[agent_name] = agent_cfg.get("bedrock_agentcore", {}).get("agent_arn")
        except Exception:
            live_arns[agent_name] = None

    # Annotate each entry with live ARN and staleness flag.
    glitch_ssm_val = result.get("glitch_arn_in_sentinel_ssm", {}).get("value")
    sentinel_ssm_val = result.get("sentinel_arn_in_glitch_ssm", {}).get("value")

    result["glitch_arn_in_sentinel_ssm"]["live_arn"] = live_arns.get("glitch")
    result["glitch_arn_in_sentinel_ssm"]["stale"] = (
        live_arns.get("glitch") is not None and glitch_ssm_val != live_arns.get("glitch")
    )
    result["sentinel_arn_in_glitch_ssm"]["live_arn"] = live_arns.get("sentinel")
    result["sentinel_arn_in_glitch_ssm"]["stale"] = (
        live_arns.get("sentinel") is not None and sentinel_ssm_val != live_arns.get("sentinel")
    )

    any_stale = result["glitch_arn_in_sentinel_ssm"]["stale"] or result["sentinel_arn_in_glitch_ssm"]["stale"]
    result["summary"] = "SSM parameters are up to date." if not any_stale else (
        "One or more SSM parameters are stale. Call update_glitch_arn_in_ssm / update_sentinel_arn_in_ssm."
    )
    return json.dumps(result, indent=2)


@tool
def update_glitch_arn_in_ssm(new_arn: str) -> str:
    """Update the Glitch agent runtime ARN in SSM after a fresh agentcore deploy.

    Call this after running 'agentcore deploy' in the agent/ directory locally.
    Sentinel reads this SSM parameter to know where to send invoke_glitch_agent
    requests.

    Args:
        new_arn: The new Glitch runtime ARN from .bedrock_agentcore.yaml
                 (agents.Glitch.bedrock_agentcore.agent_arn).

    Returns:
        Success or error message.
    """
    if not new_arn.startswith("arn:aws:bedrock-agentcore:"):
        return f"Error: ARN does not look like a Bedrock AgentCore ARN. Got: {new_arn!r}"
    try:
        _get_ssm().put_parameter(
            Name=SSM_GLITCH_ARN,
            Value=new_arn.strip(),
            Type="String",
            Overwrite=True,
        )
        return (
            f"Updated {SSM_GLITCH_ARN} → {new_arn.strip()}\n"
            "Sentinel will pick up the new Glitch ARN on its next cold start or cache expiry."
        )
    except Exception as e:
        return f"Error updating SSM parameter {SSM_GLITCH_ARN}: {e}"


@tool
def update_sentinel_arn_in_ssm(new_arn: str) -> str:
    """Update the Sentinel runtime ARN in SSM after a fresh agentcore deploy.

    Call this after running 'agentcore deploy' in the monitoring-agent/ directory
    locally. Glitch reads this SSM parameter to know where to send invoke_sentinel
    requests.

    Args:
        new_arn: The new Sentinel runtime ARN from monitoring-agent/.bedrock_agentcore.yaml
                 (agents.Sentinel.bedrock_agentcore.agent_arn).

    Returns:
        Success or error message.
    """
    if not new_arn.startswith("arn:aws:bedrock-agentcore:"):
        return f"Error: ARN does not look like a Bedrock AgentCore ARN. Got: {new_arn!r}"
    try:
        _get_ssm().put_parameter(
            Name=SSM_SENTINEL_ARN,
            Value=new_arn.strip(),
            Type="String",
            Overwrite=True,
        )
        return (
            f"Updated {SSM_SENTINEL_ARN} → {new_arn.strip()}\n"
            "Glitch will pick up the new Sentinel ARN on its next cold start or cache expiry."
        )
    except Exception as e:
        return f"Error updating SSM parameter {SSM_SENTINEL_ARN}: {e}"


@tool
def update_both_arns_in_ssm(glitch_arn: str, sentinel_arn: str) -> str:
    """Update both agent ARNs in SSM in a single call.

    Use this after deploying both agents fresh to wire them together.
    Equivalent to calling update_glitch_arn_in_ssm and update_sentinel_arn_in_ssm
    in sequence.

    Args:
        glitch_arn: New Glitch runtime ARN (from agent/.bedrock_agentcore.yaml).
        sentinel_arn: New Sentinel runtime ARN (from monitoring-agent/.bedrock_agentcore.yaml).

    Returns:
        Combined success/error message for both updates.
    """
    glitch_result = update_glitch_arn_in_ssm(glitch_arn)
    sentinel_result = update_sentinel_arn_in_ssm(sentinel_arn)
    return f"Glitch ARN update:\n{glitch_result}\n\nSentinel ARN update:\n{sentinel_result}"



@tool
def check_codebuild_deploy_status(agent: str) -> str:
    """Check the status of the most recent agentcore CodeBuild deploy for an agent.

    Use this to see if an in-progress 'agentcore deploy' is still running,
    succeeded, or failed — without needing to watch the local terminal.

    Args:
        agent: Which agent to check. Must be "glitch" or "sentinel".

    Returns:
        JSON with the build status, start time, end time, and log URL.
    """
    agent_lower = agent.lower()
    if agent_lower == "glitch":
        project = CODEBUILD_GLITCH
    elif agent_lower == "sentinel":
        project = CODEBUILD_SENTINEL
    else:
        return f"Error: agent must be 'glitch' or 'sentinel'. Got: {agent!r}"

    cb = _get_cb()
    try:
        ids_resp = cb.list_builds_for_project(projectName=project, sortOrder="DESCENDING")
        build_ids = ids_resp.get("ids", [])
        if not build_ids:
            return json.dumps({"project": project, "status": "no_builds_found"})

        builds_resp = cb.batch_get_builds(ids=[build_ids[0]])
        build = builds_resp["builds"][0]
        logs = build.get("logs", {})
        return json.dumps({
            "project": project,
            "build_id": build["id"],
            "status": build["buildStatus"],
            "phase": build.get("currentPhase", ""),
            "start_time": build.get("startTime", "").isoformat() if hasattr(build.get("startTime"), "isoformat") else str(build.get("startTime", "")),
            "end_time": build.get("endTime", "").isoformat() if hasattr(build.get("endTime"), "isoformat") else str(build.get("endTime", "")),
            "log_url": logs.get("deepLink", ""),
        }, indent=2)
    except cb.exceptions.ResourceNotFoundException:
        return json.dumps({"project": project, "status": "project_not_found"})
    except Exception as e:
        return json.dumps({"project": project, "error": str(e)})
