"""
Demo mode runner — replays a pre-baked 3-iteration pipeline in ~95 seconds.
Writes to the same state.json + JSONL log files that the real loop uses,
so all existing poll endpoints work unchanged.
"""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / "state.json"
LOGS_DIR = BASE_DIR / "outputs" / "logs"

# Short token shared across iterations (simulates a stable run hash)
_RUN_TOKEN = "a1b2c3d4"


def _read_state() -> dict:
    with open(STATE_FILE) as f:
        return json.load(f)


def _write_state(**kwargs) -> None:
    state = _read_state()
    state.update(kwargs)
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def _append_log(run_id: str, agent: str, event: str, message: str, level: str = "info") -> None:
    log_file = LOGS_DIR / f"{run_id}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "event": event,
        "level": level,
        "message": message,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Per-iteration configuration ────────────────────────────────────────────────

_ITERATIONS = [
    # Iteration 1 — FAIL (low pLDDT + clashes)
    {
        "iteration": 1,
        "strategist_rationale": "helical motif, 8–18 residues, anchor VAL18/ARG47/VAL49, secondary extension PRO10/LEU29/VAL39 included",
        "strategist_constraint": {
            "topology_hint": "helix",
            "anchor_residues": ["VAL18", "ARG47", "VAL49"],
            "secondary_zone": ["PRO10", "LEU29", "VAL39"],
            "binder_length_range": [8, 18],
            "flexibility": "moderate",
        },
        "architect_settings": {
            "task": "Binder Design",
            "targetChains": ["A"],
            "binderLength": "8-18",
            "binderHotspots": {"A": "18 47 49 10 29 39"},
            "numDesigns": 1,
        },
        "rfd_job": "rfd_e2e_a1b2c3d4_iter_1",
        "mpnn_job": "mpnn_e2e_a1b2c3d4_iter_1",
        "boltz_job": "boltz_e2e_a1b2c3d4_iter_1",
        "rfd_bytes": 24489,
        "boltz_bytes": 92015,
        "sequence": "GPLPIFLP:SSGSSGSSSPVTTVDSSATLE",
        "plddt": 54.1,
        "iptm": 0.919,
        "clashes": 233,
        "passes": False,
        "failure_reasons": [
            "pLDDT 54.1 ≤ threshold 80.0",
            "233 clash(es) detected (distance < 1.5 Å)",
            "iptm 0.919 ≥ threshold 0.800 (pass)",
        ],
        "feedback": (
            "Confidence too low (pLDDT 54.1 ≤ 80.0). Try a shorter, more rigid topology. "
            "233 steric clash(es) detected — reduce bulky residues near Arg47 "
            "(avoid extended secondary zone)."
        ),
    },
    # Iteration 2 — FAIL (improved, still short)
    {
        "iteration": 2,
        "strategist_rationale": (
            "Adjusting based on critic feedback: reducing length and removing secondary hotspots. "
            "Rigid compact_turn, 8–12 residues, dropping secondary zone."
        ),
        "strategist_constraint": {
            "topology_hint": "compact_turn",
            "anchor_residues": ["VAL18", "ARG47", "VAL49"],
            "secondary_zone": [],
            "binder_length_range": [8, 12],
            "flexibility": "low",
        },
        "architect_settings": {
            "task": "Binder Design",
            "targetChains": ["A"],
            "binderLength": "8-12",
            "binderHotspots": {"A": "18 47 49"},
            "numDesigns": 1,
        },
        "rfd_job": "rfd_e2e_a1b2c3d4_iter_2",
        "mpnn_job": "mpnn_e2e_a1b2c3d4_iter_2",
        "boltz_job": "boltz_e2e_a1b2c3d4_iter_2",
        "rfd_bytes": 24489,
        "boltz_bytes": 87340,
        "sequence": "WPYVRF:SSGSSPVTSSATLE",
        "plddt": 71.3,
        "iptm": 0.887,
        "clashes": 12,
        "passes": False,
        "failure_reasons": [
            "pLDDT 71.3 ≤ threshold 80.0",
            "12 clash(es) detected (distance < 1.5 Å)",
            "iptm 0.887 ≥ threshold 0.800 (pass)",
        ],
        "feedback": (
            "Structure improving but confidence still insufficient (pLDDT 71.3 ≤ 80.0). "
            "12 clash(es) remain near Arg47. Shorten to 8–10 residues and tighten to "
            "compact_turn with no secondary hotspots."
        ),
    },
    # Iteration 3 — PASS
    {
        "iteration": 3,
        "strategist_rationale": (
            "Adjusting based on critic feedback: tightening to 8–10 residues, compact_turn, "
            "anchor-only VAL18/ARG47 — no secondary zones."
        ),
        "strategist_constraint": {
            "topology_hint": "compact_turn",
            "anchor_residues": ["VAL18", "ARG47"],
            "secondary_zone": [],
            "binder_length_range": [8, 10],
            "flexibility": "low",
        },
        "architect_settings": {
            "task": "Binder Design",
            "targetChains": ["A"],
            "binderLength": "8-10",
            "binderHotspots": {"A": "18 47"},
            "numDesigns": 1,
        },
        "rfd_job": "rfd_e2e_a1b2c3d4_iter_3",
        "mpnn_job": "mpnn_e2e_a1b2c3d4_iter_3",
        "boltz_job": "boltz_e2e_a1b2c3d4_iter_3",
        "rfd_bytes": 24489,
        "boltz_bytes": 94120,
        "sequence": "WPYV:SSGSSPVT",
        "plddt": 87.6,
        "iptm": 0.923,
        "clashes": 0,
        "passes": True,
        "failure_reasons": [],
        "feedback": None,
    },
]


