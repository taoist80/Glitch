"""Per-session Auri state and scene tracking (DynamoDB-backed).

Stores dynamic state (mood, mode, sliders, escalation level) and scene summaries
per session_id in the glitch-telegram-config DynamoDB table, using partition keys
like AURI_STATE#{session_id} and AURI_SCENE#{session_id}.
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_SLIDERS = {
    "strictness": 3,
    "teasing": 3,
    "playfulness": 4,
    "toddler_tone": 1,
}


@dataclass
class AuriState:
    """Per-session Auri dynamic state."""

    mode: str = "cozy"                    # cozy, play, care, bratty, comfort, lore
    mood: str = "warm"                    # warm, playful, firm, gentle, mischievous
    goal: str = ""                        # current scene goal
    active_members: list = field(default_factory=lambda: ["Arc"])
    sliders: dict = field(default_factory=lambda: dict(_DEFAULT_SLIDERS))
    dynamic_level: int = 2                # escalation ladder 1-6


@dataclass
class SceneSummary:
    """Per-session scene tracking."""

    scene_mode: str = "dm"                # dm, group
    energy: str = "calm"                  # calm, playful, high, tense
    recent_events: list = field(default_factory=list)   # last 3-5 events
    open_loops: list = field(default_factory=list)      # unresolved threads


class AuriStateManager:
    """Load/save AuriState and SceneSummary per session from DynamoDB."""

    def __init__(self, table_name: Optional[str] = None):
        self._table_name = table_name or os.environ.get("GLITCH_CONFIG_TABLE", "glitch-telegram-config")
        self._table = None

    @property
    def table(self):
        if self._table is None:
            import boto3
            region = os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "us-west-2"
            self._table = boto3.resource("dynamodb", region_name=region).Table(self._table_name)
        return self._table

    def load_state(self, session_id: str) -> AuriState:
        """Load AuriState from DynamoDB, returning defaults if missing."""
        try:
            resp = self.table.get_item(
                Key={"pk": f"AURI_STATE#{session_id}", "sk": "state"}
            )
            item = resp.get("Item")
            if item and "data" in item:
                data = json.loads(item["data"]) if isinstance(item["data"], str) else item["data"]
                return AuriState(
                    mode=data.get("mode", "cozy"),
                    mood=data.get("mood", "warm"),
                    goal=data.get("goal", ""),
                    active_members=data.get("active_members", ["Arc"]),
                    sliders=data.get("sliders", dict(_DEFAULT_SLIDERS)),
                    dynamic_level=data.get("dynamic_level", 2),
                )
        except Exception as e:
            logger.warning("Failed to load AuriState for %s: %s", session_id, e)
        return AuriState()

    def save_state(self, session_id: str, state: AuriState) -> None:
        """Write AuriState to DynamoDB."""
        try:
            self.table.put_item(
                Item={
                    "pk": f"AURI_STATE#{session_id}",
                    "sk": "state",
                    "data": json.dumps(asdict(state)),
                    "updated_at": int(time.time()),
                }
            )
        except Exception as e:
            logger.warning("Failed to save AuriState for %s: %s", session_id, e)

    def load_scene(self, session_id: str) -> SceneSummary:
        """Load SceneSummary from DynamoDB, returning defaults if missing."""
        try:
            resp = self.table.get_item(
                Key={"pk": f"AURI_SCENE#{session_id}", "sk": "scene"}
            )
            item = resp.get("Item")
            if item and "data" in item:
                data = json.loads(item["data"]) if isinstance(item["data"], str) else item["data"]
                return SceneSummary(
                    scene_mode=data.get("scene_mode", "dm"),
                    energy=data.get("energy", "calm"),
                    recent_events=data.get("recent_events", []),
                    open_loops=data.get("open_loops", []),
                )
        except Exception as e:
            logger.warning("Failed to load SceneSummary for %s: %s", session_id, e)
        return SceneSummary()

    def save_scene(self, session_id: str, scene: SceneSummary) -> None:
        """Write SceneSummary to DynamoDB."""
        try:
            self.table.put_item(
                Item={
                    "pk": f"AURI_SCENE#{session_id}",
                    "sk": "scene",
                    "data": json.dumps(asdict(scene)),
                    "updated_at": int(time.time()),
                }
            )
        except Exception as e:
            logger.warning("Failed to save SceneSummary for %s: %s", session_id, e)

    def format_state_for_context(self, state: AuriState, scene: SceneSummary) -> str:
        """Format state + scene into a compact context string for system prompt injection."""
        lines = [
            "## Auri Session State",
            f"Mode: {state.mode} | Mood: {state.mood} | Energy: {scene.energy} | Scene: {scene.scene_mode}",
            f"Dynamic level: {state.dynamic_level}/6 | Members: {', '.join(state.active_members)}",
        ]
        if state.goal:
            lines.append(f"Goal: {state.goal}")
        slider_parts = [f"{k}={v}" for k, v in state.sliders.items()]
        if slider_parts:
            lines.append(f"Sliders: {', '.join(slider_parts)}")
        if scene.recent_events:
            lines.append(f"Recent: {'; '.join(scene.recent_events[-5:])}")
        if scene.open_loops:
            lines.append(f"Open threads: {'; '.join(scene.open_loops)}")
        return "\n".join(lines)
