"""
Architect agent — pure execution engine.

Responsibilities:
  1. Reads target info (sequence, hotspot numbers, PDB filename) from literature/.
  2. Uses Claude to translate Strategist constraints into RFdiffusion settings.
  3. Runs the full Tamarind pipeline: RFdiffusion → ProteinMPNN → Boltz.
  4. Saves the Boltz complex PDB and a scoring sidecar JSON locally.

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
LITERATURE_DIR = Path(__file__).parent.parent / "literature"


# ── Literature parsing ──────────────────────────────────────────────────────────

def _load_literature() -> str:
    """Return all literature/*.txt content concatenated."""
    if not LITERATURE_DIR.exists():
        return ""
    texts = []
    for path in sorted(LITERATURE_DIR.glob("*.txt")):
        texts.append(f"=== {path.name} ===\n{path.read_text().strip()}")
    return "\n\n".join(texts)


def _extract_target_sequence(literature: str) -> str | None:
    """
    Parse the canonical target sequence from the literature.
    Looks for a single-line uppercase amino-acid string of ≥20 chars
    under a heading that mentions 'sequence'.
    """
    for line in literature.splitlines():
        line = line.strip()
        if len(line) >= 20 and re.fullmatch(r"[ACDEFGHIKLMNPQRSTVWY]+", line):
            return line
    return None


def _extract_pdb_filename(literature: str) -> str | None:
    """Parse 'Local file : <name>.pdb' from literature."""
    match = re.search(r"Local file\s*:\s*(\S+\.pdb)", literature)
    return match.group(1) if match else None


def _extract_default_hotspots(literature: str) -> str:
    """Parse 'Default primary hotspots : <numbers>' from literature."""
    match = re.search(r"Default primary hotspots\s*:\s*\"([^\"]+)\"", literature)
    return match.group(1) if match else "18 47 49"


# ── Claude system prompt (generic — no hardcoded target biology) ───────────────

def _build_system_prompt(literature: str) -> str:
    return f"""You are a structural design engineer translating Strategist constraints into Tamarind RFdiffusion settings.

Use the literature below to determine the correct chain, hotspot residue numbers, and any target-specific rules.
The Strategist names residues like "VAL18" or "ARG47" — strip the amino-acid prefix to get bare residue numbers for binderHotspots.

Output ONLY a JSON object (no markdown fences) matching this exact schema:
{{
  "task": "Binder Design",
  "targetChains": ["<chain>"],
  "binderLength": "<min>-<max>",
  "binderHotspots": {{"<chain>": "<space-separated residue numbers>"}},
  "numDesigns": 1
}}

Rules:
- binderLength must be a range string like "10-15"
- binderHotspots must use bare integers separated by spaces, e.g. "18 47 49"
- Use primary anchor zone residues as hotspots by default
- Include secondary extension zone residues only when topology_hint is "helical" or flexibility is "rigid"
- numDesigns is always 1

## Literature
{literature}"""


# ── Logging ────────────────────────────────────────────────────────────────────

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


def _parse_rfd_settings(text: str, fallback_min: int, fallback_max: int, default_hotspots: str) -> dict:
    """
    Extract RFdiffusion settings dict from Claude's response.
    Falls back to literature-derived defaults if JSON cannot be parsed.
    """
    for pattern in (r"\{.*\}", r"```(?:json)?\s*(.*?)\s*```"):
        match = re.search(pattern, text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0) if pattern == r"\{.*\}" else match.group(1))
            except json.JSONDecodeError:
                continue

    return {
        "task": "Binder Design",
        "targetChains": ["A"],
        "binderLength": f"{fallback_min}-{fallback_max}",
        "binderHotspots": {"A": default_hotspots},
        "numDesigns": 1,
    }


# ── Main entry point ────────────────────────────────────────────────────────────

async def run_architect(run_id: str, iteration: int, strategy: StrategistOutput) -> tuple[str, dict | None]:
    """
    Orchestrates: Claude(settings) → RFdiffusion → ProteinMPNN → Boltz.

    Returns a tuple of (pdb_path, boltz_scores) where:
    - pdb_path is the local filesystem path to the Boltz complex PDB
    - boltz_scores is a dict with Boltz scoring metrics (e.g. iptm), or None if unavailable
    """
    # ── 0. Load target info from literature (no hardcoded biology) ──────────────
    literature = _load_literature()
    target_sequence = _extract_target_sequence(literature)
    pdb_filename = _extract_pdb_filename(literature) or "target.pdb"
    default_hotspots = _extract_default_hotspots(literature)

    if target_sequence is None:
        raise ValueError(
            "Could not extract target sequence from literature/. "
            "Add a file containing the sequence as a standalone uppercase line."
        )

    _append_log(
        run_id,
        f"Loaded target from literature: pdb={pdb_filename}, "
        f"seq_len={len(target_sequence)}, default_hotspots='{default_hotspots}'",
        event="literature_loaded",
    )

    constraints = strategy.design_constraints
    min_len: int = constraints.min_length
    max_len: int = constraints.max_length

    # ── 1. Ask Claude to translate Strategist constraints → RFdiffusion settings ─
    _append_log(run_id, f"Calling Claude to derive RFdiffusion settings (iter {iteration})", event="start")

    system_prompt = _build_system_prompt(literature)
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
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    claude_text = response.content[0].text

    rfd_settings = _parse_rfd_settings(claude_text, min_len, max_len, default_hotspots)

    _append_log(
        run_id,
        f"RFdiffusion settings: binderLength={rfd_settings.get('binderLength')}, "
        f"hotspots={rfd_settings.get('binderHotspots')}",
        event="settings_derived",
    )

    # ── 2. Run the full Tamarind pipeline (RFdiffusion → ProteinMPNN → Boltz) ───
    target_pdb_path = str(TARGET_PDBS_DIR / pdb_filename)

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
            target_sequence=target_sequence,
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

    return pdb_path, boltz_scores
