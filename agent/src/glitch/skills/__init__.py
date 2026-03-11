"""Skills module: keyword-based skill injection for Glitch agent.

Public API:
    - select_skills_for_message: Match user message to skills, return prompt suffix
"""

from glitch.skills.skills import select_skills_for_message

__all__ = ["select_skills_for_message"]
