"""Tests for SkillSelector determinism and behavior."""

import json
import pytest
from pathlib import Path

from glitch.skills.loader import SkillLoader
from glitch.skills.registry import SkillRegistry, normalize_trigger
from glitch.skills.selector import SkillSelector, create_selector_with_skills
from glitch.skills.types import (
    SkillPackage,
    SkillMetadata,
    TaskSpec,
    SelectionReason,
)


def create_test_skill(
    skill_id: str,
    triggers: list[str],
    tags: list[str] = None,
    priority: int = 50,
    model_allowlist: list[str] = None,
    model_denylist: list[str] = None,
) -> SkillPackage:
    """Helper to create test skill packages."""
    return SkillPackage(
        metadata=SkillMetadata(
            id=skill_id,
            version="1.0.0",
            description=f"Test skill {skill_id}",
            triggers=triggers,
            tags=tags or [],
            priority=priority,
            model_allowlist=model_allowlist,
            model_denylist=model_denylist,
        ),
        content=f"# {skill_id}\n\nTest content.",
        source_path=f"/test/{skill_id}",
    )


class TestSkillRegistry:
    """Tests for SkillRegistry."""
    
    def test_register_and_find_by_trigger(self):
        """Skills can be found by trigger."""
        registry = SkillRegistry()
        skill = create_test_skill("test-skill", ["hello", "world"])
        registry.register(skill)
        
        results = registry.find_by_trigger("hello")
        assert len(results) == 1
        assert results[0].metadata.id == "test-skill"
        
    def test_find_by_trigger_case_insensitive(self):
        """Trigger matching is case-insensitive."""
        registry = SkillRegistry()
        skill = create_test_skill("test-skill", ["Hello World"])
        registry.register(skill)
        
        results = registry.find_by_trigger("hello world")
        assert len(results) == 1
        
    def test_find_by_trigger_substring(self):
        """Skills can be found by trigger substring in text."""
        registry = SkillRegistry()
        skill = create_test_skill("test-skill", ["telemetry"])
        registry.register(skill)
        
        results = registry.find_by_trigger_substring(
            "I need help with the telemetry system"
        )
        assert len(results) == 1
        
    def test_find_by_tag(self):
        """Skills can be found by tag."""
        registry = SkillRegistry()
        skill = create_test_skill("test-skill", ["test"], tags=["observability"])
        registry.register(skill)
        
        results = registry.find_by_tag("observability")
        assert len(results) == 1
        
    def test_find_by_tags_multiple(self):
        """Skills can be found by multiple tags."""
        registry = SkillRegistry()
        skill1 = create_test_skill("skill-1", ["test"], tags=["tag-a"])
        skill2 = create_test_skill("skill-2", ["test"], tags=["tag-b"])
        skill3 = create_test_skill("skill-3", ["test"], tags=["tag-a", "tag-b"])
        
        registry.register_all([skill1, skill2, skill3])
        
        results = registry.find_by_tags(["tag-a", "tag-b"])
        assert len(results) == 3
        
    def test_get_by_id(self):
        """Skills can be retrieved by ID."""
        registry = SkillRegistry()
        skill = create_test_skill("my-skill", ["test"])
        registry.register(skill)
        
        result = registry.get_by_id("my-skill")
        assert result is not None
        assert result.metadata.id == "my-skill"
        
        assert registry.get_by_id("nonexistent") is None


