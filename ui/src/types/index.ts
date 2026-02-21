export type Tab =
  | 'chat'
  | 'telegram'
  | 'ollama'
  | 'memory'
  | 'telemetry'
  | 'mcp'
  | 'skills'
  | 'unifi'
  | 'pihole'
  | 'settings';

export interface TelemetryHistoryEntry {
  timestamp: number;
  metrics: {
    duration_seconds?: number;
    token_usage?: {
      input_tokens?: number;
      output_tokens?: number;
      total_tokens?: number;
      cache_read_tokens?: number;
      cache_write_tokens?: number;
    };
    cycle_count?: number;
    latency_ms?: number;
    stop_reason?: string;
    tool_usage?: Record<string, { call_count?: number; success_count?: number; error_count?: number; total_time?: number }>;
    skill_info?: {
      selected_skills?: Array<{ name?: string; score?: number } | string>;
      task_type?: string;
    };
  };
  custom_metrics?: Record<string, number>;
}

export interface PeriodAggregates {
  invocation_count: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cache_read_tokens?: number;
  cache_write_tokens?: number;
  duration_seconds?: number;
  latency_ms_total?: number;
  latency_ms_avg?: number;
  custom_metrics?: Record<string, number>;
}

export interface TelemetryThreshold {
  metric: string;
  period: string;
  limit: number;
}

export interface TelemetryData {
  history: TelemetryHistoryEntry[];
  running_totals: Record<string, PeriodAggregates>;
  thresholds: TelemetryThreshold[];
  alerts: string[];
}

export interface StatusResponse {
  session_id: string;
  memory_id: string;
  connected: boolean;
  skills_loaded: number;
  mcp_servers_connected: number;
  routing_stats: Record<string, unknown>;
  structured_memory: Record<string, unknown>;
}

export interface TelegramConfig {
  enabled: boolean;
  bot_username?: string;
  owner_id?: number;
  dm_policy: string;
  group_policy: string;
  require_mention: boolean;
  dm_allowlist: number[];
  group_allowlist: number[];
  webhook_url?: string;
  mode: string;
}

export interface OllamaHostHealth {
  name: string;
  host: string;
  healthy: boolean;
  models: string[];
  error?: string;
}

export interface OllamaHealth {
  hosts: OllamaHostHealth[];
  all_healthy: boolean;
}

export interface MemorySummary {
  session_id: string;
  memory_id: string;
  window_size: number;
  structured_memory: Record<string, unknown>;
  agentcore_connected: boolean;
  recent_events?: Array<{ role?: string; content?: string; message?: string; [key: string]: unknown }>;
}

export interface MCPServer {
  name: string;
  enabled: boolean;
  connected: boolean;
  transport: string;
  tools: string[];
  error?: string;
}

export interface MCPServersResponse {
  servers: MCPServer[];
  total_tools: number;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  enabled: boolean;
  triggers: string[];
  model_hints: string[];
  usage_count: number;
}

export interface SkillsResponse {
  skills: Skill[];
  total: number;
}

export interface SkillToggleResponse {
  skill_id: string;
  enabled: boolean;
  message: string;
}

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  metrics?: {
    duration_seconds: number;
    token_usage: {
      input_tokens: number;
      output_tokens: number;
      total_tokens: number;
    };
    cycle_count: number;
  };
}

export interface InvocationResponse {
  message: string;
  session_id: string;
  memory_id: string;
  metrics: {
    duration_seconds: number;
    token_usage: {
      input_tokens: number;
      output_tokens: number;
      total_tokens: number;
      cache_read_tokens: number;
      cache_write_tokens: number;
    };
    cycle_count: number;
    latency_ms: number;
    stop_reason: string;
    tool_usage: Record<string, {
      call_count: number;
      success_count: number;
      error_count: number;
      total_time: number;
    }>;
  };
  error?: string;
}

export interface StreamingInfo {
  streaming_enabled: boolean;
  http_streaming_supported: boolean;
  websocket_url?: string;
  session_id?: string;
  expires_in_seconds?: number;
  message: string;
}

/**
 * Event emitted during streaming responses.
 * - text: Partial text content from the agent
 * - tool_start: Tool invocation started
 * - tool_end: Tool invocation completed
 * - complete: Stream finished successfully
 * - error: An error occurred
 */
export interface StreamEvent {
  type: 'text' | 'tool_start' | 'tool_end' | 'complete' | 'error';
  data?: string;
  tool_name?: string;
  tool_input?: unknown;
  tool_result?: unknown;
  error?: string;
}
