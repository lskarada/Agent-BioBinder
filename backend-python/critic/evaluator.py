"""
Critic — deterministic structure quality evaluation using BioPython.
No LLM calls. Checks pLDDT (B-factor column), steric clashes, and Boltz iptm score.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from Bio import PDB

LOGS_DIR = Path(__file__).parent.parent / "outputs" / "logs"

PLDDT_THRESHOLD = 80.0   # PRD §11.2
CLASH_DISTANCE  = 1.5    # Angstroms
IPTM_THRESHOLD  = 0.8    # Boltz interface confidence (≥0.8 = high quality)


def _append_log(run_id: str, message: str, event: str, level: str = "info") -> None:
    log_file = LOGS_DIR / f"{run_id}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "critic",
        "event": event,
        "level": level,
        "message": message,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _build_failure_reasons(plddt_mean: float, clashes: int, iptm: float | None) -> list[str]:
    reasons = []
    if plddt_mean <= PLDDT_THRESHOLD:
        reasons.append(f"pLDDT {plddt_mean:.1f} ≤ threshold {PLDDT_THRESHOLD}")
    if clashes > 0:
        reasons.append(f"{clashes} steric clash(es) detected (<{CLASH_DISTANCE}Å)")
    if iptm is not None and iptm < IPTM_THRESHOLD:
        reasons.append(f"iptm {iptm:.3f} < threshold {IPTM_THRESHOLD}")
    return reasons


def _build_feedback(plddt_mean: float, clashes: int, iptm: float | None) -> str:
    parts = []
    if plddt_mean <= PLDDT_THRESHOLD:
        parts.append(f"Confidence too low (pLDDT={plddt_mean:.1f}). Try a shorter, more rigid topology.")
    if clashes > 0:
        parts.append(f"{clashes} clash(es) detected. Reduce bulky residues near Arg47.")
    if iptm is not None and iptm < IPTM_THRESHOLD:
        parts.append(f"Interface confidence too low (iptm={iptm:.3f}). Try a more complementary topology.")
    return " ".join(parts)


def evaluate(
    pdb_path: str,
    run_id: str | None = None,
    iteration: int | None = None,
    boltz_scores: dict | None = None,
) -> dict:
    """
    Parse PDB, compute pLDDT from B-factor column, count steric clashes,
    and apply Boltz iptm interface-confidence criterion.

    Returns a dict (PRD §13.5) with: design_id, plddt_mean, iptm,
    steric_clashes, pass, failure_reasons, feedback_to_strategist.
    """
    design_id = (
        f"{run_id}_iter_{iteration:02d}"
        if run_id and iteration is not None
        else None
    )

    parser = PDB.PDBParser(QUIET=True)
    structure = parser.get_structure("candidate", pdb_path)

    atoms = list(structure.get_atoms())
    iptm = boltz_scores.get("iptm") if boltz_scores else None

    if not atoms:
        result = {
            "design_id": design_id,
            "plddt_mean": 0.0,
            "iptm": iptm,
            "steric_clashes": 0,
            "pass": False,
            "failure_reasons": ["No atoms found in PDB"],
            "feedback_to_strategist": "Empty or invalid PDB. Try a different topology.",
        }
        if run_id:
            _append_log(run_id, "No atoms found in PDB", event="evaluation_error", level="error")
        return result

    # pLDDT from B-factor column (RFDiffusion / AF2 output convention)
    bfactors = [atom.get_bfactor() for atom in atoms]
    plddt_mean = float(np.mean(bfactors))

    # Steric clashes: O(n²) — fine for short peptides ≤20 residues
    clashes = 0
    for i, a1 in enumerate(atoms):
        for a2 in atoms[i + 2:]:  # skip i+1 (likely bonded neighbor)
            if (a1 - a2) < CLASH_DISTANCE:
                clashes += 1

    plddt_ok = plddt_mean > PLDDT_THRESHOLD
    clash_ok = clashes == 0
    iptm_ok  = (iptm is None) or (iptm >= IPTM_THRESHOLD)
    passed   = plddt_ok and clash_ok and iptm_ok

    result = {
        "design_id": design_id,
        "plddt_mean": round(plddt_mean, 2),
        "iptm": iptm,
        "steric_clashes": clashes,
        "pass": passed,
        "failure_reasons": [] if passed else _build_failure_reasons(plddt_mean, clashes, iptm),
        "feedback_to_strategist": None if passed else _build_feedback(plddt_mean, clashes, iptm),
    }

    if run_id:
        status = "pass" if passed else "fail"
        iptm_str = f", iptm={iptm:.3f}" if iptm is not None else ""
        _append_log(
            run_id,
            f"Evaluation {status}: pLDDT={plddt_mean:.1f}, clashes={clashes}{iptm_str}. "
            f"{'Passed quality gate.' if passed else result['failure_reasons']}",
            event=f"evaluation_{status}",
            level="info" if passed else "warning",
        )

    return result
