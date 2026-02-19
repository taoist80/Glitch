"""Routing package for model tier management.

Exports:
    CognitiveTier: Enum for model tiers
    ModelConfig: Configuration for a model
    RouterConfig: Configuration for ModelRouter
    RouterStats: Statistics from ModelRouter
    EscalationReason: Reason for tier escalation
    ModelRouter: Routes tasks and manages escalation
    MODEL_REGISTRY: Available models
    ROUTING_CONFIG: Task category routing rules
    TaskCategory: Type alias for task categories
    EscalationTrigger: Type alias for escalation triggers
"""

from glitch.routing.model_router import (
    CognitiveTier,
    ModelConfig,
    RouterConfig,
    RouterStats,
    EscalationReason,
    ModelRouter,
    MODEL_REGISTRY,
    ROUTING_CONFIG,
    TaskCategory,
    EscalationTrigger,
    RoutingRule,
)

__all__ = [
    "CognitiveTier",
    "ModelConfig",
    "RouterConfig",
    "RouterStats",
    "EscalationReason",
    "ModelRouter",
    "MODEL_REGISTRY",
    "ROUTING_CONFIG",
    "TaskCategory",
    "EscalationTrigger",
    "RoutingRule",
]
