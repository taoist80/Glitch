"""Simplified skill pipeline: load → keyword-match → inject.

Replaces the 5-class pipeline (Loader/Registry/Planner/Selector/PromptBuilder)
with a single function. Skills are plain folders with skill.md + metadata.json.

Usage::

    prompt_suffix = select_skills_for_message(user_message, skills_dir)
    # "" when no skills match; else "\n\n---\n\n## Active Skills\n\n..."
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

MAX_SKILLS = 3


def _normalize(text: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation except hyphens."""
    text = text.lower().strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\w\s-]", "", text)
    return text


def _find_skills_dir(override: Optional[Path] = None) -> Path:
    """Locate the skills directory relative to this file or the app root."""
    if override:
        return override

    this_file = Path(__file__).resolve()

    # Container: /app/glitch/skills/skills.py → /app/skills
    candidate = this_file.parent.parent.parent / "skills"
    if candidate.exists():
        return candidate

    # Dev: agent/src/glitch/skills/skills.py → agent/skills
    candidate = this_file.parent.parent.parent.parent / "skills"
    if candidate.exists():
        return candidate

    return this_file.parent.parent.parent / "skills"


def select_skills_for_message(
    user_message: str,
    skills_dir: Optional[Path] = None,
) -> str:
    """Return a prompt suffix with up to MAX_SKILLS matching skills injected.

    Args:
        user_message: The raw user message to match against skill triggers.
        skills_dir: Override the skill directory path (defaults to auto-detect).

    Returns:
        Empty string if no skills match; otherwise a formatted string to append
        to the system prompt.
    """
    root = _find_skills_dir(skills_dir)
    if not root.exists():
        return ""

    normalized_message = _normalize(user_message)

    candidates: list[tuple[int, str, str]] = []  # (priority, skill_id, content)

    for skill_dir in sorted(root.iterdir()):
        if not skill_dir.is_dir() or skill_dir.name.startswith((".", "_")):
            continue

        skill_md = skill_dir / "skill.md"
        metadata_path = skill_dir / "metadata.json"

        if not skill_md.exists() or not metadata_path.exists():
            continue

        try:
            metadata = json.loads(metadata_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping skill %s: bad metadata.json: %s", skill_dir.name, e)
            continue

        triggers: list[str] = metadata.get("triggers", [])
        priority: int = int(metadata.get("priority", 50))

        matched = any(_normalize(t) in normalized_message for t in triggers)
        if not matched:
            continue

        try:
            content = skill_md.read_text(encoding="utf-8").strip()
        except OSError as e:
            logger.warning("Skipping skill %s: cannot read skill.md: %s", skill_dir.name, e)
            continue

        if content:
            candidates.append((-priority, skill_dir.name, content))
            logger.info("Skill matched: %s (priority=%d)", skill_dir.name, priority)

    if not candidates:
        return ""

    # Sort by descending priority (stored as -priority), then name for determinism
    candidates.sort(key=lambda x: (x[0], x[1]))
    top = candidates[:MAX_SKILLS]

    sections = [content for _, _, content in top]
    return "\n\n---\n\n## Active Skills\n\n" + "\n\n---\n\n".join(sections)
