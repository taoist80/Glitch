"""Glitch - Primary orchestrator agent for AgentCore hybrid system.

Dataflow:
    User Message -> TaskPlanner -> TaskSpec
                                      |
                                      v
                              SkillSelector(TaskSpec, model)
                                      |
                                      v
                              List[SelectedSkill] (max 3)
                                      |
                                      v
                              build_prompt_with_skills()
                                      |
                                      v
                              Strands Agent -> AgentResult
                                      |
                                      v
                              InvocationResponse (with metrics + skill telemetry)

The GlitchAgent orchestrates:
1. Memory management (AgentCore Memory API)
2. Model routing (tier escalation)
3. Skill selection and injection
4. Tool execution (local Ollama, network tools)
5. Metrics collection (via Strands telemetry)
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, AsyncIterator
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from glitch.tools.soul_tools import load_soul_from_s3
from glitch.tools.memory_tools import set_memory_manager
from glitch.tools.registry import get_all_tools
from glitch.tools.ollama_tools import check_ollama_health
from glitch.tools.code_interpreter_tools import (
    get_code_interpreter_tool,
    is_code_interpreter_available,
)
from glitch.routing.model_router import ModelRouter
from glitch.memory.sliding_window import GlitchMemoryManager
from glitch.mcp.manager import MCPServerManager
from glitch.skills.loader import SkillLoader, get_default_skills_dir
from glitch.skills.registry import SkillRegistry
from glitch.skills.selector import SkillSelector
from glitch.skills.planner import TaskPlanner
from glitch.skills.prompt_builder import build_prompt_with_skills
from glitch.skills.types import SkillSelectionResult
from glitch.telemetry import (
    extract_metrics_from_result,
    log_invocation_metrics,
    set_last_agent_result,
    append_telemetry,
)
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
    
    When GLITCH_SOUL_S3_BUCKET is set, tries S3 first (soul.md key by default).
    Then searches local paths:
    1. agent/SOUL.md (development)
    2. /app/SOUL.md (container)
    3. ~/SOUL.md (fallback)
    
    Returns:
        Contents of SOUL.md or empty string if not found
    """
    s3_content = load_soul_from_s3()
    if s3_content:
        logger.info("Loading personality from S3")
        return s3_content

    soul_paths = [
        Path(__file__).parent.parent.parent / "SOUL.md",
        Path("/app/SOUL.md"),
        Path.home() / "SOUL.md",
    ]

    for path in soul_paths:
        if path.exists():
            logger.info("Loading personality from %s", path)
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

**Where you run:**
- You are the same Glitch agent across all interfaces. You can be reached via:
  - **Telegram DMs** (direct messages to the bot)
  - **Telegram group chats** (when the user @mentions the bot in the group, or per owner configuration)
  - **This conversation interface** (e.g. Cursor, web chat, or other clients that call your API)
- Do not claim you "don't have Telegram" or "only work here". You are one agent; the delivery channel (Telegram vs this chat) is just how the user reached you. If someone says they're not getting replies in a Telegram group, help them troubleshoot (e.g. they may need to @mention the bot in the group, or the owner may need to allow the group).

**Your Capabilities:**
- Conversation management with sliding memory
- Task routing to appropriate executors (local or cloud)
- Confidence scoring and complexity assessment
- Escalation governance (max 1 per turn, 2 per session)
- Integration with on-premises Ollama models via proxy (GLITCH_OLLAMA_PROXY_HOST)
- Delegation to Sentinel for network, camera, and DNS operations via invoke_sentinel

**Skills:**
- You have access to **skills** — packaged instructions that teach you how to handle specific tasks (e.g. telemetry, surveillance). When the "Active Skills" section appears in your prompt, **follow those skill instructions**. Each skill specifies which tools to use and how; use the tools it names. Do not substitute other tools unless the skill explicitly allows it.
- Tool names and parameters are available in your tool list; you do not need every tool described in this prompt. Prefer skill guidance for tool choice and workflow.

**Tool use:** Call tools when (1) the user's request requires it, or (2) an **active skill** instructs you to. When a skill is active, follow its instructions for which tools to use. Do not call tools on your own initiative for side tasks (e.g. telemetry, thresholds) unless the user explicitly asks. For greetings and simple conversation, respond without using any tools.

