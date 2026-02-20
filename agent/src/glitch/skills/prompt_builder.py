"""Prompt builder: assembles final prompt with skill content.

Dataflow:
    base_prompt + List[SelectedSkill] -> build_prompt_with_skills() -> final_prompt
    
The skills section is injected in a stable, inspectable format:
    ## Active Skills
    
    ### [skill-id] (v1.0.0)
    [skill content]
    
    ---
    
    ### [skill-id-2] (v1.0.0)
    [skill content 2]
"""

import logging
from typing import List, Optional

from glitch.skills.types import SelectedSkill, SkillSelectionResult

logger = logging.getLogger(__name__)

SKILLS_SECTION_HEADER = """
## Active Skills

The following skills are active for this task. Follow their guidance when relevant.
"""

SKILLS_SECTION_FOOTER = """
---
End of Active Skills
"""


def build_prompt_with_skills(
    base_prompt: str,
    selected_skills: List[SelectedSkill],
    insert_position: str = "after_context",
) -> str:
    """Build the final prompt with skill content injected.
    
    Args:
        base_prompt: The base system prompt (SOUL + technical context)
        selected_skills: List of selected skills to inject
        insert_position: Where to insert skills:
            - "after_context": After technical context (default)
            - "before_context": Before technical context
            - "end": At the end of the prompt
            
    Returns:
        Complete prompt with skills section
    """
    if not selected_skills:
        return base_prompt
        
    skills_section = _build_skills_section(selected_skills)
    
    if insert_position == "end":
        return f"{base_prompt}\n{skills_section}"
    elif insert_position == "before_context":
        # Insert before "## Technical Context"
        marker = "## Technical Context"
        if marker in base_prompt:
            idx = base_prompt.index(marker)
            return f"{base_prompt[:idx]}{skills_section}\n{base_prompt[idx:]}"
        return f"{base_prompt}\n{skills_section}"
    else:  # after_context (default)
        return f"{base_prompt}\n{skills_section}"


def _build_skills_section(selected_skills: List[SelectedSkill]) -> str:
    """Build the skills section content.
    
    Args:
        selected_skills: List of selected skills
        
    Returns:
        Formatted skills section string
    """
    parts = [SKILLS_SECTION_HEADER]
    
    for i, selected in enumerate(selected_skills):
        skill = selected.skill
        metadata = skill.metadata
        
        # Skill header with ID and version
        header = f"### [{metadata.id}] (v{metadata.version})"
        
        # Add reason codes as comment
        reasons = ", ".join(r.value for r in selected.reasons)
        reason_comment = f"<!-- Selected: {reasons}, score: {selected.match_score:.2f} -->"
        
        parts.append(f"{header}\n{reason_comment}\n")
        parts.append(skill.content)
        
        if i < len(selected_skills) - 1:
            parts.append("\n---\n")
            
    parts.append(SKILLS_SECTION_FOOTER)
    
    return "\n".join(parts)


class SkillPromptBuilder:
    """Stateful prompt builder that tracks skill injection.
    
    Useful for logging and debugging which skills were injected.
    
    Attributes:
        base_prompt: The base system prompt
        last_selection: Last skill selection result
        last_prompt: Last built prompt
    """
    
    def __init__(self, base_prompt: str):
        """Initialize SkillPromptBuilder.
        
        Args:
            base_prompt: Base system prompt to build upon
        """
        self.base_prompt = base_prompt
        self.last_selection: Optional[SkillSelectionResult] = None
        self.last_prompt: Optional[str] = None
        
    def build(
        self,
        selection_result: SkillSelectionResult,
        insert_position: str = "after_context",
    ) -> str:
        """Build prompt with skills from selection result.
        
        Args:
            selection_result: Result from SkillSelector
            insert_position: Where to insert skills
            
        Returns:
            Complete prompt with skills
        """
        self.last_selection = selection_result
        self.last_prompt = build_prompt_with_skills(
            self.base_prompt,
            selection_result.selected,
            insert_position,
        )
        
        logger.info(
            f"Built prompt with {len(selection_result.selected)} skills: "
            f"{[s.skill_id for s in selection_result.selected]}"
        )
        
        return self.last_prompt
    
    def get_injection_summary(self) -> dict:
        """Get summary of last skill injection for telemetry.
        
        Returns:
            Dictionary with injection details
        """
        if not self.last_selection:
            return {"skills_injected": 0, "skill_ids": []}
            
        return {
            "skills_injected": len(self.last_selection.selected),
            "skill_ids": [s.skill_id for s in self.last_selection.selected],
            "model_used": self.last_selection.model_used,
            "total_candidates": self.last_selection.total_candidates,
            "excluded_count": len(self.last_selection.excluded),
        }
