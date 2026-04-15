"""
Orchestration loop — runs Strategist → Architect → Tamarind → Critic up to MAX_ITERATIONS.
Writes state.json and JSONL logs at each step.
"""
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

from tools.tamarind import TamarindFailedError, TamarindTimeoutError

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / "state.json"
LOGS_DIR = BASE_DIR / "outputs" / "logs"
PDBS_DIR = BASE_DIR / "outputs" / "pdbs"


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


async def run_loop(run_id: str) -> None:
    """
    Main agent orchestration loop.
    Called as a FastAPI BackgroundTask.
    """
    from agents.architect import run_architect
    from agents.strategist import run_strategist
    from critic.evaluator import evaluate

    max_iterations = int(os.environ.get("MAX_ITERATIONS", "3"))
    previous_feedback: str | None = None
    previous_metrics: dict | None = None
    final_pdb_path: str | None = None
    mode = "live"

    _append_log(run_id, "loop", "loop_start", f"Starting agent loop for run {run_id}, max_iterations={max_iterations}")

    try:
        for iteration in range(1, max_iterations + 1):
            _append_log(run_id, "loop", "iteration_start", f"=== Iteration {iteration}/{max_iterations} ===")

            # ── 1. Strategist ──────────────────────────────────────────────────
            _write_state(status="strategist_running", iteration=iteration)
            strategy = await run_strategist(run_id, iteration, previous_feedback)

            # ── 2–4. Architect → Tamarind → Critic (with one retry on transient errors) ──
            critique = None

            for attempt in range(2):
                if attempt == 1:
                    _write_state(status="retry_pending")
                    _append_log(
                        run_id, "loop", "retry_attempt",
                        f"Retrying iteration {iteration} after transient error (attempt 2/2)",
                        level="warning",
                    )

                try:
                    # ── 2. Architect ───────────────────────────────────────────
                    _write_state(status="architect_running")
                    pdb_path, boltz_scores = await run_architect(
                        run_id, iteration, strategy, previous_metrics=previous_metrics
                    )

                    # Detect if fallback was used (tamarind.py copies mock file)
                    mock_src = BASE_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"
                    if mock_src.exists():
                        expected = Path(pdb_path)
                        if expected.exists() and expected.stat().st_size == mock_src.stat().st_size:
                            mode = "fallback"
                            _write_state(mode="fallback")

                    # ── 3. Awaiting bio API (already resolved, update status) ──
                    _write_state(status="awaiting_bio_api")
                    final_pdb_path = pdb_path

                    # ── 4. Critic ──────────────────────────────────────────────
                    _write_state(status="critic_running")
                    critique = evaluate(pdb_path, run_id=run_id, iteration=iteration, boltz_scores=boltz_scores)
                    break  # success — exit retry loop

                except (TamarindTimeoutError, TamarindFailedError, json.JSONDecodeError, ValidationError) as e:
                    _append_log(
                        run_id, "loop", "transient_error",
                        f"Transient error on iteration {iteration}, attempt {attempt + 1}: {e}",
                        level="warning",
                    )
                    if attempt == 1:
                        previous_feedback = f"Transient error after retry: {e}. Try different parameters."
                        _append_log(
                            run_id, "loop", "retry_exhausted",
                            f"Iteration {iteration} failed after retry: {e}",
                            level="error",
                        )
                        critique = None
                        break

                except Exception as e:
                    # Catches BioPython parse failures from evaluate() and other unexpected errors
                    _append_log(
                        run_id, "loop", "transient_error",
                        f"Unexpected error on iteration {iteration}, attempt {attempt + 1}: {e}",
                        level="warning",
                    )
                    if attempt == 1:
                        previous_feedback = f"Evaluator error after retry: {e}. Try a different structure."
                        _append_log(
                            run_id, "loop", "retry_exhausted",
                            f"Iteration {iteration} failed after retry: {e}",
                            level="error",
                        )
                        critique = None
                        break

            if critique is None:
                # Transient failure exhausted retries — continue to next iteration
                continue

            # Update metrics in state
            metrics = {
                "plddt_mean": critique["plddt_mean"],
                "steric_clashes": critique["steric_clashes"],
            }
            if critique.get("iptm") is not None:
                metrics["iptm"] = critique["iptm"]
            _write_state(metrics=metrics)

            if critique["pass"]:
                # ── Success ────────────────────────────────────────────────────
                # Copy final PDB to a stable name
                final_name = f"{run_id}_final.pdb"
                final_dest = PDBS_DIR / final_name
                shutil.copy2(pdb_path, final_dest)

                final_pdb_url = f"/outputs/pdbs/{final_name}"
                status = "completed_success_fallback" if mode == "fallback" else "completed_success_live"

                _write_state(
                    status=status,
                    final_pdb_url=final_pdb_url,
                )
                _append_log(
                    run_id, "loop", "loop_success",
                    f"Run completed successfully on iteration {iteration}. "
                    f"pLDDT={critique['plddt_mean']}, clashes={critique['steric_clashes']}, mode={mode}"
                )
                return

            # ── Iteration failed — pass feedback and metrics to next iteration ──
            previous_feedback = critique.get("feedback_to_strategist") or "Improve binding geometry."
            previous_metrics = {
                "plddt_mean": critique["plddt_mean"],
                "steric_clashes": critique["steric_clashes"],
                "iptm": critique.get("iptm"),
            }
            _append_log(
                run_id, "loop", "iteration_fail",
                f"Iteration {iteration} failed: {critique['failure_reasons']}. Feedback: {previous_feedback}",
                level="warning",
            )

        # ── Exhausted all iterations ───────────────────────────────────────────
        _append_log(
            run_id, "loop", "loop_exhausted",
            f"All {max_iterations} iterations exhausted without passing quality gate.",
            level="error",
        )

        # Still save last PDB URL for visualization
        if final_pdb_path:
            final_name = f"{run_id}_final.pdb"
            final_dest = PDBS_DIR / final_name
            shutil.copy2(final_pdb_path, final_dest)
            _write_state(
                status="completed_failure",
                final_pdb_url=f"/outputs/pdbs/{final_name}",
            )
        else:
            _write_state(status="completed_failure")

    except Exception as e:
        _append_log(run_id, "loop", "loop_error", f"Unhandled error in loop: {e}", level="error")
        _write_state(status="error")
        raise
