"""Sliding window memory manager with AgentCore Memory integration.

Uses the official bedrock_agentcore.memory.MemoryClient SDK for all memory operations.

Dataflow:
    User Message -> create_event() -> AgentCore Memory (short-term)
    Query -> retrieve_long_term_memories() -> AgentCore Memory (semantic search)
    Structured updates -> create_structured_event() -> AgentCore Memory (persistent)
    Context Request -> get_summary_for_context() -> StructuredMemory -> String
    Startup / reload -> load_structured_from_agentcore() -> StructuredMemory (hydrate from Memory)
"""

from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime
import json
import logging

from glitch.types import EventType

logger = logging.getLogger(__name__)

# Prefix for structured memory events stored in AgentCore Memory (for retrieval).
STRUCTURED_EVENT_PREFIX = "_structured:"


@dataclass
class Decision:
    """A recorded decision with rationale and timestamp."""
    decision: str
    rationale: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class ToolResult:
    """Summary of a tool execution result."""
    tool: str
    summary: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class StructuredMemory:
    """Structured memory state for the agent.
    
    Maintains session context including:
    - Session goal
    - Accumulated facts
    - Constraints to respect
    - Decisions made with rationale
    - Open questions to address
    - Tool execution summaries
    """
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
    
    def add_fact(self, fact: str) -> None:
        """Add a fact to memory (deduplicates)."""
        if fact not in self.facts:
            self.facts.append(fact)
            self.last_updated = datetime.utcnow().isoformat()
    
    def add_constraint(self, constraint: str) -> None:
        """Add a constraint to memory (deduplicates)."""
        if constraint not in self.constraints:
            self.constraints.append(constraint)
            self.last_updated = datetime.utcnow().isoformat()
    
    def add_decision(self, decision: str, rationale: str) -> None:
        """Add a decision with rationale to memory."""
        self.decisions.append({
            "decision": decision,
            "rationale": rationale,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.last_updated = datetime.utcnow().isoformat()
    
    def add_tool_result(self, tool_name: str, summary: str) -> None:
        """Add a tool result summary to memory."""
        self.tool_results_summary.append({
            "tool": tool_name,
            "summary": summary,
            "timestamp": datetime.utcnow().isoformat(),
        })
        self.last_updated = datetime.utcnow().isoformat()


@dataclass
class MemoryConfig:
    """Configuration for GlitchMemoryManager.
    
    Attributes:
        session_id: Unique session identifier
        memory_id: Memory store identifier
        region: AWS region for AgentCore Memory
        window_size: Sliding window size for conversation history
        compression_threshold_pct: Context usage threshold for compression (0.0-1.0)
        actor_id: Actor identifier for memory events
    """
    session_id: str
    memory_id: str
    region: str = "us-west-2"
    window_size: int = 20
    compression_threshold_pct: float = 0.7
    actor_id: str = "glitch-agent"


@dataclass
class MemoryCapsule:
    """Compressed memory for escalation to higher tier.
    
    Contains essential context for a higher-tier model to continue
    the conversation without full history.
    """
    session_id: str
    structured_memory: Dict[str, Any]
    compression_timestamp: str


class GlitchMemoryManager:
    """Three-layer memory manager for Glitch agent.
    
    Uses the official bedrock_agentcore.memory.MemoryClient SDK.
    
    Layers:
    1. Active Window: Recent raw conversation turns (handled by Strands)
    2. Structured Memory: JSON state with facts, decisions, constraints
    3. Archive: Long-term memory in AgentCore Memory (short-term + long-term)
    
    Attributes:
        session_id: Unique session identifier
        memory_id: Memory store identifier
        region: AWS region
        window_size: Sliding window size
        compression_threshold_pct: Threshold for triggering compression
        actor_id: Actor identifier for memory events
        structured_memory: Current StructuredMemory state
        memory_client: AgentCore MemoryClient instance (or None)
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
        """Initialize GlitchMemoryManager.
        
        Args:
            session_id: Unique session identifier
            memory_id: Memory store identifier
            region: AWS region for AgentCore Memory
            window_size: Sliding window size for conversation history
            compression_threshold_pct: Context usage threshold for compression
            actor_id: Actor identifier for memory events
        """
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
    
    @classmethod
    def from_config(cls, config: MemoryConfig) -> "GlitchMemoryManager":
        """Create GlitchMemoryManager from MemoryConfig.
        
        Args:
            config: MemoryConfig instance
        
        Returns:
            Configured GlitchMemoryManager instance
        """
        return cls(
            session_id=config.session_id,
            memory_id=config.memory_id,
            region=config.region,
            window_size=config.window_size,
            compression_threshold_pct=config.compression_threshold_pct,
            actor_id=config.actor_id,
        )
    
    @property
    def agentcore_client(self):
        """Backward compatibility property for memory_client."""
        return self.memory_client
    
    def get_structured_state(self) -> StructuredMemory:
        """Get the current structured memory state.
        
        Returns:
            Current StructuredMemory instance
        """
        return self.structured_memory
    
    def update_structured_state(self, updates: Dict[str, Any]) -> None:
        """Update structured memory with new information.
        
        Args:
            updates: Dictionary of field names to new values
        """
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
        """Create a short-term memory event in AgentCore Memory.
        
        Uses the official MemoryClient.create_event() API.
        
        Dataflow:
            event_content -> MemoryClient.create_event() -> AgentCore Memory
        
        Args:
            event_content: The content of the event (user/agent message)
            event_type: Type of event (user_message, agent_response, etc.)
            metadata: Optional metadata dict (not used in current SDK)
        
        Returns:
            Event ID if successful, None otherwise
        """
        if not self.memory_client:
            logger.warning("AgentCore MemoryClient not available, skipping event creation")
            return None
        
        try:
            role = "user" if event_type == EventType.USER_MESSAGE.value else "assistant"
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
        """Retrieve recent conversation turns from short-term memory.
        
        Uses the official MemoryClient.get_last_k_turns() API.
        
        Args:
            max_results: Maximum number of conversation turns to retrieve
            metadata_filter: Optional metadata filter (not used in current SDK)
        
        Returns:
            List of conversation turns as dictionaries
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
        """Retrieve relevant long-term memories using semantic search.
        
        Uses the official MemoryClient.retrieve() API for semantic memory retrieval.
        
        Args:
            query: Query to search for relevant memories
            max_results: Maximum number of memories to retrieve
            namespaces: Optional list of namespaces to search in
        
        Returns:
            List of memory records as dictionaries
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

    def _session_namespaces(self) -> List[str]:
        """Namespaces for this session's structured data in AgentCore Memory."""
        return [f"/session/{self.session_id}/"]

    def create_structured_event(self, kind: str, value: Any) -> Optional[str]:
        """Persist a structured memory update to AgentCore Memory (sync).

        Stores as a single event so retrieve() can find it by semantic search.
        Use kind in {"session_goal", "fact", "constraint", "decision", "open_question"}.

        Args:
            kind: Type of structured data (session_goal, fact, constraint, etc.)
            value: Value to store (string or serializable structure)

        Returns:
            Event ID if successful, None otherwise
        """
        if not self.memory_client:
            return None
        try:
            content = json.dumps({"_structured": kind, "value": value})
            role = "assistant"
            response = self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[(content, role)],
            )
            event_id = response.get("eventId") if isinstance(response, dict) else None
            logger.debug("Created structured event kind=%s in session %s", kind, self.session_id)
            return event_id
        except Exception as e:
            logger.warning("Failed to create_structured_event: %s", e)
            return None

    async def load_structured_from_agentcore(self) -> None:
        """Hydrate structured memory from AgentCore Memory (e.g. after restart).

        Calls retrieve() with session-scoped query and merges results into
        self.structured_memory so get_summary_for_context() and tools see persisted state.
        """
        if not self.memory_client:
            return
        try:
            memories = await self.retrieve_long_term_memories(
                query="session goal facts constraints decisions open questions",
                max_results=50,
                namespaces=self._session_namespaces(),
            )
            if not memories:
                return
            for m in memories:
                content = (m.get("content") or m.get("text") or m.get("message") or m.get("body") or "") if isinstance(m, dict) else str(m)
                if not content:
                    continue
                try:
                    if isinstance(content, str) and content.strip().startswith("{"):
                        data = json.loads(content)
                    elif isinstance(content, dict):
                        data = content
                    else:
                        continue
                    if not isinstance(data, dict) or data.get("_structured") is None or "value" not in data:
                        continue
                    kind = data["_structured"]
                    value = data["value"]
                    if kind == "session_goal" and value:
                        self.structured_memory.session_goal = value
                    elif kind == "fact" and value and value not in self.structured_memory.facts:
                        self.structured_memory.facts.append(value)
                    elif kind == "constraint" and value and value not in self.structured_memory.constraints:
                        self.structured_memory.constraints.append(value)
                    elif kind == "decision" and value:
                        entry = value if isinstance(value, dict) else {"decision": value, "rationale": "", "timestamp": datetime.utcnow().isoformat()}
                        if entry not in self.structured_memory.decisions:
                            self.structured_memory.decisions.append(entry)
                    elif kind == "open_question" and value and value not in self.structured_memory.open_questions:
                        self.structured_memory.open_questions.append(value)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.debug("Skip parsing structured memory item: %s", e)
            logger.info("Loaded structured memory from AgentCore for session %s", self.session_id)
        except Exception as e:
            logger.warning("load_structured_from_agentcore failed: %s", e)
    
    def compress_for_escalation(self) -> MemoryCapsule:
        """Compress memory for escalation to higher tier.
        
        Creates a MemoryCapsule containing essential context for a higher-tier
        model to continue the conversation.
        
        Returns:
            MemoryCapsule with compressed memory state
        """
        capsule = MemoryCapsule(
            session_id=self.session_id,
            structured_memory=self.structured_memory.to_dict(),
            compression_timestamp=datetime.utcnow().isoformat(),
        )
        
        logger.info(f"Compressed memory for escalation: {len(json.dumps(asdict(capsule)))} bytes")
        return capsule
    
    def calculate_context_usage(self, current_tokens: int, max_tokens: int) -> float:
        """Calculate context window usage percentage.
        
        Args:
            current_tokens: Current token count
            max_tokens: Maximum token limit
        
        Returns:
            Usage percentage (0.0 to 1.0)
        """
        return current_tokens / max_tokens if max_tokens > 0 else 0.0
    
    def should_compress(self, context_usage: float) -> bool:
        """Check if compression/sliding should occur.
        
        Args:
            context_usage: Current context usage percentage (0.0 to 1.0)
        
        Returns:
            True if compression should be triggered
        """
        return context_usage >= self.compression_threshold_pct
    
    def get_summary_for_context(self) -> str:
        """Get a text summary of structured memory for context injection.
        
        Returns:
            Human-readable summary of current memory state
        """
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
