"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface LogEntry {
  timestamp: string;
  agent: string;
  event: string;
  level: string;
  message: string;
}

export interface Metrics {
  plddt_mean: number | null;
  steric_clashes: number | null;
}

export interface RunState {
  runId: string | null;
  status: string;
  iteration: number;
  mode: string;
  metrics: Metrics;
  logs: LogEntry[];
  finalPdbUrl: string | null;
  isRunning: boolean;
}

const TERMINAL_STATUSES = new Set([
  "completed_success",
  "completed_success_fallback",
  "completed_failure",
  "error",
]);

const INITIAL_STATE: RunState = {
  runId: null,
  status: "idle",
  iteration: 0,
  mode: "live",
  metrics: { plddt_mean: null, steric_clashes: null },
  logs: [],
  finalPdbUrl: null,
  isRunning: false,
};

export function useRunPoller() {
  const [state, setState] = useState<RunState>(INITIAL_STATE);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  }, []);

  const poll = useCallback(async (runId: string) => {
    try {
      const [statusRes, logsRes] = await Promise.all([
        fetch(`${API_URL}/api/status?run_id=${runId}`),
        fetch(`${API_URL}/api/logs?run_id=${runId}`),
      ]);

      if (!statusRes.ok || !logsRes.ok) return;

      const statusData = await statusRes.json();
      const logsData: LogEntry[] = await logsRes.json();

      const isTerminal = TERMINAL_STATUSES.has(statusData.status);

      setState((prev) => ({
        ...prev,
        status: statusData.status,
        iteration: statusData.iteration ?? prev.iteration,
        mode: statusData.mode ?? prev.mode,
        metrics: statusData.metrics ?? prev.metrics,
        logs: logsData,
        isRunning: !isTerminal,
      }));

      if (isTerminal) {
        // Fetch final result for PDB URL
        const resultRes = await fetch(`${API_URL}/api/result?run_id=${runId}`);
        if (resultRes.ok) {
          const resultData = await resultRes.json();
          setState((prev) => ({
            ...prev,
            finalPdbUrl: resultData.final_pdb_url
              ? `${API_URL}${resultData.final_pdb_url}`
              : null,
          }));
        }
        stopPolling();
      }
    } catch {
      // Network errors — keep polling
    }
  }, [stopPolling]);

  const startRun = useCallback(async () => {
    setState((prev) => ({ ...prev, isRunning: true, status: "starting", logs: [], finalPdbUrl: null }));

    const res = await fetch(`${API_URL}/api/start-loop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_id: "CXCL12" }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: "Unknown error" }));
      setState((prev) => ({
        ...prev,
        isRunning: false,
        status: "error",
        logs: [
          {
            timestamp: new Date().toISOString(),
            agent: "system",
            event: "start_error",
            level: "error",
            message: err.detail ?? "Failed to start run",
          },
        ],
      }));
      return;
    }

    const { run_id } = await res.json();
    setState((prev) => ({ ...prev, runId: run_id, status: "started" }));

    // Start polling
    stopPolling();
    intervalRef.current = setInterval(() => poll(run_id), 1000);
  }, [poll, stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return () => stopPolling();
  }, [stopPolling]);

  return { ...state, startRun };
}
