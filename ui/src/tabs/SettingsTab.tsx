import { useEffect } from 'react';
import { Settings, RefreshCw, Info } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function SettingsTab() {
  const { status, statusLoading, statusError, fetchStatus, theme, setTheme } = useAppStore();

  useEffect(() => {
    fetchStatus();
  }, [fetchStatus]);

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Settings size={24} />
            Settings
          </h2>
          <p className="text-sm text-base-content/60">
            Agent configuration and preferences
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fetchStatus()}
          disabled={statusLoading}
        >
          <RefreshCw size={18} className={statusLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {statusError && (
        <div className="alert alert-error mb-4">
          <span>{statusError}</span>
        </div>
      )}

      <div className="space-y-6">
        <div className="card bg-base-200">
          <div className="card-body">
            <h3 className="card-title text-lg">Appearance</h3>
            <div className="form-control">
              <label className="label">
                <span className="label-text">Theme</span>
              </label>
              <select
                className="select select-bordered w-full max-w-xs"
                value={theme}
                onChange={(e) => setTheme(e.target.value as 'night' | 'winter')}
              >
                <option value="night">Dark (Night)</option>
                <option value="winter">Light (Winter)</option>
              </select>
            </div>
          </div>
        </div>

        {status && (
          <div className="card bg-base-200">
            <div className="card-body">
              <h3 className="card-title text-lg flex items-center gap-2">
                <Info size={20} />
                Agent Information
              </h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <span className="text-sm text-base-content/60">Session ID</span>
                  <p className="font-mono text-sm break-all">{status.session_id}</p>
                </div>
                <div>
                  <span className="text-sm text-base-content/60">Memory ID</span>
                  <p className="font-mono text-sm break-all">{status.memory_id}</p>
                </div>
                <div>
                  <span className="text-sm text-base-content/60">Skills Loaded</span>
                  <p className="font-medium">{status.skills_loaded}</p>
                </div>
                <div>
                  <span className="text-sm text-base-content/60">MCP Servers</span>
                  <p className="font-medium">{status.mcp_servers_connected}</p>
                </div>
              </div>
            </div>
          </div>
        )}

        <div className="card bg-base-200">
          <div className="card-body">
            <h3 className="card-title text-lg">Environment Variables</h3>
            <p className="text-sm text-base-content/60 mb-4">
              Configure these environment variables to customize Glitch behavior.
            </p>
            <div className="overflow-x-auto">
              <table className="table table-sm">
                <thead>
                  <tr>
                    <th>Variable</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="font-mono text-xs">GLITCH_TELEGRAM_BOT_TOKEN</td>
                    <td className="text-sm">Telegram bot token</td>
                  </tr>
                  <tr>
                    <td className="font-mono text-xs">GLITCH_SESSION_ID</td>
                    <td className="text-sm">Override session ID</td>
                  </tr>
                  <tr>
                    <td className="font-mono text-xs">GLITCH_MEMORY_ID</td>
                    <td className="text-sm">Override memory ID</td>
                  </tr>
                  <tr>
                    <td className="font-mono text-xs">GLITCH_MAX_TURNS</td>
                    <td className="text-sm">Max agent cycles per invocation</td>
                  </tr>
                  <tr>
                    <td className="font-mono text-xs">GLITCH_MCP_CONFIG_PATH</td>
                    <td className="text-sm">Path to MCP servers YAML</td>
                  </tr>
                  <tr>
                    <td className="font-mono text-xs">GLITCH_SOUL_S3_BUCKET</td>
                    <td className="text-sm">S3 bucket for SOUL.md</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
