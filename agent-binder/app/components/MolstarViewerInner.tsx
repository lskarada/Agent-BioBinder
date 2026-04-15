"use client";

import { useEffect, useRef } from "react";

interface MolstarViewerInnerProps {
  pdbUrl: string;
}

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
        const { ColorNames } = await import("molstar/lib/mol-util/color/names");

        if (cancelled || !containerRef.current) return;

        const plugin = await createPluginUI({
          target: containerRef.current,
          spec: {
            ...DefaultPluginUISpec(),
            layout: {
              initial: {
                isExpanded: false,
                showControls: false,
                regionState: {
                  bottom: "hidden",
                  left: "hidden",
                  right: "hidden",
                  top: "hidden",
                },
              },
            },
            config: [
              [PluginConfig.VolumeStreaming.Enabled, false],
              [PluginConfig.Viewport.ShowAnimation, false],
              [PluginConfig.Viewport.ShowTrajectoryControls, false],
            ],
          },
          render: renderReact18,
        });

        pluginRef.current = plugin;
        if (cancelled) { plugin.dispose(); return; }

        // Dark background
        await plugin.canvas3d?.setProps({
          renderer: { backgroundColor: ColorNames.black },
        });

        const data = await plugin.builders.data.download({ url: pdbUrl, isBinary: false });
        const trajectory = await plugin.builders.structure.parseTrajectory(data, "pdb");
        await plugin.builders.structure.hierarchy.applyPreset(trajectory, "default");

      } catch (err) {
        console.error("Mol* init error:", err);
        if (containerRef.current && !cancelled) {
          containerRef.current.innerHTML =
            '<div style="color:#6b7280;font-size:12px;padding:16px;text-align:center;">3D viewer unavailable.</div>';
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

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        overflow: "hidden",
        background: "#000000",
      }}
    />
  );
}
