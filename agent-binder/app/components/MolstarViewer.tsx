"use client";

import dynamic from "next/dynamic";

interface MolstarViewerProps {
  pdbUrl: string | null;
}

// Inner component — loaded only in browser (Mol* uses browser APIs)
const MolstarViewerInner = dynamic(
  () => import("./MolstarViewerInner").then((m) => m.MolstarViewerInner),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm">
        Loading viewer...
      </div>
    ),
  }
);

export function MolstarViewer({ pdbUrl }: MolstarViewerProps) {
  if (!pdbUrl) {
    return (
      <div className="bg-gray-900 border border-gray-800 rounded-xl h-80 flex items-center justify-center">
        <p className="text-gray-600 text-sm">3D structure will appear here after run completes</p>
      </div>
    );
  }

  return (
    <div className="bg-gray-900 border border-gray-800 rounded-xl h-80 overflow-hidden">
      <MolstarViewerInner pdbUrl={pdbUrl} />
    </div>
  );
}
