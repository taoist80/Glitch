import { useEffect, useRef, useState } from 'react';
import {
  RefreshCw,
  Users,
  Database,
  FileText,
  Download,
  Save,
  BarChart3,
  MessageSquare,
} from 'lucide-react';
import { LionIcon } from '../components/LionIcon';
import { api } from '../api/client';
import { useAppStore } from '../store/useAppStore';
import type { AuriChannel, AuriDmUser, AuriMemoryStats, AuriProfile } from '../types';

type SubTab = 'overview' | 'persona' | 'analytics';

// ---------------------------------------------------------------------------
// Overview sub-tab
// ---------------------------------------------------------------------------

function OverviewTab() {
  const [channels, setChannels] = useState<AuriChannel[]>([]);
  const [dmUsers, setDmUsers] = useState<AuriDmUser[]>([]);
  const [memStats, setMemStats] = useState<AuriMemoryStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [ch, dm, ms] = await Promise.all([
        api.getAuriChannels(),
        api.getAuriDmUsers(),
        api.getAuriMemoryStats(),
      ]);
      setChannels(ch.channels);
      setDmUsers(dm.users);
      setMemStats(ms);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  function sessionLabel(ch: AuriChannel): string {
    const parts = ch.session_id.split(':');
    if (parts.length >= 3) {
      const type = parts[1];
      const id = parts[2].replace(/0+$/, '') || parts[2];
      return `${type.charAt(0).toUpperCase() + type.slice(1)} ${id}`;
    }
    return ch.session_id;
  }

  function formatTs(ts?: number): string {
    if (!ts) return '—';
    try { return new Date(ts * 1000).toLocaleString(); } catch { return String(ts); }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h3 className="text-lg font-semibold flex items-center gap-2">
          <Users size={20} />
          Active Sessions
          <span className="badge badge-primary badge-sm">{channels.length}</span>
        </h3>
        <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}>
          <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {error && <div className="alert alert-error text-sm"><span>{error}</span></div>}

      {loading && !channels.length ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner loading-md" />
        </div>
      ) : channels.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="table table-sm">
            <thead>
              <tr>
                <th>Session</th>
                <th>Agent</th>
                <th>Mode</th>
                <th>Last active</th>
              </tr>
            </thead>
            <tbody>
              {channels.map((ch) => (
                <tr key={ch.session_id}>
                  <td className="font-mono text-xs">{sessionLabel(ch)}</td>
                  <td>{ch.agent_id}</td>
                  <td>
                    <span className="badge badge-secondary badge-xs">{ch.mode_id}</span>
                  </td>
                  <td className="text-xs text-base-content/60">{formatTs(ch.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : !loading ? (
        <div className="text-base-content/50 text-sm py-4 text-center">
          No active roleplay sessions found. Send <code>/auri</code> in Telegram to start one.
        </div>
      ) : null}

      {/* DM users */}
      <div>
        <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
          <MessageSquare size={20} />
          Authorized DM Users
          <span className="badge badge-ghost badge-sm">{dmUsers.length}</span>
        </h3>
        {loading && !dmUsers.length ? null : dmUsers.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {dmUsers.map((u) => (
              <span key={u.user_id} className="badge badge-outline font-mono text-xs">
                {u.display_name ?? u.user_id}
              </span>
            ))}
          </div>
        ) : !loading ? (
          <p className="text-base-content/50 text-sm">
            No authorized DM users. Use <code>/pair</code> in Telegram to grant access.
          </p>
        ) : null}
      </div>

      {/* Memory stats */}
      <div>
        <h3 className="text-lg font-semibold flex items-center gap-2 mb-3">
          <Database size={20} />
          Memory Storage
        </h3>
        {memStats ? (
          memStats.available ? (
            <div className="grid grid-cols-3 gap-3">
              {[
                { label: 'Episodic memories', value: memStats.memory_rows },
                { label: 'Participant profiles', value: memStats.profile_rows },
                { label: 'Total rows', value: memStats.total_rows },
              ].map(({ label, value }) => (
                <div key={label} className="card bg-base-200 shadow compact">
                  <div className="card-body p-4">
                    <p className="text-xs text-base-content/60">{label}</p>
                    <p className="text-2xl font-bold text-primary">{value.toLocaleString()}</p>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="alert alert-warning text-sm">
              <span>Memory stats unavailable — protect-query Lambda not reachable. {memStats.error}</span>
            </div>
          )
        ) : (
          <div className="text-base-content/50 text-sm">Loading memory stats…</div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Persona sub-tab
// ---------------------------------------------------------------------------

function PersonaTab() {
  const [coreContent, setCoreContent] = useState('');
  const [rulesContent, setRulesContent] = useState('');
  const [loadingCore, setLoadingCore] = useState(false);
  const [loadingRules, setLoadingRules] = useState(false);
  const [savingCore, setSavingCore] = useState(false);
  const [savingRules, setSavingRules] = useState(false);
  const [coreError, setCoreError] = useState<string | null>(null);
  const [rulesError, setRulesError] = useState<string | null>(null);
  const [coreSaved, setCoreSaved] = useState(false);
  const [rulesSaved, setRulesSaved] = useState(false);
  const [exportingCard, setExportingCard] = useState(false);
  const [profiles, setProfiles] = useState<AuriProfile[]>([]);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [expandedProfile, setExpandedProfile] = useState<string | null>(null);
  const coreTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const rulesTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  async function loadCore() {
    setLoadingCore(true);
    setCoreError(null);
    try {
      const res = await api.getAuriPersonaCore();
      setCoreContent(res.content);
    } catch (e) {
      setCoreError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingCore(false);
    }
  }

  async function loadRules() {
    setLoadingRules(true);
    setRulesError(null);
    try {
      const res = await api.getAuriPersonaRules();
      setRulesContent(res.content);
    } catch (e) {
      setRulesError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingRules(false);
    }
  }

  async function loadProfiles() {
    setProfilesLoading(true);
    try {
      const res = await api.getAuriProfiles();
      setProfiles(res.profiles);
    } catch {
      // Non-critical — profiles require protect-query Lambda
    } finally {
      setProfilesLoading(false);
    }
  }

  useEffect(() => {
    loadCore();
    loadRules();
    loadProfiles();
  }, []);

  async function saveCore() {
    setSavingCore(true);
    setCoreError(null);
    setCoreSaved(false);
    try {
      await api.putAuriPersonaCore(coreContent);
      setCoreSaved(true);
      if (coreTimerRef.current) clearTimeout(coreTimerRef.current);
      coreTimerRef.current = setTimeout(() => setCoreSaved(false), 3000);
    } catch (e) {
      setCoreError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingCore(false);
    }
  }

  async function saveRules() {
    setSavingRules(true);
    setRulesError(null);
    setRulesSaved(false);
    try {
      await api.putAuriPersonaRules(rulesContent);
      setRulesSaved(true);
      if (rulesTimerRef.current) clearTimeout(rulesTimerRef.current);
      rulesTimerRef.current = setTimeout(() => setRulesSaved(false), 3000);
    } catch (e) {
      setRulesError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingRules(false);
    }
  }

  async function exportCard() {
    setExportingCard(true);
    try {
      const card = await api.exportAuriCharacterCard();
      const blob = new Blob([JSON.stringify(card, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'auri-character-card.json';
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      // Non-critical — show inline error in console
      console.error('Character card export failed:', e);
    } finally {
      setExportingCard(false);
    }
  }

  return (
    <div className="space-y-8">
      {/* auri-core.md */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold flex items-center gap-2">
            <FileText size={18} />
            auri-core.md
            <span className="text-xs text-base-content/50 font-normal">— identity &amp; persona</span>
          </h3>
          <div className="flex gap-2">
            <button className="btn btn-ghost btn-xs" onClick={loadCore} disabled={loadingCore}>
              <RefreshCw size={14} className={loadingCore ? 'animate-spin' : ''} />
            </button>
            <button
              className={`btn btn-sm ${coreSaved ? 'btn-success' : 'btn-primary'}`}
              onClick={saveCore}
              disabled={savingCore || loadingCore}
            >
              <Save size={14} />
              {savingCore ? 'Saving…' : coreSaved ? 'Saved!' : 'Save'}
            </button>
          </div>
        </div>
        {coreError && <div className="alert alert-error text-xs mb-2"><span>{coreError}</span></div>}
        <textarea
          className="textarea textarea-bordered w-full font-mono text-xs leading-relaxed"
          rows={18}
          value={coreContent}
          onChange={(e) => setCoreContent(e.target.value)}
          disabled={loadingCore}
          placeholder={loadingCore ? 'Loading…' : 'auri-core.md content'}
          spellCheck={false}
        />
        <p className="text-xs text-base-content/40 mt-1">
          Saved to S3. In-process cache invalidated automatically on save. Changes take effect on the next invocation.
        </p>
      </div>

      {/* auri-runtime-rules.md */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="font-semibold flex items-center gap-2">
            <FileText size={18} />
            auri-runtime-rules.md
            <span className="text-xs text-base-content/50 font-normal">— behaviour &amp; tool rules</span>
          </h3>
          <div className="flex gap-2">
            <button className="btn btn-ghost btn-xs" onClick={loadRules} disabled={loadingRules}>
              <RefreshCw size={14} className={loadingRules ? 'animate-spin' : ''} />
            </button>
            <button
              className={`btn btn-sm ${rulesSaved ? 'btn-success' : 'btn-primary'}`}
              onClick={saveRules}
              disabled={savingRules || loadingRules}
            >
              <Save size={14} />
              {savingRules ? 'Saving…' : rulesSaved ? 'Saved!' : 'Save'}
            </button>
          </div>
        </div>
        {rulesError && <div className="alert alert-error text-xs mb-2"><span>{rulesError}</span></div>}
        <textarea
          className="textarea textarea-bordered w-full font-mono text-xs leading-relaxed"
          rows={14}
          value={rulesContent}
          onChange={(e) => setRulesContent(e.target.value)}
          disabled={loadingRules}
          placeholder={loadingRules ? 'Loading…' : 'auri-runtime-rules.md content'}
          spellCheck={false}
        />
      </div>

      {/* Character Card V2 export */}
      <div className="border-t border-base-300 pt-4">
        <h3 className="font-semibold flex items-center gap-2 mb-2">
          <Download size={18} />
          Character Card V2 Export
        </h3>
        <p className="text-sm text-base-content/60 mb-3">
          Exports auri-core.md + auri-runtime-rules.md as a portable Character Card V2 JSON file,
          compatible with SillyTavern and KoboldCPP character import.
        </p>
        <button
          className="btn btn-outline btn-sm"
          onClick={exportCard}
          disabled={exportingCard}
        >
          <Download size={14} />
          {exportingCard ? 'Exporting…' : 'Export auri-character-card.json'}
        </button>
      </div>

      {/* Participant profiles */}
      <div className="border-t border-base-300 pt-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="font-semibold flex items-center gap-2">
            <Users size={18} />
            Participant Profiles
            <span className="badge badge-ghost badge-sm">{profiles.length}</span>
          </h3>
          <button className="btn btn-ghost btn-xs" onClick={loadProfiles} disabled={profilesLoading}>
            <RefreshCw size={14} className={profilesLoading ? 'animate-spin' : ''} />
          </button>
        </div>
        {profilesLoading ? (
          <div className="flex justify-center py-4">
            <span className="loading loading-spinner loading-sm" />
          </div>
        ) : profiles.length > 0 ? (
          <div className="space-y-2">
            {profiles.map((p) => (
              <div key={p.participant_id} className="collapse collapse-arrow bg-base-200">
                <input
                  type="checkbox"
                  checked={expandedProfile === p.participant_id}
                  onChange={() =>
                    setExpandedProfile(expandedProfile === p.participant_id ? null : p.participant_id)
                  }
                />
                <div className="collapse-title text-sm font-medium py-2 min-h-0">
                  {p.participant_id}
                  {p.created_at && (
                    <span className="text-xs text-base-content/40 ml-2 font-normal">
                      {new Date(p.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
                <div className="collapse-content">
                  <pre className="text-xs whitespace-pre-wrap font-mono text-base-content/80 leading-relaxed">
                    {p.content}
                  </pre>
                </div>
              </div>
            ))}
          </div>
        ) : !profilesLoading ? (
          <p className="text-base-content/50 text-sm">
            No participant profiles yet. Auri builds profiles automatically during conversations.
          </p>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Analytics sub-tab (roleplay token usage from existing telemetry store)
// ---------------------------------------------------------------------------

function AnalyticsTab() {
  const { telemetryData, telemetryLoading, telemetryError, fetchTelemetry } = useAppStore();

  useEffect(() => {
    if (!telemetryData) fetchTelemetry();
  }, [telemetryData, fetchTelemetry]);

  // Haiku pricing per 1M tokens
  const HAIKU_INPUT = 0.80;
  const HAIKU_OUTPUT = 4.0;
  const HAIKU_CACHE_READ = 0.08;
  const HAIKU_CACHE_WRITE = 1.0;

  function fmtNum(n: number | undefined | null): string {
    if (n == null) return '—';
    return n.toLocaleString();
  }

  const totals = telemetryData?.running_totals ?? {};
  const periods = ['this_hour', 'today', 'this_week', 'this_month'] as const;

  function haikuCost(agg: { input_tokens?: number; output_tokens?: number; cache_read_tokens?: number; cache_write_tokens?: number }): number {
    return (
      ((agg.input_tokens ?? 0) * HAIKU_INPUT +
        (agg.output_tokens ?? 0) * HAIKU_OUTPUT +
        (agg.cache_read_tokens ?? 0) * HAIKU_CACHE_READ +
        (agg.cache_write_tokens ?? 0) * HAIKU_CACHE_WRITE) /
      1_000_000
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-lg font-semibold flex items-center gap-2">
            <BarChart3 size={20} />
            Auri Token Usage
          </h3>
          <p className="text-xs text-base-content/50 mt-0.5">
            Agent-level totals (all modes). Roleplay runs on Haiku — cost estimates use Haiku pricing.
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fetchTelemetry()}
          disabled={telemetryLoading}
        >
          <RefreshCw size={16} className={telemetryLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {telemetryError && (
        <div className="alert alert-error text-sm"><span>{telemetryError}</span></div>
      )}

      {telemetryLoading && !telemetryData ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner loading-md" />
        </div>
      ) : telemetryData ? (
        <div className="space-y-4">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            {periods.filter((p) => totals[p]).map((period) => {
              const agg = totals[period];
              const cost = haikuCost(agg);
              return (
                <div key={period} className="card bg-base-200 shadow compact">
                  <div className="card-body p-4">
                    <h4 className="font-semibold text-sm text-primary capitalize">
                      {period.replace(/_/g, ' ')}
                    </h4>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm mt-1">
                      <span className="text-base-content/70">Invocations</span>
                      <span className="font-mono">{fmtNum(agg.invocation_count)}</span>
                      <span className="text-base-content/70">Input</span>
                      <span className="font-mono">{fmtNum(agg.input_tokens)}</span>
                      <span className="text-base-content/70">Output</span>
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
                      <span className="text-base-content/70 font-medium">Est. cost</span>
                      <span className="font-mono font-medium text-warning">${cost.toFixed(4)}</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>

          {/* Conversation history — show entries with high token counts likely from roleplay */}
          <div>
            <h4 className="font-semibold text-sm mb-2 flex items-center gap-2">
              <MessageSquare size={16} />
              Recent invocations
              <span className="badge badge-ghost badge-xs">
                {telemetryData.history.length}
              </span>
            </h4>
            {telemetryData.history.length > 0 ? (
              <div className="bg-base-200 rounded-lg overflow-hidden">
                <div className="overflow-x-auto max-h-72 overflow-y-auto">
                  <table className="table table-xs table-pin-rows">
                    <thead>
                      <tr>
                        <th>Time (UTC)</th>
                        <th className="text-right">Input</th>
                        <th className="text-right">Output</th>
                        <th className="text-right">Cache R</th>
                        <th className="text-right">Cache W</th>
                        <th className="text-right">Cycles</th>
                        <th className="text-right">Est $</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...telemetryData.history]
                        .sort((a, b) => (b.timestamp ?? 0) - (a.timestamp ?? 0))
                        .slice(0, 50)
                        .map((entry, i) => {
                          const tu = entry.metrics?.token_usage ?? {};
                          const cost = haikuCost(tu);
                          const ts = entry.timestamp
                            ? new Date(entry.timestamp * 1000).toISOString().replace('T', ' ').slice(0, 19)
                            : '—';
                          return (
                            <tr key={i}>
                              <td className="text-xs whitespace-nowrap">{ts}</td>
                              <td className="font-mono text-right">{fmtNum(tu.input_tokens)}</td>
                              <td className="font-mono text-right">{fmtNum(tu.output_tokens)}</td>
                              <td className="font-mono text-right text-info">
                                {tu.cache_read_tokens ? fmtNum(tu.cache_read_tokens) : '—'}
                              </td>
                              <td className="font-mono text-right text-info">
                                {tu.cache_write_tokens ? fmtNum(tu.cache_write_tokens) : '—'}
                              </td>
                              <td className="font-mono text-right">
                                {entry.metrics?.cycle_count ?? '—'}
                              </td>
                              <td className="font-mono text-right text-warning">${cost.toFixed(4)}</td>
                            </tr>
                          );
                        })}
                    </tbody>
                  </table>
                </div>
              </div>
            ) : (
              <p className="text-base-content/50 text-sm py-2">
                No invocation history yet.
              </p>
            )}
          </div>

          <div className="alert alert-info py-2 text-xs">
            <span>
              Cost estimates use Claude Haiku 4.5 pricing ($0.80/$4.00/$0.08/$1.00 per 1M
              input/output/cache-read/cache-write). Actual cost depends on the active model.
            </span>
          </div>
        </div>
      ) : (
        <div className="text-center py-8 text-base-content/50">
          <BarChart3 size={40} className="mx-auto mb-3 opacity-40" />
          <p>No telemetry data — make sure the agent is running.</p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main AuriTab
// ---------------------------------------------------------------------------

export function AuriTab() {
  const [subTab, setSubTab] = useState<SubTab>('overview');

  const subTabs: { id: SubTab; label: string }[] = [
    { id: 'overview', label: 'Overview' },
    { id: 'persona', label: 'Persona Editor' },
    { id: 'analytics', label: 'Analytics' },
  ];

  return (
    <div className="p-6 h-full overflow-y-auto">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <LionIcon size={28} className="text-primary" />
        <div>
          <h2 className="text-xl font-bold">Auri</h2>
          <p className="text-sm text-base-content/60">
            Android lion companion — roleplay sessions, persona, analytics
          </p>
        </div>
      </div>

      {/* Sub-tab bar */}
      <div className="tabs tabs-bordered mb-6">
        {subTabs.map((t) => (
          <button
            key={t.id}
            className={`tab ${subTab === t.id ? 'tab-active' : ''}`}
            onClick={() => setSubTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Sub-tab content */}
      {subTab === 'overview' && <OverviewTab />}
      {subTab === 'persona' && <PersonaTab />}
      {subTab === 'analytics' && <AnalyticsTab />}
    </div>
  );
}