async def _run_iteration(run_id: str, cfg: dict) -> bool:
    """Replay one iteration. Returns True if it passed the critic."""
    it = cfg["iteration"]
    rfd_job = cfg["rfd_job"]
    mpnn_job = cfg["mpnn_job"]
    boltz_job = cfg["boltz_job"]

    # ── Strategist ────────────────────────────────────────────────────────────
    _write_state(status="strategist_running", iteration=it)
    await asyncio.sleep(0.5)

    _append_log(run_id, "strategist", "start",
                f"Iteration {it}: generating binder strategy for CXCL12. "
                f"Rationale: {cfg['strategist_rationale']}")
    await asyncio.sleep(0.5)

    _append_log(run_id, "strategist", "constraint_generated",
                f"StrategistOutput: {json.dumps(cfg['strategist_constraint'])}")
    await asyncio.sleep(0.5)

    # ── Architect ─────────────────────────────────────────────────────────────
    _write_state(status="architect_running")
    await asyncio.sleep(0.5)

    _append_log(run_id, "architect", "literature_loaded",
                "pdb=cxcl12.pdb, seq_len=68, default_hotspots='18 47 49'")
    await asyncio.sleep(0.5)

    _append_log(run_id, "architect", "start",
                f"Iteration {it}: deriving Tamarind settings from strategy")
    await asyncio.sleep(0.5)

    _append_log(run_id, "architect", "settings_derived",
                f"Tamarind settings: {json.dumps(cfg['architect_settings'])}")
    await asyncio.sleep(0.5)

    # ── Pipeline start ────────────────────────────────────────────────────────
    _write_state(status="awaiting_bio_api")
    _append_log(run_id, "tamarind", "pipeline_start",
                f"Iteration {it}: starting RFdiffusion → ProteinMPNN → Boltz pipeline")
    await asyncio.sleep(0.5)

    # ── RFdiffusion ───────────────────────────────────────────────────────────
    _append_log(run_id, "tamarind", "rfd_upload",
                f"Uploading cxcl12.pdb ({cfg['rfd_bytes']} bytes) for job {rfd_job}")
    await asyncio.sleep(0.5)

    _append_log(run_id, "tamarind", "rfd_submitted",
                f"Job {rfd_job} submitted to Tamarind queue")
    await asyncio.sleep(2.0)

    _append_log(run_id, "tamarind", "rfd_poll",
                f"[{rfd_job}] status=Pending elapsed=5s")
    await asyncio.sleep(3.0)

    _append_log(run_id, "tamarind", "rfd_poll",
                f"[{rfd_job}] status=Running elapsed=8s")
    await asyncio.sleep(3.0)

    _append_log(run_id, "tamarind", "rfd_poll",
                f"[{rfd_job}] status=Running elapsed=11s")
    await asyncio.sleep(0.5)

    _append_log(run_id, "tamarind", "rfd_done",
                f"[{rfd_job}] Complete — diffused backbone downloaded ({cfg['rfd_bytes']} bytes)")
    await asyncio.sleep(0.5)

    # ── ProteinMPNN ───────────────────────────────────────────────────────────
    _append_log(run_id, "tamarind", "mpnn_upload",
                f"Uploading backbone PDB for job {mpnn_job}")
    await asyncio.sleep(0.5)

    _append_log(run_id, "tamarind", "mpnn_submitted",
                f"Job {mpnn_job} submitted to Tamarind queue")
    await asyncio.sleep(2.0)

    _append_log(run_id, "tamarind", "mpnn_poll",
                f"[{mpnn_job}] status=Running elapsed=4s")
    await asyncio.sleep(2.0)

    _append_log(run_id, "tamarind", "mpnn_done",
                f"[{mpnn_job}] Complete — sequence: {cfg['sequence']}")
    await asyncio.sleep(0.5)

    # ── Boltz ─────────────────────────────────────────────────────────────────
    _append_log(run_id, "tamarind", "boltz_submitted",
                f"Job {boltz_job} submitted to Tamarind queue (structure prediction)")
    await asyncio.sleep(2.0)

    _append_log(run_id, "tamarind", "boltz_poll",
                f"[{boltz_job}] status=Pending elapsed=2s")
    await asyncio.sleep(3.0)

    _append_log(run_id, "tamarind", "boltz_poll",
                f"[{boltz_job}] status=Running elapsed=5s")
    await asyncio.sleep(3.0)

    _append_log(run_id, "tamarind", "boltz_poll",
                f"[{boltz_job}] status=Running elapsed=8s")
    await asyncio.sleep(2.0)

    _append_log(run_id, "tamarind", "boltz_poll",
                f"[{boltz_job}] status=Running elapsed=10s")
    await asyncio.sleep(0.5)

    _append_log(run_id, "tamarind", "boltz_done",
                f"[{boltz_job}] Complete — structure downloaded ({cfg['boltz_bytes']} bytes)")
    await asyncio.sleep(0.5)

    # ── Critic ────────────────────────────────────────────────────────────────
    _write_state(status="critic_running")
    _append_log(run_id, "critic", "pipeline_done",
                f"Iteration {it}: all pipeline jobs complete, evaluating structure")
    await asyncio.sleep(0.5)

    metrics = {
        "plddt_mean": cfg["plddt"],
        "steric_clashes": cfg["clashes"],
        "iptm": cfg["iptm"],
    }
    _write_state(metrics=metrics)

    if cfg["passes"]:
        _append_log(run_id, "critic", "evaluation_pass",
                    f"pLDDT={cfg['plddt']}, iptm={cfg['iptm']} [PASS], "
                    f"steric_clashes={cfg['clashes']} — design accepted")
    else:
        reasons_str = ", ".join(f"'{r}'" for r in cfg["failure_reasons"])
        _append_log(run_id, "critic", "evaluation_fail",
                    f"Failure reasons: [{reasons_str}]",
                    level="warning")

    await asyncio.sleep(0.5)
    return cfg["passes"]


