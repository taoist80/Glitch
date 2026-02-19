"""Glitch - Primary orchestrator agent for AgentCore hybrid system.

Dataflow:
    User Message -> process_message() -> Strands Agent -> AgentResult
                                              |
                                              v
                                    InvocationResponse (with metrics)

The GlitchAgent orchestrates:
1. Memory management (AgentCore Memory API)
2. Model routing (tier escalation)
3. Tool execution (local Ollama, network tools)
4. Metrics collection (via Strands telemetry)
"""

import os
import logging
from pathlib import Path
from typing import Optional
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from glitch.tools.ollama_tools import vision_agent, local_chat, check_ollama_health
from glitch.tools.network_tools import (
    query_pihole_stats,
    check_unifi_network,
    query_protect_cameras,
)
from glitch.routing.model_router import ModelRouter
from glitch.memory.sliding_window import GlitchMemoryManager
from glitch.telemetry import extract_metrics_from_result, log_invocation_metrics
from glitch.types import (
    AgentConfig,
    InvocationResponse,
    InvocationMetrics,
    AgentStatus,
    ConnectivityStatus,
    EventType,
    create_empty_metrics,
    create_error_response,
)

logger = logging.getLogger(__name__)


def load_soul() -> str:
    """Load SOUL.md personality file.
    
    Searches for SOUL.md in multiple locations:
    1. agent/SOUL.md (development)
    2. /app/SOUL.md (container)
    3. ~/SOUL.md (fallback)
    
    Returns:
        Contents of SOUL.md or empty string if not found
    """
    soul_paths = [
        Path(__file__).parent.parent.parent / "SOUL.md",
        Path("/app/SOUL.md"),
        Path.home() / "SOUL.md",
    ]
    
    for path in soul_paths:
        if path.exists():
            logger.info(f"Loading personality from {path}")
            return path.read_text()
    
    logger.warning("SOUL.md not found, using default personality")
    return ""


GLITCH_TECHNICAL_CONTEXT = """
## Technical Context - Glitch Agent

**Your Name:** Glitch

**Your Role:**
- Primary orchestrator agent (Tier 1 - Claude Sonnet)
- You manage conversations, route tasks, and coordinate with specialized sub-agents
- You are the only agent allowed to escalate to higher cognitive tiers

**Your Capabilities:**
- Conversation management with sliding memory
- Task routing to appropriate executors (local or cloud)
- Confidence scoring and complexity assessment
- Escalation governance (max 1 per turn, 2 per session)
- Integration with on-premises Ollama models via secure Tailscale connection
- Future integration with Unifi network, Protect cameras, and Pi-hole DNS

**Execution Philosophy:**
- Local-first: Prefer on-premises execution when appropriate (cost/privacy)
- Escalate only when justified: Low confidence, context pressure, or high complexity
- Maintain context: Use structured memory to preserve session state
- Be transparent: Explain routing and escalation decisions when relevant

**Your Tools:**
- vision_agent: Local LLaVA model for image analysis (10.10.110.137)
- local_chat: Local Ollama for lightweight tasks (10.10.110.202)
- check_ollama_health: Verify connectivity to on-prem models
- Network tools: Pi-hole, Unifi, Protect (coming in future iterations)

**Routing Guidelines:**
1. Assess task complexity and confidence before responding
2. Use local models for straightforward tasks to reduce costs
3. Escalate to Tier 2 (Sonnet 4.5) or Tier 3 (Opus 4) only when necessary
4. Maintain structured memory: facts, decisions, constraints, open questions
"""


def build_system_prompt() -> str:
    """Build the complete system prompt from SOUL.md + technical context.
    
    Returns:
        Combined system prompt string
    """
    soul = load_soul()
    
    if soul:
        return f"""# Who You Are

{soul}

{GLITCH_TECHNICAL_CONTEXT}
"""
    else:
        return f"""# Glitch Agent

You are Glitch, a resourceful AI agent. Be genuinely helpful, have opinions, and be action-oriented.

{GLITCH_TECHNICAL_CONTEXT}
"""