class TestSkillSelector:
    """Tests for SkillSelector."""
    
    def test_select_by_tag(self):
        """Skills are selected by matching tags."""
        skills = [
            create_test_skill("skill-1", ["test"], tags=["telemetry"]),
            create_test_skill("skill-2", ["test"], tags=["memory"]),
        ]
        selector = create_selector_with_skills(skills)
        
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
        
        assert len(result.selected) == 1
        assert result.selected[0].skill_id == "skill-1"
        assert SelectionReason.TAG_MATCH in result.selected[0].reasons
        
    def test_select_by_trigger(self):
        """Skills are selected by matching triggers."""
        skills = [
            create_test_skill("skill-1", ["telemetry", "metrics"]),
            create_test_skill("skill-2", ["memory"]),
        ]
        selector = create_selector_with_skills(skills)
        
        task_spec = TaskSpec(
            intent="code_modification",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=[],
            raw_triggers=["telemetry"],
            confidence=0.8,
        )
        
        result = selector.select(task_spec, "glitch")
        
        assert len(result.selected) == 1
        assert result.selected[0].skill_id == "skill-1"
        assert SelectionReason.TRIGGER_MATCH in result.selected[0].reasons
        
    def test_max_three_skills(self):
        """At most 3 skills are selected."""
        skills = [
            create_test_skill(f"skill-{i}", ["test"], tags=["common"])
            for i in range(5)
        ]
        selector = create_selector_with_skills(skills)
        
        task_spec = TaskSpec(
            intent="general",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["common"],
            raw_triggers=[],
            confidence=0.8,
        )
        
        result = selector.select(task_spec, "glitch")
        
        assert len(result.selected) == 3
        assert len(result.excluded) == 2
        
        for skill_id, reason in result.excluded:
            assert reason == SelectionReason.MAX_SKILLS_REACHED
            
    def test_model_denylist_excludes(self):
        """Skills with model in denylist are excluded."""
        skills = [
            create_test_skill(
                "excluded-skill",
                ["test"],
                tags=["common"],
                model_denylist=["vision_agent"],
            ),
            create_test_skill("included-skill", ["test"], tags=["common"]),
        ]
        selector = create_selector_with_skills(skills)
        
        task_spec = TaskSpec(
            intent="general",
            risk="low",
            required_tools=[],
            recommended_model="vision_agent",
            skill_tags=["common"],
            raw_triggers=[],
            confidence=0.8,
        )
        
        result = selector.select(task_spec, "vision_agent")
        
        assert len(result.selected) == 1
        assert result.selected[0].skill_id == "included-skill"
        assert ("excluded-skill", SelectionReason.MODEL_DENYLIST_EXCLUDED) in result.excluded
        
    def test_model_allowlist_filters(self):
        """Skills with allowlist only match allowed models."""
        skills = [
            create_test_skill(
                "restricted-skill",
                ["test"],
                tags=["common"],
                model_allowlist=["opus-4"],
            ),
            create_test_skill("open-skill", ["test"], tags=["common"]),
        ]
        selector = create_selector_with_skills(skills)
        
        task_spec = TaskSpec(
            intent="general",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["common"],
            raw_triggers=[],
            confidence=0.8,
        )
        
        # With glitch model, restricted skill is excluded
        result = selector.select(task_spec, "glitch")
        assert len(result.selected) == 1
        assert result.selected[0].skill_id == "open-skill"
        
        # With opus-4 model, restricted skill is included
        result = selector.select(task_spec, "opus-4")
        assert len(result.selected) == 2
        
    def test_deterministic_selection(self):
        """Same input always produces same output."""
        skills = [
            create_test_skill("skill-a", ["test"], tags=["common"], priority=50),
            create_test_skill("skill-b", ["test"], tags=["common"], priority=50),
            create_test_skill("skill-c", ["test"], tags=["common"], priority=50),
        ]
        selector = create_selector_with_skills(skills)
        
        task_spec = TaskSpec(
            intent="general",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["common"],
            raw_triggers=[],
            confidence=0.8,
        )
        
        # Run selection multiple times
        results = [selector.select(task_spec, "glitch") for _ in range(10)]
        
        # All results should be identical
        first_ids = [s.skill_id for s in results[0].selected]
        for result in results[1:]:
            assert [s.skill_id for s in result.selected] == first_ids
            
    def test_priority_affects_selection_order(self):
        """Higher priority skills are selected first."""
        skills = [
            create_test_skill("low-priority", ["test"], tags=["common"], priority=10),
            create_test_skill("high-priority", ["test"], tags=["common"], priority=90),
            create_test_skill("medium-priority", ["test"], tags=["common"], priority=50),
        ]
        selector = create_selector_with_skills(skills, max_skills=2)
        
        task_spec = TaskSpec(
            intent="general",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["common"],
            raw_triggers=[],
            confidence=0.8,
        )
        
        result = selector.select(task_spec, "glitch")
        
        assert len(result.selected) == 2
        assert result.selected[0].skill_id == "high-priority"
        assert result.selected[1].skill_id == "medium-priority"
        
    def test_trigger_match_scores_higher_than_tag(self):
        """Trigger matches score higher than tag matches."""
        skills = [
            create_test_skill("tag-only", ["other"], tags=["telemetry"], priority=50),
            create_test_skill("trigger-match", ["telemetry"], tags=[], priority=50),
        ]
        selector = create_selector_with_skills(skills, max_skills=1)
        
        task_spec = TaskSpec(
            intent="general",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["telemetry"],
            raw_triggers=["telemetry"],
            confidence=0.8,
        )
        
        result = selector.select(task_spec, "glitch")
        
        assert len(result.selected) == 1
        assert result.selected[0].skill_id == "trigger-match"
        
    def test_selection_result_to_log_dict(self):
        """SkillSelectionResult can be converted to log dict."""
        skills = [create_test_skill("skill-1", ["test"], tags=["common"])]
        selector = create_selector_with_skills(skills)
        
        task_spec = TaskSpec(
            intent="general",
            risk="low",
            required_tools=[],
            recommended_model="glitch",
            skill_tags=["common"],
            raw_triggers=[],
            confidence=0.8,
        )
        
        result = selector.select(task_spec, "glitch")
        log_dict = result.to_log_dict()
        
        assert "selected_skills" in log_dict
        assert "selected_reasons" in log_dict
        assert "model_used" in log_dict
        assert log_dict["model_used"] == "glitch"
        assert "skill-1" in log_dict["selected_skills"]


class TestNormalizeTrigger:
    """Tests for trigger normalization."""
    
    def test_lowercase(self):
        """Triggers are lowercased."""
        assert normalize_trigger("HELLO") == "hello"
        
    def test_strip_whitespace(self):
        """Leading/trailing whitespace is stripped."""
        assert normalize_trigger("  hello  ") == "hello"
        
    def test_collapse_spaces(self):
        """Multiple spaces are collapsed."""
        assert normalize_trigger("hello   world") == "hello world"
        
    def test_remove_punctuation(self):
        """Punctuation is removed except hyphens."""
        assert normalize_trigger("hello, world!") == "hello world"
        assert normalize_trigger("hello-world") == "hello-world"
