"""Tests for SkillLoader validation and loading."""

import json
import pytest
import tempfile
from pathlib import Path

from glitch.skills.loader import SkillLoader, get_default_skills_dir
from glitch.skills.types import SkillValidationError


class TestSkillLoader:
    """Tests for SkillLoader."""
    
    def test_load_valid_skill(self, tmp_path: Path):
        """Valid skill package loads successfully."""
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        
        # Create valid metadata
        metadata = {
            "id": "test-skill",
            "version": "1.0.0",
            "description": "A test skill",
            "triggers": ["test", "example"],
            "tags": ["testing"],
            "priority": 50,
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("# Test Skill\n\nThis is a test.")
        
        loader = SkillLoader(tmp_path)
        skills = loader.load_all()
        
        assert len(skills) == 1
        assert skills[0].metadata.id == "test-skill"
        assert skills[0].metadata.version == "1.0.0"
        assert skills[0].metadata.triggers == ["test", "example"]
        assert "Test Skill" in skills[0].content
        
    def test_missing_skill_md_fails(self, tmp_path: Path):
        """Missing skill.md raises validation error."""
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        
        metadata = {
            "id": "bad-skill",
            "version": "1.0.0",
            "description": "Missing skill.md",
            "triggers": ["test"],
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        
        loader = SkillLoader(tmp_path, strict=True)
        
        with pytest.raises(SkillValidationError) as exc_info:
            loader.load_all()
            
        assert "Missing skill.md" in str(exc_info.value)
        
    def test_missing_metadata_fails(self, tmp_path: Path):
        """Missing metadata.json raises validation error."""
        skill_dir = tmp_path / "no-meta"
        skill_dir.mkdir()
        
        (skill_dir / "skill.md").write_text("# No Metadata")
        
        loader = SkillLoader(tmp_path, strict=True)
        
        with pytest.raises(SkillValidationError) as exc_info:
            loader.load_all()
            
        assert "Missing metadata.json" in str(exc_info.value)
        
    def test_id_must_match_folder_name(self, tmp_path: Path):
        """metadata.id must match folder name."""
        skill_dir = tmp_path / "folder-name"
        skill_dir.mkdir()
        
        metadata = {
            "id": "different-id",  # Doesn't match folder
            "version": "1.0.0",
            "description": "ID mismatch",
            "triggers": ["test"],
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("# Test")
        
        loader = SkillLoader(tmp_path, strict=True)
        
        with pytest.raises(SkillValidationError) as exc_info:
            loader.load_all()
            
        assert "must match folder name" in str(exc_info.value)
        
    def test_invalid_version_format(self, tmp_path: Path):
        """Invalid semver version raises validation error."""
        skill_dir = tmp_path / "bad-version"
        skill_dir.mkdir()
        
        metadata = {
            "id": "bad-version",
            "version": "not-semver",
            "description": "Bad version",
            "triggers": ["test"],
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("# Test")
        
        loader = SkillLoader(tmp_path, strict=True)
        
        with pytest.raises(SkillValidationError) as exc_info:
            loader.load_all()
            
        assert "Invalid version format" in str(exc_info.value)
        
    def test_empty_triggers_fails(self, tmp_path: Path):
        """Empty triggers list raises validation error."""
        skill_dir = tmp_path / "no-triggers"
        skill_dir.mkdir()
        
        metadata = {
            "id": "no-triggers",
            "version": "1.0.0",
            "description": "No triggers",
            "triggers": [],
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("# Test")
        
        loader = SkillLoader(tmp_path, strict=True)
        
        with pytest.raises(SkillValidationError) as exc_info:
            loader.load_all()
            
        assert "non-empty list" in str(exc_info.value)
        
    def test_priority_out_of_range(self, tmp_path: Path):
        """Priority outside 0-100 raises validation error."""
        skill_dir = tmp_path / "bad-priority"
        skill_dir.mkdir()
        
        metadata = {
            "id": "bad-priority",
            "version": "1.0.0",
            "description": "Bad priority",
            "triggers": ["test"],
            "priority": 150,
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("# Test")
        
        loader = SkillLoader(tmp_path, strict=True)
        
        with pytest.raises(SkillValidationError) as exc_info:
            loader.load_all()
            
        assert "priority must be integer 0-100" in str(exc_info.value)
        
    def test_both_allowlist_and_denylist_fails(self, tmp_path: Path):
        """Cannot have both model_allowlist and model_denylist."""
        skill_dir = tmp_path / "both-lists"
        skill_dir.mkdir()
        
        metadata = {
            "id": "both-lists",
            "version": "1.0.0",
            "description": "Both lists",
            "triggers": ["test"],
            "model_allowlist": ["glitch"],
            "model_denylist": ["opus-4"],
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("# Test")
        
        loader = SkillLoader(tmp_path, strict=True)
        
        with pytest.raises(SkillValidationError) as exc_info:
            loader.load_all()
            
        assert "Cannot specify both" in str(exc_info.value)
        
    def test_non_strict_mode_skips_invalid(self, tmp_path: Path):
        """Non-strict mode skips invalid skills without raising."""
        # Create one valid skill
        valid_dir = tmp_path / "valid-skill"
        valid_dir.mkdir()
        valid_metadata = {
            "id": "valid-skill",
            "version": "1.0.0",
            "description": "Valid",
            "triggers": ["valid"],
        }
        (valid_dir / "metadata.json").write_text(json.dumps(valid_metadata))
        (valid_dir / "skill.md").write_text("# Valid")
        
        # Create one invalid skill
        invalid_dir = tmp_path / "invalid-skill"
        invalid_dir.mkdir()
        (invalid_dir / "skill.md").write_text("# No metadata")
        
        loader = SkillLoader(tmp_path, strict=False)
        skills = loader.load_all()
        
        assert len(skills) == 1
        assert skills[0].metadata.id == "valid-skill"
        
    def test_skips_hidden_directories(self, tmp_path: Path):
        """Directories starting with . or _ are skipped."""
        # Create hidden directory
        hidden_dir = tmp_path / ".hidden"
        hidden_dir.mkdir()
        (hidden_dir / "skill.md").write_text("# Hidden")
        
        # Create underscore directory
        underscore_dir = tmp_path / "_private"
        underscore_dir.mkdir()
        (underscore_dir / "skill.md").write_text("# Private")
        
        loader = SkillLoader(tmp_path)
        skills = loader.load_all()
        
        assert len(skills) == 0
        
    def test_empty_skill_md_fails(self, tmp_path: Path):
        """Empty skill.md raises validation error."""
        skill_dir = tmp_path / "empty-content"
        skill_dir.mkdir()
        
        metadata = {
            "id": "empty-content",
            "version": "1.0.0",
            "description": "Empty content",
            "triggers": ["test"],
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("")  # Empty
        
        loader = SkillLoader(tmp_path, strict=True)
        
        with pytest.raises(SkillValidationError) as exc_info:
            loader.load_all()
            
        assert "skill.md is empty" in str(exc_info.value)
        
    def test_model_compatibility_allowlist(self, tmp_path: Path):
        """Model allowlist is correctly loaded and checked."""
        skill_dir = tmp_path / "allowlist-skill"
        skill_dir.mkdir()
        
        metadata = {
            "id": "allowlist-skill",
            "version": "1.0.0",
            "description": "With allowlist",
            "triggers": ["test"],
            "model_allowlist": ["glitch", "sonnet-4.5"],
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("# Test")
        
        loader = SkillLoader(tmp_path)
        skills = loader.load_all()
        
        assert len(skills) == 1
        skill = skills[0]
        
        assert skill.metadata.is_compatible_with_model("glitch") is True
        assert skill.metadata.is_compatible_with_model("sonnet-4.5") is True
        assert skill.metadata.is_compatible_with_model("opus-4") is False
        
    def test_model_compatibility_denylist(self, tmp_path: Path):
        """Model denylist is correctly loaded and checked."""
        skill_dir = tmp_path / "denylist-skill"
        skill_dir.mkdir()
        
        metadata = {
            "id": "denylist-skill",
            "version": "1.0.0",
            "description": "With denylist",
            "triggers": ["test"],
            "model_denylist": ["vision_agent"],
        }
        (skill_dir / "metadata.json").write_text(json.dumps(metadata))
        (skill_dir / "skill.md").write_text("# Test")
        
        loader = SkillLoader(tmp_path)
        skills = loader.load_all()
        
        assert len(skills) == 1
        skill = skills[0]
        
        assert skill.metadata.is_compatible_with_model("glitch") is True
        assert skill.metadata.is_compatible_with_model("opus-4") is True
        assert skill.metadata.is_compatible_with_model("vision_agent") is False


class TestGetDefaultSkillsDir:
    """Tests for get_default_skills_dir."""
    
    def test_returns_path(self):
        """Returns a Path object."""
        result = get_default_skills_dir()
        assert isinstance(result, Path)
        
    def test_path_ends_with_skills(self):
        """Path ends with 'skills' directory."""
        result = get_default_skills_dir()
        assert result.name == "skills"