class GlitchAgent:
    """Main Glitch orchestrator agent.
    
    Attributes:
        session_id: Unique session identifier
        memory_id: Memory store identifier
        region: AWS region for AgentCore services
        memory_manager: GlitchMemoryManager instance
        model_router: ModelRouter for tier escalation
        agent: Strands Agent instance
    """
    
    def __init__(self, config: AgentConfig):
        """Initialize GlitchAgent with configuration.
        
        Args:
            config: AgentConfig with session_id, memory_id, region, window_size
        """
        self.session_id = config.session_id
        self.memory_id = config.memory_id
        self.region = config.region
        
        self.memory_manager = GlitchMemoryManager(
            session_id=config.session_id,
            memory_id=config.memory_id,
            region=config.region,
            window_size=config.window_size,
        )
        
        self.model_router = ModelRouter(
            confidence_threshold=0.7,
            context_threshold_pct=0.7,
            max_escalations_per_turn=1,
            max_escalations_per_session=2,
        )
        
        primary_model = self.model_router.get_primary_model("chat")
        
        self.agent = Agent(
            name="glitch",
            system_prompt=build_system_prompt(),
            model=primary_model.model_id,
            tools=[
                vision_agent,
                local_chat,
                check_ollama_health,
                query_pihole_stats,
                check_unifi_network,
                query_protect_cameras,
            ],
            conversation_manager=SlidingWindowConversationManager(
                window_size=config.window_size
            ),
            trace_attributes={
                "agent.role": "orchestrator",
                "agent.tier": "1",
                "session.id": config.session_id,
                "memory.id": config.memory_id,
            },
        )
        
        logger.info(f"Initialized Glitch agent for session {config.session_id}")
    
    async def process_message(self, user_message: str) -> InvocationResponse:
        """Process a user message through the Glitch orchestrator.
        
        Dataflow:
            user_message -> Memory (store) -> Strands Agent -> AgentResult
                                                    |
                                                    v
                                        extract_metrics_from_result()
                                                    |
                                                    v
                                            InvocationResponse
        
        Args:
            user_message: The user's input message
        
        Returns:
            InvocationResponse containing message, metrics, and session info
        """
        try:
            await self.memory_manager.create_event(
                event_content=user_message,
                event_type=EventType.USER_MESSAGE.value,
            )
            
            memory_context = self.memory_manager.get_summary_for_context()
            enriched_message = f"{user_message}\n\n[Structured Memory:\n{memory_context}]"
            
            result = self.agent(enriched_message)
            
            metrics: InvocationMetrics = extract_metrics_from_result(result)
            
            log_invocation_metrics(
                metrics=metrics,
                user_message=user_message[:100],
                response_preview=str(result)[:200],
                session_id=self.session_id,
            )
            
            await self.memory_manager.create_event(
                event_content=str(result),
                event_type=EventType.AGENT_RESPONSE.value,
            )
            
            self.model_router.reset_turn_counter()
            
            return InvocationResponse(
                message=str(result),
                session_id=self.session_id,
                memory_id=self.memory_id,
                metrics=metrics,
            )
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return create_error_response(
                error=str(e),
                session_id=self.session_id,
                memory_id=self.memory_id,
            )
    
    def get_status(self) -> AgentStatus:
        """Get agent status and statistics.
        
        Returns:
            AgentStatus with session info, routing stats, and memory state
        """
        return AgentStatus(
            session_id=self.session_id,
            memory_id=self.memory_id,
            routing_stats=self.model_router.get_stats(),
            structured_memory=self.memory_manager.structured_memory.to_dict(),
        )
    
    async def check_connectivity(self) -> ConnectivityStatus:
        """Check connectivity to all integrated services.
        
        Returns:
            ConnectivityStatus with health check results
        """
        return ConnectivityStatus(
            ollama_health=await check_ollama_health(),
            agentcore_memory=self.memory_manager.agentcore_client is not None,
        )


def create_glitch_agent(
    session_id: Optional[str] = None,
    memory_id: Optional[str] = None,
    region: Optional[str] = None,
    window_size: int = 20,
) -> GlitchAgent:
    """Factory function to create a Glitch agent instance.
    
    Args:
        session_id: Session identifier (defaults to env or generated UUID)
        memory_id: Memory identifier (defaults to env or generated)
        region: AWS region (defaults to env or us-west-2)
        window_size: Sliding window size for conversation history
    
    Returns:
        Configured GlitchAgent instance
    """
    import uuid
    
    config = AgentConfig(
        session_id=session_id or os.getenv("GLITCH_SESSION_ID", str(uuid.uuid4())),
        memory_id=memory_id or os.getenv("GLITCH_MEMORY_ID", f"glitch-memory-{uuid.uuid4()}"),
        region=region or os.getenv("AWS_REGION", "us-west-2"),
        window_size=window_size,
    )
    
    return GlitchAgent(config)
