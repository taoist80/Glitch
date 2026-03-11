"""Shared helpers for Lambda functions that call Amazon Bedrock AgentCore."""


def get_data_plane_endpoint(region: str) -> str:
    return f"https://bedrock-agentcore.{region}.amazonaws.com"


def parse_runtime_arn(runtime_arn: str) -> dict:
    """Parse a Bedrock AgentCore runtime ARN into its components.

    Returns a dict with keys: region, account_id, runtime_id.
    Raises ValueError for malformed ARNs.
    """
    parts = runtime_arn.split(':')
    if len(parts) != 6:
        raise ValueError(f"Invalid runtime ARN: {runtime_arn}")
    resource = parts[5]
    if not resource.startswith('runtime/'):
        raise ValueError(f"Invalid runtime ARN resource: {resource}")
    return {
        'region': parts[3],
        'account_id': parts[4],
        'runtime_id': resource.split('/', 1)[1],
    }
