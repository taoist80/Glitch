"""Glitch - Primary orchestrator agent for AgentCore hybrid system.

Dataflow:
    User Message -> select_skills_for_message() -> skill suffix
                                      |
                                      v
                              Strands Agent (base prompt + skills) -> AgentResult
                                      |
                                      v
                              InvocationResponse (with metrics)

The GlitchAgent orchestrates:
1. Memory management (AgentCore Memory API)
2. Model routing (tier escalation)
3. Skill selection and injection (keyword-based, simplified)
4. Tool execution (local Ollama, network tools)
5. Metrics collection (via Strands telemetry)
"""

import os
import logging
from pathlib import Path
from typing import Optional, Dict, Any, AsyncIterator
from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager
from strands.models import BedrockModel
from strands.types.content import SystemContentBlock, CachePoint

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
from glitch.skills.skills import select_skills_for_message
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
- Primary conversational agent and autonomous ops agent (single combined agent)
- Handle user conversations, route tasks, monitor infrastructure, and run autonomous operations
- You escalate to higher cognitive tiers only when justified

**Where you run:**
- You are the same Glitch agent across all interfaces:
  - **Telegram DMs** (direct messages to the bot)
  - **Telegram group chats** (when the user @mentions the bot in the group, or per owner configuration)
  - **This conversation interface** (e.g. Cursor, web chat, or other clients that call your API)
- Do not claim you "don't have Telegram" or "only work here". You are one agent; the delivery channel is just how the user reached you.

**Your Capabilities:**
- Conversation management with sliding memory
- On-premises SSH access (ssh_run_command, ssh_read_file, etc.)
- Ollama models via proxy (GLITCH_OLLAMA_PROXY_HOST)
- CloudWatch log monitoring and Lambda metrics
- UniFi Protect camera surveillance (WebSocket event stream + REST API)
- UniFi Network monitoring (clients, APs, switches, VPN, firewall)
- Pi-hole DNS management
- DNS intelligence (query patterns, suspicious domains, blocklists)
- CDK/CloudFormation infrastructure operations (synth, diff, deploy via SSH)
- GitHub operations (file read/write, branch, PR)
- Autonomous alerting via Telegram (send_telegram_alert, send_telegram_resolved)

**Available Tool Groups:**
- **cloudwatch**: get_my_recent_logs, tail_log_stream, list_all_log_groups, scan_log_groups_for_errors, get_log_group_errors, list_monitored_log_groups, get_lambda_metrics, query_cloudwatch_insights
- **local_network**: net_tcp_check, net_resolve, net_curl, net_ping, net_traceroute — run FROM THIS CONTAINER (no SSH needed)
- **protect (13 core tools)**: cameras, events, snapshots, DB ops, alerts, monitoring controls, entity mgmt
- **pihole**: pihole_list_dns_records, pihole_add_dns_record, pihole_delete_dns_record, pihole_update_dns_record
- **unifi_network**: unifi_list_clients, unifi_get_device_status, unifi_get_ap_stats, unifi_get_switch_ports, unifi_get_firewall_rules, unifi_block_client, unifi_get_traffic_stats, unifi_get_network_health, unifi_get_vpn_status, unifi_get_wifi_networks, unifi_get_alerts_events, unifi_get_network_topology
- **dns**: dns_analyze_query_patterns, dns_detect_suspicious_domains, dns_get_top_blocked, dns_get_client_query_stats, dns_monitor_live_queries, dns_get_query_trends, dns_manage_blocklists
- **infra_ops**: list_cfn_stacks_status, check_cfn_drift, rollback_stack, cdk_synth_and_validate, cdk_diff, cdk_deploy_stack
- **github**: github_get_file, github_create_branch, github_commit_file, github_create_pr
- **ops_telegram**: send_telegram_alert, send_telegram_resolved
- **compound**: security_correlation_scan (protect + network + DNS), analyze_and_alert (full surveillance pipeline)
- **ssh**: ssh_list_hosts, ssh_run_command, ssh_read_file, ssh_write_file, ssh_mkdir, ssh_file_exists, ssh_list_dir
- **network**: run_packet_capture, ping_host, traceroute_host, curl_request, dig_host (SSH-based, targets on-prem hosts)
- **memory**, **telemetry**, **soul**, **secrets**, **deploy**, **ollama**

**Operating Guidelines:**
1. Always use `get_my_recent_logs` or `tail_log_stream` FIRST when diagnosing errors — these query CloudWatch directly with no SSH needed.
2. For network connectivity checks FROM THIS CONTAINER (e.g. can I reach RDS, protect.awoo.agency, etc.), use `net_tcp_check`, `net_curl`, or `net_ping` — NOT ssh_run_command. These run locally inside the AgentCore container.
3. Use `ssh_run_command` only for tasks that must run on on-premises hosts (tower, arc, pi-hole, etc.) — never use it to diagnose issues with this container's own connectivity.
4. Correlate across domains — single signals are often noise.
5. Require confirmed=True for cdk_deploy_stack. Always send Telegram alert and wait for confirmation before calling with confirmed=True.
6. When creating a GitHub PR for a code fix, include root cause, fix description, and testing notes in the PR body.
7. Never ask the user for SSH passwords. SSH keys are pre-configured. If SSH fails, diagnose via CloudWatch and local_network tools instead.