**Execution Philosophy:**
- Local-first: Prefer on-premises execution when appropriate (cost/privacy)
- Escalate only when justified: Low confidence, context pressure, or high complexity
- Maintain context: Use structured memory to preserve session state
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
        mcp_manager: MCPServerManager for external MCP server integration
        skill_registry: SkillRegistry with loaded skills
        skill_selector: SkillSelector for task-based skill selection
        task_planner: TaskPlanner for analyzing user messages
        agent: Strands Agent instance
        last_skill_selection: Last skill selection result for telemetry
    """
    
    def __init__(self, config: AgentConfig, skills_dir: Optional[Path] = None):
        """Initialize GlitchAgent with configuration.
        
        Args:
            config: AgentConfig with session_id, memory_id, region, window_size, mcp_config_path
            skills_dir: Optional path to skills directory (defaults to agent/skills/)
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
        
        # Wire up memory manager for memory tools
        set_memory_manager(self.memory_manager)
        
        self.model_router = ModelRouter(
            confidence_threshold=0.7,
            context_threshold_pct=0.7,
            max_escalations_per_turn=1,
            max_escalations_per_session=2,
        )
        
        # Initialize MCP servers
        self._init_mcp_servers(config.mcp_config_path)
        
        # Initialize skill system
        self._init_skills(skills_dir)
        
        # Store base prompt for skill injection
        self._base_prompt = build_system_prompt()
        self.last_skill_selection: Optional[SkillSelectionResult] = None
        
        primary_model = self.model_router.get_primary_model("chat")
        self._current_model_name = primary_model.name
        
        # Build tools list from registry, then Code Interpreter and MCP
        tools_list = get_all_tools()
        code_interpreter = get_code_interpreter_tool()
        if code_interpreter:
            tools_list.append(code_interpreter)
            logger.info("Code Interpreter tool enabled")
        tools_list.extend(self.mcp_manager.get_tool_providers())
        
        # Strands Agent API: name, system_prompt, model, tools, conversation_manager, trace_attributes
        self.agent = Agent(
            name="glitch",
            system_prompt=self._base_prompt,
            model=primary_model.model_id,
            tools=tools_list,
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
        logger.info(f"Loaded {len(self.skill_registry)} skills")
        mcp_status = self.mcp_manager.get_status()
        logger.info(f"Loaded {mcp_status['connected_clients']} MCP servers: {mcp_status['server_names']}")
    
    def _init_mcp_servers(self, mcp_config_path: Optional[Path] = None) -> None:
        """Initialize MCP server connections.
        
        Args:
            mcp_config_path: Optional path to MCP configuration file
        """
        try:
            self.mcp_manager = MCPServerManager(mcp_config_path)
        except Exception as e:
            logger.warning(f"Failed to initialize MCP servers: {e}")
            # Create empty manager as fallback
            from glitch.mcp.types import MCPConfig
            self.mcp_manager = MCPServerManager.__new__(MCPServerManager)
            self.mcp_manager.config = MCPConfig(servers={})
            self.mcp_manager.clients = {}
    
    def _init_skills(self, skills_dir: Optional[Path] = None) -> None:
        """Initialize the skill system.
        
        Args:
            skills_dir: Optional path to skills directory
        """
        skills_path = skills_dir or get_default_skills_dir()
        
        # Load skills (non-strict mode to gracefully handle missing/invalid skills)
        loader = SkillLoader(skills_path, strict=False)
        skills = loader.load_all()
        
        # Build registry
        self.skill_registry = SkillRegistry()
        self.skill_registry.register_all(skills)
        
        # Create selector and planner
        self.skill_selector = SkillSelector(self.skill_registry)
        self.task_planner = TaskPlanner()
    
    def _select_and_inject_skills(self, user_message: str, model_name: str) -> str:
        """Select skills for the message and build prompt with injected skills.
        
        Args:
            user_message: The user's input message
            model_name: Name of the model that will execute
            
        Returns:
            System prompt with skills injected
        """
        # Plan the task
        task_spec = self.task_planner.plan(user_message)
        
        # Select skills
        self.last_skill_selection = self.skill_selector.select(task_spec, model_name)
        
        # Log skill selection
        if self.last_skill_selection.selected:
            logger.info(
                f"Selected skills for model {model_name}: "
                f"{[s.skill_id for s in self.last_skill_selection.selected]}"
            )
            for selected in self.last_skill_selection.selected:
                reasons = [r.value for r in selected.reasons]
                logger.debug(
                    f"  {selected.skill_id}: score={selected.match_score:.2f}, "
                    f"reasons={reasons}"
                )
        
        # Build prompt with skills
        return build_prompt_with_skills(
            self._base_prompt,
            self.last_skill_selection.selected,
        )
    
    async def process_message(self, user_message: str, **kwargs: Any) -> InvocationResponse:
        """Process a user message through the Glitch orchestrator.

        Dataflow:
            user_message -> TaskPlanner -> TaskSpec
                                              |
                                              v
                                      SkillSelector(TaskSpec, model)
                                              |
                                              v
                                      build_prompt_with_skills()
                                              |
                                              v
                                      Strands Agent -> AgentResult
                                              |
                                              v
                                      InvocationResponse (with skill telemetry)

        Args:
            user_message: The user's input message
            **kwargs: Ignored (session_id, system_prompt used by Mistral/LLaVA)

        Returns:
            InvocationResponse containing message, metrics, and session info
        """
        step = "init"
        try:
            step = "create_event_user"
            await self.memory_manager.create_event(
                event_content=user_message,
                event_type=EventType.USER_MESSAGE.value,
            )
            step = "select_skills"
            prompt_with_skills = self._select_and_inject_skills(
                user_message, self._current_model_name
            )
            
            step = "set_prompt"
            self.agent.system_prompt = prompt_with_skills
            
            step = "get_memory_context"
            memory_context = self.memory_manager.get_summary_for_context()
            enriched_message = f"{user_message}\n\n[Structured Memory:\n{memory_context}]"
            
            step = "invoke_agent"
            max_turns = int(os.getenv("GLITCH_MAX_TURNS", "3"))
            run_kwargs = {} if max_turns <= 0 else {"max_turns": max_turns}
            result = self.agent(enriched_message, **run_kwargs)
            step = "set_last_result"
            set_last_agent_result(result)
            
            step = "get_skill_telemetry"
            skill_info = self._get_skill_telemetry()
            
            step = "append_telemetry"
            append_telemetry(result, skill_info=skill_info)

            step = "extract_metrics"
            metrics: InvocationMetrics = extract_metrics_from_result(result)
            
            step = "log_metrics"
            log_invocation_metrics(
                metrics=metrics,
                user_message=user_message[:100],
                response_preview=str(result)[:200],
                session_id=self.session_id,
                extra=skill_info,
            )
            
            step = "create_event_agent"
            await self.memory_manager.create_event(
                event_content=str(result),
                event_type=EventType.AGENT_RESPONSE.value,
            )
            
            step = "reset_router"
            self.model_router.reset_turn_counter()
            
            step = "build_message"
            message_text = str(result) if not isinstance(result, dict) else (result.get("message") or result.get("response") or str(result))
            
            step = "return"
            return InvocationResponse(
                message=message_text,
                session_id=self.session_id,
                memory_id=self.memory_id,
                metrics=metrics,
            )
            
        except Exception as e:
            logger.error("Error at step=%s: %s", step, e, exc_info=True)
            return create_error_response(
                error=f"step={step}: {e}",
                session_id=self.session_id,
                memory_id=self.memory_id,
            )

    async def process_message_stream(self, user_message: str) -> AsyncIterator[Dict[str, Any]]:
        """Process a user message with streaming events (AgentCore best practice).

        Yields Strands stream events (e.g. content deltas, tool use, final result).
        Caller can send chunks progressively (e.g. to Telegram) or consume the
        final event for metrics. Memory and telemetry are applied after the stream
        completes (on the final result event).

        Args:
            user_message: The user's input message.

        Yields:
            Stream events (dicts with "data", "complete", "result", etc.).
            Final event contains "result" (AgentResult) for metrics.
        """
        try:
            await self.memory_manager.create_event(
                event_content=user_message,
                event_type=EventType.USER_MESSAGE.value,
            )

            prompt_with_skills = self._select_and_inject_skills(
                user_message, self._current_model_name
            )
            self.agent.system_prompt = prompt_with_skills

            memory_context = self.memory_manager.get_summary_for_context()
            enriched_message = f"{user_message}\n\n[Structured Memory:\n{memory_context}]"

            max_turns = int(os.getenv("GLITCH_MAX_TURNS", "3"))
            invocation_state = {} if max_turns <= 0 else {"max_turns": max_turns}

            accumulated_text: str = ""
            last_result = None

            async for event in self.agent.stream_async(
                enriched_message, invocation_state=invocation_state
            ):
                if isinstance(event, dict):
                    if "data" in event:
                        accumulated_text += event.get("data") or ""
                    if "result" in event:
                        last_result = event["result"]
                    yield event

            if last_result is not None:
                set_last_agent_result(last_result)
                skill_info = self._get_skill_telemetry()
                append_telemetry(last_result, skill_info=skill_info)
                metrics: InvocationMetrics = extract_metrics_from_result(last_result)
                log_invocation_metrics(
                    metrics=metrics,
                    user_message=user_message[:100],
                    response_preview=(accumulated_text or str(last_result))[:200],
                    session_id=self.session_id,
                    extra=skill_info,
                )
                await self.memory_manager.create_event(
                    event_content=accumulated_text or str(last_result),
                    event_type=EventType.AGENT_RESPONSE.value,
                )
                self.model_router.reset_turn_counter()

        except Exception as e:
            logger.error("Error in process_message_stream: %s", e)
            yield {"error": str(e), "message": str(e)}

    def _get_skill_telemetry(self) -> Dict[str, Any]:
        """Get skill selection info for telemetry logging.
        
        Returns:
            Dictionary with skill selection details
        """
        if not self.last_skill_selection:
            return {"skills_injected": 0, "skill_ids": []}
            
        return {
            "skills_injected": len(self.last_skill_selection.selected),
            "skill_ids": [s.skill_id for s in self.last_skill_selection.selected],
            "skill_reasons": {
                s.skill_id: [r.value for r in s.reasons]
                for s in self.last_skill_selection.selected
            },
            "model_used": self.last_skill_selection.model_used,
            "total_skill_candidates": self.last_skill_selection.total_candidates,
        }
    
    def get_status(self) -> AgentStatus:
        """Get agent status and statistics.
        
        Returns:
            AgentStatus with session info, routing stats, and memory state
        """
        status = AgentStatus(
            session_id=self.session_id,
            memory_id=self.memory_id,
            routing_stats=self.model_router.get_stats(),
            structured_memory=self.memory_manager.structured_memory.to_dict(),
        )
        # Add skill info to status
        status["skills_loaded"] = len(self.skill_registry)
        if self.last_skill_selection:
            status["last_skill_selection"] = self.last_skill_selection.to_log_dict()
        # Add MCP server info to status
        status["mcp_servers"] = self.mcp_manager.get_status()
        # Add Code Interpreter availability
        status["code_interpreter_available"] = is_code_interpreter_available()
        return status
    
    async def check_connectivity(self) -> ConnectivityStatus:
        """Check connectivity to all integrated services.
        
        Returns:
            ConnectivityStatus with health check results
        """
        return ConnectivityStatus(
            ollama_health=await check_ollama_health(),
            agentcore_memory=self.memory_manager.agentcore_client is not None,
        )


# Memory ID used when no env var is set. Must match agent/.bedrock_agentcore.yaml memory_id so
# CreateEvent targets the existing AgentCore memory (AgentCore runtime does not inject MEMORY_ID).
_DEFAULT_AGENTCORE_MEMORY_ID = "Glitch_mem-IJtoBX7Ljd"


def create_glitch_agent(
    session_id: Optional[str] = None,
    memory_id: Optional[str] = None,
    region: Optional[str] = None,
    window_size: int = 20,
) -> GlitchAgent:
    """Factory function to create a Glitch agent instance.
    
    Args:
        session_id: Session identifier (defaults to env or generated UUID)
        memory_id: Memory identifier (defaults to env or _DEFAULT_AGENTCORE_MEMORY_ID; must match [a-zA-Z][a-zA-Z0-9-_]{{0,99}}-[a-zA-Z0-9]{{10}})
        region: AWS region (defaults to env or us-west-2)
        window_size: Sliding window size for conversation history
    
    Returns:
        Configured GlitchAgent instance
    """
    import uuid

    # Prefer explicit memory_id, then GLITCH_MEMORY_ID, then MEMORY_ID (set by AgentCore deploy), else use known memory from .bedrock_agentcore.yaml
    _memory_id = (
        memory_id
        or os.getenv("GLITCH_MEMORY_ID")
        or os.getenv("MEMORY_ID")
        or _DEFAULT_AGENTCORE_MEMORY_ID
    )
    config = AgentConfig(
        session_id=session_id or os.getenv("GLITCH_SESSION_ID", str(uuid.uuid4())),
        memory_id=_memory_id,
        region=region or os.getenv("AWS_REGION", "us-west-2"),
        window_size=window_size,
    )

    return GlitchAgent(config)
