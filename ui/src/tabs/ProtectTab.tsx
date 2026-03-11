import { useEffect, useState, useCallback } from 'react';
import {
  Shield,
  Users,
  Calendar,
  Bell,
  RefreshCw,
  Camera,
  Server,
  ScanLine,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Eye,
} from 'lucide-react';
import { api } from '../api/client';
import type {
  ProtectSummary,
  ProtectCamera,
  ProtectEntity,
  ProtectEvent,
  ProtectAlert,
  ProtectHealth,
  PatrolResult,
} from '../types';

type TimeRange = '1h' | '6h' | '24h' | '7d';
const TIME_RANGE_PARAMS: Record<TimeRange, { hours?: number; days?: number }> = {
  '1h': { hours: 1 },
  '6h': { hours: 6 },
  '24h': { hours: 24 },
  '7d': { days: 7 },
};

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleString(undefined, { dateStyle: 'short', timeStyle: 'short' });
  } catch {
    return iso;
  }
}

function relativeTime(iso: string): string {
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  } catch {
    return iso;
  }
}

function componentBadgeClass(status: string): string {
  if (status === 'ok' || status === 'running' || status === 'Healthy') return 'badge-success';
  if (status === 'stopped' || status === 'unchecked' || status === 'no_data' || status === 'unknown')
    return 'badge-neutral';
  if (status.startsWith('error')) return 'badge-error';
  if (status === 'Degraded') return 'badge-warning';
  return 'badge-neutral';
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

function CameraCard({
  camera,
  patrol,
  eventCount,
  lastEvent,
}: {
  camera: ProtectCamera;
  patrol?: PatrolResult;
  eventCount: number;
  lastEvent?: string;
}) {
  const isOnline = camera.state === 'CONNECTED' || camera.state === 'connected';
  return (
    <div className="card bg-base-200 shadow-sm">
      <div className="card-body p-4 gap-2">
        <div className="flex items-center justify-between">
          <h4 className="font-semibold text-sm flex items-center gap-2">
            <Camera size={14} />
            {camera.name}
          </h4>
          <span
            className={`w-2 h-2 rounded-full ${isOnline ? 'bg-success' : 'bg-error'}`}
            title={camera.state ?? 'unknown'}
          />
        </div>

        {(camera.smart_detect_types?.length ?? 0) > 0 && (
          <div className="flex flex-wrap gap-1">
            {camera.smart_detect_types!.map((t) => (
              <span key={t} className="badge badge-outline badge-xs">
                {t}
              </span>
            ))}
          </div>
        )}

        {patrol && !patrol.error ? (
          <div className="mt-1 text-xs space-y-1">
            <p className="text-base-content/80 line-clamp-2">{patrol.scene_description}</p>
            {patrol.detected_objects.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {patrol.detected_objects.map((obj, i) => (
                  <span key={i} className="badge badge-ghost badge-xs">
                    {obj}
                  </span>
                ))}
              </div>
            )}
            {patrol.anomaly_detected && (
              <p className="text-warning flex items-center gap-1">
                <AlertTriangle size={12} />
                {patrol.anomaly_description ?? 'Anomaly detected'}
              </p>
            )}
            {patrol.timestamp && (
              <p className="text-base-content/40">Analyzed {relativeTime(patrol.timestamp)}</p>
            )}
          </div>
        ) : patrol?.error ? (
          <p className="text-xs text-error mt-1">{patrol.error}</p>
        ) : (
          <p className="text-xs text-base-content/40 mt-1">No patrol data yet</p>
        )}

        <div className="flex justify-between text-xs text-base-content/50 mt-1 pt-1 border-t border-base-300">
          <span>Events (24h): {eventCount}</span>
          {lastEvent && <span>Last: {relativeTime(lastEvent)}</span>}
        </div>
      </div>
    </div>
  );
}

function CollapsibleSection({
  title,
  icon,
  count,
  defaultOpen = false,
  children,
}: {
  title: string;
  icon: React.ReactNode;
  count: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <section>
      <button
        type="button"
        className="flex items-center gap-2 w-full text-left text-lg font-semibold mb-3 hover:text-primary transition-colors"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={18} /> : <ChevronRight size={18} />}
        {icon}
        {title}
        <span className="badge badge-neutral badge-sm ml-1">{count}</span>
      </button>
      {open && children}
    </section>
  );
}

