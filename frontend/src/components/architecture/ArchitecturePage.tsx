export function ArchitecturePage() {
  return (
    <div className="p-4 md:p-8 bg-slate-50 text-slate-900 min-h-full">
      {/* Header */}
      <header className="max-w-6xl mx-auto mb-10">
        <div className="flex items-center gap-3 mb-2">
          <div className="bg-sky-600 p-2 rounded-lg text-white">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-slate-900">
            Meridyen <span className="text-sky-600">Sandbox</span>
          </h1>
        </div>
        <p className="text-slate-600 text-lg">Comprehensive Security Architecture & Deployment Matrix</p>
      </header>

      <main className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-8">

        {/* Deployment Modes */}
        <section className="lg:col-span-12">
          <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
            <svg className="w-5 h-5 text-sky-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9" />
            </svg>
            Deployment Modes
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Cloud Mode */}
            <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-5 rounded-xl border-l-4 border-l-sky-500">
              <div className="flex justify-between items-start mb-3">
                <h3 className="font-bold text-lg">1. Cloud Mode</h3>
                <span className="px-2 py-1 bg-sky-100 text-sky-700 text-xs font-bold rounded">Managed</span>
              </div>
              <p className="text-sm text-slate-600 mb-4">Sandbox runs on Meridyen cloud infrastructure. Best for rapid scaling.</p>
              <ul className="space-y-2 text-xs text-slate-500">
                <li className="flex items-center gap-2">
                  <svg className="w-3 h-3 text-green-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                  HTTPS + mTLS connectivity
                </li>
                <li className="flex items-center gap-2">
                  <svg className="w-3 h-3 text-green-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                  Auto-scaling & Monitoring
                </li>
              </ul>
            </div>

            {/* Hybrid Mode */}
            <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-5 rounded-xl border-l-4 border-l-indigo-500">
              <div className="flex justify-between items-start mb-3">
                <h3 className="font-bold text-lg">2. Hybrid Mode</h3>
                <span className="px-2 py-1 bg-indigo-100 text-indigo-700 text-xs font-bold rounded">On-Premise</span>
              </div>
              <p className="text-sm text-slate-600 mb-4">Docker container locally; Inference via Cloud. Data never leaves your network.</p>
              <ul className="space-y-2 text-xs text-slate-500">
                <li className="flex items-center gap-2">
                  <svg className="w-3 h-3 text-green-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                  Outbound HTTPS only
                </li>
                <li className="flex items-center gap-2">
                  <svg className="w-3 h-3 text-green-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                  Local DB access
                </li>
              </ul>
            </div>

            {/* Airgapped Mode */}
            <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-5 rounded-xl border-l-4 border-l-slate-800">
              <div className="flex justify-between items-start mb-3">
                <h3 className="font-bold text-lg">3. Airgapped Mode</h3>
                <span className="px-2 py-1 bg-slate-200 text-slate-800 text-xs font-bold rounded">Isolated</span>
              </div>
              <p className="text-sm text-slate-600 mb-4">Zero external connectivity. Local LLM via Ollama. Maximum security.</p>
              <ul className="space-y-2 text-xs text-slate-500">
                <li className="flex items-center gap-2">
                  <svg className="w-3 h-3 text-green-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                  Internal-only Docker network
                </li>
                <li className="flex items-center gap-2">
                  <svg className="w-3 h-3 text-green-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" /></svg>
                  No DNS resolution
                </li>
              </ul>
            </div>
          </div>
        </section>

        {/* Architecture Diagram */}
        <section className="lg:col-span-8">
          <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-6 rounded-2xl h-full">
            <h3 className="text-lg font-bold mb-6 flex items-center gap-2">
              <svg className="w-5 h-5 text-sky-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" />
              </svg>
              Interactive Architecture
            </h3>

            <div className="relative w-full overflow-hidden bg-slate-50 rounded-xl border border-slate-200" style={{ minHeight: '480px' }}>
              <svg viewBox="0 0 800 520" className="w-full h-full">
                {/* Background: Client Network */}
                <rect x="10" y="50" width="280" height="420" rx="10" fill="#f1f5f9" stroke="#cbd5e1" />
                <text x="20" y="40" fill="#94a3b8" style={{ fontSize: '11px', fontWeight: 700 }}>CLIENT NETWORK (HYBRID/AIRGAPPED)</text>

                {/* Background: Meridyen Cloud */}
                <rect x="510" y="50" width="280" height="420" rx="10" fill="#f0f9ff" stroke="#bae6fd" />
                <text x="520" y="40" fill="#7dd3fc" style={{ fontSize: '11px', fontWeight: 700 }}>MERIDYEN CLOUD PLATFORM</text>

                {/* ---- MERIDYEN SIDE ---- */}

                {/* User Browser */}
                <rect x="580" y="75" width="140" height="55" rx="8" fill="white" stroke="#0ea5e9" strokeWidth="2" />
                <text x="610" y="100" style={{ fontSize: '12px', fontWeight: 600, fill: '#1e293b' }}>User Browser</text>
                <text x="615" y="118" style={{ fontSize: '10px', fill: '#64748b' }}>Chat / Data Sources</text>

                {/* AI Agents */}
                <rect x="580" y="175" width="140" height="55" rx="8" fill="white" stroke="#0ea5e9" strokeWidth="2" />
                <text x="614" y="198" style={{ fontSize: '12px', fontWeight: 600, fill: '#1e293b' }}>AI Agents</text>
                <text x="595" y="216" style={{ fontSize: '9px', fill: '#64748b' }}>LangGraph Multi-Agent</text>

                {/* Meridyen Backend */}
                <rect x="580" y="280" width="140" height="75" rx="8" fill="white" stroke="#0ea5e9" strokeWidth="2" />
                <text x="595" y="303" style={{ fontSize: '12px', fontWeight: 600, fill: '#1e293b' }}>Meridyen Backend</text>
                <text x="620" y="320" style={{ fontSize: '10px', fill: '#64748b' }}>Sandbox Proxy</text>
                <text x="600" y="340" style={{ fontSize: '8px', fill: '#64748b' }}>Auth + Task Routing</text>

                {/* Flow: User to Agents */}
                <path d="M 650 130 L 650 175" fill="none" stroke="#94a3b8" strokeWidth="2" strokeDasharray="5" className="animate-flow" />
                <text x="655" y="157" style={{ fontSize: '8px', fill: '#64748b' }}>Question</text>

                {/* Flow: Agents to Backend */}
                <path d="M 650 230 L 650 280" fill="none" stroke="#94a3b8" strokeWidth="2" strokeDasharray="5" className="animate-flow" />
                <text x="655" y="260" style={{ fontSize: '8px', fill: '#64748b' }}>Execute SQL</text>

                {/* ---- CLIENT SIDE ---- */}

                {/* Sandbox Container */}
                <rect x="30" y="155" width="230" height="150" rx="12" fill="white" stroke="#6366f1" strokeWidth="3" />
                <text x="95" y="180" style={{ fontSize: '14px', fontWeight: 700, fill: '#4338ca' }}>SANDBOX</text>

                {/* Sandbox sub-items */}
                <rect x="45" y="190" width="95" height="35" rx="6" fill="#eef2ff" stroke="#c7d2fe" />
                <text x="56" y="212" style={{ fontSize: '10px', fontWeight: 600, fill: '#4338ca' }}>SQL Engine</text>

                <rect x="150" y="190" width="95" height="35" rx="6" fill="#eef2ff" stroke="#c7d2fe" />
                <text x="155" y="212" style={{ fontSize: '10px', fontWeight: 600, fill: '#4338ca' }}>Python Engine</text>

                <circle cx="50" cy="248" r="4" fill="#10b981" />
                <text x="60" y="252" style={{ fontSize: '9px', fill: '#64748b' }}>AST Static Analysis</text>

                <circle cx="50" cy="268" r="4" fill="#10b981" />
                <text x="60" y="272" style={{ fontSize: '9px', fill: '#64748b' }}>Process Isolation (RLIMIT)</text>

                <circle cx="50" cy="288" r="4" fill="#10b981" />
                <text x="60" y="292" style={{ fontSize: '9px', fill: '#64748b' }}>Sensitive Column Masking</text>

                {/* Database */}
                <rect x="60" y="370" width="170" height="50" rx="6" fill="#e2e8f0" stroke="#94a3b8" />
                <text x="85" y="393" style={{ fontSize: '12px', fontWeight: 600, fill: '#1e293b' }}>Client Databases</text>
                <text x="80" y="410" style={{ fontSize: '9px', fill: '#64748b' }}>PostgreSQL, MySQL, etc.</text>

                {/* Auth badge on sandbox */}
                <rect x="170" y="140" width="95" height="22" rx="4" fill="#fef3c7" stroke="#f59e0b" />
                <text x="180" y="155" style={{ fontSize: '8px', fontWeight: 600, fill: '#92400e' }}>sb_ Key Required</text>

                {/* ---- FLOWS ---- */}

                {/* Flow: Backend to Sandbox (Task Execution - main flow) */}
                <path d="M 580 310 L 260 240" fill="none" stroke="#6366f1" strokeWidth="2.5" strokeDasharray="6" className="animate-flow" />
                {/* Label background for readability */}
                <rect x="345" y="255" width="130" height="30" rx="4" fill="white" stroke="#e2e8f0" />
                <text x="355" y="270" style={{ fontSize: '9px', fontWeight: 600, fill: '#4338ca' }}>Execute SQL/Python</text>
                <text x="360" y="281" style={{ fontSize: '8px', fill: '#64748b' }}>+ X-API-Key header</text>

                {/* Flow: Sandbox returns results to Backend */}
                <path d="M 260 260 L 580 330" fill="none" stroke="#10b981" strokeWidth="2" strokeDasharray="4" className="animate-flow" />
                <rect x="345" y="295" width="130" height="18" rx="4" fill="white" stroke="#e2e8f0" />
                <text x="352" y="307" style={{ fontSize: '8px', fontWeight: 600, fill: '#059669' }}>Masked Results + Charts</text>

                {/* Flow: Sandbox validates key with Backend */}
                <path d="M 260 175 C 410 120, 510 120, 580 175" fill="none" stroke="#f59e0b" strokeWidth="1.5" strokeDasharray="3" />
                <rect x="365" y="108" width="100" height="18" rx="4" fill="#fef3c7" stroke="#f59e0b" />
                <text x="375" y="120" style={{ fontSize: '8px', fontWeight: 600, fill: '#92400e' }}>Validate API Key</text>

                {/* Flow: Sandbox to DB */}
                <path d="M 145 305 L 145 370" fill="none" stroke="#6366f1" strokeWidth="2" />
                <text x="150" y="343" style={{ fontSize: '8px', fill: '#64748b' }}>Read-only</text>
                <text x="150" y="353" style={{ fontSize: '8px', fill: '#64748b' }}>SELECT only</text>

                {/* Flow: Results back up from DB */}
                <path d="M 160 370 L 160 305" fill="none" stroke="#10b981" strokeWidth="1.5" strokeDasharray="3" />

                {/* Legend */}
                <rect x="520" y="410" width="260" height="50" rx="6" fill="white" stroke="#e2e8f0" />
                <line x1="535" y1="428" x2="555" y2="428" stroke="#6366f1" strokeWidth="2.5" strokeDasharray="6" />
                <text x="560" y="432" style={{ fontSize: '9px', fill: '#64748b' }}>Task (SQL/Python execution)</text>
                <line x1="535" y1="445" x2="555" y2="445" stroke="#10b981" strokeWidth="2" strokeDasharray="4" />
                <text x="560" y="449" style={{ fontSize: '9px', fill: '#64748b' }}>Response (masked results)</text>
              </svg>

              <style>{`
                .animate-flow {
                  animation: flow 2s linear infinite;
                }
                @keyframes flow {
                  from { stroke-dashoffset: 20; }
                  to { stroke-dashoffset: 0; }
                }
              `}</style>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-4 text-xs text-slate-500 italic">
              <p>
                <svg className="w-3 h-3 inline mr-1" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" /></svg>
                Meridyen sends SQL/Python tasks to the sandbox for execution against client databases.
              </p>
              <p>
                <svg className="w-3 h-3 inline mr-1" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" /></svg>
                Results are masked (PII/sensitive columns) before returning to the platform.
              </p>
              <p>
                <svg className="w-3 h-3 inline mr-1" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M2.166 4.999A11.954 11.954 0 0010 1.944 11.954 11.954 0 0017.834 5c.11.65.166 1.32.166 2.001 0 5.225-3.34 9.67-8 11.317C5.34 16.67 2 12.225 2 7c0-.682.057-1.35.166-2.001zm11.541 3.708a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" /></svg>
                Database traffic never leaves the client network.
              </p>
            </div>
          </div>
        </section>

        {/* Defense in Depth */}
        <aside className="lg:col-span-4 space-y-4">
          <h3 className="text-lg font-bold flex items-center gap-2">
            <svg className="w-5 h-5 text-sky-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            Defense in Depth
          </h3>

          <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-4 rounded-xl border-l-4 hover:-translate-y-0.5 transition-transform border-l-green-500">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-xs font-bold text-green-600 uppercase">Layer 1</span>
              <h4 className="font-bold text-sm">Network Isolation</h4>
            </div>
            <p className="text-xs text-slate-600">Non-root user, read-only code, and container resource limits.</p>
          </div>

          <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-4 rounded-xl border-l-4 hover:-translate-y-0.5 transition-transform border-l-sky-500">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-xs font-bold text-sky-600 uppercase">Layer 2</span>
              <h4 className="font-bold text-sm">Auth Chain</h4>
            </div>
            <p className="text-xs text-slate-600">End-to-end validation. Hashed sb_ keys. No local caching.</p>
          </div>

          <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-4 rounded-xl border-l-4 hover:-translate-y-0.5 transition-transform border-l-amber-500">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-xs font-bold text-amber-600 uppercase">Layer 3</span>
              <h4 className="font-bold text-sm">Code Sandbox</h4>
            </div>
            <p className="text-xs text-slate-600">AST Analysis, Whitelisting, and OS-level process killing.</p>
          </div>

          <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-4 rounded-xl border-l-4 hover:-translate-y-0.5 transition-transform border-l-purple-500">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-xs font-bold text-purple-600 uppercase">Layer 4</span>
              <h4 className="font-bold text-sm">Data Protection</h4>
            </div>
            <p className="text-xs text-slate-600">Automatic column masking, row limits, and PII detection.</p>
          </div>

          <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm p-4 rounded-xl border-l-4 hover:-translate-y-0.5 transition-transform border-l-slate-500">
            <div className="flex items-center gap-3 mb-1">
              <span className="text-xs font-bold text-slate-600 uppercase">Layer 5</span>
              <h4 className="font-bold text-sm">Resource Hardening</h4>
            </div>
            <p className="text-xs text-slate-600">Hard CPU/RAM caps (2 cores, 2GB) and query timeouts.</p>
          </div>
        </aside>

        {/* Mode Matrix Table */}
        <section className="lg:col-span-12 overflow-x-auto">
          <h2 className="text-xl font-bold mb-4 flex items-center gap-2">
            <svg className="w-5 h-5 text-sky-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h18M3 14h18m-9-4v8m-7 0h14a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" />
            </svg>
            Mode Matrix
          </h2>
          <div className="bg-white/90 backdrop-blur-sm border border-slate-200 shadow-sm rounded-xl overflow-hidden">
            <table className="w-full text-left border-collapse text-slate-800">
              <thead className="bg-slate-100 text-slate-700 text-sm uppercase">
                <tr>
                  <th className="p-4">Aspect</th>
                  <th className="p-4">Cloud Mode</th>
                  <th className="p-4">Hybrid Mode</th>
                  <th className="p-4">Airgapped Mode</th>
                </tr>
              </thead>
              <tbody className="text-sm divide-y divide-slate-200">
                <tr>
                  <td className="p-4 font-bold bg-slate-100 text-slate-900">LLM Service</td>
                  <td className="p-4 text-slate-700">Meridyen-hosted</td>
                  <td className="p-4 text-slate-700">Meridyen-hosted</td>
                  <td className="p-4 text-slate-700">Local LLM</td>
                </tr>
                <tr>
                  <td className="p-4 font-bold bg-slate-100 text-slate-900">Database Access</td>
                  <td className="p-4 text-slate-700">Cloud DBs</td>
                  <td className="p-4 text-slate-700">Client DBs (local)</td>
                  <td className="p-4 text-slate-700">Client DBs (no internet)</td>
                </tr>
                <tr>
                  <td className="p-4 font-bold bg-slate-100 text-slate-900">Exfiltration Risk</td>
                  <td className="p-4"><span className="text-amber-600 font-semibold">Medium</span></td>
                  <td className="p-4"><span className="text-emerald-600 font-semibold">Low</span></td>
                  <td className="p-4"><span className="text-emerald-700 font-bold uppercase">Near-Zero</span></td>
                </tr>
                <tr>
                  <td className="p-4 font-bold bg-slate-100 text-slate-900">Network</td>
                  <td className="p-4 text-slate-700">Full Outbound</td>
                  <td className="p-4 text-slate-700">Outbound HTTPS</td>
                  <td className="p-4 text-slate-700">None (internal: true)</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* Technical Deep Dive */}
        <section className="lg:col-span-12 grid grid-cols-1 md:grid-cols-2 gap-8 mt-4">
          <div className="bg-slate-900 text-white p-6 rounded-2xl border border-slate-700">
            <h3 className="text-lg font-bold mb-4 text-sky-400">Python AST Protection</h3>
            <div className="bg-slate-800 p-4 rounded-lg font-mono text-xs overflow-x-auto space-y-2">
              <p className="text-pink-400"># Blocked Imports</p>
              <p className="text-slate-300">os, sys, subprocess, socket, requests, pickle</p>
              <br />
              <p className="text-pink-400"># Blocked Calls</p>
              <p className="text-slate-300">exec(), eval(), compile(), open(), __import__()</p>
              <br />
              <p className="text-sky-400"># Allowed (Whitelisted)</p>
              <p className="text-slate-300">pandas, numpy, math, json, datetime, plotly</p>
            </div>
          </div>

          <div className="bg-slate-900 text-white p-6 rounded-2xl border border-slate-700">
            <h3 className="text-lg font-bold mb-4 text-emerald-400">SQL Guardrails</h3>
            <div className="space-y-3 text-sm">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-emerald-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" /></svg>
                <span>Statement Whitelist: <strong>SELECT</strong> & <strong>WITH</strong> (CTEs) only</span>
              </div>
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-rose-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" /></svg>
                <span>Blocked: INSERT, UPDATE, DROP, ALTER</span>
              </div>
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-rose-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clipRule="evenodd" /></svg>
                <span>Injection Detection: Sleep(), Union All, Outfile</span>
              </div>
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-amber-500 flex-shrink-0" fill="currentColor" viewBox="0 0 20 20"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm1-12a1 1 0 10-2 0v4a1 1 0 00.293.707l2.828 2.829a1 1 0 101.415-1.415L11 9.586V6z" clipRule="evenodd" /></svg>
                <span>Hard Timeout: 300s query enforcement</span>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="max-w-6xl mx-auto mt-12 mb-8 text-center text-slate-400 text-sm">
        <p>Meridyen Security Architecture. Defense in Depth Documentation.</p>
      </footer>
    </div>
  )
}
