"""Skill registry: indexes skills by trigger and tag for fast lookup.

Dataflow:
    List[SkillPackage] -> SkillRegistry.register_all() -> indexed registry
    trigger/tag query -> SkillRegistry.find_by_*() -> List[SkillPackage]
    
The registry maintains:
    - trigger_index: Maps normalized trigger phrases to skills
    - tag_index: Maps tags to skills
    - skills_by_id: Direct lookup by skill ID
"""

import logging
import re
from typing import Dict, List, Optional, Set

from glitch.skills.types import SkillPackage

logger = logging.getLogger(__name__)


def normalize_trigger(trigger: str) -> str:
    """Normalize a trigger phrase for matching.
    
    Normalization:
    - Lowercase
    - Strip whitespace
    - Collapse multiple spaces
    - Remove punctuation except hyphens
    
    Args:
        trigger: Raw trigger string
        
    Returns:
        Normalized trigger string
    """
    normalized = trigger.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"[^\w\s-]", "", normalized)
    return normalized


class SkillRegistry:
    """Indexes skills for fast lookup by trigger and tag.
    
    Thread-safety: This class is NOT thread-safe. Create separate instances
    for concurrent access or use external synchronization.
    
    Attributes:
        skills_by_id: Map of skill_id -> SkillPackage
        trigger_index: Map of normalized_trigger -> Set[skill_id]
        tag_index: Map of tag -> Set[skill_id]
    """
    
    def __init__(self):
        """Initialize empty registry."""
        self.skills_by_id: Dict[str, SkillPackage] = {}
        self.trigger_index: Dict[str, Set[str]] = {}
        self.tag_index: Dict[str, Set[str]] = {}
        
    def register(self, skill: SkillPackage) -> None:
        """Register a single skill in the registry.
        
        Args:
            skill: SkillPackage to register
        """
        skill_id = skill.metadata.id
        
        # Store by ID
        self.skills_by_id[skill_id] = skill
        
        # Index by triggers
        for trigger in skill.metadata.triggers:
            normalized = normalize_trigger(trigger)
            if normalized not in self.trigger_index:
                self.trigger_index[normalized] = set()
            self.trigger_index[normalized].add(skill_id)
            
        # Index by tags
        for tag in skill.metadata.tags:
            tag_lower = tag.lower()
            if tag_lower not in self.tag_index:
                self.tag_index[tag_lower] = set()
            self.tag_index[tag_lower].add(skill_id)
            
        logger.debug(
            f"Registered skill {skill_id}: "
            f"{len(skill.metadata.triggers)} triggers, "
            f"{len(skill.metadata.tags)} tags"
        )
        
    def register_all(self, skills: List[SkillPackage]) -> None:
        """Register multiple skills.
        
        Args:
            skills: List of SkillPackage instances to register
        """
        for skill in skills:
            self.register(skill)
        logger.info(f"Registered {len(skills)} skills in registry")
        
    def get_by_id(self, skill_id: str) -> Optional[SkillPackage]:
        """Get a skill by its ID.
        
        Args:
            skill_id: Skill identifier
            
        Returns:
            SkillPackage if found, None otherwise
        """
        return self.skills_by_id.get(skill_id)
    
    def find_by_trigger(self, trigger: str) -> List[SkillPackage]:
        """Find skills matching a trigger phrase.
        
        Uses exact match on normalized trigger.
        
        Args:
            trigger: Trigger phrase to match
            
        Returns:
            List of matching SkillPackage instances
        """
        normalized = normalize_trigger(trigger)
        skill_ids = self.trigger_index.get(normalized, set())
        return [self.skills_by_id[sid] for sid in skill_ids]
    
    def find_by_trigger_substring(self, text: str) -> List[SkillPackage]:
        """Find skills whose triggers appear as substrings in text.
        
        Useful for matching triggers within user messages.
        
        Args:
            text: Text to search for trigger substrings
            
        Returns:
            List of matching SkillPackage instances (deduplicated)
        """
        normalized_text = normalize_trigger(text)
        matched_ids: Set[str] = set()
        
        for trigger, skill_ids in self.trigger_index.items():
            if trigger in normalized_text:
                matched_ids.update(skill_ids)
                
        return [self.skills_by_id[sid] for sid in matched_ids]
    
    def find_by_tag(self, tag: str) -> List[SkillPackage]:
        """Find skills with a specific tag.
        
        Args:
            tag: Tag to match (case-insensitive)
            
        Returns:
            List of matching SkillPackage instances
        """
        tag_lower = tag.lower()
        skill_ids = self.tag_index.get(tag_lower, set())
        return [self.skills_by_id[sid] for sid in skill_ids]
    
    def find_by_tags(self, tags: List[str]) -> List[SkillPackage]:
        """Find skills matching any of the given tags.
        
        Args:
            tags: List of tags to match (case-insensitive)
            
        Returns:
            List of matching SkillPackage instances (deduplicated)
        """
        matched_ids: Set[str] = set()
        
        for tag in tags:
            tag_lower = tag.lower()
            if tag_lower in self.tag_index:
                matched_ids.update(self.tag_index[tag_lower])
                
        return [self.skills_by_id[sid] for sid in matched_ids]
    
    def get_all_skills(self) -> List[SkillPackage]:
        """Get all registered skills.
        
        Returns:
            List of all SkillPackage instances
        """
        return list(self.skills_by_id.values())
    
    def get_all_triggers(self) -> List[str]:
        """Get all registered triggers.
        
        Returns:
            List of all normalized trigger strings
        """
        return list(self.trigger_index.keys())
    
    def get_all_tags(self) -> List[str]:
        """Get all registered tags.
        
        Returns:
            List of all tag strings
        """
        return list(self.tag_index.keys())
    
    def clear(self) -> None:
        """Clear all registered skills."""
        self.skills_by_id.clear()
        self.trigger_index.clear()
        self.tag_index.clear()
        
    def __len__(self) -> int:
        """Return number of registered skills."""
        return len(self.skills_by_id)
    
    def __contains__(self, skill_id: str) -> bool:
        """Check if a skill ID is registered."""
        return skill_id in self.skills_by_id
