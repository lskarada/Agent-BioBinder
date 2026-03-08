"use client";

interface LaunchButtonProps {
  onLaunch: () => void;
  isRunning: boolean;
  status: string;
}

export function LaunchButton({ onLaunch, isRunning, status }: LaunchButtonProps) {
  const isIdle = !isRunning && status !== "starting";

  return (
    <button
      onClick={onLaunch}
      disabled={!isIdle}
      className={`
        px-6 py-3 rounded-lg font-semibold text-sm tracking-wide transition-all duration-200
        ${isIdle
          ? "bg-indigo-600 hover:bg-indigo-500 text-white cursor-pointer shadow-lg shadow-indigo-900/40"
          : "bg-gray-800 text-gray-500 cursor-not-allowed"
        }
      `}
    >
      {isRunning || status === "starting" ? (
        <span className="flex items-center gap-2">
          <span className="inline-block w-3 h-3 rounded-full bg-indigo-400 animate-pulse" />
          Running...
        </span>
      ) : (
        "Launch Agent Loop"
      )}
    </button>
  );
}
