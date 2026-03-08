"use client";

interface StatusChipProps {
  status: string;
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  idle: { label: "Idle", color: "bg-gray-700 text-gray-400" },
  starting: { label: "Starting", color: "bg-blue-900/50 text-blue-300" },
  started: { label: "Started", color: "bg-blue-900/50 text-blue-300" },
  strategist_running: { label: "Strategist", color: "bg-violet-900/50 text-violet-300" },
  architect_running: { label: "Architect", color: "bg-indigo-900/50 text-indigo-300" },
  awaiting_bio_api: { label: "Tamarind", color: "bg-cyan-900/50 text-cyan-300" },
  critic_running: { label: "Critic", color: "bg-amber-900/50 text-amber-300" },
  completed_success: { label: "Success", color: "bg-green-900/50 text-green-300" },
  completed_success_fallback: { label: "Success (Fallback)", color: "bg-teal-900/50 text-teal-300" },
  completed_failure: { label: "Failed", color: "bg-red-900/50 text-red-400" },
  error: { label: "Error", color: "bg-red-900/50 text-red-400" },
};

export function StatusChip({ status }: StatusChipProps) {
  const config = STATUS_CONFIG[status] ?? { label: status, color: "bg-gray-700 text-gray-300" };
  const isRunning = !["idle", "completed_success", "completed_success_fallback", "completed_failure", "error"].includes(status);

  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium ${config.color}`}>
      {isRunning && (
        <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse" />
      )}
      {config.label}
    </span>
  );
}
