"""
Live end-to-end test for the Architect/Builder agent.

Exercises the full pipeline with real API calls:
  Claude (Sonnet 4.6) → RFdiffusion → ProteinMPNN → Boltz

PRD compliance checks:
  §13.3 / §13.4 — Architect input/output contract
  §15            — Log format (timestamp, agent, event, level, message)
  §16            — Live vs Fallback mode
  §18            — File contract ({run_id}_iter_{n}.pdb)

Run with:
  cd backend-python
  venv/bin/python -m pytest tests/test_e2e_live.py -v -s

The test reports timing per API step so you can see where time is spent.
ALLOW_FALLBACK=true is kept on — if Tamarind fails, the pipeline falls back
to the mock PDB and the test still validates the full output contract.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).parent.parent

# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def strategy():
    """Realistic Strategist output — mirrors PRD §13.2 schema exactly."""
    from agents.strategist import StrategistOutput
    return StrategistOutput(
        target_id="CXCL12",
        binding_hypothesis={
            "primary_anchor_zone": ["VAL18", "ARG47", "VAL49"],
            "secondary_extension_zone": ["PRO10", "LEU29", "VAL39"],
            "mode": "receptor_recognition_surface_hypothesis",
        },
        design_constraints={
            "min_length": 10,
            "max_length": 15,
            "desired_flexibility": "moderate",
            "topology_hint": "compact_turn_or_helical_motif",
            "avoid_excess_bulk_near": "ARG47",
        },
        rationale=(
            "Anchor in the validated sTyr21-recognition cleft (Val18/Arg47/Val49). "
            "Moderate length, compact topology to match the shallow receptor-recognition surface."
        ),
    )


# ── E2E Test ───────────────────────────────────────────────────────────────────

@pytest.mark.live
@pytest.mark.asyncio
async def test_e2e_architect_full_pipeline(strategy, tmp_path, capsys):
    """
    Full live pipeline: Claude → RFdiffusion → ProteinMPNN → Boltz (or fallback).

    Validates:
    - Architect returns a string path (PRD §13.4)
    - Output PDB file exists on disk (PRD §18)
    - Output filename matches {run_id}_iter_{n}.pdb (PRD §18)
    - Log file exists with ≥1 entries (PRD §15)
    - Every log entry has all required fields (PRD §15.2)
    - Log entries from architect have agent="architect" (PRD §15)
    - Affinity sidecar is written when Boltz runs (live mode)
    - Mode is correctly detected and reported (PRD §16)
    """
    import agents.architect as A
    import tools.tamarind as T

    run_id = f"e2e_{uuid.uuid4().hex[:8]}"
    iteration = 1

    print(f"\n{'='*60}")
    print(f"  LIVE E2E — Architect/Builder Pipeline")
    print(f"  run_id  : {run_id}")
    print(f"  target  : CXCL12  (PRD §2 — hardcoded target)")
    print(f"  iter    : {iteration}")
    print(f"{'='*60}")

    # Redirect file I/O to tmp_path so test doesn't pollute outputs/pdbs/
    import tools.tamarind as _T_module
    original_pdbs = _T_module.PDBS_DIR
    original_logs = _T_module.LOGS_DIR
    original_arch_logs = A.LOGS_DIR
    _T_module.PDBS_DIR = tmp_path
    _T_module.LOGS_DIR = tmp_path
    A.LOGS_DIR = tmp_path

    t_start = time.monotonic()

    try:
        # ── Step 1: Claude call (Strategist constraints → RFdiffusion settings) ──
        print(f"\n[1/4] Claude (sonnet-4-6): translating design constraints...")
        t0 = time.monotonic()
        pdb_path, boltz_scores = await A.run_architect(run_id, iteration, strategy)
        elapsed_total = time.monotonic() - t0
        print(f"      ✓ Completed in {elapsed_total:.1f}s")

    finally:
        _T_module.PDBS_DIR = original_pdbs
        _T_module.LOGS_DIR = original_logs
        A.LOGS_DIR = original_arch_logs

    # ── Assertions: Output contract (PRD §13.4, §18) ──────────────────────────
    print(f"\n[CHECKS] Validating PRD output contract...")

    # 1. Returns a string
    assert isinstance(pdb_path, str), "run_architect must return a string path"
    print(f"  ✓ Returns string path")

    # 2. File exists
    pdb_file = Path(pdb_path)
    assert pdb_file.exists(), f"Output PDB must exist on disk: {pdb_path}"
    print(f"  ✓ PDB file exists ({pdb_file.stat().st_size} bytes): {pdb_file.name}")

    # 3. Filename matches PRD §18 contract: {run_id}_iter_{n}.pdb
    expected_name = f"{run_id}_iter_{iteration}.pdb"
    assert pdb_file.name == expected_name, (
        f"Filename mismatch — got '{pdb_file.name}', expected '{expected_name}'"
    )
    print(f"  ✓ Filename matches PRD §18 contract: {pdb_file.name}")

    # 4. PDB file is non-empty and starts with valid PDB content
    pdb_content = pdb_file.read_bytes()
    assert len(pdb_content) > 100, "PDB file must contain real content"
    assert any(
        pdb_content.startswith(prefix)
        for prefix in (b"ATOM", b"REMARK", b"HEADER", b"MODEL")
    ), "PDB content must start with a valid PDB record"
    print(f"  ✓ PDB content valid ({len(pdb_content)} bytes)")

    # 5. Log file exists (PRD §15)
    log_file = tmp_path / f"{run_id}.jsonl"
    assert log_file.exists(), f"Log file must be created: {log_file}"
    log_lines = [l for l in log_file.read_text().splitlines() if l.strip()]
    assert len(log_lines) >= 1, "Log file must contain at least one entry"
    print(f"  ✓ Log file exists ({len(log_lines)} entries)")

    # 6. Every log entry has all required fields (PRD §15.2)
    required_fields = {"timestamp", "agent", "event", "level", "message"}
    for i, line in enumerate(log_lines):
        entry = json.loads(line)
        missing = required_fields - entry.keys()
        assert not missing, f"Log entry {i} missing fields: {missing}\n  entry: {entry}"
    print(f"  ✓ All log entries have required fields: {required_fields}")

    # 7. At least one log entry from the architect agent
    entries = [json.loads(l) for l in log_lines]
    architect_entries = [e for e in entries if e["agent"] == "architect"]
    assert len(architect_entries) >= 1, "Must have at least one architect log entry"
    print(f"  ✓ architect agent logged {len(architect_entries)} entries")

    # 8. Affinity sidecar — present in live mode, absent in fallback
    sidecar = tmp_path / f"{run_id}_iter_{iteration}_affinity.json"
    tamarind_entries = [e for e in entries if e["agent"] == "tamarind"]
    is_fallback = any("fallback" in e["event"] for e in tamarind_entries)
    mode = "fallback" if is_fallback else "live"

    if not is_fallback:
        assert sidecar.exists(), "Affinity sidecar JSON must exist in live mode"
        sidecar_data = json.loads(sidecar.read_text())
        print(f"  ✓ Affinity sidecar written:")
        print(f"      affinity_pred_value = {sidecar_data.get('affinity_pred_value')}")
        print(f"      binder_sequence     = {sidecar_data.get('binder_sequence', '')[:30]}...")
    else:
        print(f"  ⚠ Fallback mode — Tamarind was unavailable, used mock PDB (PRD §16.3)")

    # ── Summary ───────────────────────────────────────────────────────────────
    elapsed = time.monotonic() - t_start
    print(f"\n{'='*60}")
    print(f"  RESULT  : PASS")
    print(f"  mode    : {mode}  (PRD §16)")
    print(f"  pdb     : {pdb_file.name}")
    print(f"  logs    : {len(log_lines)} entries")
    print(f"  elapsed : {elapsed:.1f}s")
    print(f"{'='*60}\n")

    # Print the full agent log so the user can see the trace
    print("── Agent log trace ──────────────────────────────────────")
    for entry in entries:
        ts = entry["timestamp"][11:19]  # HH:MM:SS
        agent = entry["agent"].ljust(12)
        level = entry["level"].upper().ljust(7)
        print(f"  {ts}  [{agent}] {level}  {entry['message']}")
    print("─────────────────────────────────────────────────────────\n")
