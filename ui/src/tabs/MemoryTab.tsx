import { useEffect } from 'react';
import { RefreshCw, Brain, Database, CheckCircle, XCircle, MessageSquare } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function MemoryTab() {
  const { memorySummary, memoryLoading, memoryError, fetchMemorySummary } = useAppStore();

  useEffect(() => {
    fetchMemorySummary();
  }, [fetchMemorySummary]);

  const sm = memorySummary?.structured_memory ?? {};
  const section = (title: string, value: unknown, emptyLabel = '—') => {
    if (value === undefined || value === null) return null;
    if (Array.isArray(value) && value.length === 0)
      return (
        <div className="mb-3">
          <span className="text-primary font-medium">{title}:</span>{' '}
          <span className="text-base-content/50">{emptyLabel}</span>
        </div>
      );
    if (typeof value === 'string' && value === '')
      return (
        <div className="mb-3">
          <span className="text-primary font-medium">{title}:</span>{' '}
          <span className="text-base-content/50">{emptyLabel}</span>
        </div>
      );
    if (Array.isArray(value))
      return (
        <div className="mb-3">
          <span className="text-primary font-medium">{title}:</span>
          <ul className="list-disc list-inside mt-1 ml-2 text-sm">
            {value.map((item, i) => (
              <li key={i}>
                {typeof item === 'object' && item !== null && 'decision' in (item as object)
                  ? `${(item as { decision?: string }).decision ?? ''} (${(item as { rationale?: string }).rationale ?? ''})`
                  : String(item)}
              </li>
            ))}
          </ul>
        </div>
      );
    return (
      <div className="mb-3">
        <span className="text-primary font-medium">{title}:</span>{' '}
        <span className="text-base-content">{String(value)}</span>
      </div>
    );
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
              <div className="bg-base-300 rounded-lg p-4 text-sm">
                {section('Session goal', sm.session_goal)}
                {section('Facts', sm.facts, 'None')}
                {section('Constraints', sm.constraints, 'None')}
                {section('Decisions', sm.decisions, 'None')}
                {section('Open questions', sm.open_questions, 'None')}
                {section('Tool results summary', sm.tool_results_summary, 'None')}
                {section('Last updated', sm.last_updated)}
              </div>
            </div>
          </div>

          {Array.isArray(memorySummary.recent_events) && memorySummary.recent_events.length > 0 && (
            <div className="card bg-base-200">
              <div className="card-body">
                <h3 className="card-title text-lg flex items-center gap-2">
                  <MessageSquare size={20} />
                  Recent conversation turns
                </h3>
                <div className="bg-base-300 rounded-lg p-4 font-mono text-sm overflow-x-auto max-h-64 overflow-y-auto">
                  <ul className="space-y-2">
                    {memorySummary.recent_events.map((ev: { role?: string; content?: string; message?: string }, i: number) => (
                      <li key={i} className="border-b border-base-content/10 pb-2 last:border-0">
                        <span className="text-primary font-medium">
                          {(ev.role ?? ev.message ?? 'message')}:
                        </span>{' '}
                        {(ev.content ?? ev.message ?? JSON.stringify(ev)).toString().slice(0, 200)}
                        {((ev.content ?? ev.message ?? '') as string).length > 200 ? '…' : ''}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>
            </div>
          )}
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
