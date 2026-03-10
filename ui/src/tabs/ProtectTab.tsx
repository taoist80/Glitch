import { useEffect, useState } from 'react';
import { Shield, Users, Calendar, Bell, Activity, RefreshCw, Camera, Server } from 'lucide-react';
import { api } from '../api/client';
import type {
  ProtectSummary,
  ProtectEntity,
  ProtectEvent,
  ProtectAlert,
  ProtectPattern,
  SentinelHealth,
} from '../types';

function formatTs(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
  } catch {
    return iso;
  }
}

function trustBadgeClass(level: string): string {
  const map: Record<string, string> = {
    trusted: 'badge-success',
    hostile: 'badge-error',
    suspicious: 'badge-warning',
    unknown: 'badge-neutral',
  };
  return map[level] ?? 'badge-neutral';
}

function priorityBadgeClass(priority: string): string {
  const map: Record<string, string> = {
    critical: 'badge-error',
    high: 'badge-warning',
    medium: 'badge-info',
    low: 'badge-neutral',
  };
  return map[priority] ?? 'badge-neutral';
}

function componentBadgeClass(status: string): string {
  if (status === 'ok' || status === 'running' || status === 'Healthy') return 'badge-success';
  if (status === 'stopped' || status === 'unchecked' || status === 'no_data' || status === 'unknown') return 'badge-neutral';
  if (status.startsWith('error')) return 'badge-error';
  if (status === 'Degraded') return 'badge-warning';
  return 'badge-neutral';
}

