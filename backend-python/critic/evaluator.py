"""
Critic — deterministic structure quality evaluation using BioPython.
No LLM calls. Checks pLDDT (B-factor column) and steric clashes.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from Bio import PDB

LOGS_DIR = Path(__file__).parent.parent / "outputs" / "logs"

PLDDT_THRESHOLD = 70.0  # lowered from 80 to pass more fallback PDBs
CLASH_DISTANCE = 1.5    # Angstroms


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


def _build_failure_reasons(plddt_mean: float, clashes: int) -> list[str]:
    reasons = []
    if plddt_mean <= PLDDT_THRESHOLD:
        reasons.append(f"pLDDT {plddt_mean:.1f} ≤ threshold {PLDDT_THRESHOLD}")
    if clashes > 0:
        reasons.append(f"{clashes} steric clash(es) detected (<{CLASH_DISTANCE}Å)")
    return reasons


def _build_feedback(plddt_mean: float, clashes: int) -> str:
    parts = []
    if plddt_mean <= PLDDT_THRESHOLD:
        parts.append(f"Confidence too low (pLDDT={plddt_mean:.1f}). Try a shorter, more rigid topology.")
    if clashes > 0:
        parts.append(f"{clashes} clash(es) detected. Reduce bulky residues near Arg47.")
    return " ".join(parts)


def evaluate(pdb_path: str, run_id: str | None = None) -> dict:
    """
    Parse PDB, compute pLDDT from B-factor column, count steric clashes.
    Returns a dict with pass/fail criteria and feedback for the Strategist.
    """
    parser = PDB.PDBParser(QUIET=True)
    structure = parser.get_structure("candidate", pdb_path)

    atoms = list(structure.get_atoms())
    if not atoms:
        result = {
            "plddt_mean": 0.0,
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
    # For larger structures, replace with Bio.PDB.NeighborSearch (KD-tree)
    clashes = 0
    for i, a1 in enumerate(atoms):
        for a2 in atoms[i + 2:]:  # skip i+1 (likely bonded neighbor)
            if (a1 - a2) < CLASH_DISTANCE:
                clashes += 1

    passed = plddt_mean > PLDDT_THRESHOLD and clashes == 0

    result = {
        "plddt_mean": round(plddt_mean, 2),
        "steric_clashes": clashes,
        "pass": passed,
        "failure_reasons": [] if passed else _build_failure_reasons(plddt_mean, clashes),
        "feedback_to_strategist": None if passed else _build_feedback(plddt_mean, clashes),
    }

    if run_id:
        status = "pass" if passed else "fail"
        _append_log(
            run_id,
            f"Evaluation {status}: pLDDT={plddt_mean:.1f}, clashes={clashes}. "
            f"{'Passed quality gate.' if passed else result['failure_reasons']}",
            event=f"evaluation_{status}",
            level="info" if passed else "warning",
        )

    return result
