import type {
  StatusResponse,
  TelegramConfig,
  OllamaHealth,
  MemorySummary,
  TelemetryData,
  MCPServersResponse,
  SkillsResponse,
  InvocationResponse,
} from '../types';

const API_BASE = '/api';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options?.headers,
      },
    });
  } catch (networkError) {
    const msg =
      networkError instanceof TypeError && (networkError as Error).message === 'Failed to fetch'
        ? 'Cannot reach the server. Is the agent running? In proxy mode use GLITCH_UI_MODE=proxy and ensure the deployed agent is ready.'
        : (networkError as Error).message;
    throw new Error(msg);
  }

  const text = await response.text();
  if (!response.ok) {
    try {
      const errBody = JSON.parse(text) as { error?: string };
      throw new Error(errBody?.error || text || `HTTP ${response.status}`);
    } catch (e) {
      if (e instanceof Error && e.name === 'SyntaxError') throw new Error(text || `HTTP ${response.status}`);
      throw e;
    }
  }

  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error(text || 'Invalid response');
  }

  // Check for error payload from proxy/agent (200 body with error field)
  if (data && typeof data === 'object' && 'error' in data && !('message' in (data as object))) {
    throw new Error((data as { error?: string }).error || 'Unknown error');
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

  async getTelemetry(): Promise<TelemetryData> {
    return fetchJson<TelemetryData>(`${API_BASE}/telemetry`);
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
