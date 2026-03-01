import { useEffect } from 'react';
import { RefreshCw, BarChart3, AlertTriangle, Clock, Hash, Wrench, DollarSign } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';
import type { TelemetryHistoryEntry, PeriodAggregates } from '../types';

// Claude Sonnet 4 pricing (per 1M tokens, USD) — used for cost estimates
const PRICE_INPUT_PER_M = 3.0;
const PRICE_OUTPUT_PER_M = 15.0;
const PRICE_CACHE_READ_PER_M = 0.3;
const PRICE_CACHE_WRITE_PER_M = 3.75;

function estimateCost(agg: PeriodAggregates): number {
  return (
    ((agg.input_tokens ?? 0) * PRICE_INPUT_PER_M +
      (agg.output_tokens ?? 0) * PRICE_OUTPUT_PER_M +
      (agg.cache_read_tokens ?? 0) * PRICE_CACHE_READ_PER_M +
      (agg.cache_write_tokens ?? 0) * PRICE_CACHE_WRITE_PER_M) /
    1_000_000
  );
}

function formatTs(ts: number): string {
  try {
    return new Date(ts * 1000).toISOString().replace('T', ' ').slice(0, 19);
  } catch {
    return String(ts);
  }
}

function fmtNum(n: number | undefined | null): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

