"use client";

import { LaunchButton } from "./components/LaunchButton";
import { LogFeed } from "./components/LogFeed";
import { MetricsPanel } from "./components/MetricsPanel";
import { MolstarViewer } from "./components/MolstarViewer";
import { StatusChip } from "./components/StatusChip";
import { useRunPoller } from "./hooks/useRunPoller";

export default function Home() {
  const { runId, status, iteration, mode, metrics, logs, finalPdbUrl, isRunning, startRun } =
    useRunPoller();

  return (
    <main className="min-h-screen bg-gray-950 text-gray-100 p-8 max-w-5xl mx-auto">
      {/* Header */}
      <header className="mb-8">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white tracking-tight">Agent Binder</h1>
            <p className="text-sm text-gray-500 mt-0.5">
              Autonomous peptide binder design &mdash; Target:{" "}
              <span className="text-indigo-400 font-medium">CXCL12</span>
            </p>
          </div>
          <StatusChip status={status} />
        </div>
        {runId && (
          <p className="text-xs text-gray-600 mt-2 font-mono">run: {runId}</p>
        )}
      </header>

      {/* Launch */}
      <section className="mb-6">
        <LaunchButton onLaunch={startRun} isRunning={isRunning} status={status} />
      </section>

      {/* Metrics */}
      <section className="mb-6">
        <MetricsPanel iteration={iteration} mode={mode} metrics={metrics} />
      </section>

      {/* Log Feed */}
      <section className="mb-6">
        <LogFeed logs={logs} />
      </section>

      {/* 3D Viewer */}
      <section>
        <div className="mb-2 flex items-center gap-2">
          <h2 className="text-sm font-medium text-gray-400 uppercase tracking-wider">
            Final Structure
          </h2>
          {finalPdbUrl && (
            <a
              href={finalPdbUrl}
              download
              className="text-xs text-indigo-400 hover:text-indigo-300 transition-colors"
            >
              Download PDB
            </a>
          )}
        </div>
        <MolstarViewer pdbUrl={finalPdbUrl} />
      </section>
    </main>
  );
}
