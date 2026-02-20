"""Skill selector: selects up to 3 skills for a TaskSpec.

Dataflow:
    TaskSpec + model -> SkillSelector.select() -> SkillSelectionResult
    
Selection algorithm:
    1. Find candidate skills by matching triggers and tags
    2. Filter by model compatibility (allowlist/denylist)
    3. Score candidates by match quality
    4. Sort by (score desc, priority desc, id asc) for determinism
    5. Take top 3

Invariants:
    - Same input always produces same output (deterministic)
    - Max 3 skills returned
    - Model compatibility is enforced
    - All decisions are logged with reason codes
"""

import logging
from typing import List, Set

from glitch.skills.types import (
    SkillPackage,
    TaskSpec,
    SelectedSkill,
    SkillSelectionResult,
    SelectionReason,
)
from glitch.skills.registry import SkillRegistry, normalize_trigger

logger = logging.getLogger(__name__)

MAX_SKILLS = 3


class SkillSelector:
    """Selects skills for a task based on triggers, tags, and model compatibility.
    
    Attributes:
        registry: SkillRegistry to query for skills
        max_skills: Maximum number of skills to select (default 3)
    """
    
    def __init__(self, registry: SkillRegistry, max_skills: int = MAX_SKILLS):
        """Initialize SkillSelector.
        
        Args:
            registry: SkillRegistry containing available skills
            max_skills: Maximum skills to select (default 3)
        """
        self.registry = registry
        self.max_skills = max_skills
        
    def select(self, task_spec: TaskSpec, model_name: str) -> SkillSelectionResult:
        """Select skills for a task specification.
        
        Args:
            task_spec: TaskSpec with skill_tags and raw_triggers
            model_name: Name of the model that will execute the task
            
        Returns:
            SkillSelectionResult with selected skills and exclusion reasons
        """
        candidates: List[tuple[SkillPackage, float, List[SelectionReason]]] = []
        excluded: List[tuple[str, SelectionReason]] = []
        seen_ids: Set[str] = set()
        
        # Collect candidates from tags
        skill_tags = task_spec.get("skill_tags", [])
        for tag in skill_tags:
            for skill in self.registry.find_by_tag(tag):
                if skill.metadata.id not in seen_ids:
                    seen_ids.add(skill.metadata.id)
                    score, reasons = self._score_skill(skill, task_spec, is_tag_match=True)
                    candidates.append((skill, score, reasons))
                    
        # Collect candidates from raw triggers
        raw_triggers = task_spec.get("raw_triggers", [])
        for trigger in raw_triggers:
            for skill in self.registry.find_by_trigger(trigger):
                if skill.metadata.id not in seen_ids:
                    seen_ids.add(skill.metadata.id)
                    score, reasons = self._score_skill(skill, task_spec, is_trigger_match=True)
                    candidates.append((skill, score, reasons))
                    
        total_candidates = len(candidates)
        
        # Filter by model compatibility
        compatible_candidates: List[tuple[SkillPackage, float, List[SelectionReason]]] = []
        for skill, score, reasons in candidates:
            if not skill.metadata.is_compatible_with_model(model_name):
                excluded.append((skill.metadata.id, SelectionReason.MODEL_DENYLIST_EXCLUDED))
                logger.debug(
                    f"Skill {skill.metadata.id} excluded: incompatible with model {model_name}"
                )
            else:
                if skill.metadata.model_allowlist:
                    reasons.append(SelectionReason.MODEL_ALLOWLIST)
                compatible_candidates.append((skill, score, reasons))
                
        # Sort deterministically: score desc, priority desc, id asc
        compatible_candidates.sort(
            key=lambda x: (-x[1], -x[0].metadata.priority, x[0].metadata.id)
        )
        
        # Select top N
        selected: List[SelectedSkill] = []
        for skill, score, reasons in compatible_candidates[:self.max_skills]:
            selected.append(SelectedSkill(
                skill=skill,
                reasons=reasons,
                match_score=score,
            ))
            
        # Mark remaining as excluded due to max limit
        for skill, score, reasons in compatible_candidates[self.max_skills:]:
            excluded.append((skill.metadata.id, SelectionReason.MAX_SKILLS_REACHED))
            
        result = SkillSelectionResult(
            selected=selected,
            excluded=excluded,
            model_used=model_name,
            total_candidates=total_candidates,
        )
        
        logger.info(
            f"Selected {len(selected)} skills for model {model_name}: "
            f"{[s.skill_id for s in selected]}"
        )
        
        return result
    
    def _score_skill(
        self,
        skill: SkillPackage,
        task_spec: TaskSpec,
        is_tag_match: bool = False,
        is_trigger_match: bool = False,
    ) -> tuple[float, List[SelectionReason]]:
        """Score a skill for selection.
        
        Scoring factors:
        - Trigger match: +2.0
        - Tag match: +1.0
        - Priority bonus: priority / 100 (0.0 to 1.0)
        - Multiple tag matches: +0.5 per additional tag
        
        Args:
            skill: Skill to score
            task_spec: Task specification
            is_tag_match: Whether skill was found via tag
            is_trigger_match: Whether skill was found via trigger
            
        Returns:
            Tuple of (score, list of reasons)
        """
        score = 0.0
        reasons: List[SelectionReason] = []
        
        if is_trigger_match:
            score += 2.0
            reasons.append(SelectionReason.TRIGGER_MATCH)
            
        if is_tag_match:
            score += 1.0
            reasons.append(SelectionReason.TAG_MATCH)
            
        # Count additional tag matches
        skill_tags_lower = {t.lower() for t in skill.metadata.tags}
        task_tags_lower = {t.lower() for t in task_spec.get("skill_tags", [])}
        additional_matches = len(skill_tags_lower & task_tags_lower) - 1
        if additional_matches > 0:
            score += 0.5 * additional_matches
            
        # Priority bonus
        score += skill.metadata.priority / 100.0
        
        # Add priority tie-break reason if priority is non-default
        if skill.metadata.priority != 50:
            reasons.append(SelectionReason.PRIORITY_TIE_BREAK)
            
        return score, reasons


def create_selector_with_skills(
    skills: List[SkillPackage],
    max_skills: int = MAX_SKILLS,
) -> SkillSelector:
    """Convenience function to create a selector with pre-loaded skills.
    
    Args:
        skills: List of SkillPackage instances
        max_skills: Maximum skills to select
        
    Returns:
        Configured SkillSelector
    """
    registry = SkillRegistry()
    registry.register_all(skills)
    return SkillSelector(registry, max_skills)
