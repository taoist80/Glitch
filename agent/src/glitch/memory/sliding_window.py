"""Sliding window memory manager with AgentCore Memory integration.

Uses the official bedrock_agentcore.memory.MemoryClient SDK for all memory operations.
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class StructuredMemory:
    """Structured memory state for the agent."""
    session_goal: str = ""
    facts: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    tool_results_summary: List[Dict[str, Any]] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StructuredMemory":
        """Create from dictionary."""
        return cls(**data)
    
    def add_fact(self, fact: str):
        """Add a fact to memory."""
        if fact not in self.facts:
            self.facts.append(fact)
            self.last_updated = datetime.utcnow().isoformat()
    
    def add_constraint(self, constraint: str):
        """Add a constraint to memory."""
        if constraint not in self.constraints:
            self.constraints.append(constraint)
            self.last_updated = datetime.utcnow().isoformat()
    
    def add_decision(self, decision: str, rationale: str):
        """Add a decision to memory."""
        self.decisions.append({
            "decision": decision,
            "rationale": rationale,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.last_updated = datetime.utcnow().isoformat()
    
    def add_tool_result(self, tool_name: str, summary: str):
        """Add a tool result summary."""
        self.tool_results_summary.append({
            "tool": tool_name,
            "summary": summary,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.last_updated = datetime.utcnow().isoformat()


class GlitchMemoryManager:
    """
    Three-layer memory manager for Glitch agent.
    
    Uses the official bedrock_agentcore.memory.MemoryClient SDK.
    
    Layers:
    1. Active Window: Recent raw conversation turns (handled by Strands)
    2. Structured Memory: JSON state with facts, decisions, constraints
    3. Archive: Long-term memory in AgentCore Memory (short-term + long-term)
    """
    
    def __init__(
        self,
        session_id: str,
        memory_id: str,
        region: str = "us-west-2",
        window_size: int = 20,
        compression_threshold_pct: float = 0.7,
        actor_id: str = "glitch-agent",
    ):
        self.session_id = session_id
        self.memory_id = memory_id
        self.region = region
        self.window_size = window_size
        self.compression_threshold_pct = compression_threshold_pct
        self.actor_id = actor_id
        
        self.structured_memory = StructuredMemory()
        self.memory_client = None
        
        try:
            from bedrock_agentcore.memory import MemoryClient
            self.memory_client = MemoryClient(region_name=region)
            logger.info(f"Initialized AgentCore MemoryClient for region {region}")
        except ImportError:
            logger.warning("bedrock_agentcore.memory not available, memory features disabled")
        except Exception as e:
            logger.warning(f"Could not initialize AgentCore MemoryClient: {e}")
    
    @property
    def agentcore_client(self):
        """Backward compatibility property."""
        return self.memory_client
    
    def get_structured_state(self) -> StructuredMemory:
        """Get the current structured memory state."""
        return self.structured_memory
    
    def update_structured_state(self, updates: Dict[str, Any]):
        """Update structured memory with new information."""
        for key, value in updates.items():
            if hasattr(self.structured_memory, key):
                setattr(self.structured_memory, key, value)
        self.structured_memory.last_updated = datetime.utcnow().isoformat()
    
    async def create_event(
        self,
        event_content: str,
        event_type: str = "conversation",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Create a short-term memory event in AgentCore Memory.
        
        Uses the official MemoryClient.create_event() API.
        
        Args:
            event_content: The content of the event (user/agent message)
            event_type: Type of event (conversation, tool_use, etc.)
            metadata: Optional metadata dict for filtering
        
        Returns:
            Event ID if successful, None otherwise
        """
        if not self.memory_client:
            logger.warning("AgentCore MemoryClient not available, skipping event creation")
            return None
        
        try:
            role = "user" if event_type == "user_message" else "assistant"
            messages: List[Tuple[str, str]] = [(event_content, role)]
            
            response = self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=messages,
            )
            
            event_id = response.get("eventId") if isinstance(response, dict) else None
            logger.info(f"Created event in session {self.session_id}")
            return event_id
            
        except Exception as e:
            logger.error(f"Failed to create event: {e}")
            return None
    
    async def retrieve_recent_events(
        self,
        max_results: int = 10,
        metadata_filter: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent conversation turns from short-term memory.
        
        Uses the official MemoryClient.get_last_k_turns() API.
        
        Args:
            max_results: Maximum number of conversation turns to retrieve
            metadata_filter: Optional metadata filter (not used in current SDK)
        
        Returns:
            List of conversation turns
        """
        if not self.memory_client:
            return []
        
        try:
            turns = self.memory_client.get_last_k_turns(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                k=max_results,
            )
            
            logger.info(f"Retrieved {len(turns) if turns else 0} turns from session {self.session_id}")
            return turns if turns else []
            
        except Exception as e:
            logger.error(f"Failed to retrieve recent events: {e}")
            return []
    
    async def retrieve_long_term_memories(
        self,
        query: str,
        max_results: int = 5,
        namespaces: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant long-term memories using semantic search.
        
        Uses the official MemoryClient.retrieve() API for semantic memory retrieval.
        
        Args:
            query: Query to search for relevant memories
            max_results: Maximum number of memories to retrieve
            namespaces: Optional list of namespaces to search in
        
        Returns:
            List of memory records
        """
        if not self.memory_client:
            return []
        
        try:
            memories = self.memory_client.retrieve(
                memory_id=self.memory_id,
                query=query,
                max_results=max_results,
                namespaces=namespaces or ["/user/facts/", "/user/preferences/"],
            )
            
            logger.info(f"Retrieved {len(memories) if memories else 0} long-term memories for query: {query}")
            return memories if memories else []
            
        except AttributeError:
            logger.warning("MemoryClient.retrieve() not available in this SDK version")
            return []
        except Exception as e:
            logger.error(f"Failed to retrieve long-term memories: {e}")
            return []
    
    def compress_for_escalation(self) -> Dict[str, Any]:
        """
        Compress memory for escalation to higher tier.
        
        Returns:
            Compressed memory capsule
        """
        capsule = {
            "session_id": self.session_id,
            "structured_memory": self.structured_memory.to_dict(),
            "compression_timestamp": datetime.utcnow().isoformat(),
        }
        
        logger.info(f"Compressed memory for escalation: {len(json.dumps(capsule))} bytes")
        return capsule
    
    def calculate_context_usage(self, current_tokens: int, max_tokens: int) -> float:
        """
        Calculate context window usage percentage.
        
        Args:
            current_tokens: Current token count
            max_tokens: Maximum token limit
        
        Returns:
            Usage percentage (0.0 to 1.0)
        """
        return current_tokens / max_tokens if max_tokens > 0 else 0.0
    
    def should_compress(self, context_usage: float) -> bool:
        """Check if compression/sliding should occur."""
        return context_usage >= self.compression_threshold_pct
    
    def get_summary_for_context(self) -> str:
        """Get a text summary of structured memory for context."""
        summary_parts = []
        
        if self.structured_memory.session_goal:
            summary_parts.append(f"Goal: {self.structured_memory.session_goal}")
        
        if self.structured_memory.facts:
            summary_parts.append(f"Facts: {', '.join(self.structured_memory.facts)}")
        
        if self.structured_memory.constraints:
            summary_parts.append(f"Constraints: {', '.join(self.structured_memory.constraints)}")
        
        if self.structured_memory.decisions:
            recent_decisions = self.structured_memory.decisions[-3:]
            decisions_str = "; ".join([d["decision"] for d in recent_decisions])
            summary_parts.append(f"Recent Decisions: {decisions_str}")
        
        if self.structured_memory.open_questions:
            summary_parts.append(f"Open Questions: {', '.join(self.structured_memory.open_questions)}")
        
        return "\n".join(summary_parts) if summary_parts else "No structured memory yet."
