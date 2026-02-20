import { Wifi, Router, Users, Activity } from 'lucide-react';

export function UnifiTab() {
  return (
    <div className="p-6 h-full overflow-y-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold flex items-center gap-2">
            <Wifi size={24} />
            Unifi Network
          </h2>
          <p className="text-sm text-base-content/60">
            Network devices and status
          </p>
        </div>
        <span className="badge badge-secondary">Coming Soon</span>
      </div>

      <div className="hero bg-base-200 rounded-lg py-12">
        <div className="hero-content text-center">
          <div className="max-w-md">
            <Wifi size={64} className="mx-auto mb-4 text-primary opacity-50" />
            <h3 className="text-2xl font-bold">Unifi Integration</h3>
            <p className="py-4 text-base-content/70">
              Monitor your Unifi network devices, clients, and traffic statistics 
              directly from the Glitch dashboard.
            </p>
            
            <div className="grid grid-cols-2 gap-4 mt-6">
              <div className="card bg-base-300">
                <div className="card-body items-center py-4">
                  <Router size={32} className="text-primary" />
                  <span className="text-sm font-medium">Devices</span>
                  <span className="text-xs text-base-content/60">
                    Switches, APs, Gateways
                  </span>
                </div>
              </div>
              <div className="card bg-base-300">
                <div className="card-body items-center py-4">
                  <Users size={32} className="text-primary" />
                  <span className="text-sm font-medium">Clients</span>
                  <span className="text-xs text-base-content/60">
                    Connected devices
                  </span>
                </div>
              </div>
              <div className="card bg-base-300">
                <div className="card-body items-center py-4">
                  <Activity size={32} className="text-primary" />
                  <span className="text-sm font-medium">Traffic</span>
                  <span className="text-xs text-base-content/60">
                    Bandwidth stats
                  </span>
                </div>
              </div>
              <div className="card bg-base-300">
                <div className="card-body items-center py-4">
                  <Wifi size={32} className="text-primary" />
                  <span className="text-sm font-medium">Topology</span>
                  <span className="text-xs text-base-content/60">
                    Network map
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
