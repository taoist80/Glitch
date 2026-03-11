"""Shared types for the AgentCore A2A JSON-RPC 2.0 protocol.

These TypedDicts mirror the contract specified at:
https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html

Used by Glitch for any future A2A communication patterns.
"""

from typing import Any, Dict, List, Literal, Optional
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Request types (client → A2A server)
# ---------------------------------------------------------------------------


class A2AMessagePart(TypedDict):
    """A single content part inside an A2A message."""

    kind: Literal["text"]
    text: str


class A2AMessage(TypedDict):
    """An A2A message envelope as defined by the AgentCore A2A contract."""

    role: Literal["user", "assistant"]
    parts: List[A2AMessagePart]
    messageId: str


class A2AParams(TypedDict):
    """Params block for the message/send JSON-RPC method."""

    message: A2AMessage


class A2ARequest(TypedDict):
    """Full JSON-RPC 2.0 A2A request payload.

    POST / with Content-Type: application/json.
    Method must be "message/send" per AgentCore A2A contract.
    """

    jsonrpc: Literal["2.0"]
    id: str
    method: Literal["message/send"]
    params: A2AParams


# ---------------------------------------------------------------------------
# Response types (A2A server → client)
# ---------------------------------------------------------------------------


class A2AArtifactPart(TypedDict):
    """One part of an artifact in an A2A response."""

    kind: str
    text: str


class A2AArtifact(TypedDict, total=False):
    """An artifact returned by a completed A2A task."""

    artifactId: str
    name: str
    parts: List[A2AArtifactPart]


class A2AResult(TypedDict):
    """The result block of a successful A2A JSON-RPC response."""

    artifacts: List[A2AArtifact]


class A2AResponse(TypedDict):
    """Full JSON-RPC 2.0 A2A response (success path)."""

    jsonrpc: Literal["2.0"]
    id: str
    result: A2AResult


# ---------------------------------------------------------------------------
# Error types (A2A JSON-RPC 2.0 error responses)
# ---------------------------------------------------------------------------

# Error codes from the AgentCore A2A contract
A2A_ERROR_RESOURCE_NOT_FOUND = -32501
A2A_ERROR_VALIDATION = -32052
A2A_ERROR_THROTTLING = -32053
A2A_ERROR_RESOURCE_CONFLICT = -32054
A2A_ERROR_RUNTIME_CLIENT = -32055


class A2AErrorDetail(TypedDict):
    """JSON-RPC 2.0 error object."""

    code: int
    message: str


class A2AErrorResponse(TypedDict):
    """Full JSON-RPC 2.0 error response.

    Note: A2A errors are returned with HTTP 200 status codes per the contract;
    the actual error information is inside the JSON-RPC error field.
    """

    jsonrpc: Literal["2.0"]
    id: str
    error: A2AErrorDetail


# ---------------------------------------------------------------------------
# Agent Card types (GET /.well-known/agent-card.json)
# ---------------------------------------------------------------------------


class AgentCardSkill(TypedDict, total=False):
    """A skill advertised in an Agent Card."""

    id: str
    name: str
    description: str
    tags: List[str]


class AgentCardCapabilities(TypedDict, total=False):
    """Capability flags in an Agent Card."""

    streaming: bool


class AgentCard(TypedDict, total=False):
    """Agent Card metadata served at /.well-known/agent-card.json.

    Used for agent discovery in multi-agent systems.
    """

    name: str
    description: str
    version: str
    url: str
    protocolVersion: str
    preferredTransport: str
    capabilities: AgentCardCapabilities
    defaultInputModes: List[str]
    defaultOutputModes: List[str]
    skills: List[AgentCardSkill]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def build_a2a_request(query: str, request_id: str, message_id: str) -> A2ARequest:
    """Construct a well-formed A2A request dict ready for json.dumps."""
    return A2ARequest(
        jsonrpc="2.0",
        id=request_id,
        method="message/send",
        params=A2AParams(
            message=A2AMessage(
                role="user",
                parts=[A2AMessagePart(kind="text", text=query)],
                messageId=message_id,
            )
        ),
    )


def extract_a2a_text(response: Dict[str, Any]) -> Optional[str]:
    """Pull the first text part from an A2A response artifact.

    Returns None if the response cannot be parsed as a valid A2A response.
    """
    result = response.get("result")
    if not isinstance(result, dict):
        return None
    artifacts: List[Dict[str, Any]] = result.get("artifacts", [])
    if not artifacts:
        return None
    parts: List[Dict[str, Any]] = artifacts[0].get("parts", [])
    if not parts:
        return None
    text = parts[0].get("text")
    return str(text) if text is not None else None
