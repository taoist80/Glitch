"""Skill loader: reads and validates skill packages from disk.

Dataflow:
    skills_directory -> SkillLoader.load_all() -> List[SkillPackage]
    skill_path -> SkillLoader.load_skill() -> SkillPackage
    
Validation rules:
    - Folder must contain skill.md (non-empty)
    - Folder must contain metadata.json with required fields
    - metadata.id must match folder name
    - version must be valid semver format
    - triggers must be non-empty list
    - priority must be 0-100
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

from glitch.skills.types import (
    SkillMetadata,
    SkillPackage,
    SkillValidationError,
)

logger = logging.getLogger(__name__)

# Semver regex (simplified)
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[\w.]+)?(\+[\w.]+)?$")


class SkillLoader:
    """Loads and validates skill packages from the filesystem.
    
    Attributes:
        skills_dir: Root directory containing skill folders
        strict: If True, raise on validation errors; if False, skip invalid skills
    """
    
    def __init__(self, skills_dir: str | Path, strict: bool = True):
        """Initialize SkillLoader.
        
        Args:
            skills_dir: Path to directory containing skill folders
            strict: Whether to raise on validation errors (default True)
        """
        self.skills_dir = Path(skills_dir)
        self.strict = strict
        
    def load_all(self) -> List[SkillPackage]:
        """Load all valid skill packages from the skills directory.
        
        Returns:
            List of validated SkillPackage instances
            
        Raises:
            SkillValidationError: If strict=True and any skill fails validation
        """
        if not self.skills_dir.exists():
            logger.warning(f"Skills directory does not exist: {self.skills_dir}")
            return []
            
        skills: List[SkillPackage] = []
        
        for item in self.skills_dir.iterdir():
            if not item.is_dir():
                continue
            if item.name.startswith(".") or item.name.startswith("_"):
                continue
                
            try:
                skill = self.load_skill(item)
                skills.append(skill)
                logger.info(f"Loaded skill: {skill.metadata.id} v{skill.metadata.version}")
            except SkillValidationError as e:
                if self.strict:
                    raise
                logger.warning(f"Skipping invalid skill {item.name}: {e}")
            except Exception as e:
                if self.strict:
                    raise SkillValidationError(item.name, [str(e)])
                logger.warning(f"Error loading skill {item.name}: {e}")
                
        logger.info(f"Loaded {len(skills)} skills from {self.skills_dir}")
        return skills
    
    def load_skill(self, skill_path: Path) -> SkillPackage:
        """Load a single skill package from a directory.
        
        Args:
            skill_path: Path to the skill folder
            
        Returns:
            Validated SkillPackage
            
        Raises:
            SkillValidationError: If skill fails validation
        """
        folder_name = skill_path.name
        errors: List[str] = []
        
        # Check skill.md exists
        skill_md_path = skill_path / "skill.md"
        if not skill_md_path.exists():
            errors.append("Missing skill.md file")
        
        # Check metadata.json exists
        metadata_path = skill_path / "metadata.json"
        if not metadata_path.exists():
            errors.append("Missing metadata.json file")
            
        if errors:
            raise SkillValidationError(folder_name, errors)
            
        # Load and validate content
        content = skill_md_path.read_text().strip()
        if not content:
            errors.append("skill.md is empty")
            
        # Load and validate metadata
        try:
            metadata_raw = json.loads(metadata_path.read_text())
        except json.JSONDecodeError as e:
            errors.append(f"Invalid JSON in metadata.json: {e}")
            raise SkillValidationError(folder_name, errors)
            
        # Validate metadata fields
        metadata_errors = self._validate_metadata(metadata_raw, folder_name)
        errors.extend(metadata_errors)
        
        if errors:
            raise SkillValidationError(folder_name, errors)
            
        # Build SkillMetadata
        metadata = SkillMetadata(
            id=metadata_raw["id"],
            version=metadata_raw["version"],
            description=metadata_raw["description"],
            triggers=metadata_raw["triggers"],
            tags=metadata_raw.get("tags", []),
            priority=metadata_raw.get("priority", 50),
            model_allowlist=metadata_raw.get("model_allowlist"),
            model_denylist=metadata_raw.get("model_denylist"),
            required_tools=metadata_raw.get("required_tools", []),
            author=metadata_raw.get("author"),
        )
        
        return SkillPackage(
            metadata=metadata,
            content=content,
            source_path=str(skill_path),
        )
    
    def _validate_metadata(self, metadata: dict, folder_name: str) -> List[str]:
        """Validate metadata dictionary against schema.
        
        Args:
            metadata: Raw metadata dictionary
            folder_name: Name of the skill folder (for id matching)
            
        Returns:
            List of validation error messages (empty if valid)
        """
        errors: List[str] = []
        
        # Required fields
        required = ["id", "version", "description", "triggers"]
        for field in required:
            if field not in metadata:
                errors.append(f"Missing required field: {field}")
                
        if errors:
            return errors  # Can't continue without required fields
            
        # id must match folder name
        if metadata["id"] != folder_name:
            errors.append(
                f"metadata.id '{metadata['id']}' must match folder name '{folder_name}'"
            )
            
        # version must be semver
        if not SEMVER_PATTERN.match(metadata["version"]):
            errors.append(
                f"Invalid version format '{metadata['version']}' (expected semver)"
            )
            
        # triggers must be non-empty list of strings
        triggers = metadata["triggers"]
        if not isinstance(triggers, list) or len(triggers) == 0:
            errors.append("triggers must be a non-empty list")
        elif not all(isinstance(t, str) and t.strip() for t in triggers):
            errors.append("triggers must contain non-empty strings")
            
        # priority must be 0-100
        priority = metadata.get("priority", 50)
        if not isinstance(priority, int) or not (0 <= priority <= 100):
            errors.append(f"priority must be integer 0-100, got {priority}")
            
        # tags must be list of strings if present
        tags = metadata.get("tags", [])
        if not isinstance(tags, list):
            errors.append("tags must be a list")
        elif not all(isinstance(t, str) for t in tags):
            errors.append("tags must contain strings")
            
        # model_allowlist/denylist must be lists if present
        for field in ["model_allowlist", "model_denylist"]:
            if field in metadata and metadata[field] is not None:
                if not isinstance(metadata[field], list):
                    errors.append(f"{field} must be a list or null")
                elif not all(isinstance(m, str) for m in metadata[field]):
                    errors.append(f"{field} must contain strings")
                    
        # Cannot have both allowlist and denylist
        if metadata.get("model_allowlist") and metadata.get("model_denylist"):
            errors.append("Cannot specify both model_allowlist and model_denylist")
            
        # required_tools must be list of strings if present
        required_tools = metadata.get("required_tools", [])
        if not isinstance(required_tools, list):
            errors.append("required_tools must be a list")
        elif not all(isinstance(t, str) for t in required_tools):
            errors.append("required_tools must contain strings")
            
        return errors


def get_default_skills_dir() -> Path:
    """Get the default skills directory path.
    
    Returns:
        Path to skills/ directory (relative to app root)
    """
    # In container: /app/glitch/skills/loader.py -> /app/skills/
    # In dev: agent/src/glitch/skills/loader.py -> agent/skills/
    # 
    # Navigate up to find the skills directory:
    # - Container: /app/glitch/skills/loader.py -> /app/skills
    # - Dev: agent/src/glitch/skills/loader.py -> agent/skills
    loader_path = Path(__file__).resolve()
    
    # Try container path first: /app/skills
    container_skills = loader_path.parent.parent.parent / "skills"
    if container_skills.exists():
        return container_skills
    
    # Try dev path: agent/skills (4 levels up from loader.py)
    dev_skills = loader_path.parent.parent.parent.parent / "skills"
    if dev_skills.exists():
        return dev_skills
    
    # Fallback to container path (will be created if needed)
    return container_skills
