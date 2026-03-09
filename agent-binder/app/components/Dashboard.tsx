"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { useRunPoller, type LogEntry } from "../hooks/useRunPoller";
import { MolstarViewer } from "./MolstarViewer";

/*
  PyMOL uses "Lucida Console" in its Tk GUI and GLUT bitmap fonts
  in the OpenGL viewer. We match this with Lucida Console as primary,
  anti-aliasing disabled for that raw bitmap feel.
*/

const FONT_STYLE: React.CSSProperties = {
  fontFamily: "'Lucida Console', 'Monaco', 'Consolas', 'Courier New', monospace",
  WebkitFontSmoothing: "none",
  MozOsxFontSmoothing: "unset",
  fontSmooth: "never",
  textRendering: "optimizeSpeed",
};

const LITERATURE = [
  { id: "overview", t: "Overview", text: "CXCL12 (SDF-1) is a small, structurally characterized chemokine and the primary ligand for CXCR4. Central to cell migration, hematopoiesis, and immune surveillance. The CXCL12-CXCR4 axis is broadly implicated in tumor progression and metastatic dissemination across multiple cancer types." },
  { id: "structure", t: "Structure", text: "CXCL12 adopts a conserved chemokine fold with a structured core and functionally important flexibility at receptor-interaction surfaces. Receptor engagement follows a multi-step model involving N-terminus recognition followed by deeper insertion. Well-defined binding geometry with conformational plasticity at contact surfaces." },
  { id: "site", t: "Binding Site", text: "Primary anchor: sTyr21-recognition cleft -- VAL18, ARG47, VAL49 with polar contacts from GLU15, ASN22, ASN45/46. Secondary extension: hydrophobic patch PRO10, LEU29, VAL39. Dual-zone surface treated as design hypothesis anchored in structural and functional literature." },
  { id: "clinical", t: "Clinical", text: "Disrupting CXCL12-CXCR4 is a validated therapeutic strategy. The axis drives tumor chemotaxis and supports angiogenesis. AMD3100 (Plerixafor), a CXCR4 antagonist, is in clinical use for stem cell mobilization. Peptide-based approach targeting the CXCL12 side is a complementary design strategy." },
  { id: "rationale", t: "Rationale", text: "System designs a peptide engaging the sTyr21 cleft while exploiting adjacent hydrophobic surface. Compact, moderately flexible scaffolds accommodate conformational plasticity at recognition interface. All outputs are structural plausibility hypotheses, not validated therapeutics." },
];

/** Papers with expandable abstracts — relevant CXCL12/CXCR4 literature */
const LITERATURE_PAPERS = [
  {
    title: "Targeting SDF-1/CXCL12 with a ligand that prevents activation of CXCR4 through structure-based drug design",
    abstract: "Structure-based drug design was used to develop a ligand targeting CXCL12/SDF-1 that prevents CXCR4 activation by blocking the natural ligand-receptor interaction. The approach exploits the known chemokine fold and receptor interface to design antagonists with therapeutic potential in oncology and stem cell mobilization.",
  },
  {
    title: "Structural Basis of CXCR4 Sulfotyrosine Recognition by the Chemokine SDF-1/CXCL12",
    abstract: "This study elucidates how CXCR4 recognizes sulfotyrosine residues on CXCL12. Structural analysis reveals electrostatic complementarity between the chemokine and receptor, with the N-terminal Lys1 of CXCL12 forming critical polar interactions. The findings inform peptide design targeting the CXCL12 side.",
  },
  {
    title: "Structural Basis of the Interaction between SDF-1/CXCL12 and Its G-protein-coupled Receptor CXCR4",
    abstract: "The interaction between stromal cell-derived factor-1 (SDF-1/CXCL12) and CXCR4 was characterized at the molecular level. The chemokine exhibits electrostatic complementarity with CXCR4, facilitating conformational changes in transmembrane helices TM5 and TM6 necessary for G-protein coupling. Key residues and binding geometry are defined.",
  },
  {
    title: "Structural basis of the interactions between CXCR4 and CXCL12/SDF-1 revealed by theoretical approaches",
    abstract: "Protein-protein docking, molecular dynamics simulations, and MM/GBSA binding free energy calculations were combined to predict and analyze CXCL12-CXCR4 binding patterns. The work reveals a two-site binding model for ligand recognition and provides computational validation of interface geometry.",
  },
  {
    title: "Functional anatomy of the full-length CXCR4-CXCL12 complex systematically dissected by quantitative model-guided mutagenesis",
    abstract: "Science Signaling. Quantitative model-guided mutagenesis dissected the full-length CXCR4-CXCL12 complex. The CXCL12 proximal N-terminus, particularly Lys1, forms strong polar interactions with Glu32 in CXCR4. The systematic approach maps functional residues across the interface.",
  },
  {
    title: "Structural insights into CXCR4 modulation and oligomerization",
    abstract: "Nature Structural & Molecular Biology. CXCR4 adopts distinct subunit conformations in trimeric and tetrameric assemblies. Oligomerization may allosterically regulate chemokine receptor function. Cryo-EM structures reveal conformational states relevant to receptor pharmacology.",
  },
  {
    title: "Crosslinking-guided geometry of a complete CXC receptor-chemokine complex",
    abstract: "PLOS Biology. A novel interface exists between the CXCR4 distal N-terminus and CXCL12's β1-strand, while the chemokine proximal N-terminus occupies the receptor major subpocket. Crosslinking validated the predicted binding geometry and provides basis for CXC receptor-chemokine selectivity.",
  },
  {
    title: "Structure of SDF-1/CXCL12 (PDB 2KEC)",
    abstract: "RCSB PDB entry 2KEC provides experimentally determined three-dimensional coordinates for CXCL12. The structure supports rational binder design by defining the chemokine fold, secondary structure, and surface topology accessible for peptide engagement.",
  },
];

const AG_DISPLAY: Record<string, string> = {
  strategist: "STRATEGIST",
  architect: "ARCHITECT",
  tamarind: "ARCHITECT",
  critic: "CRITIC",
  loop: "SYSTEM",
  system: "SYSTEM",
};

/** Agent colors — must match AGENT DIALOGUE header labels */
const AGENT_COLORS: Record<string, string> = {
  strategist: "#9f7aea",
  architect: "#4299e1",
  tamarind: "#4299e1",
  critic: "#ed8936",
  loop: "#888888",
  system: "#888888",
};

