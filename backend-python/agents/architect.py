"""
Architect agent — pure execution engine.

Responsibilities:
  1. Uses Claude to translate Strategist constraints into RFdiffusion settings.
  2. Runs the full Tamarind pipeline: RFdiffusion → ProteinMPNN → Boltz.
  3. Saves the Boltz complex PDB and an affinity sidecar JSON locally.

Returns the path to the final PDB so the Critic can evaluate it.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from agents.strategist import StrategistOutput
from tools.tamarind import TamarindFailedError, TamarindTimeoutError, run_pipeline

LOGS_DIR = Path(__file__).parent.parent / "outputs" / "logs"
TARGET_PDBS_DIR = Path(__file__).parent.parent / "target_pdbs"

# ── CXCL12 canonical sequence (human mature form, UniProt P10145) ─────────────
# Used as the target input for Boltz affinity prediction.
# Residues: Val18, Arg47, Val49 form the sTyr21-recognition cleft (primary anchor zone).
CXCL12_SEQUENCE = (
    "KPVSLSYRCPCRFFESHVARANTSGRKTSIINLTTLHQLSRKALNCRITEELIQKLES"
    "DGPHQVLDYVQEG"
)

# ── Claude prompt ──────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """You are a structural design engineer translating Strategist constraints into Tamarind RFdiffusion settings.

Target: CXCL12 (chain A). Primary hotspots: A18, A47, A49 (sTyr21-recognition cleft).
Secondary hotspots: A10, A29, A39 (adjacent hydrophobic patch).

Output ONLY a JSON object (no markdown fences) matching this exact schema:
{
  "task": "Binder Design",
  "targetChains": ["A"],
  "binderLength": "<min>-<max>",
  "binderHotspots": {"A": "<space-separated residue numbers>"},
  "numDesigns": 1
}

Rules:
- binderLength must be a range string like "10-15"
- binderHotspots["A"] must be space-separated integers, e.g. "18 47 49"
- Include secondary hotspots only when topology_hint is "helical" or flexibility is "rigid"
- numDesigns is always 1"""


def _append_log(run_id: str, message: str, event: str = "info", level: str = "info") -> None:
    log_file = LOGS_DIR / f"{run_id}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "architect",
        "event": event,
        "level": level,
        "message": message,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _parse_rfd_settings(text: str, fallback_min: int, fallback_max: int) -> dict:
    """
    Extract RFdiffusion settings dict from Claude's response.
    Falls back to sensible defaults if JSON cannot be parsed.
    """
    # Try bare JSON first, then fenced block
    for pattern in (r"\{.*\}", r"```(?:json)?\s*(.*?)\s*```"):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0) if pattern == r"\{.*\}" else match.group(1))
            except json.JSONDecodeError:
                continue

    _default_hotspots = "18 47 49"
    return {
        "task": "Binder Design",
        "targetChains": ["A"],
        "binderLength": f"{fallback_min}-{fallback_max}",
        "binderHotspots": {"A": _default_hotspots},
        "numDesigns": 1,
    }


# ── Main entry point ───────────────────────────────────────────────────────────

async def run_architect(run_id: str, iteration: int, strategy: StrategistOutput) -> str:
    """
    Orchestrates: Claude(settings) → RFdiffusion → ProteinMPNN → Boltz.

    Returns the local filesystem path to the Boltz complex PDB.
    Interface is unchanged: always returns a str path that the Critic can open.
    """
    constraints = strategy.design_constraints
    # DesignConstraints is a Pydantic model — use attribute access
    min_len: int = constraints.min_length
    max_len: int = constraints.max_length

    # ── 1. Ask Claude to translate Strategist constraints → RFdiffusion settings
    _append_log(run_id, f"Calling Claude to derive RFdiffusion settings (iter {iteration})", event="start")

    claude = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    constraints_dict = constraints.model_dump()
    binding_dict = strategy.binding_hypothesis.model_dump()
    user_message = (
        f"Strategist constraints (iteration {iteration}):\n"
        f"{json.dumps({'binding_hypothesis': binding_dict, 'design_constraints': constraints_dict}, indent=2)}\n\n"
        f"Binder length range: {min_len}–{max_len}.\n"
        "Output the RFdiffusion settings JSON."
    )

    response = await claude.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    claude_text = response.content[0].text

    rfd_settings = _parse_rfd_settings(claude_text, min_len, max_len)

    _append_log(
        run_id,
        f"RFdiffusion settings: binderLength={rfd_settings.get('binderLength')}, "
        f"hotspots={rfd_settings.get('binderHotspots')}",
        event="settings_derived",
    )

    # ── 2. Run the full Tamarind pipeline (RFdiffusion → ProteinMPNN → Boltz) ──
    target_pdb_path = str(TARGET_PDBS_DIR / "cxcl12.pdb")

    _append_log(
        run_id,
        f"Starting Tamarind pipeline for iter {iteration}: "
        f"RFdiffusion → ProteinMPNN → Boltz",
        event="pipeline_start",
    )

    try:
        pdb_path, affinity, boltz_scores = await run_pipeline(
            run_id=run_id,
            iteration=iteration,
            target_pdb_path=target_pdb_path,
            target_sequence=CXCL12_SEQUENCE,
            rfd_settings=rfd_settings,
        )
    except (TamarindTimeoutError, TamarindFailedError) as e:
        _append_log(run_id, f"Pipeline failed: {e}", event="pipeline_failed", level="error")
        raise

    iptm = boltz_scores.get("iptm") if boltz_scores else None
    if iptm is not None:
        quality = "PASS" if iptm >= 0.8 else "FAIL"
        _append_log(
            run_id,
            f"Pipeline done. iptm={iptm:.3f} [{quality}], complex PDB saved: {pdb_path}",
            event="pipeline_done",
        )
    elif affinity is not None:
        _append_log(
            run_id,
            f"Pipeline done. affinity_pred_value={affinity:.4f}, PDB saved: {pdb_path}",
            event="pipeline_done",
        )
    else:
        _append_log(
            run_id,
            f"Pipeline done (no scoring available). PDB saved: {pdb_path}",
            event="pipeline_done",
        )

    return pdb_path