export function ProtectTab() {
  const [summary, setSummary] = useState<ProtectSummary | null>(null);
  const [cameras, setCameras] = useState<ProtectCamera[]>([]);
  const [patrols, setPatrols] = useState<PatrolResult[]>([]);
  const [entities, setEntities] = useState<ProtectEntity[]>([]);
  const [events, setEvents] = useState<ProtectEvent[]>([]);
  const [alerts, setAlerts] = useState<ProtectAlert[]>([]);
  const [health, setHealth] = useState<ProtectHealth | null>(null);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [timeRange, setTimeRange] = useState<TimeRange>('24h');

  const fetchAll = useCallback(
    async (range?: TimeRange) => {
      setLoading(true);
      setError(null);
      const tr = range ?? timeRange;
      const eventParams = { ...TIME_RANGE_PARAMS[tr], limit: 50 };

      const results = await Promise.allSettled([
        api.getProtectSummary(),
        api.getProtectCameras({ limit: 50 }),
        api.getProtectPatrols({ hours: 24, limit: 50 }),
        api.getProtectEntities({ limit: 50 }),
        api.getProtectEvents(eventParams),
        api.getProtectAlerts({ limit: 20, unack_only: false }),
        api.getProtectHealth(),
      ]);

      const errors: string[] = [];
      if (results[0].status === 'fulfilled') setSummary(results[0].value);
      else {
        setSummary(null);
        errors.push('Summary: ' + (results[0].reason?.message ?? 'Failed'));
      }
      if (results[1].status === 'fulfilled') setCameras(results[1].value.cameras);
      else setCameras([]);
      if (results[2].status === 'fulfilled') setPatrols(results[2].value.patrols);
      else setPatrols([]);
      if (results[3].status === 'fulfilled') setEntities(results[3].value.entities);
      else setEntities([]);
      if (results[4].status === 'fulfilled') setEvents(results[4].value.events);
      else {
        setEvents([]);
        errors.push('Events: ' + (results[4].reason?.message ?? 'Failed'));
      }
      if (results[5].status === 'fulfilled') setAlerts(results[5].value.alerts);
      else setAlerts([]);
      if (results[6].status === 'fulfilled') setHealth(results[6].value);
      else setHealth(null);

      setError(errors.length > 0 ? errors.join('; ') : null);
      setLoading(false);
    },
    [timeRange],
  );

  const handleScanNow = async () => {
    setScanning(true);
    try {
      await api.triggerProtectScan();
      await fetchAll();
    } catch (e) {
      setError(`Scan failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setScanning(false);
    }
  };

  const handleTimeRangeChange = (range: TimeRange) => {
    setTimeRange(range);
    fetchAll(range);
  };

  useEffect(() => {
    fetchAll();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const patrolByCamera = new Map(patrols.map((p) => [p.camera_id, p]));

  const eventCountsByCamera = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.camera_id] = (acc[e.camera_id] ?? 0) + 1;
    return acc;
  }, {});

  const lastEventByCamera = events.reduce<Record<string, string>>((acc, e) => {
    if (!acc[e.camera_id] || e.timestamp > acc[e.camera_id]) {
      acc[e.camera_id] = e.timestamp;
    }
    return acc;
  }, {});

  const lastPatrolTs = patrols.length > 0
    ? patrols.reduce<string | undefined>((latest, p) => {
        if (!p.timestamp) return latest;
        if (!latest) return p.timestamp;
        return p.timestamp > latest ? p.timestamp : latest;
      }, undefined) ?? null
    : null;

  if (loading && !summary) {
    return (
      <div className="p-6 flex items-center justify-center h-64">
        <span className="loading loading-spinner loading-lg text-primary" />
      </div>
    );
  }

  return (
    <div className="p-6 h-full overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Shield size={24} />
            Protect
            {loading ? (
              <span className="badge badge-neutral badge-sm">Checking...</span>
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
          <p className="text-sm text-base-content/60">Camera surveillance, patrols, and event monitoring</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="btn btn-primary btn-sm gap-2"
            onClick={handleScanNow}
            disabled={scanning}
          >
            {scanning ? (
              <span className="loading loading-spinner loading-xs" />
            ) : (
              <ScanLine size={16} />
            )}
            Scan Now
          </button>
          <button
            type="button"
            className="btn btn-ghost btn-sm gap-2"
            onClick={() => fetchAll()}
            disabled={loading}
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <div className="alert alert-warning mb-4">
          <span>{error}</span>
        </div>
      )}

      {/* Summary Stats */}
      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
          <div className="stat bg-base-200 rounded-lg">
            <div className="stat-title flex items-center gap-2">
              <Camera size={16} /> Cameras
            </div>
            <div className="stat-value text-2xl">
              {summary.cameras_online}/{summary.cameras_total}
            </div>
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
              <Eye size={16} /> Last Patrol
            </div>
            <div className="stat-value text-lg">
              {lastPatrolTs ? relativeTime(lastPatrolTs) : 'None'}
            </div>
          </div>
        </div>
      )}

      {/* Camera Cards Grid */}
      {cameras.length > 0 && (
        <section className="mb-6">
          <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
            <Camera size={20} /> Cameras
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {cameras.map((cam) => (
              <CameraCard
                key={cam.camera_id}
                camera={cam}
                patrol={patrolByCamera.get(cam.camera_id)}
                eventCount={eventCountsByCamera[cam.camera_id] ?? 0}
                lastEvent={lastEventByCamera[cam.camera_id]}
              />
            ))}
          </div>
        </section>
      )}

      {/* Event Timeline */}
      <section className="mb-6">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <Calendar size={20} /> Events
          </h3>
          <div className="join">
            {(['1h', '6h', '24h', '7d'] as TimeRange[]).map((range) => (
              <button
                key={range}
                type="button"
                className={`join-item btn btn-xs ${timeRange === range ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => handleTimeRangeChange(range)}
              >
                {range}
              </button>
            ))}
          </div>
        </div>
        <div className="card bg-base-200">
          <div className="card-body p-4">
            {events.length === 0 ? (
              <p className="text-base-content/60">No events in this time range.</p>
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
                        <td className="text-sm">{e.camera_name ?? e.camera_id}</td>
                        <td>
                          <span className="badge badge-outline badge-sm">
                            {e.entity_type ?? 'motion'}
                          </span>
                        </td>
                        <td>
                          <span
                            className={`font-mono text-xs ${
                              (e.anomaly_score ?? 0) >= 0.7
                                ? 'text-error'
                                : (e.anomaly_score ?? 0) >= 0.4
                                  ? 'text-warning'
                                  : ''
                            }`}
                          >
                            {(e.anomaly_score ?? 0).toFixed(2)}
                          </span>
                        </td>
                        <td>
                          {e.processed ? (
                            <span className="badge badge-success badge-xs">Yes</span>
                          ) : (
                            <span className="badge badge-neutral badge-xs">No</span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Collapsible: Entities */}
      <div className="grid gap-6 mb-6">
        <CollapsibleSection
          title="Entities"
          icon={<Users size={20} />}
          count={entities.length}
        >
          <div className="card bg-base-200">
            <div className="card-body p-4">
              {entities.length === 0 ? (
                <p className="text-base-content/60">No entities registered.</p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="table table-sm">
                    <thead>
                      <tr>
                        <th>Label</th>
                        <th>Type</th>
                        <th>Trust</th>
                        <th>Last seen</th>
                        <th>Sightings</th>
                      </tr>
                    </thead>
                    <tbody>
                      {entities.map((e) => (
                        <tr key={e.entity_id}>
                          <td>{e.label ?? e.entity_id}</td>
                          <td>{e.type}</td>
                          <td>
                            <span className={`badge badge-sm ${trustBadgeClass(e.trust_level)}`}>
                              {e.trust_level}
                            </span>
                          </td>
                          <td className="text-xs">
                            {e.last_seen ? relativeTime(e.last_seen) : '---'}
                          </td>
                          <td>{e.sightings_count ?? 0}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        </CollapsibleSection>

        {/* Collapsible: Alerts */}
        <CollapsibleSection
          title="Alerts"
          icon={<Bell size={20} />}
          count={alerts.length}
        >
          <div className="card bg-base-200">
            <div className="card-body p-4">
              {alerts.length === 0 ? (
                <p className="text-base-content/60">No alerts.</p>
              ) : (
                <ul className="space-y-2">
                  {alerts.map((a) => (
                    <li
                      key={a.alert_id}
                      className="flex flex-wrap items-start gap-2 p-2 rounded bg-base-300"
                    >
                      <span className={`badge ${priorityBadgeClass(a.priority)}`}>
                        {a.priority}
                      </span>
                      <span className="font-medium">{a.title}</span>
                      <span className="text-xs text-base-content/60">
                        {formatTs(a.timestamp)}
                      </span>
                      {a.user_response && (
                        <span className="badge badge-outline">{a.user_response}</span>
                      )}
                      {a.body && (
                        <p className="w-full text-sm text-base-content/70">{a.body}</p>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </CollapsibleSection>
      </div>

      {/* System Health Footer */}
      <div className="card bg-base-200">
        <div className="card-body p-4">
          <h3 className="font-semibold flex items-center gap-2 mb-3 text-sm">
            <Server size={14} />
            Protect System Health
          </h3>
          {health ? (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <div>
                <span className="text-base-content/60 block text-xs mb-1">Overall</span>
                <span className={`badge ${componentBadgeClass(health.status)}`}>
                  {health.status}
                </span>
              </div>
              <div>
                <span className="text-base-content/60 block text-xs mb-1">DB</span>
                <span className={`badge ${componentBadgeClass(health.protect_db)}`}>
                  {health.protect_db}
                </span>
              </div>
              <div>
                <span className="text-base-content/60 block text-xs mb-1">Poller</span>
                <span className={`badge ${componentBadgeClass(health.protect_poller)}`}>
                  {health.protect_poller}
                </span>
              </div>
              <div>
                <span className="text-base-content/60 block text-xs mb-1">Processor</span>
                <span className={`badge ${componentBadgeClass(health.protect_processor)}`}>
                  {health.protect_processor}
                </span>
              </div>
            </div>
          ) : (
            <p className="text-sm text-base-content/60">
              No health data available.
            </p>
          )}
          {health?.updated_at && (
            <p className="text-xs text-base-content/40 mt-2">
              Last updated: {formatTs(health.updated_at)}
              {health.uptime_seconds != null && (
                <span> / Uptime: {Math.floor(health.uptime_seconds / 60)}m</span>
              )}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
