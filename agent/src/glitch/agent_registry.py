"""Agent registry for chat agents (glitch, mistral, llava).

In-process registry populated at startup. Used by server and channels to resolve
which agent handles a session. Duck-typed: agents need process_message() and get_status().
"""

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default agent when no session override. Allowed: glitch, mistral, llava.
_DEFAULT_AGENT_ID_ENV = "GLITCH_DEFAULT_CHAT_AGENT"
_DEFAULT_AGENT_ID_FALLBACK = "mistral"
_ALLOWED_AGENT_IDS = frozenset({"glitch", "mistral", "llava"})

_registry: Dict[str, Any] = {}  # agent_id -> agent instance
_meta: Dict[str, Dict[str, Any]] = {}  # agent_id -> { name?, description?, is_default? }
_default_agent_id: Optional[str] = None


def _get_default_from_env() -> str:
    """Read default agent id from env; validate against allowed set."""
    raw = (os.environ.get(_DEFAULT_AGENT_ID_ENV) or _DEFAULT_AGENT_ID_FALLBACK).strip().lower()
    return raw if raw in _ALLOWED_AGENT_IDS else _DEFAULT_AGENT_ID_FALLBACK


def register_agent(agent_id: str, agent: Any, meta: Optional[Dict[str, Any]] = None) -> None:
    """Register a chat agent by id.

    Args:
        agent_id: Identifier (e.g. glitch, mistral, llava).
        agent: Instance with process_message() and get_status() (duck-typed).
        meta: Optional { name?, description? }. Default agent comes from env (get_default_agent_id).
    """
    _registry[agent_id] = agent
    _meta[agent_id] = dict(meta or {})
    logger.info("Registered agent", extra={"agent_id": agent_id})


def get_agent(agent_id: str) -> Optional[Any]:
    """Return the agent instance for agent_id, or None if not registered."""
    return _registry.get(agent_id)


def list_agents() -> List[Dict[str, Any]]:
    """Return list of { id, name?, description?, is_default? } for all registered agents.
    Optionally include status from get_status() per agent.
    """
    result: List[Dict[str, Any]] = []
    default = get_default_agent_id()
    for aid, agent in _registry.items():
        entry: Dict[str, Any] = {
            "id": aid,
            "name": _meta.get(aid, {}).get("name") or aid.capitalize(),
            "description": _meta.get(aid, {}).get("description", ""),
            "is_default": aid == default,
        }
        try:
            entry["status"] = agent.get_status()
        except Exception:
            entry["status"] = {}
        result.append(entry)
    return result


def get_default_agent_id() -> str:
    """Return the configured default agent id (e.g. mistral). Used when no session override."""
    global _default_agent_id
    if _default_agent_id is not None:
        return _default_agent_id
    return _get_default_from_env()


def set_default_agent_id(agent_id: str) -> None:
    """Set the default agent id (config override). Validates against allowed set."""
    global _default_agent_id
    if agent_id not in _ALLOWED_AGENT_IDS:
        logger.warning("set_default_agent_id: invalid agent_id=%s, allowed=%s", agent_id, _ALLOWED_AGENT_IDS)
        return
    _default_agent_id = agent_id
    logger.info("Default agent set", extra={"agent_id": agent_id})


def get_allowed_agent_ids() -> frozenset:
    """Return the set of allowed agent id strings."""
    return _ALLOWED_AGENT_IDS
