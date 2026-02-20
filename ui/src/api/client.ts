import type {
  StatusResponse,
  TelegramConfig,
  OllamaHealth,
  MemorySummary,
  MCPServersResponse,
  SkillsResponse,
  InvocationResponse,
} from '../types';

const API_BASE = '/api';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  
  if (!response.ok) {
    const error = await response.text();
    throw new Error(error || `HTTP ${response.status}`);
  }
  
  const data = await response.json();
  
  // Check for error responses from the proxy/agent
  if (data && typeof data === 'object' && 'error' in data && !('message' in data)) {
    throw new Error(data.error || 'Unknown error');
  }
  
  return data as T;
}

export const api = {
  async getStatus(): Promise<StatusResponse> {
    return fetchJson<StatusResponse>(`${API_BASE}/status`);
  },

  async getTelegramConfig(): Promise<TelegramConfig> {
    return fetchJson<TelegramConfig>(`${API_BASE}/telegram/config`);
  },

  async updateTelegramConfig(config: Partial<TelegramConfig>): Promise<TelegramConfig> {
    return fetchJson<TelegramConfig>(`${API_BASE}/telegram/config`, {
      method: 'POST',
      body: JSON.stringify(config),
    });
  },

  async getOllamaHealth(): Promise<OllamaHealth> {
    return fetchJson<OllamaHealth>(`${API_BASE}/ollama/health`);
  },

  async getMemorySummary(): Promise<MemorySummary> {
    return fetchJson<MemorySummary>(`${API_BASE}/memory/summary`);
  },

  async getMCPServers(): Promise<MCPServersResponse> {
    return fetchJson<MCPServersResponse>(`${API_BASE}/mcp/servers`);
  },

  async getSkills(): Promise<SkillsResponse> {
    return fetchJson<SkillsResponse>(`${API_BASE}/skills`);
  },

  async toggleSkill(skillId: string, enabled: boolean): Promise<{ skill_id: string; enabled: boolean; message: string }> {
    return fetchJson(`${API_BASE}/skills/${skillId}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    });
  },

  async sendMessage(prompt: string): Promise<InvocationResponse> {
    return fetchJson<InvocationResponse>('/invocations', {
      method: 'POST',
      body: JSON.stringify({ prompt }),
    });
  },
};