async def run_demo_loop(run_id: str) -> None:
    """
    Entry point called by FastAPI BackgroundTask in demo mode.
    Replays all 3 pre-baked iterations with realistic timing.
    """
    _append_log(run_id, "loop", "loop_start",
                f"[DEMO] Starting demo loop for run {run_id}, max_iterations=3")

    try:
        for cfg in _ITERATIONS:
            it = cfg["iteration"]
            _append_log(run_id, "loop", "iteration_start",
                        f"=== Iteration {it}/3 ===")

            passed = await _run_iteration(run_id, cfg)

            if passed:
                # Write a placeholder final PDB URL (demo — no real file)
                final_pdb_url = f"/outputs/pdbs/{run_id}_final.pdb"
                _write_state(
                    status="completed_success_live",
                    final_pdb_url=final_pdb_url,
                )
                _append_log(run_id, "loop", "loop_success",
                            f"Design accepted after {it} iterations. "
                            f"iptm={cfg['iptm']}, pLDDT={cfg['plddt']}")
                return

            # Iteration failed — log feedback and continue
            _append_log(run_id, "loop", "iteration_fail",
                        f"Iteration {it} failed: feedback → strategist: '{cfg['feedback']}'",
                        level="warning")
            await asyncio.sleep(0.5)

        # Should not reach here with 3 iterations where last passes, but guard anyway
        _append_log(run_id, "loop", "loop_exhausted",
                    "All 3 iterations exhausted without passing quality gate.",
                    level="error")
        _write_state(status="completed_failure")

    except Exception as e:
        _append_log(run_id, "loop", "loop_error",
                    f"Unhandled error in demo loop: {e}", level="error")
        _write_state(status="error")
        raise
