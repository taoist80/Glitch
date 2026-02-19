"""Model routing and tier escalation logic for Glitch agent."""

from typing import Dict, List, Optional, Literal
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)

TaskCategory = Literal["chat", "coding", "vision", "tool_use", "mcp_use", "skill_workflow"]


class CognitiveTier(Enum):
    """Cognitive tiers for model escalation."""
    LOCAL = 0
    TIER_1 = 1  # Sonnet 4.5
    TIER_2 = 2  # Sonnet 4.6
    TIER_3 = 3  # Opus 4.5


@dataclass
class ModelConfig:
    """Configuration for a specific model."""
    name: str
    model_id: str
    tier: CognitiveTier
    supports_vision: bool = False
    supports_tools: bool = True
    max_context_tokens: int = 200000
    cost_per_million_tokens: float = 0.0


ROUTING_CONFIG: Dict[TaskCategory, Dict[str, List[str]]] = {
    "chat": {
        "primary": "glitch",
        "escalation": ["sonnet-4.6", "opus-4.5"],
    },
    "coding": {
        "primary": "glitch",
        "escalation": ["sonnet-4.6", "opus-4.5"],
    },
    "vision": {
        "primary": "vision_agent",
        "escalation": ["sonnet-4.6"],
    },
    "tool_use": {
        "primary": "tool_agent",
        "escalation": [],
    },
    "mcp_use": {
        "primary": "mcp_agent",
        "escalation": [],
    },
    "skill_workflow": {
        "primary": "glitch",
        "escalation": ["sonnet-4.6"],
    },
}

MODEL_REGISTRY: Dict[str, ModelConfig] = {
    "glitch": ModelConfig(
        name="glitch",
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        tier=CognitiveTier.TIER_1,
        supports_vision=False,
        supports_tools=True,
        max_context_tokens=200000,
        cost_per_million_tokens=3.0,
    ),
    "sonnet-4.6": ModelConfig(
        name="sonnet-4.6",
        model_id="us.anthropic.claude-sonnet-4.6-20250514-v1:0",
        tier=CognitiveTier.TIER_2,
        supports_vision=True,
        supports_tools=True,
        max_context_tokens=200000,
        cost_per_million_tokens=5.0,
    ),
    "opus-4.5": ModelConfig(
        name="opus-4.5",
        model_id="us.anthropic.claude-opus-4-20250514-v1:0",
        tier=CognitiveTier.TIER_3,
        supports_vision=True,
        supports_tools=True,
        max_context_tokens=200000,
        cost_per_million_tokens=15.0,
    ),
    "vision_agent": ModelConfig(
        name="vision_agent",
        model_id="local:llava",
        tier=CognitiveTier.LOCAL,
        supports_vision=True,
        supports_tools=False,
        max_context_tokens=4096,
        cost_per_million_tokens=0.0,
    ),
    "tool_agent": ModelConfig(
        name="tool_agent",
        model_id="local:llama3.2",
        tier=CognitiveTier.LOCAL,
        supports_vision=False,
        supports_tools=True,
        max_context_tokens=8192,
        cost_per_million_tokens=0.0,
    ),
}


@dataclass
class EscalationReason:
    """Reason for escalating to a higher tier."""
    trigger: Literal["confidence", "context", "complexity", "manual"]
    description: str
    current_tier: CognitiveTier
    target_tier: CognitiveTier


class ModelRouter:
    """Routes tasks to appropriate models and manages tier escalation."""
    
    def __init__(
        self,
        confidence_threshold: float = 0.7,
        context_threshold_pct: float = 0.7,
        max_escalations_per_turn: int = 1,
        max_escalations_per_session: int = 2,
    ):
        self.confidence_threshold = confidence_threshold
        self.context_threshold_pct = context_threshold_pct
        self.max_escalations_per_turn = max_escalations_per_turn
        self.max_escalations_per_session = max_escalations_per_session
        
        self.session_escalation_count = 0
        self.turn_escalation_count = 0
    
    def get_primary_model(self, category: TaskCategory) -> ModelConfig:
        """Get the primary model for a task category."""
        primary_name = ROUTING_CONFIG[category]["primary"]
        return MODEL_REGISTRY[primary_name]
    
    def get_escalation_chain(self, category: TaskCategory) -> List[ModelConfig]:
        """Get the escalation chain for a task category."""
        escalation_names = ROUTING_CONFIG[category]["escalation"]
        return [MODEL_REGISTRY[name] for name in escalation_names]
    
    def should_escalate(
        self,
        confidence: Optional[float] = None,
        context_usage_pct: Optional[float] = None,
        complexity_flag: bool = False,
    ) -> Optional[EscalationReason]:
        """
        Determine if escalation is needed based on various factors.
        
        Args:
            confidence: Model's confidence score (0.0 to 1.0)
            context_usage_pct: Current context window usage (0.0 to 1.0)
            complexity_flag: Manual flag indicating high complexity
        
        Returns:
            EscalationReason if escalation is needed, None otherwise
        """
        if self.session_escalation_count >= self.max_escalations_per_session:
            logger.warning("Session escalation limit reached")
            return None
        
        if self.turn_escalation_count >= self.max_escalations_per_turn:
            logger.warning("Turn escalation limit reached")
            return None
        
        if complexity_flag:
            return EscalationReason(
                trigger="manual",
                description="Manual complexity flag set",
                current_tier=CognitiveTier.TIER_1,
                target_tier=CognitiveTier.TIER_2,
            )
        
        if confidence is not None and confidence < self.confidence_threshold:
            return EscalationReason(
                trigger="confidence",
                description=f"Confidence {confidence:.2f} below threshold {self.confidence_threshold}",
                current_tier=CognitiveTier.TIER_1,
                target_tier=CognitiveTier.TIER_2,
            )
        
        if context_usage_pct is not None and context_usage_pct > self.context_threshold_pct:
            return EscalationReason(
                trigger="context",
                description=f"Context usage {context_usage_pct:.1%} exceeds threshold {self.context_threshold_pct:.1%}",
                current_tier=CognitiveTier.TIER_1,
                target_tier=CognitiveTier.TIER_2,
            )
        
        return None
    
    def escalate(
        self,
        current_model: ModelConfig,
        category: TaskCategory,
        reason: EscalationReason,
    ) -> Optional[ModelConfig]:
        """
        Escalate to the next tier model for the given category.
        
        Args:
            current_model: The current model being used
            category: Task category
            reason: Reason for escalation
        
        Returns:
            Next tier model or None if no escalation available
        """
        escalation_chain = self.get_escalation_chain(category)
        
        if not escalation_chain:
            logger.info(f"No escalation chain available for category {category}")
            return None
        
        current_tier = current_model.tier
        for model in escalation_chain:
            if model.tier.value > current_tier.value:
                self.session_escalation_count += 1
                self.turn_escalation_count += 1
                logger.info(
                    f"Escalating from {current_model.name} to {model.name}. "
                    f"Reason: {reason.description}"
                )
                return model
        
        logger.info(f"Already at highest tier for category {category}")
        return None
    
    def reset_turn_counter(self):
        """Reset the per-turn escalation counter."""
        self.turn_escalation_count = 0
    
    def get_stats(self) -> Dict[str, int]:
        """Get routing statistics."""
        return {
            "session_escalations": self.session_escalation_count,
            "turn_escalations": self.turn_escalation_count,
            "max_escalations_per_turn": self.max_escalations_per_turn,
            "max_escalations_per_session": self.max_escalations_per_session,
        }
