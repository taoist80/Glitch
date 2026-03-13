"""Session modes (default, poet, roleplay). Each mode injects persona context into prompts."""

import logging
import os
from pathlib import Path
from typing import Coroutine, Optional, Tuple

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
    """Load Auri persona from split files (core + rules) or monolithic auri.md fallback."""
    try:
        from glitch.tools.soul_tools import (
            load_auri_core_from_s3, load_auri_rules_from_s3,
            get_auri_s3_config, load_auri_from_s3,
        )
        # Try layered files first (Phase 2+)
        core = load_auri_core_from_s3()
        rules = load_auri_rules_from_s3()
        if core and core.strip():
            parts = [core.strip()]
            if rules and rules.strip():
                parts.append(rules.strip())
            logger.info("Loaded layered Auri context: core=%d rules=%d chars",
                        len(core), len(rules) if rules else 0)
            return "\n\n".join(parts)
        # Fallback to monolithic auri.md
        bucket, _ = get_auri_s3_config()
        if bucket:
            content = load_auri_from_s3()
            if content and content.strip():
                return content.strip()
        for path in (_AURI_PATH, Path("/app/auri.md"), Path.home() / "auri.md"):
            if path.exists():
                return path.read_text().strip()
        logger.warning("auri persona not found (tried core+rules, auri.md S3, %s)", _AURI_PATH)
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


async def apply_mode_with_memories(
    mode_id: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    session_id: Optional[str] = None,
    active_members: Optional[list] = None,
) -> Tuple[str, Optional[str], Optional[list]]:
    """Like apply_mode_to_prompt, but also assembles full layered Auri context.

    Uses AuriContextComposer when split files exist (core+rules in S3), otherwise
    falls back to monolithic auri.md + memory retrieval.

    Returns:
        (prompt, system_prompt, mode_context) — mode_context is a list of
        SystemContentBlock for GlitchAgent injection, or None for non-roleplay modes.
    """
    prompt_out, sys_out = apply_mode_to_prompt(mode_id, prompt, system_prompt)
    if mode_id != MODE_ROLEPLAY:
        return prompt_out, sys_out, None

    # Try the layered composer first (Phase 5+)
    try:
        from glitch.auri_context import AuriContextComposer
        composer = AuriContextComposer()
        # Check if split files exist by seeing if core loads
        if composer._load_core():
            mode_context = await composer.compose(
                session_id=session_id or "",
                user_message=prompt,
                active_members=active_members,
            )
            # Build sys_out from composed blocks for Mistral/LLaVA fallback
            if mode_context:
                sys_out = "\n\n".join(
                    b.get("text", "") for b in mode_context if isinstance(b, dict) and "text" in b
                ) or sys_out
            return prompt_out, sys_out, mode_context or None
    except Exception as e:
        logger.warning("AuriContextComposer failed, falling back to legacy: %s", e)

    # Fallback: legacy monolithic path with memory retrieval
    from glitch.auri_memory import retrieve_memories

    try:
        memories = await retrieve_memories(None, prompt, k=8)
        if memories:
            block = (
                "\n\n## Auri's recalled memories\n\n"
                + "\n---\n".join(f"- {m}" for m in memories)
            )
            sys_out = (sys_out or "") + block
            logger.debug("auri_memory: injected %d memories into roleplay context", len(memories))
    except Exception as e:
        logger.warning("auri_memory: non-fatal injection error: %s", e)

    # Build mode_context blocks for GlitchAgent (Strands) system prompt injection.
    mode_context = None
    if sys_out:
        try:
            from strands.types.content import SystemContentBlock
            mode_context = [SystemContentBlock(text=sys_out)]
        except ImportError:
            logger.debug("strands not available; mode_context will be None")

    return prompt_out, sys_out, mode_context
