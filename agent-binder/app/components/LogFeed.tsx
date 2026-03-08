"use client";

import { useEffect, useRef } from "react";
import type { LogEntry } from "../hooks/useRunPoller";

interface LogFeedProps {
  logs: LogEntry[];
}

const LEVEL_STYLES: Record<string, string> = {
  info: "text-gray-300",
  warning: "text-amber-400",
  error: "text-red-400",
};

const AGENT_STYLES: Record<string, string> = {
  strategist: "text-violet-400",
  architect: "text-indigo-400",
  tamarind: "text-cyan-400",
  critic: "text-amber-400",
  loop: "text-gray-400",
  system: "text-gray-500",
};

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

export function LogFeed({ logs }: LogFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [logs.length]);

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
      <div className="px-4 py-2 border-b border-gray-800 flex items-center gap-2">
        <span className="text-xs font-medium text-gray-400 uppercase tracking-wider">Agent Log</span>
        <span className="text-xs text-gray-600 tabular-nums">{logs.length} entries</span>
      </div>
      <div className="h-64 overflow-y-auto p-3 font-mono text-xs space-y-0.5">
        {logs.length === 0 ? (
          <p className="text-gray-600 italic">Waiting for run to start...</p>
        ) : (
          logs.map((entry, i) => (
            <div key={i} className="flex gap-2 items-start leading-relaxed">
              <span className="text-gray-600 shrink-0 w-20">{formatTime(entry.timestamp)}</span>
              <span className={`shrink-0 w-20 ${AGENT_STYLES[entry.agent] ?? "text-gray-400"}`}>
                [{entry.agent}]
              </span>
              <span className={LEVEL_STYLES[entry.level] ?? "text-gray-300"}>
                {entry.message}
              </span>
            </div>
          ))
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
