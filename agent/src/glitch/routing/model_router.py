"""Model routing and tier escalation logic for Glitch agent.

Model IDs use Bedrock cross-region inference profile format for optimal throughput.
Reference: https://docs.aws.amazon.com/bedrock/latest/userguide/cross-region-inference.html

Dataflow:
    TaskCategory -> get_primary_model() -> ModelConfig
    (confidence, context, complexity) -> should_escalate() -> EscalationReason
    EscalationReason -> escalate() -> ModelConfig (next tier)
"""

from typing import Dict, List, Optional, Literal, TypedDict
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)

TaskCategory = Literal["chat", "coding", "vision", "tool_use", "mcp_use", "skill_workflow"]
EscalationTrigger = Literal["confidence", "context", "complexity", "manual"]


class CognitiveTier(Enum):
    """Cognitive tiers for model escalation.
    
    Values:
        LOCAL: On-premises models (Ollama)
        TIER_1: Primary cloud model (Sonnet 4)
        TIER_2: Enhanced cloud model (Sonnet 4.5)
        TIER_3: Premium cloud model (Opus 4)
    """
    LOCAL = 0
    TIER_1 = 1
    TIER_2 = 2
    TIER_3 = 3


@dataclass
class ModelConfig:
    """Configuration for a specific model.
    
    Attributes:
        name: Human-readable model name
        model_id: Bedrock model ID or local model identifier
        tier: Cognitive tier for escalation ordering
        supports_vision: Whether model supports image input
        supports_tools: Whether model supports tool calling
        max_context_tokens: Maximum context window size
        cost_per_million_tokens: Cost in USD per million tokens
    """
    name: str
    model_id: str
    tier: CognitiveTier
    supports_vision: bool = False
    supports_tools: bool = True
    max_context_tokens: int = 200000
    cost_per_million_tokens: float = 0.0


class RoutingRule(TypedDict):
    """Routing rule for a task category."""
    primary: str
    escalation: List[str]


@dataclass
class RouterConfig:
    """Configuration for ModelRouter.
    
    Attributes:
        confidence_threshold: Minimum confidence before escalation (0.0-1.0)
        context_threshold_pct: Context usage threshold for escalation (0.0-1.0)
        max_escalations_per_turn: Maximum escalations allowed per turn
        max_escalations_per_session: Maximum escalations allowed per session
    """
    confidence_threshold: float = 0.7
    context_threshold_pct: float = 0.7
    max_escalations_per_turn: int = 1
    max_escalations_per_session: int = 2


class RouterStats(TypedDict):
    """Statistics from ModelRouter."""
    session_escalations: int
    turn_escalations: int
    max_escalations_per_turn: int
    max_escalations_per_session: int


ROUTING_CONFIG: Dict[TaskCategory, RoutingRule] = {
    "chat": {
        "primary": "glitch",
        "escalation": ["sonnet-4.5", "opus-4"],
    },
    "coding": {
        "primary": "glitch",
        "escalation": ["sonnet-4.5", "opus-4"],
    },
    "vision": {
        "primary": "vision_agent",
        "escalation": ["sonnet-4.5"],
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
        "escalation": ["sonnet-4.5"],
    },
}

