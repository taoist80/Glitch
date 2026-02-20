import { useEffect } from 'react';
import { RefreshCw, Zap, ToggleLeft, ToggleRight } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function SkillsTab() {
  const { skills, skillsLoading, skillsError, fetchSkills, toggleSkill } = useAppStore();

  useEffect(() => {
    fetchSkills();
  }, [fetchSkills]);

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Zap size={24} />
            Skills
          </h2>
          <p className="text-sm text-base-content/60">
            Agent capabilities and behaviors
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fetchSkills()}
          disabled={skillsLoading}
        >
          <RefreshCw size={18} className={skillsLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {skillsError && (
        <div className="alert alert-error mb-4">
          <span>{skillsError}</span>
        </div>
      )}

      {skillsLoading && !skills ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner loading-lg"></span>
        </div>
      ) : skills ? (
        <div className="space-y-4">
          <div className="stats shadow w-full">
            <div className="stat">
              <div className="stat-figure text-primary">
                <Zap size={32} />
              </div>
              <div className="stat-title">Total Skills</div>
              <div className="stat-value">{skills.total}</div>
            </div>
            <div className="stat">
              <div className="stat-title">Enabled</div>
              <div className="stat-value text-success">
                {skills.skills.filter(s => s.enabled).length}
              </div>
            </div>
            <div className="stat">
              <div className="stat-title">Disabled</div>
              <div className="stat-value text-base-content/50">
                {skills.skills.filter(s => !s.enabled).length}
              </div>
            </div>
          </div>

          {skills.skills.length > 0 ? (
            <div className="space-y-3">
              {skills.skills.map((skill) => (
                <div key={skill.id} className="card bg-base-200">
                  <div className="card-body py-4">
                    <div className="flex items-start justify-between">
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <h3 className="font-bold">{skill.name}</h3>
                          <span className="badge badge-sm badge-ghost font-mono">
                            {skill.id}
                          </span>
                        </div>
                        <p className="text-sm text-base-content/70 mt-1">
                          {skill.description}
                        </p>
                        
                        {skill.triggers.length > 0 && (
                          <div className="mt-2">
                            <span className="text-xs text-base-content/50">Triggers:</span>
                            <div className="flex flex-wrap gap-1 mt-1">
                              {skill.triggers.map((trigger) => (
                                <span key={trigger} className="badge badge-xs badge-outline">
                                  {trigger}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                        
                        {skill.model_hints.length > 0 && (
                          <div className="mt-2">
                            <span className="text-xs text-base-content/50">Model hints:</span>
                            <div className="flex flex-wrap gap-1 mt-1">
                              {skill.model_hints.map((hint) => (
                                <span key={hint} className="badge badge-xs badge-secondary">
                                  {hint}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                      
                      <button
                        className={`btn btn-sm ${skill.enabled ? 'btn-success' : 'btn-ghost'}`}
                        onClick={() => toggleSkill(skill.id, !skill.enabled)}
                      >
                        {skill.enabled ? (
                          <ToggleRight size={20} />
                        ) : (
                          <ToggleLeft size={20} />
                        )}
                        {skill.enabled ? 'On' : 'Off'}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-base-content/60">
              <Zap size={48} className="mx-auto mb-4 opacity-50" />
              <p>No skills loaded</p>
              <p className="text-sm mt-2">
                Add skills to agent/skills/ directory
              </p>
            </div>
          )}
        </div>
      ) : (
        <div className="text-center py-8 text-base-content/60">
          <Zap size={48} className="mx-auto mb-4 opacity-50" />
          <p>No skills data available</p>
        </div>
      )}
    </div>
  );
}
