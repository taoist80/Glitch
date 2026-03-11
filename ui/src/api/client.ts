import type {
  StatusResponse,
  TelegramConfig,
  OllamaHealth,
  MemorySummary,
  TelemetryData,
  MCPServersResponse,
  SkillsResponse,
  SkillToggleResponse,
  AgentsResponse,
  SessionAgentResponse,
  SessionModeResponse,
  ModesResponse,
  InvocationResponse,
  StreamingInfo,
  StreamEvent,
  ProtectCamerasResponse,
  ProtectEntitiesResponse,
  ProtectEventsResponse,
  ProtectAlertsResponse,
  ProtectSummary,
  ProtectHealth,
  ProtectPatrolsResponse,
  ProtectScanResult,
  ProtectBackfillResult,
} from '../types';

// API base URL: use environment variable for Lambda Function URL, or default to relative path
// In production, set VITE_API_BASE_URL to the Lambda Function URL
const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api';
const INVOCATIONS_BASE = import.meta.env.VITE_API_BASE_URL || '';

// Generate a unique client ID for session tracking
const CLIENT_ID = localStorage.getItem('glitch_client_id') || (() => {
  const id = `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
  localStorage.setItem('glitch_client_id', id);
  return id;
})();

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        'X-Client-Id': CLIENT_ID,
        ...options?.headers,
      },
    });
  } catch (networkError) {
    const msg =
      networkError instanceof TypeError && (networkError as Error).message === 'Failed to fetch'
        ? 'Cannot reach the server. Is the agent running?'
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

  async getProtectSummary(): Promise<ProtectSummary> {
    return fetchJson<ProtectSummary>(`${API_BASE}/protect/summary`);
  },

  async getProtectCameras(params?: { limit?: number }): Promise<ProtectCamerasResponse> {
    const q = params?.limit != null ? `?limit=${params.limit}` : '';
    return fetchJson<ProtectCamerasResponse>(`${API_BASE}/protect/cameras${q}`);
  },

  async getProtectEntities(params?: { limit?: number }): Promise<ProtectEntitiesResponse> {
    const q = params?.limit != null ? `?limit=${params.limit}` : '';
    return fetchJson<ProtectEntitiesResponse>(`${API_BASE}/protect/entities${q}`);
  },

  async getProtectEvents(params?: { hours?: number; days?: number; limit?: number }): Promise<ProtectEventsResponse> {
    const sp = new URLSearchParams();
    if (params?.days != null) sp.set('days', String(params.days));
    else if (params?.hours != null) sp.set('hours', String(params.hours));
    if (params?.limit != null) sp.set('limit', String(params.limit));
    const q = sp.toString() ? `?${sp}` : '';
    return fetchJson<ProtectEventsResponse>(`${API_BASE}/protect/events${q}`);
  },

  async getProtectAlerts(params?: { limit?: number; unack_only?: boolean }): Promise<ProtectAlertsResponse> {
    const sp = new URLSearchParams();
    if (params?.limit != null) sp.set('limit', String(params.limit));
    if (params?.unack_only === true) sp.set('unack_only', '1');
    const q = sp.toString() ? `?${sp}` : '';
    return fetchJson<ProtectAlertsResponse>(`${API_BASE}/protect/alerts${q}`);
  },

  async getProtectHealth(): Promise<ProtectHealth> {
    return fetchJson<ProtectHealth>(`${API_BASE}/protect/health`);
  },

  async getSentinelHealth(): Promise<ProtectHealth> {
    return this.getProtectHealth();
  },

  async getProtectPatrols(params?: { hours?: number; limit?: number }): Promise<ProtectPatrolsResponse> {
    const sp = new URLSearchParams();
    if (params?.hours != null) sp.set('hours', String(params.hours));
    if (params?.limit != null) sp.set('limit', String(params.limit));
    const q = sp.toString() ? `?${sp}` : '';
    return fetchJson<ProtectPatrolsResponse>(`${API_BASE}/protect/patrols${q}`);
  },

  async triggerProtectScan(): Promise<ProtectScanResult> {
    return fetchJson<ProtectScanResult>(`${API_BASE}/protect/scan`, { method: 'POST' });
  },

  async triggerProtectBackfill(days?: number): Promise<ProtectBackfillResult> {
    const sp = days != null ? `?days=${days}` : '';
    return fetchJson<ProtectBackfillResult>(`${API_BASE}/protect/backfill${sp}`, { method: 'POST' });
  },

  async getMCPServers(): Promise<MCPServersResponse> {
    return fetchJson<MCPServersResponse>(`${API_BASE}/mcp/servers`);
  },

  async getSkills(): Promise<SkillsResponse> {
    return fetchJson<SkillsResponse>(`${API_BASE}/skills`);
  },

  async toggleSkill(skillId: string, enabled: boolean): Promise<SkillToggleResponse> {
    return fetchJson<SkillToggleResponse>(`${API_BASE}/skills/${skillId}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    });
  },

  async getAgents(): Promise<AgentsResponse> {
    return fetchJson<AgentsResponse>(`${API_BASE}/agents`);
  },

  async getSessionAgent(sessionId: string): Promise<SessionAgentResponse> {
    return fetchJson<SessionAgentResponse>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/agent`);
  },

  async putSessionAgent(sessionId: string, agentId: string): Promise<SessionAgentResponse> {
    return fetchJson<SessionAgentResponse>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/agent`, {
      method: 'PUT',
      body: JSON.stringify({ agent_id: agentId }),
    });
  },

  async getSessionMode(sessionId: string): Promise<SessionModeResponse> {
    return fetchJson<SessionModeResponse>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/mode`);
  },

  async putSessionMode(sessionId: string, modeId: string): Promise<SessionModeResponse> {
    return fetchJson<SessionModeResponse>(`${API_BASE}/sessions/${encodeURIComponent(sessionId)}/mode`, {
      method: 'PUT',
      body: JSON.stringify({ mode_id: modeId }),
    });
  },

  async getModes(): Promise<ModesResponse> {
    return fetchJson<ModesResponse>(`${API_BASE}/modes`);
  },

  async sendMessage(prompt: string, opts?: { session_id?: string; agent_id?: string; mode_id?: string }): Promise<InvocationResponse> {
    return fetchJson<InvocationResponse>(`${INVOCATIONS_BASE}/invocations`, {
      method: 'POST',
      body: JSON.stringify({ prompt, ...opts }),
    });
  },

  async getStreamingInfo(): Promise<StreamingInfo> {
    return fetchJson<StreamingInfo>(`${API_BASE}/streaming-info`);
  },

  async *sendMessageStream(prompt: string): AsyncGenerator<StreamEvent, void, unknown> {
    const response = await fetch(`${INVOCATIONS_BASE}/invocations`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Client-Id': CLIENT_ID,
      },
      body: JSON.stringify({ prompt, stream: true }),
    });

    if (!response.ok) {
      const text = await response.text();
      yield { type: 'error', error: text || `HTTP ${response.status}` };
      return;
    }

    if (!response.body) {
      yield { type: 'error', error: 'No response body for streaming' };
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const event = JSON.parse(line) as StreamEvent;
            yield event;
          } catch {
            yield { type: 'text', data: line };
          }
        }
      }

      if (buffer.trim()) {
        try {
          const event = JSON.parse(buffer) as StreamEvent;
          yield event;
        } catch {
          yield { type: 'text', data: buffer };
        }
      }
    } finally {
      reader.releaseLock();
    }
  },

  getClientId(): string {
    return CLIENT_ID;
  },
};
