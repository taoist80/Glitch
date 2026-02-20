"""Type definitions for the Skills runtime.

This module defines all data types for the skill system, enabling:
- Clear function signatures and IDE support
- Validation at load time
- Traceable dataflow from skill package to prompt injection

Dataflow:
    skill.md + metadata.json -> SkillLoader -> SkillPackage
    SkillPackage -> SkillRegistry (indexed by triggers)
    TaskSpec + model -> SkillSelector -> List[SelectedSkill]
    List[SelectedSkill] -> PromptBuilder -> final prompt
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Literal, TypedDict
from enum import Enum


class SkillValidationError(Exception):
    """Raised when a skill package fails validation."""
    
    def __init__(self, skill_id: str, errors: List[str]):
        self.skill_id = skill_id
        self.errors = errors
        super().__init__(f"Skill '{skill_id}' validation failed: {'; '.join(errors)}")


class SelectionReason(str, Enum):
    """Reason codes for skill selection decisions."""
    TRIGGER_MATCH = "trigger_match"
    TAG_MATCH = "tag_match"
    PRIORITY_TIE_BREAK = "priority_tie_break"
    MODEL_ALLOWLIST = "model_allowlist"
    MODEL_DENYLIST_EXCLUDED = "model_denylist_excluded"
    MAX_SKILLS_REACHED = "max_skills_reached"


@dataclass(frozen=True)
class SkillMetadata:
    """Metadata for a skill package.
    
    Attributes:
        id: Unique skill identifier (must match folder name)
        version: Semantic version string (e.g., "1.0.0")
        description: Human-readable description
        triggers: List of trigger phrases/patterns that activate this skill
        tags: List of tags for categorization (e.g., ["telemetry", "observability"])
        priority: Selection priority (higher = preferred, default 50)
        model_allowlist: If set, skill only injected for these models
        model_denylist: If set, skill excluded for these models
        required_tools: Tools this skill expects to be available
        author: Optional author name
    """
    id: str
    version: str
    description: str
    triggers: List[str]
    tags: List[str] = field(default_factory=list)
    priority: int = 50
    model_allowlist: Optional[List[str]] = None
    model_denylist: Optional[List[str]] = None
    required_tools: List[str] = field(default_factory=list)
    author: Optional[str] = None
    
    def is_compatible_with_model(self, model_name: str) -> bool:
        """Check if this skill is compatible with the given model.
        
        Args:
            model_name: Name of the model to check
            
        Returns:
            True if skill can be used with this model
        """
        if self.model_denylist and model_name in self.model_denylist:
            return False
        if self.model_allowlist and model_name not in self.model_allowlist:
            return False
        return True


@dataclass
class SkillPackage:
    """A complete skill package with metadata and content.
    
    Attributes:
        metadata: Validated SkillMetadata
        content: The skill.md content (instructions for the model)
        source_path: Filesystem path where skill was loaded from
    """
    metadata: SkillMetadata
    content: str
    source_path: str


class TaskSpec(TypedDict, total=False):
    """Specification produced by the Planner for a task.
    
    This is the contract between Planner and Executor.
    
    Attributes:
        intent: High-level intent classification (e.g., "code_modification", "query", "analysis")
        risk: Risk level assessment ("low", "medium", "high")
        required_tools: List of tool names needed for this task
        recommended_model: Model name recommended by planner
        skill_tags: Tags to match against skill registry
        raw_triggers: Raw trigger phrases extracted from user message
        confidence: Planner's confidence in this classification (0.0-1.0)
    """
    intent: str
    risk: Literal["low", "medium", "high"]
    required_tools: List[str]
    recommended_model: str
    skill_tags: List[str]
    raw_triggers: List[str]
    confidence: float


@dataclass
class SelectedSkill:
    """A skill selected for injection into the prompt.
    
    Attributes:
        skill: The skill package
        reasons: Why this skill was selected
        match_score: Numeric score for selection (higher = better match)
    """
    skill: SkillPackage
    reasons: List[SelectionReason]
    match_score: float
    
    @property
    def skill_id(self) -> str:
        return self.skill.metadata.id


@dataclass
class SkillSelectionResult:
    """Result of skill selection for a task.
    
    Attributes:
        selected: List of selected skills (max 3)
        excluded: Skills that matched but were excluded (with reasons)
        model_used: The model skills were selected for
        total_candidates: Total skills that matched triggers/tags
    """
    selected: List[SelectedSkill]
    excluded: List[tuple[str, SelectionReason]]  # (skill_id, reason)
    model_used: str
    total_candidates: int
    
    def to_log_dict(self) -> Dict:
        """Convert to dictionary for telemetry logging."""
        return {
            "selected_skills": [s.skill_id for s in self.selected],
            "selected_reasons": {
                s.skill_id: [r.value for r in s.reasons] 
                for s in self.selected
            },
            "excluded": [(sid, r.value) for sid, r in self.excluded],
            "model_used": self.model_used,
            "total_candidates": self.total_candidates,
        }


# Intent categories for task classification
INTENT_CATEGORIES = Literal[
    "code_modification",
    "code_review", 
    "debugging",
    "documentation",
    "query",
    "analysis",
    "configuration",
    "deployment",
    "testing",
    "general",
]

# Default model routing table: intent -> default model
DEFAULT_MODEL_ROUTING: Dict[str, str] = {
    "code_modification": "glitch",
    "code_review": "sonnet-4.5",
    "debugging": "glitch",
    "documentation": "glitch",
    "query": "glitch",
    "analysis": "sonnet-4.5",
    "configuration": "glitch",
    "deployment": "glitch",
    "testing": "glitch",
    "general": "glitch",
}