export function ProtectTab() {
  const [summary, setSummary] = useState<ProtectSummary | null>(null);
  const [entities, setEntities] = useState<ProtectEntity[]>([]);
  const [events, setEvents] = useState<ProtectEvent[]>([]);
  const [alerts, setAlerts] = useState<ProtectAlert[]>([]);
  const [patterns, setPatterns] = useState<ProtectPattern[]>([]);
  const [sentinelHealth, setSentinelHealth] = useState<SentinelHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAll = async () => {
    setLoading(true);
    setError(null);
    const results = await Promise.allSettled([
      api.getProtectSummary(),
      api.getProtectEntities({ limit: 50 }),
      api.getProtectEvents({ hours: 24, limit: 30 }),
      api.getProtectAlerts({ limit: 20, unack_only: false }),
      api.getProtectPatterns({ limit: 20 }),
      api.getSentinelHealth(),
    ]);
    const errors: string[] = [];
    if (results[0].status === 'fulfilled') {
      setSummary(results[0].value);
    } else {
      setSummary(null);
      errors.push('Summary: ' + (results[0].reason?.message ?? 'Failed'));
    }
    if (results[1].status === 'fulfilled') {
      setEntities(results[1].value.entities);
    } else {
      setEntities([]);
      errors.push('Entities: ' + (results[1].reason?.message ?? 'Failed'));
    }
    if (results[2].status === 'fulfilled') {
      setEvents(results[2].value.events);
    } else {
      setEvents([]);
      errors.push('Events: ' + (results[2].reason?.message ?? 'Failed'));
    }
    if (results[3].status === 'fulfilled') {
      setAlerts(results[3].value.alerts);
    } else {
      setAlerts([]);
      errors.push('Alerts: ' + (results[3].reason?.message ?? 'Failed'));
    }
    if (results[4].status === 'fulfilled') {
      setPatterns(results[4].value.patterns);
    } else {
      setPatterns([]);
      errors.push('Patterns: ' + (results[4].reason?.message ?? 'Failed'));
    }
    if (results[5].status === 'fulfilled') {
      setSentinelHealth(results[5].value);
    } else {
      setSentinelHealth(null);
    }
    setError(errors.length > 0 ? errors.join('; ') : null);
    setLoading(false);
  };

  useEffect(() => {
    fetchAll();
  }, []);

  if (loading && !summary) {
    return (
      <div className="p-6 flex items-center justify-center h-64">
        <span className="loading loading-spinner loading-lg text-primary" />
      </div>
    );
  }

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Shield size={24} />
            Protect
            {loading ? (
              <span className="badge badge-neutral badge-sm">Checking…</span>
            ) : summary !== null ? (
              <span className="badge badge-success badge-sm gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-current" />
                Connected
              </span>
            ) : (
              <span className="badge badge-error badge-sm gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-current" />
                Disconnected
              </span>
            )}
          </h2>
          <p className="text-sm text-base-content/60">
            Entities, events, alerts, and behaviours from UniFi Protect
          </p>
        </div>
        <button
          type="button"
          className="btn btn-ghost btn-sm gap-2"
          onClick={() => fetchAll()}
          disabled={loading}
        >
          <RefreshCw size={18} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {error && (
        <div className="alert alert-warning mb-4">
          <span>{error}</span>
          <span className="text-sm opacity-80">
            Ensure the Protect API is deployed (backend that reads from the Protect DB or Sentinel).
          </span>
        </div>
      )}

      {/* Sentinel agent health panel */}
      <div className="card bg-base-200 mb-6">
        <div className="card-body p-4">
          <h3 className="font-semibold flex items-center gap-2 mb-3">
            <Server size={16} />
            Sentinel agent health
          </h3>
          {sentinelHealth ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div>
                <span className="text-base-content/60 block text-xs mb-1">Overall</span>
                <span className={`badge ${componentBadgeClass(sentinelHealth.status)}`}>
                  {sentinelHealth.status}
                </span>
              </div>
              <div>
                <span className="text-base-content/60 block text-xs mb-1">DB</span>
                <span className={`badge ${componentBadgeClass(sentinelHealth.protect_db)}`}>
                  {sentinelHealth.protect_db}
                </span>
              </div>
              <div>
                <span className="text-base-content/60 block text-xs mb-1">Poller</span>
                <span className={`badge ${componentBadgeClass(sentinelHealth.protect_poller)}`}>
                  {sentinelHealth.protect_poller}
                </span>
              </div>
              <div>
                <span className="text-base-content/60 block text-xs mb-1">Processor</span>
                <span className={`badge ${componentBadgeClass(sentinelHealth.protect_processor)}`}>
                  {sentinelHealth.protect_processor}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-base-content/60">
              No health data — Sentinel has not written to the DB yet.
            </p>
          )}
          {sentinelHealth?.updated_at && (
            <p className="text-xs text-base-content/40 mt-2">
              Last updated: {formatTs(sentinelHealth.updated_at)}
              {sentinelHealth.uptime_seconds != null && (
                <span> · Uptime: {Math.floor(sentinelHealth.uptime_seconds / 60)}m</span>
              )}
            </p>
          )}
        </div>
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="stat bg-base-200 rounded-lg">
            <div className="stat-title flex items-center gap-2">
              <Users size={16} /> Entities
            </div>
            <div className="stat-value text-2xl">{summary.entities_total}</div>
          </div>
          <div className="stat bg-base-200 rounded-lg">
            <div className="stat-title flex items-center gap-2">
              <Calendar size={16} /> Events (24h)
            </div>
            <div className="stat-value text-2xl">{summary.events_24h}</div>
          </div>
          <div className="stat bg-base-200 rounded-lg">
            <div className="stat-title flex items-center gap-2">
              <Bell size={16} /> Unack. Alerts
            </div>
            <div className="stat-value text-2xl">{summary.alerts_unack}</div>
          </div>
          <div className="stat bg-base-200 rounded-lg">
            <div className="stat-title flex items-center gap-2">
              <Camera size={16} /> Cameras
            </div>
            <div className="stat-value text-2xl">{summary.cameras_online}</div>
          </div>
        </div>
      )}

      <div className="grid gap-6">
        {/* Entities */}
        <section>
          <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
            <Users size={20} /> Entities
          </h3>
          <div className="card bg-base-200">
            <div className="card-body p-4">
              {entities.length === 0 ? (
                <p className="text-base-content/60">No entities. Register people/vehicles in Sentinel.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="table table-sm">
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>Type</th>
                        <th>Label</th>
                        <th>Trust</th>
                        <th>Last seen</th>
                        <th>Sightings</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entities.map((e) => (
                        <tr key={e.entity_id}>
                          <td className="font-mono text-xs">{e.entity_id}</td>
                          <td>{e.type}</td>
                          <td>{e.label ?? '—'}</td>
                          <td><span className={`badge ${trustBadgeClass(e.trust_level)}`}>{e.trust_level}</span></td>
                          <td className="text-xs">{e.last_seen ? formatTs(e.last_seen) : '—'}</td>
                          <td>{e.sightings_count ?? 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Events */}
        <section>
          <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
            <Calendar size={20} /> Recent events
          </h3>
          <div className="card bg-base-200">
            <div className="card-body p-4">
              {events.length === 0 ? (
                <p className="text-base-content/60">No events in the last 24h.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="table table-sm">
                    <thead>
                      <tr>
                        <th>Time</th>
                        <th>Camera</th>
                        <th>Type</th>
                        <th>Anomaly</th>
                        <th>Processed</th>
                      </tr>
                    </thead>
                    <tbody>
                      {events.map((e) => (
                        <tr key={e.event_id}>
                          <td className="text-xs">{formatTs(e.timestamp)}</td>
                          <td className="font-mono text-xs">{e.camera_id}</td>
                          <td>{e.entity_type ?? 'motion'}</td>
                          <td>{(e.anomaly_score ?? 0).toFixed(2)}</td>
                          <td>{e.processed ? 'Yes' : 'No'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </section>

        {/* Alerts */}
        <section>
          <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
            <Bell size={20} /> Alerts
          </h3>
          <div className="card bg-base-200">
            <div className="card-body p-4">
              {alerts.length === 0 ? (
                <p className="text-base-content/60">No alerts.</p>
              ) : (
                <ul className="space-y-2">
                  {alerts.map((a) => (
                    <li key={a.alert_id} className="flex flex-wrap items-start gap-2 p-2 rounded bg-base-300">
                      <span className={`badge ${priorityBadgeClass(a.priority)}`}>{a.priority}</span>
                      <span className="font-medium">{a.title}</span>
                      <span className="text-xs text-base-content/60">{formatTs(a.timestamp)}</span>
                      {a.user_response && <span className="badge badge-outline">{a.user_response}</span>}
                      {a.body && <p className="w-full text-sm text-base-content/70">{a.body}</p>}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </section>

        {/* Behaviours / Patterns */}
        <section>
          <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
            <Activity size={20} /> Behaviours (patterns)
          </h3>
          <div className="card bg-base-200">
            <div className="card-body p-4">
              {patterns.length === 0 ? (
                <p className="text-base-content/60">No behaviour patterns recorded.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="table table-sm">
                    <thead>
                      <tr>
                        <th>Camera</th>
                        <th>Entity</th>
                        <th>Type</th>
                        <th>Frequency</th>
                        <th>Last seen</th>
                        <th>Confidence</th>
                      </tr>
                    </thead>
                    <tbody>
                      {patterns.map((p) => (
                        <tr key={p.pattern_id}>
                          <td className="font-mono text-xs">{p.camera_id}</td>
                          <td className="font-mono text-xs">{p.entity_id ?? '—'}</td>
                          <td>{p.pattern_type}</td>
                          <td>{(p.frequency ?? 0).toFixed(2)}</td>
                          <td className="text-xs">{p.last_seen ? formatTs(p.last_seen) : '—'}</td>
                          <td>{p.confidence != null ? (p.confidence * 100).toFixed(0) + '%' : '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
