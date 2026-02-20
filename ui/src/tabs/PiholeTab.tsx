import { Shield, BarChart3, List, Ban } from 'lucide-react';

export function PiholeTab() {
  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Shield size={24} />
            Pi-hole DNS
          </h2>
          <p className="text-sm text-base-content/60">
            DNS filtering and statistics
          </p>
        </div>
        <span className="badge badge-secondary">Coming Soon</span>
      </div>

      <div className="hero bg-base-200 rounded-lg py-12">
        <div className="hero-content text-center">
          <div className="max-w-md">
            <Shield size={64} className="mx-auto mb-4 text-primary opacity-50" />
            <h3 className="text-2xl font-bold">Pi-hole Integration</h3>
            <p className="py-4 text-base-content/70">
              Monitor DNS queries, blocked domains, and manage your blocklists 
              directly from the Glitch dashboard.
            </p>
            
            <div className="grid grid-cols-2 gap-4 mt-6">
              <div className="card bg-base-300">
                <div className="card-body items-center py-4">
                  <BarChart3 size={32} className="text-primary" />
                  <span className="text-sm font-medium">Statistics</span>
                  <span className="text-xs text-base-content/60">
                    Query counts & rates
                  </span>
                </div>
              </div>
              <div className="card bg-base-300">
                <div className="card-body items-center py-4">
                  <Ban size={32} className="text-primary" />
                  <span className="text-sm font-medium">Blocked</span>
                  <span className="text-xs text-base-content/60">
                    Top blocked domains
                  </span>
                </div>
              </div>
              <div className="card bg-base-300">
                <div className="card-body items-center py-4">
                  <List size={32} className="text-primary" />
                  <span className="text-sm font-medium">Query Log</span>
                  <span className="text-xs text-base-content/60">
                    Recent DNS queries
                  </span>
                </div>
              </div>
              <div className="card bg-base-300">
                <div className="card-body items-center py-4">
                  <Shield size={32} className="text-primary" />
                  <span className="text-sm font-medium">Blocklists</span>
                  <span className="text-xs text-base-content/60">
                    Manage lists
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
