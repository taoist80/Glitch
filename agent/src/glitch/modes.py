"""Session modes (default, poet). Poet mode injects poet-soul + story-book into context."""

import logging
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MODE_DEFAULT = "default"
MODE_POET = "poet"


def get_poet_context() -> str:
    """Load poet-soul and story-book and return combined context for Poet mode."""
    try:
        from glitch.poet_soul import load_poet_soul
        from glitch.tools.soul_tools import load_story_book
        soul = load_poet_soul()
        story_book = load_story_book()
        parts = []
        if soul and soul.strip():
            parts.append(soul.strip())
        if story_book and story_book.strip():
            parts.append("## Story book (for continuity)\n\n" + story_book.strip())
        if not parts:
            return ""
        return "\n\n".join(parts)
    except Exception as e:
        logger.warning("Failed to load poet context: %s", e)
        return ""


def apply_mode_to_prompt(
    mode_id: str,
    prompt: str,
    system_prompt: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """When mode is poet, inject poet-soul + story-book into system prompt (or prompt).

    Returns:
        (prompt, system_prompt). If mode_id is poet, system_prompt is extended with poet context;
        if no system_prompt was given, prompt is prefixed with poet context.
    """
    if mode_id != MODE_POET:
        return prompt, system_prompt
    context = get_poet_context()
    if not context:
        return prompt, system_prompt
    if system_prompt is not None and system_prompt.strip():
        new_system = f"{system_prompt.strip()}\n\n{context}"
        return prompt, new_system
    new_prompt = f"{context}\n\n---\n\n{prompt}"
    return new_prompt, system_prompt
