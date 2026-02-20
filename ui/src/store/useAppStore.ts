import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type {
  Tab,
  StatusResponse,
  TelegramConfig,
  OllamaHealth,
  MemorySummary,
  MCPServersResponse,
  SkillsResponse,
  ChatMessage,
} from '../types';
import { api } from '../api/client';

interface AppState {
  activeTab: Tab;
  setActiveTab: (tab: Tab) => void;
  
  theme: 'night' | 'winter';
  setTheme: (theme: 'night' | 'winter') => void;
  
  sidebarCollapsed: boolean;
  setSidebarCollapsed: (collapsed: boolean) => void;
  
  connected: boolean;
  setConnected: (connected: boolean) => void;
  
  status: StatusResponse | null;
  statusLoading: boolean;
  statusError: string | null;
  fetchStatus: () => Promise<void>;
  
  telegramConfig: TelegramConfig | null;
  telegramLoading: boolean;
  telegramError: string | null;
  fetchTelegramConfig: () => Promise<void>;
  
  ollamaHealth: OllamaHealth | null;
  ollamaLoading: boolean;
  ollamaError: string | null;
  fetchOllamaHealth: () => Promise<void>;
  
  memorySummary: MemorySummary | null;
  memoryLoading: boolean;
  memoryError: string | null;
  fetchMemorySummary: () => Promise<void>;
  
  mcpServers: MCPServersResponse | null;
  mcpLoading: boolean;
  mcpError: string | null;
  fetchMCPServers: () => Promise<void>;
  
  skills: SkillsResponse | null;
  skillsLoading: boolean;
  skillsError: string | null;
  fetchSkills: () => Promise<void>;
  toggleSkill: (skillId: string, enabled: boolean) => Promise<void>;
  
  chatMessages: ChatMessage[];
  chatLoading: boolean;
  chatError: string | null;
  sendMessage: (content: string) => Promise<void>;
  clearChat: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      activeTab: 'chat',
      setActiveTab: (tab) => set({ activeTab: tab }),
      
      theme: 'night',
      setTheme: (theme) => {
        document.documentElement.setAttribute('data-theme', theme);
        set({ theme });
      },
      
      sidebarCollapsed: false,
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),
      
      connected: false,
      setConnected: (connected) => set({ connected }),
      
      status: null,
      statusLoading: false,
      statusError: null,
      fetchStatus: async () => {
        set({ statusLoading: true, statusError: null });
        try {
          const status = await api.getStatus();
          set({ status, connected: true, statusLoading: false });
        } catch (error) {
          set({ 
            statusError: error instanceof Error ? error.message : 'Failed to fetch status',
            connected: false,
            statusLoading: false,
          });
        }
      },
      
      telegramConfig: null,
      telegramLoading: false,
      telegramError: null,
      fetchTelegramConfig: async () => {
        set({ telegramLoading: true, telegramError: null });
        try {
          const config = await api.getTelegramConfig();
          set({ telegramConfig: config, telegramLoading: false });
        } catch (error) {
          set({ 
            telegramError: error instanceof Error ? error.message : 'Failed to fetch Telegram config',
            telegramLoading: false,
          });
        }
      },
      
      ollamaHealth: null,
      ollamaLoading: false,
      ollamaError: null,
      fetchOllamaHealth: async () => {
        set({ ollamaLoading: true, ollamaError: null });
        try {
          const health = await api.getOllamaHealth();
          set({ ollamaHealth: health, ollamaLoading: false });
        } catch (error) {
          set({ 
            ollamaError: error instanceof Error ? error.message : 'Failed to fetch Ollama health',
            ollamaLoading: false,
          });
        }
      },
      
      memorySummary: null,
      memoryLoading: false,
      memoryError: null,
      fetchMemorySummary: async () => {
        set({ memoryLoading: true, memoryError: null });
        try {
          const summary = await api.getMemorySummary();
          set({ memorySummary: summary, memoryLoading: false });
        } catch (error) {
          set({ 
            memoryError: error instanceof Error ? error.message : 'Failed to fetch memory summary',
            memoryLoading: false,
          });
        }
      },
      
      mcpServers: null,
      mcpLoading: false,
      mcpError: null,
      fetchMCPServers: async () => {
        set({ mcpLoading: true, mcpError: null });
        try {
          const servers = await api.getMCPServers();
          set({ mcpServers: servers, mcpLoading: false });
        } catch (error) {
          set({ 
            mcpError: error instanceof Error ? error.message : 'Failed to fetch MCP servers',
            mcpLoading: false,
          });
        }
      },
      
      skills: null,
      skillsLoading: false,
      skillsError: null,
      fetchSkills: async () => {
        set({ skillsLoading: true, skillsError: null });
        try {
          const skills = await api.getSkills();
          set({ skills, skillsLoading: false });
        } catch (error) {
          set({ 
            skillsError: error instanceof Error ? error.message : 'Failed to fetch skills',
            skillsLoading: false,
          });
        }
      },
      toggleSkill: async (skillId, enabled) => {
        try {
          await api.toggleSkill(skillId, enabled);
          await get().fetchSkills();
        } catch (error) {
          set({ 
            skillsError: error instanceof Error ? error.message : 'Failed to toggle skill',
          });
        }
      },
      
      chatMessages: [],
      chatLoading: false,
      chatError: null,
      sendMessage: async (content) => {
        const userMessage: ChatMessage = {
          id: crypto.randomUUID(),
          role: 'user',
          content,
          timestamp: new Date(),
        };
        
        set((state) => ({
          chatMessages: [...state.chatMessages, userMessage],
          chatLoading: true,
          chatError: null,
        }));
        
        try {
          const response = await api.sendMessage(content);
          
          // Handle metrics safely - they may be missing or have different structure
          const metrics = response.metrics ? {
            duration_seconds: response.metrics.duration_seconds ?? 0,
            token_usage: response.metrics.token_usage ?? {
              input_tokens: 0,
              output_tokens: 0,
              total_tokens: 0,
            },
            cycle_count: response.metrics.cycle_count ?? 0,
          } : undefined;
          
          const assistantMessage: ChatMessage = {
            id: crypto.randomUUID(),
            role: 'assistant',
            content: response.message || String(response),
            timestamp: new Date(),
            metrics,
          };
          
          set((state) => ({
            chatMessages: [...state.chatMessages, assistantMessage],
            chatLoading: false,
          }));
        } catch (error) {
          set({ 
            chatError: error instanceof Error ? error.message : 'Failed to send message',
            chatLoading: false,
          });
        }
      },
      clearChat: () => set({ chatMessages: [], chatError: null }),
    }),
    {
      name: 'glitch-ui-storage',
      partialize: (state) => ({
        theme: state.theme,
        sidebarCollapsed: state.sidebarCollapsed,
        activeTab: state.activeTab,
      }),
    }
  )
);