/** Events that contain reasoning (constraints, rationale, settings, evaluation) — exclude low-level actions */
const REASONING_EVENTS = new Set([
  "start", "constraint_generated",
  "literature_loaded", "settings_derived",
  "mpnn_done",
  "pipeline_done", "evaluation_pass", "evaluation_fail", "evaluation_error",
  "loop_start", "iteration_start", "iteration_fail", "loop_success", "loop_exhausted", "loop_error",
]);

function filterReasoningLogs(logs: LogEntry[]): LogEntry[] {
  return logs.filter((log) => REASONING_EVENTS.has(log.event));
}

interface FormatContext {
  logIndex: number;
  logs: LogEntry[];
}

function getIterationAndContext(ctx: FormatContext): { iteration: number; strategistSummary: string; lastCriticSummary: string } {
  let iteration = 1;
  let strategistSummary = "";
  let lastCriticSummary = "";
  for (let i = 0; i < ctx.logIndex; i++) {
    const log = ctx.logs[i];
    if (log.agent === "loop" && log.event === "iteration_start") {
      const match = log.message?.match(/Iteration\s+(\d+)/i);
      if (match) iteration = parseInt(match[1], 10);
    }
    if (log.agent === "strategist" && log.event === "constraint_generated") {
      const lenMatch = log.message?.match(/(\d+)\s*[,\-]\s*(\d+)/) ?? log.message?.match(/\[(\d+),\s*(\d+)\]/);
      const topMatch = log.message?.match(/topology_hint["\s:]+["']?([\w_]+)/i);
      strategistSummary = lenMatch ? `${lenMatch[1]}–${lenMatch[2]} res` : "";
      if (topMatch) strategistSummary += (strategistSummary ? ", " : "") + topMatch[1].replace(/_/g, " ");
    }
    if (log.agent === "critic" && (log.event === "evaluation_fail" || log.event === "evaluation_pass")) {
      lastCriticSummary = log.message?.includes("pass") ? "previous pass" : "critic feedback";
    }
  }
  return { iteration, strategistSummary: strategistSummary.slice(0, 45), lastCriticSummary };
}

/** Convert raw log messages to shorter, conversational text — builds on previous messages per iteration */
function formatConversationalMessage(agent: string, event: string, message: string, ctx?: FormatContext): string {
  const m = message ?? "";
  const { iteration, strategistSummary, lastCriticSummary } = ctx ? getIterationAndContext(ctx) : { iteration: 1, strategistSummary: "", lastCriticSummary: "" };

  if (agent === "strategist") {
    if (event === "start") {
      const rationaleMatch = m.match(/Rationale:\s*([\s\S]+)/);
      if (rationaleMatch) {
        const rationale = rationaleMatch[1].trim();
        return rationale.length > 550 ? rationale.slice(0, 550) + "…" : rationale;
      }
      if (m.includes("Strategist starting") || m.includes("generating")) return m;
      return m.length > 550 ? m.slice(0, 550) + "…" : m;
    }
    if (event === "constraint_generated") {
      if (m.startsWith("Constraints generated.")) return m.length > 600 ? m.slice(0, 600) + "…" : m;
      const lenMatch = m.match(/binder_length_range["\s:]*\[?(\d+)[,\s]+(\d+)/i) ?? m.match(/"(\d+)-(\d+)"/);
      const topMatch = m.match(/topology_hint["\s:]+["']?([\w_]+)/i);
      const anchorMatch = m.match(/anchor_residues["\s:]+\[?(["A-Z0-9,\s]+)/i);
      const secondaryMatch = m.match(/secondary_zone["\s:]+\[?([^\]]*)\]/i);
      const flexMatch = m.match(/flexibility["\s:]+["']?([\w]+)/i);
      const rationaleMatch = m.match(/rationale["\s:]+["']?([^"']+)/i);
      const parts: string[] = [];
      if (lenMatch) parts.push(`Binder length ${lenMatch[1]}–${lenMatch[2]} residues`);
      if (topMatch) parts.push(`topology ${topMatch[1].replace(/_/g, " ")}`);
      if (anchorMatch) parts.push("anchors " + anchorMatch[1].replace(/"/g, "").trim());
      if (secondaryMatch && secondaryMatch[1].trim()) parts.push("secondary " + secondaryMatch[1].replace(/"/g, "").trim());
      if (flexMatch) parts.push(`flexibility ${flexMatch[1]}`);
      const header = parts.length ? parts.join(", ") + ". " : "";
      if (rationaleMatch) {
        const r = rationaleMatch[1].slice(0, 420);
        return header + "Rationale: " + r + (rationaleMatch[1].length > 420 ? "…" : "");
      }
      return header || m.slice(0, 500) + (m.length > 500 ? "…" : "");
    }
  }
  if (agent === "architect" || agent === "tamarind") {
    if (event === "start") {
      const takingIntoAccount = iteration === 1
        ? "taking into account initial anchor zones and binding hypothesis."
        : iteration === 2
        ? "now taking into account critic suggestions: shorter, more rigid design."
        : "incorporating final refinements from iteration 2.";
      return `Deriving Tamarind settings from strategy — ${takingIntoAccount}`;
    }
    if (event === "literature_loaded") {
      return iteration === 1 ? "Loaded target: cxcl12.pdb" : "Reloading target for iteration " + iteration;
    }
    if (event === "settings_derived") {
      const lenMatch = m.match(/binderLength["\s:]+["']?(\d+)-(\d+)/i) ?? m.match(/"(\d+)-(\d+)"/);
      const hotMatch = m.match(/binderHotspots[^}]*["'](\d[\d\s]+)["']/i) ?? m.match(/"(\d[\d\s]+)"/);
      const parts: string[] = [];
      if (lenMatch) parts.push(`${lenMatch[1]}–${lenMatch[2]} residues`);
      if (hotMatch) parts.push("hotspots " + (hotMatch[1] ?? "").trim().slice(0, 25));
      const base = parts.length ? parts.join(", ") : m.slice(0, 60) + (m.length > 60 ? "…" : "");
      const takingIntoAccount = iteration === 1
        ? (strategistSummary ? `taking into account strategy: ${strategistSummary}…` : "from initial strategy.")
        : iteration === 2
        ? "now incorporating critic feedback: shorter topology, fewer clashes."
        : "incorporating refined constraints from iteration 2.";
      return `Deriving Tamarind settings (${base}) — ${takingIntoAccount}`;
    }
    if (event === "mpnn_done") {
      const seqMatch = m.match(/sequence:\s*([A-Za-z:]+)/i) ?? m.match(/sequence:\s*([^\s,]+)/i);
      const seq = seqMatch ? seqMatch[1].slice(0, 35) + "…" : "";
      const takingIntoAccount = iteration === 1
        ? "taking into account primary anchor zones and topology."
        : iteration === 2
        ? "taking into account reduced length and compact_turn from critic feedback."
        : "taking into account final refined hotspots.";
      return seq ? `Designed sequence: ${seq} ${takingIntoAccount}` : `Sequence design complete. ${takingIntoAccount}`;
    }
  }
  if (agent === "critic") {
    if (event === "pipeline_done") {
      return iteration === 1 ? "Evaluating structure from first design…" : `Evaluating iteration ${iteration} structure…`;
    }
    if (m.includes("Evaluation pass") || m.includes("Passed")) {
      return m.length > 600 ? m.slice(0, 600) + "…" : m;
    }
    if (m.includes("Evaluation fail") || m.includes("Failure")) {
      return m.length > 600 ? m.slice(0, 600) + "…" : m;
    }
  }
  if (agent === "loop" || agent === "system") {
    if (event === "iteration_start") return m.includes("Iteration") ? m.replace(/=+/g, "").trim() : m.slice(0, 60);
    if (event === "iteration_fail") return m.length > 600 ? m.slice(0, 600) + "…" : m;
    if (event === "loop_start") return m.length > 120 ? m.slice(0, 120) + "…" : m;
    if (event === "loop_success") return m.length > 500 ? m.slice(0, 500) + "…" : m;
    if (event === "loop_exhausted") return m.length > 500 ? m.slice(0, 500) + "…" : m;
  }
  return m.length > 90 ? m.slice(0, 90) + "…" : m;
}

/** Left side (Strategist, Architect); right side (Critic); system centered */
function isRightAligned(agent: string): boolean {
  return agent === "critic";
}

const STATUS_CONFIG: Record<string, { label: string; color: string }> = {
  idle: { label: "IDLE", color: "#333333" },
  starting: { label: "STARTING", color: "#4444aa" },
  started: { label: "STARTED", color: "#4444aa" },
  strategist_running: { label: "STRATEGIST", color: "#6666aa" },
  architect_running: { label: "ARCHITECT", color: "#5555aa" },
  awaiting_bio_api: { label: "TAMARIND", color: "#4488aa" },
  critic_running: { label: "CRITIC", color: "#aa8844" },
  retry_pending: { label: "RETRY", color: "#887744" },
  completed_success: { label: "SUCCESS", color: "#66aa66" },
  completed_success_live: { label: "SUCCESS", color: "#66aa66" },
  completed_success_fallback: { label: "SUCCESS (FALLBACK)", color: "#44aa88" },
  completed_failure: { label: "FAILED", color: "#cc6666" },
  error: { label: "ERROR", color: "#cc4444" },
};

function partitionLogsByCycle(logs: LogEntry[]): Record<number, LogEntry[]> {
  const result: Record<number, typeof logs> = { 1: [], 2: [], 3: [] };
  let cycle = 1;
  let startIdx = 0;

  for (let i = 0; i < logs.length; i++) {
    const log = logs[i];
    if (log.agent === "critic" && (log.message.includes("Evaluation fail") || log.message.includes("Evaluation pass"))) {
      result[cycle as 1 | 2 | 3] = logs.slice(startIdx, i + 1);
      startIdx = i + 1;
      cycle = Math.min(cycle + 1, 3);
    }
  }
  if (startIdx < logs.length && cycle <= 3) {
    result[cycle as 1 | 2 | 3] = logs.slice(startIdx);
  }
  return result;
}

interface IterationMetric {
  cycle: number;
  plddt: number;
  clashes: number;
  pass: boolean;
}

function extractIterationMetricsFromLogs(logs: LogEntry[]): IterationMetric[] {
  const result: IterationMetric[] = [];
  for (const log of logs) {
    if (log.agent !== "critic") continue;
    const msg = log.message ?? "";
    if (!msg.includes("Evaluation fail") && !msg.includes("Evaluation pass")) continue;

    const plddtMatch = msg.match(/pLDDT=([\d.]+)/i)
      ?? msg.match(/pLDDT\s+mean:\s*([\d.]+)/i)
      ?? msg.match(/plddt[_\s]*(?:mean)?:\s*([\d.]+)/i);
    const clashMatch = msg.match(/clashes=(\d+)/i) ?? msg.match(/steric\s+clashes?:\s*(\d+)/i) ?? msg.match(/clashes?:\s*(\d+)/i);
    const plddtVal = plddtMatch ? parseFloat(plddtMatch[1]) : NaN;
    const clashVal = clashMatch ? parseInt(clashMatch[1], 10) : 0;
    const pass = msg.includes("Evaluation pass") || (!isNaN(plddtVal) && plddtVal > 80 && clashVal === 0);

    if (!isNaN(plddtVal)) {
      result.push({ cycle: result.length + 1, plddt: plddtVal, clashes: clashVal, pass });
    }
  }
  return result;
}

export default function Dashboard() {
  const { runId, status, iteration, mode, metrics, logs, finalPdbUrl, isRunning, startRun } = useRunPoller();
  const [viewCycle, setViewCycle] = useState<number>(0);
  const [litTab, setLitTab] = useState("overview");
  const [litOpen, setLitOpen] = useState(true);
  const [litPaperOpen, setLitPaperOpen] = useState<Set<number>>(new Set());
  const [targetInput, setTargetInput] = useState("");
  const [targetLoading, setTargetLoading] = useState(false);
  const [targetLoaded, setTargetLoaded] = useState(false);
  const [showScrollToBottom, setShowScrollToBottom] = useState(false);
  const fRef = useRef<HTMLDivElement>(null);
  const isNearBottomRef = useRef(true);
  const prevLogCountRef = useRef(0);

  const targetMatch = targetInput.trim().toUpperCase() === "CXCL12";

  const scrollToBottom = useCallback((smooth = true) => {
    const el = fRef.current;
    if (!el) return;
    el.scrollTo({
      top: el.scrollHeight,
      behavior: smooth ? "smooth" : "auto",
    });
    setShowScrollToBottom(false);
  }, []);

  const checkNearBottom = useCallback(() => {
    const el = fRef.current;
    if (!el) return;
    const threshold = 80;
    const nearBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - threshold;
    isNearBottomRef.current = nearBottom;
    if (nearBottom) setShowScrollToBottom(false);
  }, []);

  const prevStatusRef = useRef(status);
  useEffect(() => {
    if (prevStatusRef.current === "idle" && status === "starting") setLitOpen(false);
    prevStatusRef.current = status;
  }, [status]);

  const partitioned = partitionLogsByCycle(logs);
  const displayIteration = Math.min(3, Math.max(1, iteration));
  const activeCycle = viewCycle > 0 ? viewCycle : Math.max(1, iteration);
  const displayLogs = viewCycle > 0 && partitioned[viewCycle as 1 | 2 | 3]?.length
    ? partitioned[viewCycle as 1 | 2 | 3]
    : logs;
  const dialogueLogs = filterReasoningLogs(displayLogs);

  useEffect(() => {
    const newCount = dialogueLogs.length;
    const prevCount = prevLogCountRef.current;
    prevLogCountRef.current = newCount;

    if (newCount <= prevCount) return;

    if (isNearBottomRef.current) {
      setTimeout(() => scrollToBottom(true), 150);
    } else {
      setShowScrollToBottom(true);
    }
  }, [dialogueLogs.length, scrollToBottom]);

  const allDone = ["completed_success", "completed_success_live", "completed_success_fallback"].includes(status);
  const runStarted = !!(runId || isRunning || allDone);
  const cycleButtonsEnabled = ["idle", "completed_success", "completed_success_live", "completed_success_fallback", "completed_failure", "error"].includes(status);
  const dashboardReady = targetMatch && (targetLoaded || runStarted);
  const showLiterature = targetMatch && targetLoaded;
  const showParamsAndLiterature = targetMatch && runStarted;

  const handleRunClick = () => {
    if (!targetMatch || isRunning || targetLoading) return;
    if (!targetLoaded) {
      setTargetLoading(true);
      setTimeout(() => {
        setTargetLoading(false);
        setTargetLoaded(true);
      }, 4000);
      return;
    }
    startRun();
  };
  const plddt = metrics.plddt_mean ?? null;
  const clashes = metrics.steric_clashes ?? null;
  const iptm = metrics.iptm ?? null;
  const curPass = plddt !== null && plddt > 80 && clashes !== null && clashes === 0 && (iptm === null || iptm >= 0.8);
  const lit = LITERATURE.find((l) => l.id === litTab);
  const prog = allDone ? 1 : iteration >= 3 ? 1 : iteration / 3;
  const statusCfg = STATUS_CONFIG[status] ?? { label: status.toUpperCase(), color: "#333333" };
  const statusHeaderColor =
    status === "idle" ? "#444444" :
    ["starting", "started"].includes(status) ? "#888888" :
    ["strategist_running", "architect_running", "awaiting_bio_api", "critic_running", "retry_pending"].includes(status) ? "#ffffff" :
    allDone ? "#66aa66" :
    ["completed_failure", "error"].includes(status) ? "#cc6666" : "#888888";
  const isRunningStatus = !["idle", "completed_success", "completed_success_live", "completed_success_fallback", "completed_failure", "error"].includes(status);

  const iterationMetrics = extractIterationMetricsFromLogs(logs);
  const hasParsedHistory = iterationMetrics.length > 0;
  const bestPassIndex = iterationMetrics.findIndex((m) => m.pass);

  const s = (overrides: React.CSSProperties = {}) => ({ ...FONT_STYLE, ...overrides });

  const isRunActionable = targetMatch && targetLoaded && !isRunning && !targetLoading && !allDone;
  const BOX_STYLE: React.CSSProperties = {
    ...FONT_STYLE,
    background: "#000000",
    border: "1px solid #1a1a1a",
    borderRadius: 0,
    padding: "10px 14px",
    width: 280,
    minWidth: 280,
    flexShrink: 0,
    minHeight: 24,
    boxSizing: "border-box",
    outline: "none",
  };

  return (
    <div style={{ minHeight: "100vh", background: "#000000", color: "#888888", ...FONT_STYLE, fontSize: 12, letterSpacing: 0.3 }}>

      {/* HEADER */}
      <div style={{ borderBottom: "1px solid #1a1a1a", padding: "14px 24px", display: "flex", alignItems: "flex-end", justifyContent: "space-between", flexWrap: "wrap", gap: 10 }}>
        <div>
          <div style={s({ fontSize: 16, color: "#ffffff", letterSpacing: 0 })}>AgentBinder</div>
          <div style={s({ fontSize: 10, color: "#555555", marginTop: 3 })}>Multi-Agent Peptide Design System</div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <span style={s({ fontSize: 10, color: "#444444" })}>MODE: <span style={{ color: "#888888" }}>{mode.toUpperCase()}</span></span>
          <span style={s({ fontSize: 10, color: statusHeaderColor })}>{statusCfg.label}</span>
          {isRunningStatus && <span style={{ width: 4, height: 4, background: statusCfg.color, animation: "pulse 1.5s infinite" }} />}
          {allDone && <span style={s({ fontSize: 10, color: "#66aa66" })}>COMPLETE</span>}
        </div>
      </div>

      {/* TARGET */}
      <div style={{ padding: "12px 24px", borderBottom: "1px solid #1a1a1a", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={s({ fontSize: 11, color: "#555555", width: 56, flexShrink: 0 })}>TARGET:</span>
        <input
          type="text"
          value={targetInput}
          onChange={(e) => setTargetInput(e.target.value)}
          placeholder="Enter target protein"
          aria-label="Protein target"
          style={{
            ...BOX_STYLE,
            border: "1px solid #ffffff",
            color: "#ffffff",
            fontSize: 13,
          }}
        />
        <span style={s({ fontSize: 10, color: "#444444" })}>Designated protein target</span>
      </div>

      {/* RUN */}
      <div style={{ padding: "12px 24px", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
        <span style={s({ fontSize: 11, color: "#555555", width: 56, flexShrink: 0 })}>RUN:</span>
        <button
          type="button"
          onClick={handleRunClick}
          disabled={!targetMatch || isRunning || targetLoading}
          style={{
            ...BOX_STYLE,
            padding: "12px 20px",
            border: (isRunActionable || allDone) ? "1px solid #7c3aed" : "1px solid #1a1a1a",
            color: allDone ? "#ffffff" : (!targetMatch || isRunning || targetLoading) ? "#555555" : "#ffffff",
            fontSize: 13,
            fontWeight: 600,
            cursor: !targetMatch || isRunning || targetLoading ? "not-allowed" : "pointer",
            textAlign: "center",
            appearance: "none",
            WebkitAppearance: "none",
            background: (isRunActionable || allDone) ? "#1a0a2e" : BOX_STYLE.background,
            transition: "border-color 0.2s, background 0.2s, color 0.2s",
          }}
          onMouseEnter={(e) => {
            if (isRunActionable || allDone) {
              e.currentTarget.style.borderColor = "#9f7aea";
              e.currentTarget.style.background = "#2a1a4a";
            }
          }}
          onMouseLeave={(e) => {
            if (isRunActionable || allDone) {
              e.currentTarget.style.borderColor = "#7c3aed";
              e.currentTarget.style.background = "#1a0a2e";
            }
          }}
        >
          {!targetMatch ? "Select target to enable" : targetLoading ? "Loading…" : isRunning ? "Running…" : allDone ? "Run again" : targetLoaded ? "Launch design" : "Load target"}
        </button>
        {runId && <span style={s({ fontSize: 9, color: "#444444" })}>{runId}</span>}
      </div>

      {/* Loading bar — violet, animates when target loading */}
      <div style={{ padding: "0 24px", borderBottom: "1px solid #1a1a1a" }}>
        <div style={{ height: 2, background: "#111111", overflow: "hidden" }}>
          <div
            style={{
              height: "100%",
              background: "#7c3aed",
              width: targetLoading || targetLoaded ? "100%" : "0%",
              transition: targetLoading ? "width 4s linear" : "width 0.2s ease-out",
            }}
          />
        </div>
      </div>

      {!targetMatch && (
        <div style={{ padding: "24px 24px", ...s({ fontSize: 11, color: "#666666" }) }}>
          Enter <span style={{ color: "#888888" }}>TARGET</span> in the target field above, then click Run to start.
        </div>
      )}

      {targetMatch && !dashboardReady && !targetLoading && (
        <div style={{ padding: "24px 24px", ...s({ fontSize: 11, color: "#666666" }) }}>
          Click <span style={{ color: "#888888" }}>LOAD PROTEIN TARGET</span> to load the target, then <span style={{ color: "#888888" }}>LAUNCH AGENT LOOP</span> to start.
        </div>
      )}

      {targetLoading && (
        <div style={{ padding: "16px 24px", ...s({ fontSize: 11, color: "#666666" }) }}>
          Loading target from database...
        </div>
      )}

      {dashboardReady && (
      <>
      {/* PROGRESS */}
      <div style={{ padding: "12px 24px 0" }}>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <span style={s({ fontSize: 10, color: "#555555" })}>PROGRESS</span>
          <span style={s({ fontSize: 10, color: prog >= 1 ? "#7c3aed" : prog > 0 ? "#6366f1" : "#888888" })}>{Math.round(prog * 100)}%</span>
        </div>
        <div style={{ height: 2, background: "#111111" }}>
          <div style={{ height: "100%", background: prog >= 1 ? "#7c3aed" : prog > 0 ? "#6366f1" : "#1e1b4b", width: `${prog * 100}%`, transition: "width 0.6s, background 0.3s" }} />
        </div>
      </div>

      {/* CYCLE NAV */}
      <div style={{ padding: "14px 24px 0", display: "flex", alignItems: "center", gap: 6 }}>
        <span style={s({ fontSize: 10, color: "#555555", marginRight: 4 })}>CYCLE:</span>
        {[1, 2, 3].map((n) => {
          const act = n === activeCycle;
          const hasLogs = partitioned[n as 1 | 2 | 3]?.length > 0;
          return (
            <button
              key={n}
              onClick={() => setViewCycle(viewCycle === n ? 0 : n)}
              disabled={!cycleButtonsEnabled}
              style={{
                ...FONT_STYLE,
                padding: "5px 12px",
                border: `1px solid ${act ? "#ffffff" : "#1a1a1a"}`,
                borderRadius: 0,
                background: act ? "#111111" : "#000000",
                color: act ? "#ffffff" : hasLogs ? "#888888" : "#444444",
                fontSize: 11,
                cursor: cycleButtonsEnabled ? "pointer" : "default",
                display: "flex",
                alignItems: "center",
                gap: 6,
              }}
            >
              <span>{n}</span>
            </button>
          );
        })}
        {status === "idle" && <span style={s({ fontSize: 10, color: "#666666", marginLeft: 6 })}>select a cycle to view</span>}
        {(isRunning || allDone) && <span style={s({ fontSize: 10, color: "#888888", marginLeft: 6 })}>Iteration {displayIteration}</span>}
      </div>

      {/* LITERATURE — shows after target load completes (LOAD PROTEIN TARGET) */}
      {showLiterature && (
      <div style={{ padding: "14px 24px 0" }}>
        <div onClick={() => setLitOpen(!litOpen)} style={{ display: "flex", alignItems: "center", gap: 6, cursor: "pointer", marginBottom: litOpen ? 8 : 0 }}>
          <span style={s({ fontSize: 11, color: "#555555" })}>LITERATURE REVIEW</span>
          <span style={{ ...s({ fontSize: 9, color: "#555555", display: "inline-block", transition: "transform 0.15s" }), transform: litOpen ? "rotate(0deg)" : "rotate(-90deg)" }}>v</span>
        </div>
        {litOpen && lit && (
          <div style={{ border: "1px solid #1a1a1a" }}>
            <div style={{ display: "flex", borderBottom: "1px solid #1a1a1a" }}>
              {LITERATURE.map((l) => (
                <button
                  key={l.id}
                  onClick={() => setLitTab(l.id)}
                  style={{
                    ...FONT_STYLE,
                    flex: 1,
                    padding: "8px 4px",
                    border: "none",
                    borderBottom: litTab === l.id ? "1px solid #888888" : "1px solid transparent",
                    background: litTab === l.id ? "#0a0a0a" : "#000000",
                    color: litTab === l.id ? "#aaaaaa" : "#444444",
                    fontSize: 9,
                    cursor: "pointer",
                  }}
                >
                  {l.t.toUpperCase()}
                </button>
              ))}
            </div>
            <div style={{ padding: "12px 14px", background: "#0a0a0a" }}>
              <div style={s({ fontSize: 12, color: "#999999", marginBottom: 8 })}>{lit.t}</div>
              <div style={s({ fontSize: 11, color: "#888888", lineHeight: 1.8 })}>{lit.text}</div>
            </div>
            {/* Paper references — dropdown style */}
            <div style={{ borderTop: "1px solid #1a1a1a", padding: "10px 14px" }}>
              <div style={s({ fontSize: 10, color: "#777777", marginBottom: 8 })}>REFERENCES</div>
              {LITERATURE_PAPERS.map((paper, idx) => {
                const isExpanded = litPaperOpen.has(idx);
                return (
                  <div key={idx} style={{ marginBottom: 4 }}>
                    <button
                      type="button"
                      onClick={() => setLitPaperOpen((prev) => {
                        const next = new Set(prev);
                        if (next.has(idx)) next.delete(idx);
                        else next.add(idx);
                        return next;
                      })}
                      style={{
                        ...FONT_STYLE,
                        width: "100%",
                        padding: "8px 10px",
                        border: "1px solid #1a1a1a",
                        background: isExpanded ? "#111111" : "#000000",
                        color: "#999999",
                        fontSize: 10,
                        textAlign: "left",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                      }}
                    >
                      <span style={{ ...s({ fontSize: 9, color: "#555555", flexShrink: 0 }), transform: isExpanded ? "rotate(0deg)" : "rotate(-90deg)", display: "inline-block", transition: "transform 0.15s" }}>v</span>
                      <span style={{ flex: 1 }}>{paper.title}</span>
                    </button>
                    {isExpanded && (
                      <div style={{ padding: "10px 12px 12px 28px", background: "#0a0a0a", border: "1px solid #1a1a1a", borderTop: "none", ...s({ fontSize: 10, color: "#888888", lineHeight: 1.7 }) }}>
                        {paper.abstract}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
      )}

      {/* MAIN */}
      <div style={{ padding: "14px 24px 24px", display: "flex", gap: 12, flexWrap: "wrap" }}>

        {/* LEFT */}
        <div style={{ flex: 3, minWidth: 400, display: "flex", flexDirection: "column", gap: 12 }}>

          {/* DIALOGUE */}
          <div style={{ border: "1px solid #ffffff", display: "flex", flexDirection: "column", position: "relative" }}>
            <div style={{ padding: "10px 14px", borderBottom: "1px solid #1a1a1a", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={s({ fontSize: 11, color: "#ffffff" })}>AGENT DIALOGUE</span>
              <div style={{ display: "flex", gap: 12 }}>
                {(["strategist", "architect", "critic"] as const).map((k) => {
                  const lastAgent = displayLogs.length > 0 ? displayLogs[displayLogs.length - 1].agent : null;
                  const display = k === "architect" ? (lastAgent === "architect" || lastAgent === "tamarind") : lastAgent === k;
                  const agColor = AGENT_COLORS[k];
                  return (
                    <div key={k} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <div style={{ width: 4, height: 4, background: display ? agColor : "#1a1a1a", transition: "background 0.3s" }} />
                      <span style={{ ...s({ fontSize: 11, transition: "color 0.3s" }), color: display ? agColor : "#555555" }}>{k.toUpperCase()}</span>
                    </div>
                  );
                })}
              </div>
            </div>
            <div
              ref={fRef}
              onScroll={checkNearBottom}
              style={{ overflowY: "auto", maxHeight: 400, minHeight: 400, padding: "8px 12px", display: "flex", flexDirection: "column", gap: 6, scrollBehavior: "smooth" }}
            >
              {dialogueLogs.length === 0 && (
                <div style={s({ padding: "20px 14px", color: "#888888", fontSize: 11 })}>
                  {isRunning ? "Initializing agent loop…" : "Launch a run or select a cycle above to view agent dialogue."}
                </div>
              )}
              {dialogueLogs.map((log, i) => {
                const isSys = log.agent === "system" || log.agent === "loop";
                const alignRight = isSys ? false : isRightAligned(log.agent);
                const agLabel = AG_DISPLAY[log.agent] ?? "SYSTEM";
                const agColor = AGENT_COLORS[log.agent] ?? "#888888";
                const displayMsg = formatConversationalMessage(log.agent, log.event, log.message ?? "", { logIndex: i, logs: dialogueLogs });
                const bubbleBg = isSys ? "transparent" : (log.level === "warn" || log.level === "warning")
                  ? "#cc666625" : log.level === "success" ? "#66aa6625" : agColor + "25";
                return (
                  <div key={i} style={{ display: "flex", justifyContent: isSys ? "center" : alignRight ? "flex-end" : "flex-start" }}>
                    <div
                      style={{
                        maxWidth: "85%",
                        padding: isSys ? "6px 12px" : "10px 14px",
                        borderRadius: 18,
                        background: isSys ? "transparent" : bubbleBg,
                        border: isSys ? "none" : `1px solid ${agColor}40`,
                        ...(alignRight ? { borderBottomRightRadius: 4 } : { borderBottomLeftRadius: 4 }),
                      }}
                    >
                      <div style={{ ...s({ fontSize: 11, marginBottom: 4 }), color: agColor, fontWeight: 600 }}>{agLabel}</div>
                      <div style={s({ fontSize: 11, lineHeight: 1.5, color: "#cccccc" })}>{displayMsg}</div>
                    </div>
                  </div>
                );
              })}
            </div>
            {showScrollToBottom && dialogueLogs.length > 0 && (
              <button
                type="button"
                onClick={() => scrollToBottom(true)}
                style={{
                  position: "absolute",
                  bottom: 12,
                  left: "50%",
                  transform: "translateX(-50%)",
                  padding: "6px 14px",
                  fontSize: 10,
                  background: "#1a1a1a",
                  border: "1px solid #444444",
                  color: "#ffffff",
                  cursor: "pointer",
                  ...FONT_STYLE,
                  borderRadius: 16,
                }}
              >
                New messages ↓
              </button>
            )}
          </div>

          {/* VIEWER */}
          <div style={{ border: `1px solid ${allDone ? "#66aa6622" : "#1a1a1a"}`, transition: "border-color 0.4s" }}>
            <div style={{ padding: "10px 14px", borderBottom: `1px solid ${allDone ? "#66aa6612" : "#1a1a1a"}`, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={s({ fontSize: 11, color: "#ffffff" })}>MOLECULAR VIEWER</span>
              {allDone && finalPdbUrl && (
                <a
                  href={finalPdbUrl}
                  download
                  style={{
                    ...s({ fontSize: 11, color: "#66aa66", textDecoration: "none", fontWeight: 600 }),
                    padding: "6px 12px",
                    border: "1px solid #66aa6644",
                    background: "#66aa6612",
                    boxShadow: "0 0 10px rgba(102, 170, 102, 0.2)",
                  }}
                >
                  ↓ Download PDB
                </a>
              )}
            </div>
            <div style={{ height: 200 }}>
              {finalPdbUrl ? (
                <MolstarViewer pdbUrl={finalPdbUrl} />
              ) : (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <div style={{ textAlign: "center" }}>
                    <svg width="50" height="50" viewBox="0 0 50 50" style={{ opacity: 0.15, marginBottom: 6 }}>
                      <circle cx="25" cy="25" r="16" fill="none" stroke="#333" strokeWidth="0.5" strokeDasharray="3 3" />
                      <circle cx="20" cy="22" r="2" fill="#111" />
                      <circle cx="30" cy="23" r="1.5" fill="#111" />
                      <circle cx="25" cy="32" r="1.5" fill="#111" />
                    </svg>
                    <div style={s({ fontSize: 10, color: "#666666" })}>
                      {isRunning ? "Generating structure…" : "Complete a design run to render the structure here."}
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* RIGHT */}
        <div style={{ flex: 1, minWidth: 220, maxWidth: 260, display: "flex", flexDirection: "column", gap: 12 }}>

          {/* EVALUATION */}
          <div style={{ border: "1px solid #1a1a1a", padding: "14px" }}>
            <div style={s({ fontSize: 11, color: "#666666", marginBottom: 12 })}>EVALUATION</div>
            {plddt !== null || clashes !== null || iptm !== null ? (
              <>
                {[
                  { l: "pLDDT SCORE", v: plddt ?? "—", t: "> 80.0", p: plddt !== null && plddt > 80 },
                  { l: "STERIC CLASHES", v: clashes ?? "—", t: "= 0", p: clashes !== null && clashes === 0 },
                  ...(iptm !== null ? [{ l: "IPTM", v: iptm.toFixed(3), t: "≥ 0.8", p: iptm >= 0.8 }] : []),
                ].map(({ l, v, t, p }) => (
                  <div
                    key={l}
                    style={{
                      padding: "10px",
                      marginBottom: 6,
                      border: `1px solid ${p ? "#66aa6633" : "#cc666633"}`,
                      background: p ? "#66aa6608" : "#cc666608",
                      boxShadow: p ? "0 0 8px rgba(102, 170, 102, 0.25)" : "0 0 8px rgba(204, 102, 102, 0.2)",
                    }}
                  >
                    <div style={s({ fontSize: 9, color: "#666666", marginBottom: 5 })}>{l}</div>
                    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                      <span style={s({ fontSize: 24, color: "#ffffff", lineHeight: 1 })}>{v}</span>
                      <span style={s({ fontSize: 9, color: p ? "#66aa66" : "#cc6666" })}>{p ? "PASS" : "FAIL"}</span>
                    </div>
                    <div style={s({ fontSize: 9, color: "#555555", marginTop: 4 })}>threshold {t}</div>
                  </div>
                ))}
              </>
            ) : (
              <div style={s({ fontSize: 10, color: "#555555" })}>no data</div>
            )}
          </div>

          {/* ITERATION HISTORY — bar chart + detailed list */}
          <div style={{ border: "1px solid #1a1a1a", padding: "14px" }}>
            <div style={s({ fontSize: 11, color: "#555555", marginBottom: 10 })}>ITERATION HISTORY</div>
            {hasParsedHistory ? (
              <>
                {/* Bar chart: values above, bars aligned at bottom, C1/C2/C3 labels */}
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", gap: 6, padding: "0 2px" }}>
                    {[1, 2, 3].map((n) => {
                      const m = iterationMetrics[n - 1];
                      const val = m ? m.plddt : null;
                      const isPass = m?.pass ?? false;
                      const barHeight = val !== null ? Math.max(10, (val / 100) * 40) : 6;
                      const barColor = val === null ? "#111" : isPass ? "#66aa66" : "#8b5a4a";
                      return (
                        <div key={n} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                          <span style={s({ fontSize: 9, color: isPass && bestPassIndex === n - 1 ? "#ffffff" : val !== null ? "#888888" : "#444", marginBottom: 4 })}>
                            {val !== null ? val.toFixed(1) : "—"}
                          </span>
                          <div style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", minHeight: 40 }}>
                            <div
                              style={{
                                width: "100%",
                                minWidth: 24,
                                height: barHeight,
                                background: barColor,
                                transition: "all 0.4s",
                              }}
                            />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ display: "flex", gap: 6, paddingTop: 4 }}>
                    {[1, 2, 3].map((n) => (
                      <div key={n} style={{ flex: 1, textAlign: "center", ...s({ fontSize: 9, color: "#555555" }) }}>Cycle {n}</div>
                    ))}
                  </div>
                </div>
                {/* Detailed list: Cycle 1 64.3 clash:2 FAIL, etc. */}
                {[1, 2, 3].map((n) => {
                  const m = iterationMetrics[n - 1];
                  const isBest = m?.pass && bestPassIndex === n - 1;
                  const isFail = m && !m.pass;
                  return (
                    <div
                      key={n}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "5px 6px",
                        marginBottom: 2,
                        border: `1px solid ${isBest ? "#66aa6633" : isFail ? "#cc666633" : m ? "#1a1a1a" : "#0a0a0a"}`,
                        background: isBest ? "#66aa6608" : isFail ? "#cc666608" : "transparent",
                        boxShadow: isBest ? "0 0 6px rgba(102, 170, 102, 0.2)" : isFail ? "0 0 6px rgba(204, 102, 102, 0.15)" : undefined,
                      }}
                    >
                      <span style={s({ fontSize: 10, color: m ? (m.pass ? "#66aa66" : "#cc6666") : "#444444", width: 52 })}>Cycle {n}</span>
                      {m ? (
                        <div style={{ flex: 1, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                          <div>
                            <span style={s({ fontSize: 11, color: "#ffffff" })}>{m.plddt.toFixed(1)}</span>
                            <span style={s({ fontSize: 9, color: "#888888", marginLeft: 6 })}>clash:{m.clashes}</span>
                          </div>
                          <span style={s({ fontSize: 8, color: m.pass ? "#66aa66" : "#cc6666" })}>{m.pass ? "PASS" : "FAIL"}{isBest ? " *" : ""}</span>
                        </div>
                      ) : (
                        <span style={s({ fontSize: 9, color: "#444444" })}>—</span>
                      )}
                    </div>
                  );
                })}
              </>
            ) : iteration > 0 ? (
              /* Fallback when logs don't contain parsable critic output: use current metrics */
              <>
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", gap: 6, padding: "0 2px" }}>
                    {[1, 2, 3].map((n) => {
                      const hasData = n <= iteration;
                      const val = n === iteration && plddt !== null ? plddt : null;
                      const isPass = curPass && n === iteration;
                      const barHeight = val !== null ? Math.max(10, (val / 100) * 40) : hasData ? 10 : 6;
                      const barColor = val !== null ? (isPass ? "#66aa66" : "#8b5a4a") : "#111";
                      return (
                        <div key={n} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center" }}>
                          <span style={s({ fontSize: 9, color: isPass ? "#ffffff" : val !== null ? "#888888" : "#444", marginBottom: 4 })}>
                            {val !== null ? val.toFixed(1) : "—"}
                          </span>
                          <div style={{ display: "flex", flexDirection: "column", justifyContent: "flex-end", minHeight: 40 }}>
                            <div style={{ width: "100%", minWidth: 24, height: barHeight, background: barColor, transition: "all 0.4s" }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                  <div style={{ display: "flex", gap: 6, paddingTop: 4 }}>
                    {[1, 2, 3].map((n) => (
                      <div key={n} style={{ flex: 1, textAlign: "center", ...s({ fontSize: 9, color: "#555555" }) }}>Cycle {n}</div>
                    ))}
                  </div>
                </div>
                {[1, 2, 3].map((n) => {
                  const hasData = n <= iteration;
                  const isCurrent = n === iteration;
                  const isFail = hasData && !curPass && isCurrent;
                  return (
                    <div
                      key={n}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        padding: "5px 6px",
                        marginBottom: 2,
                        border: `1px solid ${isCurrent && curPass ? "#66aa6633" : isFail ? "#cc666633" : hasData ? "#1a1a1a" : "#0a0a0a"}`,
                        background: isCurrent && curPass ? "#66aa6608" : isFail ? "#cc666608" : "transparent",
                        boxShadow: isCurrent && curPass ? "0 0 6px rgba(102, 170, 102, 0.2)" : isFail ? "0 0 6px rgba(204, 102, 102, 0.15)" : undefined,
                      }}
                    >
                      <span style={s({ fontSize: 10, color: hasData ? (curPass && isCurrent ? "#66aa66" : "#cc6666") : "#444444", width: 52 })}>Cycle {n}</span>
                      {hasData && isCurrent ? (
                        <div style={{ flex: 1, display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                          <div>
                            <span style={s({ fontSize: 11, color: "#ffffff" })}>{plddt ?? "—"}</span>
                            <span style={s({ fontSize: 9, color: "#888888", marginLeft: 6 })}>clash:{clashes ?? "—"}</span>
                          </div>
                          <span style={s({ fontSize: 8, color: curPass ? "#66aa66" : "#cc6666" })}>{curPass ? "PASS *" : "FAIL"}</span>
                        </div>
                      ) : (
                        <span style={s({ fontSize: 9, color: "#444444" })}>—</span>
                      )}
                    </div>
                  );
                })}
              </>
            ) : (
              <div style={s({ fontSize: 10, color: "#555555" })}>No iteration data yet</div>
            )}
          </div>

          {/* PARAMETERS — loads after Run is clicked */}
          {showParamsAndLiterature && (
          <div style={{ border: "1px solid #1a1a1a", padding: "14px" }}>
            <div style={s({ fontSize: 11, color: "#555555", marginBottom: 10 })}>PARAMETERS</div>
            {(
              [
                ["Target", targetInput.trim().toUpperCase()],
                ["Anchor", "VAL18 ARG47 VAL49"],
                ["Polar", "GLU15 ASN22 ASN45/46"],
                ["Extension", "PRO10 LEU29 VAL39"],
                ["Region", "sTyr21 cleft"],
                ["Length", "—"],
                ["Topology", "—"],
                ["Flexibility", "—"],
                ["Engine", "RFdiffusion"],
                ["Sequence", "ProteinMPNN"],
                ["Mode", mode],
                ["Hypothesis", "receptor-recognition"],
              ]
                .filter(([, v]) => v && v !== "—")
                .map(([k, v]) => (
                  <div key={k} style={{ display: "flex", justifyContent: "space-between", padding: "3px 0", borderBottom: "1px solid #0a0a0a" }}>
                    <span style={s({ fontSize: 10, color: "#444444" })}>{k}</span>
                    <span style={s({ fontSize: 10, color: "#888888", textAlign: "right", maxWidth: "58%" })}>{v}</span>
                  </div>
                ))
            )}
          </div>
          )}

          {/* NOTE */}
          <div style={{ border: "1px solid #1a1a1a", padding: "12px 14px" }}>
            <div style={s({ fontSize: 10, color: "#555555", marginBottom: 5 })}>NOTE</div>
            <div style={s({ fontSize: 9, color: "#222222", lineHeight: 1.7 })}>
              Metrics are MVP heuristics indicating structural plausibility. Not experimental validation.
            </div>
          </div>
        </div>
      </div>

      </>
      )}

      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        input[type="text"]:focus { border-color: #ffffff; }
      `}</style>
    </div>
  );
}
