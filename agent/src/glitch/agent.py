"""Glitch - Primary orchestrator agent for AgentCore hybrid system."""

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
from glitch.routing.model_router import ModelRouter, MODEL_REGISTRY
from glitch.memory.sliding_window import GlitchMemoryManager

logger = logging.getLogger(__name__)


def load_soul() -> str:
    """Load SOUL.md personality file."""
    soul_paths = [
        Path(__file__).parent.parent.parent / "SOUL.md",  # agent/SOUL.md
        Path("/app/SOUL.md"),  # Container path
        Path.home() / "SOUL.md",  # Home directory fallback
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
3. Escalate to Tier 2 (Sonnet 4.6) or Tier 3 (Opus 4.5) only when necessary
4. Maintain structured memory: facts, decisions, constraints, open questions
"""


def build_system_prompt() -> str:
    """Build the complete system prompt from SOUL.md + technical context."""
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
    """Main Glitch orchestrator agent."""
    
    def __init__(
        self,
        session_id: str,
        memory_id: str,
        region: str = "us-west-2",
        window_size: int = 20,
    ):
        self.session_id = session_id
        self.memory_id = memory_id
        self.region = region
        
        self.memory_manager = GlitchMemoryManager(
            session_id=session_id,
            memory_id=memory_id,
            region=region,
            window_size=window_size,
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
            conversation_manager=SlidingWindowConversationManager(window_size=window_size),
            trace_attributes={
                "agent.role": "orchestrator",
                "agent.tier": "1",
                "session.id": session_id,
                "memory.id": memory_id,
            },
        )
        
        logger.info(f"Initialized Glitch agent for session {session_id}")
    
    async def process_message(self, user_message: str) -> str:
        """
        Process a user message through the Glitch orchestrator.
        
        Args:
            user_message: User's input message
        
        Returns:
            Agent's response
        """
        try:
            await self.memory_manager.create_event(
                event_content=user_message,
                event_type="user_message",
                metadata={"source": "user"},
            )
            
            memory_context = self.memory_manager.get_summary_for_context()
            
            enriched_message = f"{user_message}\n\n[Structured Memory:\n{memory_context}]"
            
            response = self.agent(enriched_message)
            
            await self.memory_manager.create_event(
                event_content=str(response),
                event_type="agent_response",
                metadata={"source": "glitch"},
            )
            
            self.model_router.reset_turn_counter()
            
            return str(response)
            
        except Exception as e:
            logger.error(f"Error processing message: {e}")
            return f"I encountered an error processing your request: {str(e)}"
    
    def get_status(self) -> dict:
        """Get agent status and statistics."""
        return {
            "session_id": self.session_id,
            "memory_id": self.memory_id,
            "routing_stats": self.model_router.get_stats(),
            "structured_memory": self.memory_manager.structured_memory.to_dict(),
        }
    
    async def check_connectivity(self) -> dict:
        """Check connectivity to all integrated services."""
        results = {
            "ollama_health": await check_ollama_health(),
            "agentcore_memory": self.memory_manager.agentcore_client is not None,
        }
        return results


def create_glitch_agent(
    session_id: Optional[str] = None,
    memory_id: Optional[str] = None,
    region: Optional[str] = None,
) -> GlitchAgent:
    """
    Factory function to create a Glitch agent instance.
    
    Args:
        session_id: Session identifier (defaults to env or generated)
        memory_id: Memory identifier (defaults to env or generated)
        region: AWS region (defaults to env or us-west-2)
    
    Returns:
        Configured GlitchAgent instance
    """
    import uuid
    
    session_id = session_id or os.getenv("GLITCH_SESSION_ID", str(uuid.uuid4()))
    memory_id = memory_id or os.getenv("GLITCH_MEMORY_ID", f"glitch-memory-{uuid.uuid4()}")
    region = region or os.getenv("AWS_REGION", "us-west-2")
    
    return GlitchAgent(
        session_id=session_id,
        memory_id=memory_id,
        region=region,
    )
