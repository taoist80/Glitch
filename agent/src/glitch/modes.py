"""Session modes (default, poet, roleplay). Each mode injects persona context into prompts."""

import logging
import os
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

MODE_DEFAULT = "default"
MODE_POET = "poet"
MODE_ROLEPLAY = "roleplay"

# Auri persona file: agent/auri.md (alongside poet-soul.md)
_AURI_PATH = Path(__file__).parent.parent.parent / "auri.md"


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


def get_roleplay_context() -> str:
    """Load auri.md from S3 (preferred) or local file fallback."""
    try:
        from glitch.tools.soul_tools import get_auri_s3_config, load_auri_from_s3
        bucket, _ = get_auri_s3_config()
        if bucket:
            content = load_auri_from_s3()
            if content and content.strip():
                return content.strip()
        for path in (_AURI_PATH, Path("/app/auri.md"), Path.home() / "auri.md"):
            if path.exists():
                return path.read_text().strip()
        logger.warning("auri.md not found (tried S3, %s, /app/auri.md)", _AURI_PATH)
        return ""
    except Exception as e:
        logger.warning("Failed to load roleplay context: %s", e)
        return ""


def _inject_context(context: str, prompt: str, system_prompt: Optional[str]) -> Tuple[str, Optional[str]]:
    """Inject persona context into system prompt (preferred) or prompt prefix."""
    if not context:
        return prompt, system_prompt
    if system_prompt is not None and system_prompt.strip():
        return prompt, f"{system_prompt.strip()}\n\n{context}"
    return f"{context}\n\n---\n\n{prompt}", system_prompt


# Instruction so the model does not try to read auri.md via SSH or other tools when in roleplay mode.
_ROLEPLAY_PREAMBLE = (
    "You are in Auri roleplay mode. The full persona definition is provided below. "
    "Do not use tools (SSH, read_file, etc.) to load or fetch auri.md — it is already in this context. "
    "Respond only as Auri using the definition below.\n\n"
)
# When auri.md could not be loaded (e.g. S3 missing), still enforce Auri mode and no tool use for fetching it.
_ROLEPLAY_FALLBACK = (
    "You are Auri (Aurelion), a playful caretaker android lion. Respond in character. "
    "Do not use tools to read or fetch auri.md or any file; stay in character and reply to the user.\n\n"
)


def apply_mode_to_prompt(
    mode_id: str,
    prompt: str,
    system_prompt: Optional[str] = None,
) -> Tuple[str, Optional[str]]:
    """Inject mode-specific persona context into system prompt (or prompt prefix).

    Returns:
        (prompt, system_prompt) — possibly modified with persona context.
    """
    if mode_id == MODE_POET:
        return _inject_context(get_poet_context(), prompt, system_prompt)
    if mode_id == MODE_ROLEPLAY:
        context = get_roleplay_context()
        if context:
            context = _ROLEPLAY_PREAMBLE + context
        else:
            context = _ROLEPLAY_FALLBACK
        return _inject_context(context, prompt, system_prompt)
    return prompt, system_prompt
