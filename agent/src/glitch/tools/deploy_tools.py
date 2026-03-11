"""Agent deployment management tools for Glitch.

Provides tools to:
- Read the current deployed ARN for Glitch from SSM and .bedrock_agentcore.yaml
- Update the Glitch ARN in SSM after a fresh agentcore deploy
- Check CodeBuild project status for in-progress agentcore deploys

NOTE: Container image builds (agentcore deploy) require Docker and must be
run locally on a machine with the source tree.
"""

import json
import logging

from strands import tool

from glitch.aws_utils import get_client

logger = logging.getLogger(__name__)

# SSM parameter name for Glitch's own runtime ARN (read by infra/other services)
SSM_GLITCH_ARN = "/glitch/agent/runtime-arn"

# CodeBuild project name used by agentcore deploy
CODEBUILD_GLITCH = "bedrock-agentcore-glitch-builder"


def _get_ssm():
    return get_client("ssm")


def _get_cb():
    return get_client("codebuild")


@tool
def get_deployed_arns() -> str:
    """Read the currently deployed runtime ARN for Glitch from SSM.

    Also reads the live ARN from .bedrock_agentcore.yaml and compares to the
    SSM value so you can see at a glance whether SSM is stale and needs updating.

    Returns:
        JSON with SSM value, live YAML value, and a stale flag.
        If stale=true, call update_glitch_arn_in_ssm.
    """
    import os
    import yaml  # pyyaml is a project dependency

    ssm = _get_ssm()
    result: dict = {}
    try:
        resp = ssm.get_parameter(Name=SSM_GLITCH_ARN)
        result["glitch_arn_in_ssm"] = {"value": resp["Parameter"]["Value"], "param": SSM_GLITCH_ARN, "status": "ok"}
    except ssm.exceptions.ParameterNotFound:
        result["glitch_arn_in_ssm"] = {"value": None, "param": SSM_GLITCH_ARN, "status": "missing"}
    except Exception as e:
        result["glitch_arn_in_ssm"] = {"value": None, "param": SSM_GLITCH_ARN, "status": f"error: {e}"}

    # Read live ARN from .bedrock_agentcore.yaml for staleness comparison.
    repo_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
    )
    yaml_path = os.path.join(repo_root, "agent", ".bedrock_agentcore.yaml")
    live_arn = None
    try:
        with open(yaml_path) as f:
            cfg = yaml.safe_load(f)
        agents_cfg = cfg.get("agents", {})
        agent_cfg = agents_cfg.get("Glitch", agents_cfg.get("glitch", {}))
        live_arn = agent_cfg.get("bedrock_agentcore", {}).get("agent_arn")
    except Exception:
        pass

    ssm_val = result.get("glitch_arn_in_ssm", {}).get("value")
    result["glitch_arn_in_ssm"]["live_arn"] = live_arn
    result["glitch_arn_in_ssm"]["stale"] = live_arn is not None and ssm_val != live_arn

    result["summary"] = (
        "SSM parameter is up to date."
        if not result["glitch_arn_in_ssm"]["stale"]
        else "SSM parameter is stale. Call update_glitch_arn_in_ssm with the new ARN."
    )
    return json.dumps(result, indent=2)


@tool
def update_glitch_arn_in_ssm(new_arn: str) -> str:
    """Update the Glitch agent runtime ARN in SSM after a fresh agentcore deploy.

    Call this after running 'agentcore deploy' in the agent/ directory locally.

    Args:
        new_arn: The new Glitch runtime ARN from agent/.bedrock_agentcore.yaml
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
        return f"Updated {SSM_GLITCH_ARN} → {new_arn.strip()}"
    except Exception as e:
        return f"Error updating SSM parameter {SSM_GLITCH_ARN}: {e}"


@tool
def check_codebuild_deploy_status(agent: str = "glitch") -> str:
    """Check the status of the most recent agentcore CodeBuild deploy.

    Use this to see if an in-progress 'agentcore deploy' is still running,
    succeeded, or failed — without needing to watch the local terminal.

    Args:
        agent: Which agent to check. Currently only "glitch" is supported.

    Returns:
        JSON with the build status, start time, end time, and log URL.
    """
    project = CODEBUILD_GLITCH

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
