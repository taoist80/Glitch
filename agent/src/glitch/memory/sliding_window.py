"""Sliding window memory manager with AgentCore Memory integration."""

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import logging
import boto3
from botocore.exceptions import ClientError

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
    ):
        self.session_id = session_id
        self.memory_id = memory_id
        self.region = region
        self.window_size = window_size
        self.compression_threshold_pct = compression_threshold_pct
        
        self.structured_memory = StructuredMemory()
        
        try:
            self.agentcore_client = boto3.client("bedrock-agentcore", region_name=region)
        except Exception as e:
            logger.warning(f"Could not initialize AgentCore Memory client: {e}")
            self.agentcore_client = None
    
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
        metadata: Optional[Dict[str, str]] = None,
    ) -> Optional[str]:
        """
        Create a short-term memory event in AgentCore Memory.
        
        Args:
            event_content: The content of the event (user/agent message)
            event_type: Type of event (conversation, tool_use, etc.)
            metadata: Optional metadata tags for filtering
        
        Returns:
            Event ID if successful, None otherwise
        """
        if not self.agentcore_client:
            logger.warning("AgentCore Memory client not available")
            return None
        
        try:
            response = self.agentcore_client.create_event(
                memoryId=self.memory_id,
                sessionId=self.session_id,
                eventContent=event_content,
                eventType=event_type,
                metadata=metadata or {},
            )
            
            event_id = response.get("eventId")
            logger.info(f"Created event {event_id} in session {self.session_id}")
            return event_id
            
        except ClientError as e:
            logger.error(f"Failed to create event: {e}")
            return None
    
    async def retrieve_recent_events(
        self,
        max_results: int = 10,
        metadata_filter: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve recent events from short-term memory.
        
        Args:
            max_results: Maximum number of events to retrieve
            metadata_filter: Optional metadata filter
        
        Returns:
            List of events
        """
        if not self.agentcore_client:
            return []
        
        try:
            params = {
                "memoryId": self.memory_id,
                "sessionId": self.session_id,
                "maxResults": max_results,
            }
            
            if metadata_filter:
                params["metadataFilter"] = metadata_filter
            
            response = self.agentcore_client.list_events(**params)
            events = response.get("events", [])
            
            logger.info(f"Retrieved {len(events)} events from session {self.session_id}")
            return events
            
        except ClientError as e:
            logger.error(f"Failed to retrieve events: {e}")
            return []
    
    async def retrieve_long_term_memories(
        self,
        query: str,
        max_results: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve relevant long-term memories using semantic search.
        
        Args:
            query: Query to search for relevant memories
            max_results: Maximum number of memories to retrieve
        
        Returns:
            List of memory records
        """
        if not self.agentcore_client:
            return []
        
        try:
            response = self.agentcore_client.retrieve_memory_records(
                memoryId=self.memory_id,
                query=query,
                maxResults=max_results,
            )
            
            memories = response.get("memoryRecords", [])
            logger.info(f"Retrieved {len(memories)} long-term memories for query: {query}")
            return memories
            
        except ClientError as e:
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
