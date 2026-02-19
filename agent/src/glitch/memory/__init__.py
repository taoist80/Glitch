"""Memory management package for conversation and context.

Exports:
    StructuredMemory: Dataclass for session memory state
    MemoryConfig: Configuration for GlitchMemoryManager
    MemoryCapsule: Compressed memory for tier escalation
    GlitchMemoryManager: Three-layer memory manager
"""

from glitch.memory.sliding_window import (
    StructuredMemory,
    MemoryConfig,
    MemoryCapsule,
    GlitchMemoryManager,
    Decision,
    ToolResult,
)

__all__ = [
    "StructuredMemory",
    "MemoryConfig",
    "MemoryCapsule",
    "GlitchMemoryManager",
    "Decision",
    "ToolResult",
]