function AggregatesCard({ title, agg }: { title: string; agg: PeriodAggregates }) {
  const cost = estimateCost(agg);
  return (
    <div className="card bg-base-200 shadow compact">
      <div className="card-body p-4">
        <h4 className="font-semibold text-sm text-primary capitalize">{title.replace(/_/g, ' ')}</h4>
        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
          <span className="text-base-content/70">Invocations</span>
          <span className="font-mono">{fmtNum(agg.invocation_count)}</span>
          <span className="text-base-content/70">Input tokens</span>
          <span className="font-mono">{fmtNum(agg.input_tokens)}</span>
          <span className="text-base-content/70">Output tokens</span>
          <span className="font-mono">{fmtNum(agg.output_tokens)}</span>
          {(agg.cache_read_tokens ?? 0) > 0 && (
            <>
              <span className="text-base-content/70">Cache read</span>
              <span className="font-mono text-info">{fmtNum(agg.cache_read_tokens)}</span>
            </>
          )}
          {(agg.cache_write_tokens ?? 0) > 0 && (
            <>
              <span className="text-base-content/70">Cache write</span>
              <span className="font-mono text-info">{fmtNum(agg.cache_write_tokens)}</span>
            </>
          )}
          {agg.duration_seconds != null && (
            <>
              <span className="text-base-content/70">Duration (s)</span>
              <span className="font-mono">{agg.duration_seconds.toFixed(1)}</span>
            </>
          )}
          {agg.latency_ms_avg != null && agg.latency_ms_avg > 0 && (
            <>
              <span className="text-base-content/70">Avg latency</span>
              <span className="font-mono">{fmtNum(agg.latency_ms_avg)} ms</span>
            </>
          )}
          <span className="text-base-content/70 font-medium">Est. cost</span>
          <span className="font-mono font-medium text-warning">${cost.toFixed(4)}</span>
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

  // Aggregate tool and skill usage from history
  const toolUsage: Record<string, { calls: number; successes: number; errors: number; totalTime: number }> = {};
  const skillUsage: Record<string, number> = {};

  if (telemetryData?.history) {
    for (const entry of telemetryData.history as TelemetryHistoryEntry[]) {
      const m = entry.metrics ?? {};
      if (m.tool_usage && typeof m.tool_usage === 'object') {
        for (const [name, stats] of Object.entries(m.tool_usage)) {
          if (!toolUsage[name]) toolUsage[name] = { calls: 0, successes: 0, errors: 0, totalTime: 0 };
          toolUsage[name].calls += stats.call_count ?? 0;
          toolUsage[name].successes += stats.success_count ?? 0;
          toolUsage[name].errors += stats.error_count ?? 0;
          toolUsage[name].totalTime += stats.total_time ?? 0;
        }
      }
      if (m.skill_info?.selected_skills && Array.isArray(m.skill_info.selected_skills)) {
        for (const skill of m.skill_info.selected_skills) {
          const name = typeof skill === 'string' ? skill : skill?.name || 'unknown';
          skillUsage[name] = (skillUsage[name] || 0) + 1;
        }
      }
    }
  }

  const history = (telemetryData?.history ?? []) as TelemetryHistoryEntry[];
  // Show newest first
  const sortedHistory = [...history].sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0));

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <BarChart3 size={24} />
            Telemetry
          </h2>
          <p className="text-sm text-base-content/60">
            Invocation metrics, token usage, tool calls, and cost estimates
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
        <div className="space-y-8">

          {/* Threshold alerts */}
          {telemetryData.alerts.length > 0 && (
            <div className="alert alert-warning">
              <AlertTriangle size={20} />
              <div>
                <h4 className="font-semibold">Threshold alerts</h4>
                <ul className="list-disc list-inside mt-1">
                  {telemetryData.alerts.map((a, i) => <li key={i}>{a}</li>)}
                </ul>
              </div>
            </div>
          )}

          {/* Running totals */}
          <div>
            <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
              <Clock size={20} />
              Running totals
            </h3>
            {Object.keys(telemetryData.running_totals).length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {['this_hour', 'today', 'this_week', 'this_month']
                  .filter(k => telemetryData.running_totals[k])
                  .map(k => (
                    <AggregatesCard key={k} title={k} agg={telemetryData.running_totals[k]} />
                  ))}
              </div>
            ) : (
              <p className="text-base-content/60 text-sm">No running totals yet — invoke the agent to generate data.</p>
            )}
          </div>

          {/* Cost estimate note */}
          <div className="alert alert-info py-2 text-sm">
            <DollarSign size={16} />
            <span>
              Cost estimates use Claude Sonnet 4 pricing ($3/$15/$0.30/$3.75 per 1M input/output/cache-read/cache-write tokens).
              Actual costs depend on the model used.
            </span>
          </div>

          {/* Tool Usage */}
          {Object.keys(toolUsage).length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <Wrench size={20} />
                Tool usage (from history)
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {Object.entries(toolUsage)
                  .sort(([, a], [, b]) => b.calls - a.calls)
                  .map(([tool, stats]) => (
                    <div key={tool} className="bg-base-200 rounded-lg p-3">
                      <div className="font-mono text-sm truncate mb-2 font-medium" title={tool}>{tool}</div>
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

          {/* Skill Usage */}
          {Object.keys(skillUsage).length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <BarChart3 size={20} />
                Skill usage (from history)
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

          {/* Thresholds */}
          {telemetryData.thresholds.length > 0 && (
            <div>
              <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
                <AlertTriangle size={20} />
                Thresholds
              </h3>
              <div className="overflow-x-auto">
                <table className="table table-sm">
                  <thead>
                    <tr><th>Metric</th><th>Period</th><th>Limit</th></tr>
                  </thead>
                  <tbody>
                    {telemetryData.thresholds.map((t, i) => (
                      <tr key={i}>
                        <td className="font-mono">{t.metric}</td>
                        <td>{t.period}</td>
                        <td className="font-mono">{t.limit.toLocaleString()}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* History table */}
          <div>
            <h3 className="text-lg font-semibold mb-3 flex items-center gap-2">
              <Hash size={20} />
              Recent history
              <span className="badge badge-ghost badge-sm">{sortedHistory.length}</span>
            </h3>
            {sortedHistory.length > 0 ? (
              <div className="bg-base-200 rounded-lg overflow-hidden">
                <div className="overflow-x-auto max-h-[28rem] overflow-y-auto">
                  <table className="table table-xs table-pin-rows">
                    <thead>
                      <tr>
                        <th>Time (UTC)</th>
                        <th className="text-right">In</th>
                        <th className="text-right">Out</th>
                        <th className="text-right">Total</th>
                        <th className="text-right">Cache R</th>
                        <th className="text-right">Cache W</th>
                        <th className="text-right">Cycles</th>
                        <th className="text-right">Dur (s)</th>
                        <th className="text-right">Lat (ms)</th>
                        <th className="text-right">Est $</th>
                      </tr>
                    </thead>
                    <tbody>
                      {sortedHistory.map((entry, i) => {
                        const m = entry.metrics ?? {};
                        const tu = m.token_usage ?? {};
                        const rowCost = estimateCost({
                          invocation_count: 1,
                          input_tokens: tu.input_tokens ?? 0,
                          output_tokens: tu.output_tokens ?? 0,
                          total_tokens: tu.total_tokens ?? (tu.input_tokens ?? 0) + (tu.output_tokens ?? 0),
                          cache_read_tokens: tu.cache_read_tokens ?? 0,
                          cache_write_tokens: tu.cache_write_tokens ?? 0,
                        });
                        return (
                          <tr key={i}>
                            <td className="text-xs whitespace-nowrap">{formatTs(entry.timestamp)}</td>
                            <td className="font-mono text-right">{fmtNum(tu.input_tokens)}</td>
                            <td className="font-mono text-right">{fmtNum(tu.output_tokens)}</td>
                            <td className="font-mono text-right font-medium">{fmtNum(tu.total_tokens)}</td>
                            <td className="font-mono text-right text-info">{tu.cache_read_tokens ? fmtNum(tu.cache_read_tokens) : '—'}</td>
                            <td className="font-mono text-right text-info">{tu.cache_write_tokens ? fmtNum(tu.cache_write_tokens) : '—'}</td>
                            <td className="font-mono text-right">{m.cycle_count ?? '—'}</td>
                            <td className="font-mono text-right">{m.duration_seconds != null ? m.duration_seconds.toFixed(1) : '—'}</td>
                            <td className="font-mono text-right">{m.latency_ms ?? '—'}</td>
                            <td className="font-mono text-right text-warning">${rowCost.toFixed(4)}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <p className="text-base-content/60 text-sm py-4">
                No telemetry history yet. History is loaded from CloudWatch on cold start and accumulated in-memory during the session.
              </p>
            )}
          </div>

        </div>
      ) : (
        <div className="text-center py-8 text-base-content/60">
          <BarChart3 size={48} className="mx-auto mb-4 opacity-50" />
          <p>No telemetry data available</p>
          <p className="text-sm mt-2">Make sure the agent is running and reachable.</p>
        </div>
      )}
    </div>
  );
}
