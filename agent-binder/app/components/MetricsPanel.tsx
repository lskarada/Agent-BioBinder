"use client";

import type { Metrics } from "../hooks/useRunPoller";

interface MetricsPanelProps {
  iteration: number;
  mode: string;
  metrics: Metrics;
}

function MetricItem({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-gray-500 uppercase tracking-wider">{label}</span>
      <span className="text-2xl font-bold text-gray-100 tabular-nums">{value}</span>
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  );
}

export function MetricsPanel({ iteration, mode, metrics }: MetricsPanelProps) {
  const plddt = metrics.plddt_mean !== null ? metrics.plddt_mean.toFixed(1) : "—";
  const clashes = metrics.steric_clashes !== null ? String(metrics.steric_clashes) : "—";
  const plddt_color =
    metrics.plddt_mean === null
      ? "text-gray-100"
      : metrics.plddt_mean > 80
      ? "text-green-400"
      : metrics.plddt_mean > 70
      ? "text-amber-400"
      : "text-red-400";

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl p-5 grid grid-cols-2 gap-x-8 gap-y-5">
      <div className="flex flex-col gap-0.5">
        <span className="text-xs text-gray-500 uppercase tracking-wider">pLDDT</span>
        <span className={`text-2xl font-bold tabular-nums ${plddt_color}`}>{plddt}</span>
        <span className="text-xs text-gray-500">confidence score</span>
      </div>

      <div className="flex flex-col gap-0.5">
        <span className="text-xs text-gray-500 uppercase tracking-wider">Clashes</span>
        <span className={`text-2xl font-bold tabular-nums ${metrics.steric_clashes === 0 && metrics.steric_clashes !== null ? "text-green-400" : metrics.steric_clashes !== null ? "text-red-400" : "text-gray-100"}`}>
          {clashes}
        </span>
        <span className="text-xs text-gray-500">steric clashes</span>
      </div>

      <MetricItem label="Iteration" value={iteration > 0 ? String(iteration) : "—"} sub="current cycle" />

      <div className="flex flex-col gap-0.5">
        <span className="text-xs text-gray-500 uppercase tracking-wider">Mode</span>
        <span className={`text-sm font-semibold mt-1 px-2 py-0.5 rounded inline-block w-fit ${
          mode === "fallback"
            ? "bg-amber-900/50 text-amber-300"
            : "bg-green-900/50 text-green-300"
        }`}>
          {mode}
        </span>
      </div>
    </div>
  );
}