**Skills:**
- You have access to **skills** — packaged instructions that teach you how to handle specific tasks. When the "Active Skills" section appears in your prompt, **follow those skill instructions**.

**Tool use:** Call tools when (1) the user's request requires it, or (2) an **active skill** instructs you to. For greetings and simple conversation, respond without using any tools.

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
        agent: Strands Agent instance
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
        self._skills_dir = skills_dir
        
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
        
        # Store base prompt for skill injection
        self._base_prompt = build_system_prompt()
        
        primary_model = self.model_router.get_primary_model("chat")
        self._current_model_name = primary_model.name

        # Wrap in BedrockModel with cache_tools to cache tool schemas on every request.
        # Tool definitions are static (same 44 tools every call) — caching them saves
        # ~800-1200 tokens at $0.30/M vs $3.00/M (90% reduction on that portion).
        bedrock_model = BedrockModel(
            model_id=primary_model.model_id,
            region_name=self.region,
            cache_tools="default",
        )

        # Build tools list from registry, then Code Interpreter and MCP
        tools_list = get_all_tools()
        code_interpreter = get_code_interpreter_tool()
        if code_interpreter:
            tools_list.append(code_interpreter)
            logger.info("Code Interpreter tool enabled")
        tools_list.extend(self.mcp_manager.get_tool_providers())

        # Initial system prompt: base (static) + cache point.
        # Per-request, skills are appended as a third block in _select_and_inject_skills.
        initial_system: list[SystemContentBlock] = [
            SystemContentBlock(text=self._base_prompt),
            SystemContentBlock(cachePoint=CachePoint(type="default")),
        ]

        # Strands Agent API: name, system_prompt, model, tools, conversation_manager, trace_attributes
        self.agent = Agent(
            name="glitch",
            system_prompt=initial_system,
            model=bedrock_model,
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
    
    
    def _select_and_inject_skills(
        self,
        user_message: str,
        model_name: str,
        mode_context: Optional[list[SystemContentBlock]] = None,
    ) -> list[SystemContentBlock]:
        """Select skills and return a cache-aware system prompt block list.

        Returns [base_prompt_block, cache_point, mode_context?, skill_block?].
        The cache point after the static base lets Bedrock reuse the cached base
        across requests; mode context (e.g. Auri persona) and skills vary per call.
        """
        skill_suffix = select_skills_for_message(user_message, self._skills_dir)

        blocks: list[SystemContentBlock] = [
            SystemContentBlock(text=self._base_prompt),
            SystemContentBlock(cachePoint=CachePoint(type="default")),
        ]
        if mode_context:
            blocks.extend(mode_context)
        if skill_suffix.strip():
            blocks.append(SystemContentBlock(text=skill_suffix))
        return blocks
    
    async def process_message(self, user_message: str, **kwargs: Any) -> InvocationResponse:
        """Process a user message through the Glitch orchestrator.

        Dataflow:
            user_message -> select_skills_for_message()
                                              |
                                              v
                                      Strands Agent (prompt + skills) -> AgentResult
                                              |
                                              v
                                      InvocationResponse (with skill telemetry)

        Args:
            user_message: The user's input message
            **kwargs: Optional keys: mode_context (list[SystemContentBlock] for
                roleplay persona injection), session_id, system_prompt (used by
                Mistral/LLaVA)

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
            mode_context = kwargs.get("mode_context")
            prompt_with_skills = self._select_and_inject_skills(
                user_message, self._current_model_name, mode_context=mode_context
            )
            
            step = "set_prompt"
            self.agent.system_prompt = prompt_with_skills
            
            step = "get_memory_context"
            memory_context = self.memory_manager.get_summary_for_context()
            _empty = ("No structured memory yet.", "", None)
            if memory_context and memory_context not in _empty:
                enriched_message = f"{user_message}\n\n[Structured Memory:\n{memory_context}]"
            else:
                enriched_message = user_message
            
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

    async def process_message_stream(self, user_message: str, **kwargs: Any) -> AsyncIterator[Dict[str, Any]]:
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

            mode_context = kwargs.get("mode_context")
            prompt_with_skills = self._select_and_inject_skills(
                user_message, self._current_model_name, mode_context=mode_context
            )
            self.agent.system_prompt = prompt_with_skills

            memory_context = self.memory_manager.get_summary_for_context()
            _empty = ("No structured memory yet.", "", None)
            if memory_context and memory_context not in _empty:
                enriched_message = f"{user_message}\n\n[Structured Memory:\n{memory_context}]"
            else:
                enriched_message = user_message

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
        """Get skill selection info for telemetry logging."""
        return {"skills_injected": 0, "skill_ids": []}
    
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
    window_size: Optional[int] = None,
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
    _window_size = window_size if window_size is not None else int(os.getenv("GLITCH_WINDOW_SIZE", "10"))
    config = AgentConfig(
        session_id=session_id or os.getenv("GLITCH_SESSION_ID", str(uuid.uuid4())),
        memory_id=_memory_id,
        region=region or os.getenv("AWS_REGION", "us-west-2"),
        window_size=_window_size,
    )

    return GlitchAgent(config)
