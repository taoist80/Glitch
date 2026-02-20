import { useEffect } from 'react';
import { RefreshCw, Send, Users, MessageSquare, Globe } from 'lucide-react';
import { useAppStore } from '../store/useAppStore';

export function TelegramTab() {
  const { telegramConfig, telegramLoading, telegramError, fetchTelegramConfig } = useAppStore();

  useEffect(() => {
    fetchTelegramConfig();
  }, [fetchTelegramConfig]);

  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Send size={24} />
            Telegram
          </h2>
          <p className="text-sm text-base-content/60">
            Bot configuration and status
          </p>
        </div>
        <button
          className="btn btn-ghost btn-sm"
          onClick={() => fetchTelegramConfig()}
          disabled={telegramLoading}
        >
          <RefreshCw size={18} className={telegramLoading ? 'animate-spin' : ''} />
          Refresh
        </button>
      </div>

      {telegramError && (
        <div className="alert alert-error mb-4">
          <span>{telegramError}</span>
        </div>
      )}

      {telegramLoading && !telegramConfig ? (
        <div className="flex justify-center py-8">
          <span className="loading loading-spinner loading-lg"></span>
        </div>
      ) : telegramConfig ? (
        <div className="space-y-6">
          <div className="card bg-base-200">
            <div className="card-body">
              <h3 className="card-title text-lg">Bot Status</h3>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <span className="text-sm text-base-content/60">Status</span>
                  <div className="flex items-center gap-2 mt-1">
                    <div className={`w-3 h-3 rounded-full ${telegramConfig.enabled ? 'bg-success' : 'bg-error'}`} />
                    <span className="font-medium">{telegramConfig.enabled ? 'Enabled' : 'Disabled'}</span>
                  </div>
                </div>
                <div>
                  <span className="text-sm text-base-content/60">Mode</span>
                  <p className="font-medium capitalize">{telegramConfig.mode}</p>
                </div>
                {telegramConfig.bot_username && (
                  <div>
                    <span className="text-sm text-base-content/60">Bot Username</span>
                    <p className="font-medium">@{telegramConfig.bot_username}</p>
                  </div>
                )}
                {telegramConfig.owner_id && (
                  <div>
                    <span className="text-sm text-base-content/60">Owner ID</span>
                    <p className="font-medium font-mono">{telegramConfig.owner_id}</p>
                  </div>
                )}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="card bg-base-200">
              <div className="card-body">
                <h3 className="card-title text-lg flex items-center gap-2">
                  <MessageSquare size={20} />
                  DM Policy
                </h3>
                <div className="space-y-3">
                  <div>
                    <span className="text-sm text-base-content/60">Policy</span>
                    <p className="font-medium capitalize">{telegramConfig.dm_policy}</p>
                  </div>
                  <div>
                    <span className="text-sm text-base-content/60">Allowlist</span>
                    <p className="font-medium">
                      {telegramConfig.dm_allowlist.length} users
                    </p>
                  </div>
                </div>
              </div>
            </div>

            <div className="card bg-base-200">
              <div className="card-body">
                <h3 className="card-title text-lg flex items-center gap-2">
                  <Users size={20} />
                  Group Policy
                </h3>
                <div className="space-y-3">
                  <div>
                    <span className="text-sm text-base-content/60">Policy</span>
                    <p className="font-medium capitalize">{telegramConfig.group_policy}</p>
                  </div>
                  <div>
                    <span className="text-sm text-base-content/60">Require @mention</span>
                    <p className="font-medium">{telegramConfig.require_mention ? 'Yes' : 'No'}</p>
                  </div>
                  <div>
                    <span className="text-sm text-base-content/60">Allowlist</span>
                    <p className="font-medium">
                      {telegramConfig.group_allowlist.length} groups
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>

          {telegramConfig.webhook_url && (
            <div className="card bg-base-200">
              <div className="card-body">
                <h3 className="card-title text-lg flex items-center gap-2">
                  <Globe size={20} />
                  Webhook
                </h3>
                <p className="font-mono text-sm break-all">{telegramConfig.webhook_url}</p>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="text-center py-8 text-base-content/60">
          <Send size={48} className="mx-auto mb-4 opacity-50" />
          <p>Telegram bot not configured</p>
          <p className="text-sm mt-2">
            Set GLITCH_TELEGRAM_BOT_TOKEN to enable
          </p>
        </div>
      )}
    </div>
  );
}
