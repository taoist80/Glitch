export type Tab = 
  | 'chat'
  | 'telegram'
  | 'ollama'
  | 'memory'
  | 'mcp'
  | 'skills'
  | 'unifi'
  | 'pihole'
  | 'settings';

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
