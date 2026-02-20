import { useEffect } from 'react';
import { RefreshCw, Brain, Database, CheckCircle, XCircle } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function MemoryTab() {
  const { memorySummary, memoryLoading, memoryError, fetchMemorySummary } = useAppStore();

  useEffect(() => {
    fetchMemorySummary();
  }, [fetchMemorySummary]);

  const renderValue = (value: unknown, depth = 0): React.ReactNode => {
    if (value === null || value === undefined) {
      return <span className="text-base-content/50">null</span>;
    }
    if (typeof value === 'string') {
      return <span className="text-success">"{value}"</span>;
    }
    if (typeof value === 'number') {
      return <span className="text-info">{value}</span>;
    }
    if (typeof value === 'boolean') {
      return <span className="text-warning">{value.toString()}</span>;
    }
    if (Array.isArray(value)) {
      if (value.length === 0) {
        return <span className="text-base-content/50">[]</span>;
      }
      return (
        <div className="ml-4">
          {value.map((item, i) => (
            <div key={i} className="flex">
              <span className="text-base-content/50 mr-2">{i}:</span>
              {renderValue(item, depth + 1)}
            </div>
          ))}
        </div>
      );
    }
    if (typeof value === 'object') {
      const entries = Object.entries(value as Record<string, unknown>);
      if (entries.length === 0) {
        return <span className="text-base-content/50">{'{}'}</span>;
      }
      return (
        <div className={depth > 0 ? 'ml-4' : ''}>
          {entries.map(([key, val]) => (
            <div key={key} className="flex">
              <span className="text-primary mr-2">{key}:</span>
              {renderValue(val, depth + 1)}
            </div>
          ))}
        </div>
      );
    }
    return <span>{String(value)}</span>;
  };

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Brain size={24} />
            Memory
          </h2>
          <p className="text-sm text-base-content/60">
            Agent memory state and context
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fetchMemorySummary()}
          disabled={memoryLoading}
        >
          <RefreshCw size={18} className={memoryLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {memoryError && (
        <div className="alert alert-error mb-4">
          <span>{memoryError}</span>
        </div>
      )}

      {memoryLoading && !memorySummary ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner loading-lg"></span>
        </div>
      ) : memorySummary ? (
        <div className="space-y-4">
          <div className="stats shadow w-full">
            <div className="stat">
              <div className="stat-figure text-primary">
                <Database size={32} />
              </div>
              <div className="stat-title">Session ID</div>
              <div className="stat-value text-sm font-mono truncate max-w-xs">
                {memorySummary.session_id.slice(0, 8)}...
              </div>
            </div>
            <div className="stat">
              <div className="stat-title">Window Size</div>
              <div className="stat-value">{memorySummary.window_size}</div>
              <div className="stat-desc">conversation turns</div>
            </div>
            <div className="stat">
              <div className="stat-title">AgentCore</div>
              <div className="stat-value flex items-center gap-2">
                {memorySummary.agentcore_connected ? (
                  <CheckCircle className="text-success" size={24} />
                ) : (
                  <XCircle className="text-error" size={24} />
                )}
              </div>
              <div className="stat-desc">
                {memorySummary.agentcore_connected ? 'Connected' : 'Disconnected'}
              </div>
            </div>
          </div>

          <div className="card bg-base-200">
            <div className="card-body">
              <h3 className="card-title text-lg">Structured Memory</h3>
              <div className="bg-base-300 rounded-lg p-4 font-mono text-sm overflow-x-auto">
                {renderValue(memorySummary.structured_memory)}
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-base-content/60">
          <Brain size={48} className="mx-auto mb-4 opacity-50" />
          <p>No memory data available</p>
        </div>
      )}
    </div>
  );
}
