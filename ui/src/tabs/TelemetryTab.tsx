import { useEffect } from 'react';
import { RefreshCw, BarChart3, AlertTriangle, Clock, Hash, Wrench } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import type { TelemetryHistoryEntry, PeriodAggregates } from '../types';

function formatTs(ts: number): string {
  try {
    return new Date(ts * 1000).toISOString().replace('T', ' ').slice(0, 19);
  } catch {
    return String(ts);
  }
}

function AggregatesCard({ title, agg }: { title: string; agg: PeriodAggregates }) {
  const tu = agg;
  return (
    <div className="card bg-base-200 shadow compact">
      <div className="card-body p-4">
        <h4 className="font-semibold text-sm text-primary">{title}</h4>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <span className="text-base-content/70">Invocations</span>
          <span className="font-mono">{tu.invocation_count ?? 0}</span>
          <span className="text-base-content/70">Input tokens</span>
          <span className="font-mono">{tu.input_tokens ?? 0}</span>
          <span className="text-base-content/70">Output tokens</span>
          <span className="font-mono">{tu.output_tokens ?? 0}</span>
          <span className="text-base-content/70">Total tokens</span>
          <span className="font-mono">{tu.total_tokens ?? 0}</span>
          {tu.duration_seconds != null && (
            <>
              <span className="text-base-content/70">Duration (s)</span>
              <span className="font-mono">{tu.duration_seconds}</span>
            </>
          )}
          {tu.latency_ms_avg != null && (
            <>
              <span className="text-base-content/70">Avg latency (ms)</span>
              <span className="font-mono">{tu.latency_ms_avg}</span>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

export function TelemetryTab() {
  const { telemetryData, telemetryLoading, telemetryError, fetchTelemetry } = useAppStore();

  useEffect(() => {
    fetchTelemetry();
  }, [fetchTelemetry]);

  // Extract tool usage from history
  const toolUsage: Record<string, { calls: number; successes: number; errors: number; totalTime: number }> = {};
  const skillUsage: Record<string, number> = {};
  
  if (telemetryData?.history) {
    for (const entry of telemetryData.history as TelemetryHistoryEntry[]) {
      const m = entry.metrics ?? {};
      // Count tool usage from tool_usage field
      if (m.tool_usage && typeof m.tool_usage === 'object') {
        for (const [name, stats] of Object.entries(m.tool_usage)) {
          if (!toolUsage[name]) {
            toolUsage[name] = { calls: 0, successes: 0, errors: 0, totalTime: 0 };
          }
          toolUsage[name].calls += stats.call_count ?? 0;
          toolUsage[name].successes += stats.success_count ?? 0;
          toolUsage[name].errors += stats.error_count ?? 0;
          toolUsage[name].totalTime += stats.total_time ?? 0;
        }
      }
      // Count skill usage
      if (m.skill_info?.selected_skills && Array.isArray(m.skill_info.selected_skills)) {
        for (const skill of m.skill_info.selected_skills) {
          const name = typeof skill === 'string' ? skill : skill?.name || 'unknown';
          skillUsage[name] = (skillUsage[name] || 0) + 1;
        }
      }
    }
  }

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <BarChart3 size={24} />
            Telemetry
          </h2>
          <p className="text-sm text-base-content/60">
            Invocation metrics, tool usage, and cost tracking
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fetchTelemetry()}
          disabled={telemetryLoading}
        >
          <RefreshCw size={18} className={telemetryLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {telemetryError && (
        <div className="alert alert-error mb-4">
          <span>{telemetryError}</span>
        </div>
      )}

      {telemetryLoading && !telemetryData ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner loading-lg"></span>
        </div>
      ) : telemetryData ? (
        <div className="space-y-6">
          {telemetryData.alerts.length > 0 && (
            <div className="alert alert-warning">
              <AlertTriangle size={20} />
              <div>
                <h4 className="font-semibold">Threshold alerts</h4>
                <ul className="list-disc list-inside mt-1">
                  {telemetryData.alerts.map((a, i) => (
                    <li key={i}>{a}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}

          <div>
            <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
              <Clock size={20} />
              Running totals (this hour, today, this week, this month)
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
              {Object.entries(telemetryData.running_totals).map(([period, agg]) => (
                <AggregatesCard key={period} title={period.replace(/_/g, ' ')} agg={agg} />
              ))}
            </div>
            {Object.keys(telemetryData.running_totals).length === 0 && (
              <p className="text-base-content/60 text-sm">No running totals yet.</p>
            )}
          </div>

          {/* Tool Usage Section */}
          {Object.keys(toolUsage).length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <Wrench size={20} />
                Tool Usage (from history)
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {Object.entries(toolUsage)
                  .sort(([, a], [, b]) => b.calls - a.calls)
                  .map(([tool, stats]) => (
                    <div key={tool} className="bg-base-200 rounded-lg p-3">
                      <div className="font-mono text-sm truncate mb-2" title={tool}>{tool}</div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
                        <span className="text-base-content/70">Calls</span>
                        <span className="font-mono text-primary">{stats.calls}</span>
                        <span className="text-base-content/70">Success</span>
                        <span className="font-mono text-success">{stats.successes}</span>
                        {stats.errors > 0 && (
                          <>
                            <span className="text-base-content/70">Errors</span>
                            <span className="font-mono text-error">{stats.errors}</span>
                          </>
                        )}
                        {stats.totalTime > 0 && (
                          <>
                            <span className="text-base-content/70">Time</span>
                            <span className="font-mono">{stats.totalTime.toFixed(2)}s</span>
                          </>
                        )}
                      </div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {/* Skill Usage Section */}
          {Object.keys(skillUsage).length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <BarChart3 size={20} />
                Skill Usage (from history)
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                {Object.entries(skillUsage)
                  .sort(([, a], [, b]) => b - a)
                  .map(([skill, count]) => (
                    <div key={skill} className="bg-base-200 rounded-lg p-3">
                      <div className="font-mono text-sm truncate" title={skill}>{skill}</div>
                      <div className="text-2xl font-bold text-secondary">{count}</div>
                    </div>
                  ))}
              </div>
            </div>
          )}

          {telemetryData.thresholds.length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <AlertTriangle size={20} />
                Thresholds
              </h3>
              <div className="overflow-x-auto">
                <table className="table table-sm">
                  <thead>
                    <tr>
                      <th>Metric</th>
                      <th>Period</th>
                      <th>Limit</th>
                    </tr>
                  </thead>
                  <tbody>
                    {telemetryData.thresholds.map((t, i) => (
                      <tr key={i}>
                        <td className="font-mono">{t.metric}</td>
                        <td>{t.period}</td>
                        <td className="font-mono">{t.limit}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          <div>
            <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
              <Hash size={20} />
              Recent history (newest first, max 100)
            </h3>
            <div className="bg-base-200 rounded-lg overflow-hidden">
              <div className="overflow-x-auto max-h-96 overflow-y-auto">
                <table className="table table-sm table-pin-rows">
                  <thead>
                    <tr>
                      <th>Time (UTC)</th>
                      <th>In</th>
                      <th>Out</th>
                      <th>Total</th>
                      <th>Cycles</th>
                      <th>Duration (s)</th>
                      <th>Latency (ms)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(telemetryData.history as TelemetryHistoryEntry[]).map((entry, i) => {
                      const m = entry.metrics ?? {};
                      const tu = m.token_usage ?? {};
                      return (
                        <tr key={i}>
                          <td className="text-xs whitespace-nowrap">{formatTs(entry.timestamp)}</td>
                          <td className="font-mono text-right">{tu.input_tokens ?? '—'}</td>
                          <td className="font-mono text-right">{tu.output_tokens ?? '—'}</td>
                          <td className="font-mono text-right">{tu.total_tokens ?? '—'}</td>
                          <td className="font-mono text-right">{m.cycle_count ?? '—'}</td>
                          <td className="font-mono text-right">{m.duration_seconds ?? '—'}</td>
                          <td className="font-mono text-right">{m.latency_ms ?? '—'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
            {telemetryData.history.length === 0 && (
              <p className="text-base-content/60 text-sm py-4">No telemetry history yet.</p>
            )}
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-base-content/60">
          <BarChart3 size={48} className="mx-auto mb-4 opacity-50" />
          <p>No telemetry data available</p>
        </div>
      )}
    </div>
  );
}
