"""Skills runtime module for Glitch agent.

This module provides a first-class skill system with three layers:
1. Skill packaging (filesystem-based skill definitions)
2. Skill loading + selection (runtime validation and matching)
3. Model routing + prompt assembly (planner/executor flow)

Public API:
    - SkillLoader: Reads and validates skill packages from disk
    - SkillRegistry: Indexes skills by trigger/tag for fast lookup
    - SkillSelector: Selects up to 3 skills for a TaskSpec
    - TaskPlanner: Produces TaskSpec from user message
    - build_prompt_with_skills: Assembles final prompt with skill content

Dataflow:
    User Message -> TaskPlanner -> TaskSpec
                                      |
                                      v
                              SkillSelector(TaskSpec, model)
                                      |
                                      v
                              List[SelectedSkill] (max 3)
                                      |
                                      v
                              build_prompt_with_skills()
                                      |
                                      v
                              Final system prompt
"""

from glitch.skills.types import (
    SkillMetadata,
    SkillPackage,
    TaskSpec,
    SelectedSkill,
    SkillSelectionResult,
    SkillValidationError,
)
from glitch.skills.loader import SkillLoader
from glitch.skills.registry import SkillRegistry
from glitch.skills.selector import SkillSelector
from glitch.skills.planner import TaskPlanner
from glitch.skills.prompt_builder import build_prompt_with_skills, SkillPromptBuilder

__all__ = [
    # Types
    "SkillMetadata",
    "SkillPackage",
    "TaskSpec",
    "SelectedSkill",
    "SkillSelectionResult",
    "SkillValidationError",
    # Runtime
    "SkillLoader",
    "SkillRegistry",
    "SkillSelector",
    "TaskPlanner",
    # Prompt building
    "build_prompt_with_skills",
    "SkillPromptBuilder",
]
