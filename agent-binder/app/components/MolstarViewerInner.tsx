"use client";

import { useEffect, useRef } from "react";

interface MolstarViewerInnerProps {
  pdbUrl: string;
}

/**
 * Mol* viewer inner component (browser-only).
 * TASK: Run `npm install molstar` before using.
 * Loaded via dynamic import in MolstarViewer.tsx (no SSR).
 */
export function MolstarViewerInner({ pdbUrl }: MolstarViewerInnerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pluginRef = useRef<any>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    let cancelled = false;

    async function init() {
      try {
        const { createPluginUI } = await import("molstar/lib/mol-plugin-ui");
        const { DefaultPluginUISpec } = await import("molstar/lib/mol-plugin-ui/spec");
        const { PluginConfig } = await import("molstar/lib/mol-plugin/config");
        const { renderReact18 } = await import("molstar/lib/mol-plugin-ui/react18");

        if (cancelled || !containerRef.current) return;

        const plugin = await createPluginUI({
          target: containerRef.current,
          spec: {
            ...DefaultPluginUISpec(),
            config: [[PluginConfig.VolumeStreaming.Enabled, false]],
          },
          render: renderReact18,
        });

        pluginRef.current = plugin;
        if (cancelled) { plugin.dispose(); return; }

        const data = await plugin.builders.data.download({ url: pdbUrl, isBinary: false });
        const trajectory = await plugin.builders.structure.parseTrajectory(data, "pdb");
        await plugin.builders.structure.hierarchy.applyPreset(trajectory, "default");

      } catch (err) {
        console.error("Mol* init error:", err);
        if (containerRef.current && !cancelled) {
          containerRef.current.innerHTML =
            '<div style="color:#6b7280;font-size:12px;padding:16px;text-align:center;">3D viewer unavailable.<br/>Run: npm install molstar</div>';
        }
      }
    }

    init();

    return () => {
      cancelled = true;
      try { pluginRef.current?.dispose(); } catch { /* ignore */ }
      pluginRef.current = null;
    };
  }, [pdbUrl]);

  return <div ref={containerRef} className="w-full h-full" />;
}
