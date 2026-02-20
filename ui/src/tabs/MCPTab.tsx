import { useEffect } from 'react';
import { RefreshCw, Plug, CheckCircle, XCircle, Wrench } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function MCPTab() {
  const { mcpServers, mcpLoading, mcpError, fetchMCPServers } = useAppStore();

  useEffect(() => {
    fetchMCPServers();
  }, [fetchMCPServers]);

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Plug size={24} />
            MCP Servers
          </h2>
          <p className="text-sm text-base-content/60">
            Model Context Protocol integrations
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fetchMCPServers()}
          disabled={mcpLoading}
        >
          <RefreshCw size={18} className={mcpLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {mcpError && (
        <div className="alert alert-error mb-4">
          <span>{mcpError}</span>
        </div>
      )}

      {mcpLoading && !mcpServers ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner loading-lg"></span>
        </div>
      ) : mcpServers ? (
        <div className="space-y-4">
          <div className="stats shadow w-full">
            <div className="stat">
              <div className="stat-figure text-primary">
                <Plug size={32} />
              </div>
              <div className="stat-title">Connected Servers</div>
              <div className="stat-value">
                {mcpServers.servers.filter(s => s.connected).length}
              </div>
              <div className="stat-desc">of {mcpServers.servers.length} configured</div>
            </div>
            <div className="stat">
              <div className="stat-figure text-secondary">
                <Wrench size={32} />
              </div>
              <div className="stat-title">Total Tools</div>
              <div className="stat-value">{mcpServers.total_tools}</div>
              <div className="stat-desc">available</div>
            </div>
          </div>

          {mcpServers.servers.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {mcpServers.servers.map((server) => (
                <div key={server.name} className="card bg-base-200">
                  <div className="card-body">
                    <div className="flex items-center justify-between">
                      <h3 className="card-title text-lg">{server.name}</h3>
                      {server.connected ? (
                        <CheckCircle className="text-success" size={24} />
                      ) : (
                        <XCircle className="text-error" size={24} />
                      )}
                    </div>
                    
                    <div className="space-y-2">
                      <div className="flex gap-2">
                        <span className={`badge ${server.enabled ? 'badge-success' : 'badge-ghost'}`}>
                          {server.enabled ? 'Enabled' : 'Disabled'}
                        </span>
                        <span className="badge badge-outline">{server.transport}</span>
                      </div>
                      
                      {server.tools.length > 0 && (
                        <div>
                          <span className="text-sm text-base-content/60">Tools</span>
                          <div className="flex flex-wrap gap-1 mt-1">
                            {server.tools.map((tool) => (
                              <span key={tool} className="badge badge-sm badge-primary">
                                {tool}
                              </span>
                            ))}
                          </div>
                        </div>
                      )}
                      
                      {server.error && (
                        <div>
                          <span className="text-sm text-base-content/60">Error</span>
                          <p className="text-error text-sm">{server.error}</p>
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-base-content/60">
              <Plug size={48} className="mx-auto mb-4 opacity-50" />
              <p>No MCP servers configured</p>
              <p className="text-sm mt-2">
                Add servers to mcp_servers.yaml
              </p>
            </div>
          )}
        </div>
      ) : (
        <div className="text-center py-8 text-base-content/60">
          <Plug size={48} className="mx-auto mb-4 opacity-50" />
          <p>No MCP data available</p>
        </div>
      )}
    </div>
  );
}
