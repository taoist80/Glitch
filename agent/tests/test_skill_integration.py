"""Integration tests for the skills system end-to-end."""

import json
import pytest
from pathlib import Path

from glitch.skills.loader import SkillLoader, get_default_skills_dir
from glitch.skills.registry import SkillRegistry
from glitch.skills.selector import SkillSelector
from glitch.skills.planner import TaskPlanner
from glitch.skills.prompt_builder import build_prompt_with_skills, SkillPromptBuilder
from glitch.skills.types import TaskSpec


class TestEndToEndFlow:
    """Tests for the complete skill selection flow."""
    
    @pytest.fixture
    def skills_dir(self, tmp_path: Path) -> Path:
        """Create a temporary skills directory with test skills."""
        # Create telemetry skill
        telemetry_dir = tmp_path / "telemetry-skill"
        telemetry_dir.mkdir()
        (telemetry_dir / "metadata.json").write_text(json.dumps({
            "id": "telemetry-skill",
            "version": "1.0.0",
            "description": "Telemetry expertise",
            "triggers": ["telemetry", "metrics", "cloudwatch"],
            "tags": ["telemetry", "observability"],
            "priority": 80,
        }))
        (telemetry_dir / "skill.md").write_text(
            "# Telemetry Skill\n\nExpert guidance for telemetry."
        )
        
        # Create memory skill
        memory_dir = tmp_path / "memory-skill"
        memory_dir.mkdir()
        (memory_dir / "metadata.json").write_text(json.dumps({
            "id": "memory-skill",
            "version": "1.0.0",
            "description": "Memory management",
            "triggers": ["memory", "context", "conversation"],
            "tags": ["memory"],
            "priority": 60,
        }))
        (memory_dir / "skill.md").write_text(
            "# Memory Skill\n\nGuidance for memory management."
        )
        
        # Create restricted skill (only for opus-4)
        restricted_dir = tmp_path / "restricted-skill"
        restricted_dir.mkdir()
        (restricted_dir / "metadata.json").write_text(json.dumps({
            "id": "restricted-skill",
            "version": "1.0.0",
            "description": "Advanced analysis",
            "triggers": ["deep analysis"],
            "tags": ["analysis"],
            "priority": 90,
            "model_allowlist": ["opus-4"],
        }))
        (restricted_dir / "skill.md").write_text(
            "# Restricted Skill\n\nAdvanced analysis for opus-4 only."
        )
        
        return tmp_path
    
    def test_full_flow_telemetry_request(self, skills_dir: Path):
        """User asks about telemetry -> correct skill is injected."""
        # Load skills
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        assert len(skills) == 3
        
        # Create registry and selector
        registry = SkillRegistry()
        registry.register_all(skills)
        selector = SkillSelector(registry)
        
        # Plan the task
        planner = TaskPlanner()
        user_message = "I need to add a new metric to the telemetry system"
        task_spec = planner.plan(user_message)
        
        # Verify planning detected telemetry
        assert "telemetry" in task_spec["skill_tags"]
        
        # Select skills
        result = selector.select(task_spec, "glitch")
        
        # Verify telemetry skill was selected
        assert len(result.selected) >= 1
        skill_ids = [s.skill_id for s in result.selected]
        assert "telemetry-skill" in skill_ids
        
        # Build prompt
        base_prompt = "# Glitch Agent\n\nYou are Glitch."
        final_prompt = build_prompt_with_skills(base_prompt, result.selected)
        
        # Verify skill content is in prompt
        assert "Telemetry Skill" in final_prompt
        assert "telemetry-skill" in final_prompt
        assert "v1.0.0" in final_prompt
        
    def test_model_restriction_enforced(self, skills_dir: Path):
        """Restricted skills are only injected for allowed models."""
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        
        registry = SkillRegistry()
        registry.register_all(skills)
        selector = SkillSelector(registry)
        
        task_spec = TaskSpec(
            intent="analysis",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["analysis"],
            raw_triggers=["deep analysis"],
            confidence=0.8,
        )
        
        # With glitch model, restricted skill is excluded
        result_glitch = selector.select(task_spec, "glitch")
        glitch_ids = [s.skill_id for s in result_glitch.selected]
        assert "restricted-skill" not in glitch_ids
        
        # With opus-4 model, restricted skill is included
        result_opus = selector.select(task_spec, "opus-4")
        opus_ids = [s.skill_id for s in result_opus.selected]
        assert "restricted-skill" in opus_ids
        
    def test_prompt_builder_tracks_injection(self, skills_dir: Path):
        """SkillPromptBuilder tracks what was injected."""
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        
        registry = SkillRegistry()
        registry.register_all(skills)
        selector = SkillSelector(registry)
        
        task_spec = TaskSpec(
            intent="code_modification",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["telemetry"],
            raw_triggers=[],
            confidence=0.8,
        )
        
        result = selector.select(task_spec, "glitch")
        
        builder = SkillPromptBuilder("# Base Prompt")
        prompt = builder.build(result)
        
        summary = builder.get_injection_summary()
        
        assert summary["skills_injected"] >= 1
        assert "telemetry-skill" in summary["skill_ids"]
        assert summary["model_used"] == "glitch"
        
    def test_deterministic_across_runs(self, skills_dir: Path):
        """Selection is deterministic across multiple runs."""
        loader = SkillLoader(skills_dir)
        skills = loader.load_all()
        
        task_spec = TaskSpec(
            intent="general",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["telemetry", "memory"],
            raw_triggers=[],
            confidence=0.8,
        )
        
        results = []
        for _ in range(5):
            registry = SkillRegistry()
            registry.register_all(skills)
            selector = SkillSelector(registry)
            result = selector.select(task_spec, "glitch")
            results.append([s.skill_id for s in result.selected])
            
        # All runs should produce identical results
        for r in results[1:]:
            assert r == results[0]


