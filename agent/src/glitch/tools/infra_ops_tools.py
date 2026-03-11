"""Infrastructure operations tools.

Provides CDK and CloudFormation operations: synth/validate, diff, deploy,
stack status, drift detection, and rollback.

CDK/CLI operations run on the owner's local machine via SSH (ssh_run_command).
CloudFormation read-only operations (describe, drift) are executed directly via boto3.
"""

import json
import logging
from typing import Optional

import boto3
from strands import tool

from glitch.aws_utils import REGION, CLIENT_CONFIG_LONG

logger = logging.getLogger(__name__)

_cfn_client = None


def _get_cfn() -> boto3.client:
    global _cfn_client
    if _cfn_client is None:
        # CloudFormation drift detection can take 60s; use long timeout config.
        _cfn_client = boto3.client("cloudformation", region_name=REGION, config=CLIENT_CONFIG_LONG)
    return _cfn_client


_KNOWN_STACKS = [
    "GlitchFoundationStack",
    "GlitchProtectDbStack",
    "GlitchGatewayStack",
    "GlitchTelegramWebhookStack",
    "GlitchUiHostingStack",
    "GlitchEdgeStack",
    "GlitchAgentCoreStack",
]


@tool
def list_cfn_stacks_status() -> str:
    """List all CloudFormation stacks with their current status.

    Returns:
        JSON list of stacks with name, status, last updated time, and drift status.
    """
    try:
        cfn = _get_cfn()
        paginator = cfn.get_paginator("describe_stacks")
        stacks = []
        for page in paginator.paginate():
            for s in page.get("Stacks", []):
                stacks.append({
                    "name": s["StackName"],
                    "status": s["StackStatus"],
                    "status_reason": s.get("StackStatusReason", ""),
                    "last_updated": s.get("LastUpdatedTime", s.get("CreationTime", "")).isoformat() if hasattr(s.get("LastUpdatedTime", s.get("CreationTime", "")), "isoformat") else str(s.get("LastUpdatedTime", "")),
                    "drift_status": s.get("DriftInformation", {}).get("StackDriftStatus", "NOT_CHECKED"),
                })
        # Sort: Glitch stacks first
        glitch = [s for s in stacks if s["name"] in _KNOWN_STACKS]
        others = [s for s in stacks if s["name"] not in _KNOWN_STACKS]
        return json.dumps({"stack_count": len(stacks), "stacks": glitch + others}, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def check_cfn_drift(stack_name: str) -> str:
    """Detect configuration drift on a CloudFormation stack.

    Initiates a drift detection check and waits for results (up to 60 seconds).

    Args:
        stack_name: The CloudFormation stack name (e.g., "GlitchAgentCoreStack").

    Returns:
        JSON with overall drift status and drifted resource details.
    """
    import time
    try:
        cfn = _get_cfn()
        resp = cfn.detect_stack_drift(StackName=stack_name)
        detection_id = resp["StackDriftDetectionId"]

        for _ in range(12):
            time.sleep(5)
            status_resp = cfn.describe_stack_drift_detection_status(
                StackDriftDetectionId=detection_id
            )
            detection_status = status_resp.get("DetectionStatus")
            if detection_status in ("DETECTION_COMPLETE", "DETECTION_FAILED"):
                break

        drift_status = status_resp.get("StackDriftStatus", "UNKNOWN")

        drifted_resources = []
        if drift_status == "DRIFTED":
            try:
                dr_resp = cfn.describe_stack_resource_drifts(
                    StackName=stack_name,
                    StackResourceDriftStatusFilters=["MODIFIED", "DELETED"],
                )
                for r in dr_resp.get("StackResourceDrifts", []):
                    drifted_resources.append({
                        "logical_id": r["LogicalResourceId"],
                        "resource_type": r["ResourceType"],
                        "drift_status": r["StackResourceDriftStatus"],
                        "expected": r.get("ExpectedProperties"),
                        "actual": r.get("ActualProperties"),
                    })
            except Exception as dr_err:
                logger.warning(f"Could not retrieve drift details: {dr_err}")

        return json.dumps({
            "stack": stack_name,
            "drift_status": drift_status,
            "drifted_resource_count": len(drifted_resources),
            "drifted_resources": drifted_resources,
        }, indent=2)
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def rollback_stack(stack_name: str) -> str:
    """Attempt to roll back a CloudFormation stack that is in a FAILED or ROLLBACK state.

    This operation cancels an in-progress update or continues a rollback.
    Only available for stacks in UPDATE_ROLLBACK_FAILED state.

    Args:
        stack_name: The CloudFormation stack name to roll back.

    Returns:
        JSON with the rollback operation result.
    """
    try:
        cfn = _get_cfn()
        # Check current status first
        resp = cfn.describe_stacks(StackName=stack_name)
        stack = resp["Stacks"][0]
        status = stack["StackStatus"]

        if status == "UPDATE_ROLLBACK_FAILED":
            cfn.continue_update_rollback(StackName=stack_name)
            return json.dumps({"stack": stack_name, "action": "continue_update_rollback", "status": "initiated"})
        elif status == "UPDATE_IN_PROGRESS":
            cfn.cancel_update_stack(StackName=stack_name)
            return json.dumps({"stack": stack_name, "action": "cancel_update", "status": "initiated"})
        else:
            return json.dumps({
                "stack": stack_name,
                "current_status": status,
                "message": f"Stack is in {status} — no rollback action available. Manual intervention may be required.",
            })
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
async def cdk_synth_and_validate(stack_name: Optional[str] = None) -> str:
    """Run CDK synth and cfn-lint validation on the infrastructure stack(s).

    Runs the command on the owner's local machine via SSH.

    Args:
        stack_name: Specific stack name to synth (e.g., "GlitchAgentCoreStack").
                    If omitted, synths all stacks.

    Returns:
        JSON with synth output and any lint warnings/errors.
    """
    from glitch.tools.ssh_tools import ssh_run_command
    stack_arg = stack_name or ""
    cmd = f"cd ~/IdeaProjects/AgentCore-Glitch/infrastructure && npx cdk synth {stack_arg} 2>&1 | tail -50"
    return await ssh_run_command(host="owner", command=cmd)


@tool
async def cdk_diff(stack_name: Optional[str] = None) -> str:
    """Show the CDK diff for a stack to preview pending changes before deployment.

    Runs the command on the owner's local machine via SSH.

    Args:
        stack_name: Specific stack name (e.g., "GlitchAgentCoreStack").
                    If omitted, diffs all stacks.

    Returns:
        CDK diff output showing what would change.
    """
    from glitch.tools.ssh_tools import ssh_run_command
    stack_arg = stack_name or ""
    cmd = f"cd ~/IdeaProjects/AgentCore-Glitch/infrastructure && npx cdk diff {stack_arg} 2>&1"
    return await ssh_run_command(host="owner", command=cmd)


@tool
async def cdk_deploy_stack(stack_name: str, confirmed: bool = False) -> str:
    """Deploy a specific CDK stack to AWS.

    IMPORTANT: This is a destructive operation. Set confirmed=True only after
    you have received explicit human approval via Telegram.

    Args:
        stack_name: The CDK stack to deploy (e.g., "GlitchAgentCoreStack").
        confirmed: Must be True to proceed. If False, returns a confirmation prompt.

    Returns:
        Deployment output or a prompt asking for confirmation.
    """
    if not confirmed:
        return json.dumps({
            "status": "awaiting_confirmation",
            "message": (
                f"About to deploy {stack_name}. This will modify AWS infrastructure. "
                "Send Telegram confirmation to proceed, then call again with confirmed=True."
            ),
            "stack": stack_name,
        })

    from glitch.tools.ssh_tools import ssh_run_command
    cmd = (
        f"cd ~/IdeaProjects/AgentCore-Glitch/infrastructure && "
        f"npx cdk deploy {stack_name} --require-approval never 2>&1 | tail -80"
    )
    return await ssh_run_command(host="owner", command=cmd)
