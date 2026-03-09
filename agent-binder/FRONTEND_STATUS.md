# Agent Binder Frontend — Functionality Status

## What Works

| Feature | Status | Notes |
|---------|--------|------|
| **Launch Agent Loop** | Works | Calls `/api/start-loop` with target_id CXCL12. Starts backend run. |
| **Status display** | Works | Shows IDLE, STRATEGIST, ARCHITECT, etc. from backend status. |
| **Progress bar** | Works | Driven by iteration (1/3, 2/3, 3/3). Violet-blue colored. |
| **Agent dialogue logs** | Works | Streams logs from `/api/logs`. Displays message, agent, level. |
| **Agent mapping** | Works | tamarind→ARCHITECT, loop→SYSTEM. Strategist, Architect, Critic have distinct colors. |
| **Log partitioning** | Partial | Splits by critic REJECTED/ACCEPTED. Depends on backend log format. |
| **Cycle nav** | Works | Buttons 1, 2, 3 switch log view when partitions exist. |
| **Evaluation panel** | Works | Shows pLDDT and steric clashes when backend provides them. |
| **Iteration history** | Partial | Shows bars; backend only returns current metrics, not per-iteration. |
| **Molstar viewer** | Works | Loads PDB when `final_pdb_url` is available from `/api/result`. |
| **Download PDB** | Works | Link appears when run completes successfully. |
| **Literature review** | Works | Collapsible tabs with hardcoded CXCL12 content. |
| **Parameters panel** | Works | Pops up when target is CXCL12. Shows placeholder "—" for Length, Topology, Flexibility. |
| **Target text box** | Works | Editable input. Backend still receives CXCL12 for now. |

## What Doesn't Work / Limitations

| Issue | Notes |
|-------|------|
| **Target passed to backend** | Text box is UI-only. `startRun` always sends `target_id: "CXCL12"`. Backend must be updated to accept dynamic target. |
| **Per-iteration metrics** | Backend returns single `plddt_mean`, `steric_clashes`. Iteration history bars show same value for active iteration. |
| **Parameters Length/Topology/Flexibility** | Always "—". Backend does not provide these; would need new API fields. |
| **Cycle log partitioning** | Heuristic: splits on critic REJECTED/ACCEPTED. If backend logs differ, partitioning may fail. |
| **Backend down** | No explicit error toast. Polling fails silently; user sees no logs. |
| **Run history** | Only one run at a time. No list of past runs. |

## Data Flow

```
User clicks Launch
  → POST /api/start-loop { target_id: "CXCL12" }
  → Poll /api/status, /api/logs every 1s
  → On terminal status → GET /api/result for final_pdb_url
  → Display logs, metrics, PDB in Molstar
```

## Backend Contract (unchanged)

- **start-loop**: `target_id` (string) — currently only CXCL12 accepted
- **status**: `run_id`, `status`, `iteration`, `mode`, `metrics`
- **logs**: Array of `{ timestamp, agent, event, level, message }`
- **result**: `final_pdb_url`, `metrics`
