"""Auri Context Composer — assembles layered Auri context for system prompt injection.

Replaces the monolithic auri.md injection with a layered architecture:
  1. auri-core.md (always-on identity, ~600-900 tokens, S3 cached)
  2. auri-runtime-rules.md (behavioral rules, ~350-500 tokens, S3 cached)
  3. AuriState + SceneSummary (per-session dynamic state, ~100-250 tokens, DynamoDB)
  4. Participant profiles (per-member, vector DB via Lambda)
  5. Episodic memories (vector search by user message, via Lambda)
  6. Storybook excerpt (cold archive, only when mode=lore or backstory keyword)

Target: ~900-1200 tokens per turn (down from ~3000-3800 monolithic).
"""

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# In-process cache for S3 content (core + rules) — 5-minute TTL.
_cache: dict = {}
_CACHE_TTL = 300  # seconds


def _get_cached(key: str, loader) -> str:
    """Return cached value or call loader() and cache the result."""
    entry = _cache.get(key)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["val"]
    val = loader()
    _cache[key] = {"val": val, "ts": time.time()}
    return val


def invalidate_cache(key: Optional[str] = None):
    """Invalidate S3 cache. Called after update_auri_core / update_auri_rules."""
    if key:
        _cache.pop(key, None)
    else:
        _cache.clear()


class AuriContextComposer:
    """Assembles layered Auri context for system prompt injection."""

    async def compose(
        self,
        session_id: str,
        user_message: str,
        active_members: Optional[list] = None,
    ) -> list:
        """Build system prompt blocks for roleplay mode.

        Returns a list of SystemContentBlock dicts suitable for GlitchAgent injection.
        Also returns a plain-text version for Mistral/LLaVA via the combined text.

        Args:
            session_id:      Current session ID for state lookup.
            user_message:    The user's message (used for memory retrieval).
            active_members:  List of participant IDs in this session.

        Returns:
            List of SystemContentBlock (with 'text' key).
        """
        from strands.types.content import SystemContentBlock

        parts: list[str] = []

        # 1. Load auri-core.md (cached)
        core = self._load_core()
        if core:
            parts.append(core)

        # 2. Load auri-runtime-rules.md (cached)
        rules = self._load_rules()
        if rules:
            parts.append(rules)

        # 3. Load per-session state + scene from DynamoDB
        state_text = await self._load_state(session_id)
        if state_text:
            parts.append(state_text)

        # 4. Retrieve participant profiles for active members
        members = active_members or []
        profiles_text = await self._load_profiles(members) if members else ""
        if profiles_text:
            parts.append(profiles_text)

        # 5. Retrieve episodic memories
        memories_text = await self._load_memories(user_message)
        if memories_text:
            parts.append(memories_text)

        # 6. Storybook (only for lore mode or backstory keywords)
        storybook_text = self._maybe_load_storybook(user_message, session_id)
        if storybook_text:
            parts.append(storybook_text)

        if not parts:
            logger.warning("AuriContextComposer: no layers loaded for session %s", session_id)
            return []

        # Roleplay preamble
        preamble = (
            "You are in Auri roleplay mode. The full persona definition is provided below. "
            "Do not use tools (SSH, read_file, etc.) to load or fetch auri.md — it is already in this context. "
            "Respond only as Auri using the definition below.\n\n"
        )

        assembled = preamble + "\n\n".join(parts)

        est_tokens = int(len(assembled.split()) * 1.3)
        logger.info(
            "AuriContextComposer: assembled %d chars (~%d tokens) for session %s",
            len(assembled), est_tokens, session_id,
        )

        return [SystemContentBlock(text=assembled)]

    def _load_core(self) -> str:
        """Load auri-core.md from S3 with in-process cache."""
        from glitch.tools.soul_tools import load_auri_core_from_s3
        return _get_cached("auri-core", load_auri_core_from_s3).strip()

    def _load_rules(self) -> str:
        """Load auri-runtime-rules.md from S3 with in-process cache."""
        from glitch.tools.soul_tools import load_auri_rules_from_s3
        return _get_cached("auri-rules", load_auri_rules_from_s3).strip()

    async def _load_state(self, session_id: str) -> str:
        """Load AuriState + SceneSummary from DynamoDB and format for context."""
        try:
            from glitch.auri_state import AuriStateManager
            mgr = AuriStateManager()
            state = mgr.load_state(session_id)
            scene = mgr.load_scene(session_id)
            return mgr.format_state_for_context(state, scene)
        except Exception as e:
            logger.warning("AuriContextComposer: state load failed: %s", e)
            return ""

    async def _load_profiles(self, member_ids: list) -> str:
        """Retrieve participant profiles from vector DB."""
        try:
            from glitch.auri_memory import retrieve_participant_profiles
            profiles = await retrieve_participant_profiles(member_ids, k=1)
            if not profiles:
                return ""
            lines = ["## Participant Profiles"]
            for p in profiles:
                lines.append(f"- {p}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("AuriContextComposer: profile load failed: %s", e)
            return ""

    async def _load_memories(self, user_message: str) -> str:
        """Retrieve episodic memories relevant to the user message."""
        try:
            from glitch.auri_memory import retrieve_memories
            memories = await retrieve_memories(None, user_message, k=5)
            if not memories:
                return ""
            lines = ["## Auri's recalled memories"]
            for m in memories:
                lines.append(f"- {m}")
            return "\n".join(lines)
        except Exception as e:
            logger.warning("AuriContextComposer: memory retrieval failed: %s", e)
            return ""

    def _maybe_load_storybook(self, user_message: str, session_id: str) -> str:
        """Load storybook excerpt only when relevant (lore mode or backstory keywords)."""
        lore_keywords = {"backstory", "origin", "lore", "history", "how were you made",
                         "where did you come from", "tell me about yourself"}
        msg_lower = user_message.lower()
        if not any(kw in msg_lower for kw in lore_keywords):
            return ""
        try:
            from glitch.tools.soul_tools import load_story_book
            content = load_story_book()
            if not content or not content.strip():
                return ""
            # Truncate to avoid excessive token cost
            text = content.strip()
            if len(text) > 2000:
                text = text[:2000] + "\n\n[...storybook truncated for context limit]"
            return "## Storybook (Lore Archive)\n\n" + text
        except Exception as e:
            logger.warning("AuriContextComposer: storybook load failed: %s", e)
            return ""
