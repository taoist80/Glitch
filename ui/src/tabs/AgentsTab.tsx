import { useEffect } from 'react';
import { RefreshCw, Bot, Palette } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function AgentsTab() {
  const {
    status,
    agents,
    agentsLoading,
    agentsError,
    fetchAgents,
    modes,
    modesLoading,
    fetchModes,
    sessionAgent,
    sessionAgentLoading,
    sessionAgentError,
    fetchSessionAgent,
    putSessionAgent,
    putSessionMode,
    fetchStatus,
  } = useAppStore();

  const sessionId = status?.session_id || '';

  useEffect(() => {
    fetchAgents();
    fetchModes();
  }, [fetchAgents, fetchModes]);

  useEffect(() => {
    if (sessionId) {
      fetchSessionAgent(sessionId);
    }
  }, [sessionId, fetchSessionAgent]);

  const handleRefresh = () => {
    if (sessionId) fetchStatus().then(() => fetchSessionAgent(sessionId));
    fetchAgents();
    fetchModes();
  };

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Bot size={24} />
            Agents
          </h2>
          <p className="text-sm text-base-content/60">
            Agent registry: choose chat agent (Glitch, Mistral, LLaVA) and mode (Default, Poet) for this session
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={handleRefresh}
          disabled={agentsLoading || sessionAgentLoading}
        >
          <RefreshCw size={18} className={agentsLoading || sessionAgentLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {(agentsError || sessionAgentError) && (
        <div className="alert alert-error mb-4">
          <span>{agentsError || sessionAgentError}</span>
        </div>
      )}

      {!sessionId && (
        <div className="alert alert-warning mb-4">
          <span>Load status to get session ID; then you can set agent and mode.</span>
        </div>
      )}

      {sessionAgentLoading && !sessionAgent ? (
        <div className="flex justify-center py-4">
          <span className="loading loading-spinner loading-lg" />
        </div>
      ) : (
        <div className="space-y-6">
          <div className="card bg-base-200">
            <div className="card-body">
              <h3 className="card-title text-base">Current session</h3>
              <p className="text-sm text-base-content/60 font-mono break-all">{sessionId || '—'}</p>
              {sessionAgent && (
                <div className="flex flex-wrap gap-2 mt-2">
                  <span className="badge badge-primary">Agent: {sessionAgent.agent_id}</span>
                  <span className="badge badge-secondary">Mode: {sessionAgent.mode_id}</span>
                </div>
              )}
            </div>
          </div>

          {agents ? (
            <div className="card bg-base-200">
              <div className="card-body">
                <h3 className="card-title text-base flex items-center gap-2">
                  <Bot size={18} />
                  Agent
                </h3>
                <p className="text-sm text-base-content/60 mb-3">
                  Select which agent handles this session.
                </p>
                <div className="flex flex-wrap gap-2">
                  {agents.agents.map((agent) => (
                    <button
                      key={agent.id}
                      className={`btn btn-sm ${
                        sessionAgent?.agent_id === agent.id ? 'btn-primary' : 'btn-ghost'
                      }`}
                      onClick={() => sessionId && putSessionAgent(sessionId, agent.id)}
                      disabled={!sessionId}
                    >
                      {agent.name}
                      {agent.is_default && (
                        <span className="badge badge-ghost badge-xs ml-1">default</span>
                      )}
                    </button>
                  ))}
                </div>
                {agents.agents.length > 0 && (
                  <div className="mt-3 space-y-2">
                    {agents.agents.map((agent) => (
                      <div key={agent.id} className="text-sm text-base-content/70">
                        <span className="font-medium">{agent.name}</span>
                        {agent.description && ` — ${agent.description}`}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : agentsLoading ? (
            <div className="flex justify-center py-4">
              <span className="loading loading-spinner loading-lg" />
            </div>
          ) : null}

          {modes ? (
            <div className="card bg-base-200">
              <div className="card-body">
                <h3 className="card-title text-base flex items-center gap-2">
                  <Palette size={18} />
                  Mode
                </h3>
                <p className="text-sm text-base-content/60 mb-3">
                  Personality mode (e.g. Poet) applied to the selected agent.
                </p>
                <div className="flex flex-wrap gap-2">
                  {modes.modes.map((mode) => (
                    <button
                      key={mode.id}
                      className={`btn btn-sm ${
                        sessionAgent?.mode_id === mode.id ? 'btn-primary' : 'btn-ghost'
                      }`}
                      onClick={() => sessionId && putSessionMode(sessionId, mode.id)}
                      disabled={!sessionId}
                    >
                      {mode.name}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          ) : modesLoading ? (
            <div className="flex justify-center py-4">
              <span className="loading loading-spinner loading-lg" />
            </div>
          ) : null}
        </div>
      )}
    </div>
  );
}
