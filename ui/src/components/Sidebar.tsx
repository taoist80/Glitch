import {
  MessageSquare,
  Send,
  Server,
  Brain,
  BarChart3,
  Plug,
  Zap,
  Bot,
  Camera,
  Settings,
  ChevronLeft,
  ChevronRight,
  Sun,
  Moon,
} from 'lucide-react';
import { LionIcon } from './LionIcon';
import type { Tab } from '../types';
import { useAppStore } from '../store/useAppStore';

interface NavItem {
  id: Tab;
  label: string;
  icon: React.ReactNode;
  badge?: string;
}

const navItems: NavItem[] = [
  { id: 'chat', label: 'Chat', icon: <MessageSquare size={20} /> },
  { id: 'agents', label: 'Agents', icon: <Bot size={20} /> },
  { id: 'telegram', label: 'Telegram', icon: <Send size={20} /> },
  { id: 'ollama', label: 'Ollama', icon: <Server size={20} /> },
  { id: 'memory', label: 'Memory', icon: <Brain size={20} /> },
  { id: 'telemetry', label: 'Telemetry', icon: <BarChart3 size={20} /> },
  { id: 'mcp', label: 'MCP', icon: <Plug size={20} /> },
  { id: 'skills', label: 'Skills', icon: <Zap size={20} /> },
  { id: 'protect', label: 'Protect', icon: <Camera size={20} /> },
  { id: 'auri', label: 'Auri', icon: <LionIcon size={20} /> },
  { id: 'settings', label: 'Settings', icon: <Settings size={20} /> },
];

export function Sidebar() {
  const { 
    activeTab, 
    setActiveTab, 
    sidebarCollapsed, 
    setSidebarCollapsed,
    theme,
    setTheme,
    connected,
  } = useAppStore();

  return (
    <aside
      className={`bg-base-200 flex flex-col h-full transition-all duration-300 ${
        sidebarCollapsed ? 'w-16' : 'w-64'
      }`}
    >
      <div className="p-4 flex items-center justify-between border-b border-base-300">
        {!sidebarCollapsed && (
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center">
              <span className="text-primary-content font-bold text-lg">G</span>
            </div>
            <div>
              <h1 className="font-bold text-lg">Glitch</h1>
              <div className="flex items-center gap-1">
                <div className={`w-2 h-2 rounded-full ${connected ? 'bg-success' : 'bg-error'}`} />
                <span className="text-xs text-base-content/60">
                  {connected ? 'Connected' : 'Disconnected'}
                </span>
              </div>
            </div>
          </div>
        )}
        <button
          className="btn btn-ghost btn-sm btn-square"
          onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
          title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
        >
          {sidebarCollapsed ? <ChevronRight size={18} /> : <ChevronLeft size={18} />}
        </button>
      </div>

      <nav className="flex-1 p-2 overflow-y-auto">
        <ul className="menu menu-sm gap-1">
          {navItems.map((item) => (
            <li key={item.id}>
              <button
                className={`flex items-center gap-3 ${
                  activeTab === item.id ? 'active' : ''
                } ${sidebarCollapsed ? 'justify-center' : ''}`}
                onClick={() => setActiveTab(item.id)}
                title={sidebarCollapsed ? item.label : undefined}
              >
                {item.icon}
                {!sidebarCollapsed && (
                  <>
                    <span className="flex-1">{item.label}</span>
                    {item.badge && (
                      <span className="badge badge-xs badge-secondary">{item.badge}</span>
                    )}
                  </>
                )}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="p-2 border-t border-base-300">
        <button
          className={`btn btn-ghost btn-sm w-full ${sidebarCollapsed ? 'btn-square' : ''}`}
          onClick={() => setTheme(theme === 'night' ? 'winter' : 'night')}
          title={theme === 'night' ? 'Switch to light mode' : 'Switch to dark mode'}
        >
          {theme === 'night' ? <Sun size={18} /> : <Moon size={18} />}
          {!sidebarCollapsed && (
            <span className="ml-2">{theme === 'night' ? 'Light Mode' : 'Dark Mode'}</span>
          )}
        </button>
      </div>
    </aside>
  );
}
