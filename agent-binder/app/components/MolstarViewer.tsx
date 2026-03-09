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
      <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", fontSize: 11, color: "#555555", fontFamily: "'Lucida Console', monospace" }}>
        Loading viewer...
      </div>
    ),
  }
);

export function MolstarViewer({ pdbUrl }: MolstarViewerProps) {
  if (!pdbUrl) {
    return null;
  }

  return (
    <div style={{ width: "100%", height: "100%", minHeight: 180, overflow: "hidden", background: "#0a0a0a" }}>
      <MolstarViewerInner pdbUrl={pdbUrl} />
    </div>
  );
}