MODEL_REGISTRY: Dict[str, ModelConfig] = {
    "glitch": ModelConfig(
        name="glitch",
        model_id="us.anthropic.claude-sonnet-4-20250514-v1:0",
        tier=CognitiveTier.TIER_1,
        supports_vision=True,
        supports_tools=True,
        max_context_tokens=200000,
        cost_per_million_tokens=3.0,
    ),
    "sonnet-4.5": ModelConfig(
        name="sonnet-4.5",
        model_id="us.anthropic.claude-sonnet-4-5-20250514-v1:0",
        tier=CognitiveTier.TIER_2,
        supports_vision=True,
        supports_tools=True,
        max_context_tokens=200000,
        cost_per_million_tokens=5.0,
    ),
    "opus-4": ModelConfig(
        name="opus-4",
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
    "poet": ModelConfig(
        name="poet",
        model_id="us.anthropic.claude-sonnet-4-5-20250514-v1:0",
        tier=CognitiveTier.TIER_2,
        supports_vision=False,
        supports_tools=False,
        max_context_tokens=200000,
        cost_per_million_tokens=5.0,
    ),
}


@dataclass
class EscalationReason:
    """Reason for escalating to a higher tier.
    
    Attributes:
        trigger: What triggered the escalation
        description: Human-readable description
        current_tier: Tier being escalated from
        target_tier: Tier being escalated to
    """
    trigger: EscalationTrigger
    description: str
    current_tier: CognitiveTier
    target_tier: CognitiveTier


class ModelRouter:
    """Routes tasks to appropriate models and manages tier escalation.
    
    Dataflow:
        1. get_primary_model(category) -> ModelConfig for initial routing
        2. should_escalate(confidence, context, complexity) -> EscalationReason?
        3. escalate(current, category, reason) -> ModelConfig (next tier)
    
    Attributes:
        confidence_threshold: Minimum confidence before escalation
        context_threshold_pct: Context usage threshold for escalation
        max_escalations_per_turn: Maximum escalations per turn
        max_escalations_per_session: Maximum escalations per session
        session_escalation_count: Current session escalation count
        turn_escalation_count: Current turn escalation count
    """
    
    def __init__(
        self,
        confidence_threshold: float = 0.7,
        context_threshold_pct: float = 0.7,
        max_escalations_per_turn: int = 1,
        max_escalations_per_session: int = 2,
    ):
        """Initialize ModelRouter.
        
        Args:
            confidence_threshold: Minimum confidence before escalation (0.0-1.0)
            context_threshold_pct: Context usage threshold for escalation (0.0-1.0)
            max_escalations_per_turn: Maximum escalations allowed per turn
            max_escalations_per_session: Maximum escalations allowed per session
        """
        self.confidence_threshold = confidence_threshold
        self.context_threshold_pct = context_threshold_pct
        self.max_escalations_per_turn = max_escalations_per_turn
        self.max_escalations_per_session = max_escalations_per_session
        
        self.session_escalation_count = 0
        self.turn_escalation_count = 0
    
    @classmethod
    def from_config(cls, config: RouterConfig) -> "ModelRouter":
        """Create ModelRouter from RouterConfig.
        
        Args:
            config: RouterConfig instance
        
        Returns:
            Configured ModelRouter instance
        """
        return cls(
            confidence_threshold=config.confidence_threshold,
            context_threshold_pct=config.context_threshold_pct,
            max_escalations_per_turn=config.max_escalations_per_turn,
            max_escalations_per_session=config.max_escalations_per_session,
        )
    
    def get_primary_model(self, category: TaskCategory) -> ModelConfig:
        """Get the primary model for a task category.
        
        Args:
            category: Task category (chat, coding, vision, etc.)
        
        Returns:
            ModelConfig for the primary model
        """
        primary_name = ROUTING_CONFIG[category]["primary"]
        return MODEL_REGISTRY[primary_name]
    
    def get_escalation_chain(self, category: TaskCategory) -> List[ModelConfig]:
        """Get the escalation chain for a task category.
        
        Args:
            category: Task category
        
        Returns:
            List of ModelConfig in escalation order
        """
        escalation_names = ROUTING_CONFIG[category]["escalation"]
        return [MODEL_REGISTRY[name] for name in escalation_names]
    
    def should_escalate(
        self,
        confidence: Optional[float] = None,
        context_usage_pct: Optional[float] = None,
        complexity_flag: bool = False,
    ) -> Optional[EscalationReason]:
        """Determine if escalation is needed based on various factors.
        
        Checks in order:
        1. Session/turn escalation limits
        2. Manual complexity flag
        3. Confidence below threshold
        4. Context usage above threshold
        
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
        """Escalate to the next tier model for the given category.
        
        Args:
            current_model: The current model being used
            category: Task category
            reason: Reason for escalation
        
        Returns:
            Next tier ModelConfig, or None if no escalation available
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
    
    def reset_turn_counter(self) -> None:
        """Reset the per-turn escalation counter."""
        self.turn_escalation_count = 0
    
    def get_stats(self) -> RouterStats:
        """Get routing statistics.
        
        Returns:
            RouterStats with current escalation counts and limits
        """
        return RouterStats(
            session_escalations=self.session_escalation_count,
            turn_escalations=self.turn_escalation_count,
            max_escalations_per_turn=self.max_escalations_per_turn,
            max_escalations_per_session=self.max_escalations_per_session,
        )
