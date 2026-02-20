import { useEffect } from 'react';
import { RefreshCw, Server, CheckCircle, XCircle } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function OllamaTab() {
  const { ollamaHealth, ollamaLoading, ollamaError, fetchOllamaHealth } = useAppStore();

  useEffect(() => {
    fetchOllamaHealth();
  }, [fetchOllamaHealth]);

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Server size={24} />
            Ollama
          </h2>
          <p className="text-sm text-base-content/60">
            Local model health and status
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fetchOllamaHealth()}
          disabled={ollamaLoading}
        >
          <RefreshCw size={18} className={ollamaLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {ollamaError && (
        <div className="alert alert-error mb-4">
          <span>{ollamaError}</span>
        </div>
      )}

      {ollamaLoading && !ollamaHealth ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner loading-lg"></span>
        </div>
      ) : ollamaHealth ? (
        <div className="space-y-4">
          <div className="stats shadow w-full">
            <div className="stat">
              <div className="stat-title">Overall Status</div>
              <div className={`stat-value text-${ollamaHealth.all_healthy ? 'success' : 'error'}`}>
                {ollamaHealth.all_healthy ? 'Healthy' : 'Degraded'}
              </div>
              <div className="stat-desc">
                {ollamaHealth.hosts.filter(h => h.healthy).length} of {ollamaHealth.hosts.length} hosts online
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {ollamaHealth.hosts.map((host) => (
              <div key={host.name} className="card bg-base-200">
                <div className="card-body">
                  <div className="flex items-center justify-between">
                    <h3 className="card-title text-lg">{host.name}</h3>
                    {host.healthy ? (
                      <CheckCircle className="text-success" size={24} />
                    ) : (
                      <XCircle className="text-error" size={24} />
                    )}
                  </div>
                  
                  <div className="space-y-2">
                    <div>
                      <span className="text-sm text-base-content/60">Host</span>
                      <p className="font-mono">{host.host}</p>
                    </div>
                    
                    {host.healthy ? (
                      <div>
                        <span className="text-sm text-base-content/60">Models</span>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {host.models.length > 0 ? (
                            host.models.map((model) => (
                              <span key={model} className="badge badge-primary badge-sm">
                                {model}
                              </span>
                            ))
                          ) : (
                            <span className="text-sm text-base-content/60">No models loaded</span>
                          )}
                        </div>
                      </div>
                    ) : (
                      <div>
                        <span className="text-sm text-base-content/60">Error</span>
                        <p className="text-error text-sm">{host.error}</p>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-base-content/60">
          <Server size={48} className="mx-auto mb-4 opacity-50" />
          <p>No Ollama data available</p>
        </div>
      )}
    </div>
  );
}
