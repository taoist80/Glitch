import { useEffect } from 'react';
import { Layout } from './components/Layout';
import { ChatTab } from './tabs/ChatTab';
import { AgentsTab } from './tabs/AgentsTab';
import { TelegramTab } from './tabs/TelegramTab';
import { OllamaTab } from './tabs/OllamaTab';
import { MemoryTab } from './tabs/MemoryTab';
import { TelemetryTab } from './tabs/TelemetryTab';
import { MCPTab } from './tabs/MCPTab';
import { SkillsTab } from './tabs/SkillsTab';
import { UnifiTab } from './tabs/UnifiTab';
import { ProtectTab } from './tabs/ProtectTab';
import { PiholeTab } from './tabs/PiholeTab';
import { SettingsTab } from './tabs/SettingsTab';
import { useAppStore } from './store/useAppStore';

function App() {
  const { activeTab, theme, fetchStatus } = useAppStore();

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
  }, [theme]);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  const renderTab = () => {
    switch (activeTab) {
      case 'chat':
        return <ChatTab />;
      case 'agents':
        return <AgentsTab />;
      case 'telegram':
        return <TelegramTab />;
      case 'ollama':
        return <OllamaTab />;
      case 'memory':
        return <MemoryTab />;
      case 'telemetry':
        return <TelemetryTab />;
      case 'mcp':
        return <MCPTab />;
      case 'skills':
        return <SkillsTab />;
      case 'unifi':
        return <UnifiTab />;
      case 'protect':
        return <ProtectTab />;
      case 'pihole':
        return <PiholeTab />;
      case 'settings':
        return <SettingsTab />;
      default:
        return <ChatTab />;
    }
  };

  return (
    <Layout>
      {renderTab()}
    </Layout>
  );
}

export default App;