class TestTaskPlanner:
    """Tests for TaskPlanner."""
    
    def test_detects_code_modification_intent(self):
        """Planner detects code modification intent."""
        planner = TaskPlanner()
        
        messages = [
            "Add a new function to handle errors",
            "Create a class for user management",
            "Implement the login feature",
        ]
        
        for msg in messages:
            task_spec = planner.plan(msg)
            assert task_spec["intent"] == "code_modification"
            
    def test_detects_debugging_intent(self):
        """Planner detects debugging intent."""
        planner = TaskPlanner()
        
        messages = [
            "Debug the authentication issue",
            "Why is the API returning 500 errors?",
            "The login is not working",
        ]
        
        for msg in messages:
            task_spec = planner.plan(msg)
            assert task_spec["intent"] == "debugging"
            
    def test_detects_high_risk(self):
        """Planner detects high-risk operations."""
        planner = TaskPlanner()
        
        messages = [
            "Delete the production database",
            "Force push to main",
            "Update the API credentials",
        ]
        
        for msg in messages:
            task_spec = planner.plan(msg)
            assert task_spec["risk"] == "high"
            
    def test_extracts_telemetry_tag(self):
        """Planner extracts telemetry tag from message."""
        planner = TaskPlanner()
        
        task_spec = planner.plan("Add monitoring to the telemetry system")
        
        assert "telemetry" in task_spec["skill_tags"]
        
    def test_recommends_model_escalation_for_high_risk(self):
        """Planner recommends higher tier model for high-risk tasks."""
        planner = TaskPlanner()
        
        task_spec = planner.plan("Delete the production database tables")
        
        assert task_spec["risk"] == "high"
        assert task_spec["recommended_model"] in ["sonnet-4.5", "opus-4"]


class TestPromptBuilder:
    """Tests for prompt building."""
    
    def test_empty_skills_returns_base_prompt(self):
        """No skills returns base prompt unchanged."""
        base = "# Base Prompt\n\nContent here."
        result = build_prompt_with_skills(base, [])
        assert result == base
        
    def test_skills_section_format(self):
        """Skills section has correct format."""
        from glitch.skills.types import SkillPackage, SkillMetadata, SelectedSkill, SelectionReason
        
        skill = SkillPackage(
            metadata=SkillMetadata(
                id="test-skill",
                version="2.0.0",
                description="Test",
                triggers=["test"],
            ),
            content="# Test Content\n\nInstructions here.",
            source_path="/test",
        )
        
        selected = SelectedSkill(
            skill=skill,
            reasons=[SelectionReason.TAG_MATCH],
            match_score=1.5,
        )
        
        result = build_prompt_with_skills("# Base", [selected])
        
        assert "## Active Skills" in result
        assert "[test-skill]" in result
        assert "(v2.0.0)" in result
        assert "Test Content" in result
        assert "End of Active Skills" in result
        
    def test_multiple_skills_separated(self):
        """Multiple skills are separated by dividers."""
        from glitch.skills.types import SkillPackage, SkillMetadata, SelectedSkill, SelectionReason
        
        skills = []
        for i in range(2):
            skill = SkillPackage(
                metadata=SkillMetadata(
                    id=f"skill-{i}",
                    version="1.0.0",
                    description="Test",
                    triggers=["test"],
                ),
                content=f"# Skill {i}",
                source_path="/test",
            )
            skills.append(SelectedSkill(
                skill=skill,
                reasons=[SelectionReason.TAG_MATCH],
                match_score=1.0,
            ))
            
        result = build_prompt_with_skills("# Base", skills)
        
        assert "[skill-0]" in result
        assert "[skill-1]" in result
        assert result.count("---") >= 1  # Separator between skills


class TestRealSkillsDirectory:
    """Tests using the actual skills directory."""
    
    def test_load_demo_skill(self):
        """The demo telemetry skill loads correctly."""
        skills_dir = get_default_skills_dir()
        
        if not skills_dir.exists():
            pytest.skip("Skills directory does not exist")
            
        loader = SkillLoader(skills_dir, strict=True)
        skills = loader.load_all()
        
        # Should have at least the demo skill
        assert len(skills) >= 1
        
        # Find the telemetry skill
        telemetry_skill = next(
            (s for s in skills if s.metadata.id == "glitch-telemetry-maintainer"),
            None
        )
        
        if telemetry_skill:
            assert telemetry_skill.metadata.version == "1.0.0"
            assert "telemetry" in telemetry_skill.metadata.triggers
            assert "Glitch Telemetry" in telemetry_skill.content
