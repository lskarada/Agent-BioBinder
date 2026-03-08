"""
Tests for critic/evaluator.py — PRD §13.5 contract + helper unit coverage.
All tests are mocked (no live API calls, no real PDB files needed).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.conftest import CLASH_PDB, LOW_PLDDT_PDB, PASSING_PDB
from critic.evaluator import (
    IPTM_THRESHOLD,
    PLDDT_THRESHOLD,
    _build_failure_reasons,
    _build_feedback,
    evaluate,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _write_pdb(tmp_path: Path, content: str, name: str = "test.pdb") -> str:
    p = tmp_path / name
    p.write_text(content)
    return str(p)


# ── A. Unit — _build_failure_reasons / _build_feedback ───────────────────────

def test_failure_reasons_plddt():
    reasons = _build_failure_reasons(plddt_mean=60.0, clashes=0, iptm=None)
    assert any("pLDDT" in r and str(PLDDT_THRESHOLD) in r for r in reasons)


def test_failure_reasons_clashes():
    reasons = _build_failure_reasons(plddt_mean=90.0, clashes=3, iptm=None)
    assert any("3" in r and "clash" in r.lower() for r in reasons)


def test_failure_reasons_iptm():
    reasons = _build_failure_reasons(plddt_mean=90.0, clashes=0, iptm=0.5)
    assert any("iptm" in r and "0.500" in r for r in reasons)


def test_feedback_plddt():
    feedback = _build_feedback(plddt_mean=60.0, clashes=0, iptm=None)
    assert "topology" in feedback.lower() or "rigid" in feedback.lower()


def test_feedback_iptm():
    feedback = _build_feedback(plddt_mean=90.0, clashes=0, iptm=0.5)
    assert "complementary" in feedback.lower() or "topology" in feedback.lower()


# ── B. Unit — evaluate() with real PDB fixtures ───────────────────────────────

def test_evaluate_passing_pdb(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb, boltz_scores={"iptm": 0.9})
    assert result["pass"] is True


def test_evaluate_low_plddt(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, LOW_PLDDT_PDB)
    result = evaluate(pdb)
    assert result["pass"] is False
    assert result["plddt_mean"] <= PLDDT_THRESHOLD


def test_evaluate_steric_clash(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, CLASH_PDB)
    result = evaluate(pdb)
    assert result["pass"] is False
    assert result["steric_clashes"] > 0


def test_evaluate_low_iptm(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb, boltz_scores={"iptm": 0.5})
    assert result["pass"] is False
    assert result["iptm"] == 0.5


def test_evaluate_no_boltz_scores(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb, boltz_scores=None)
    assert result["iptm"] is None
    # Should still pass — iptm=None is not penalised
    assert result["pass"] is True


# ── C. PRD §13.5 contract ─────────────────────────────────────────────────────

def test_contract_design_id(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb, run_id="run-001", iteration=2)
    assert result["design_id"] == "run-001_iter_02"


def test_contract_all_keys_present(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb, run_id="run-001", iteration=1, boltz_scores={"iptm": 0.9})
    for key in ("design_id", "plddt_mean", "iptm", "steric_clashes", "pass",
                "failure_reasons", "feedback_to_strategist"):
        assert key in result, f"Missing key: {key}"


def test_contract_pass_is_bool(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb)
    assert isinstance(result["pass"], bool)


def test_contract_failure_reasons_empty_on_pass(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb, boltz_scores={"iptm": 0.9})
    assert result["pass"] is True
    assert result["failure_reasons"] == []


def test_contract_feedback_none_on_pass(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb, boltz_scores={"iptm": 0.9})
    assert result["pass"] is True
    assert result["feedback_to_strategist"] is None


# ── D. Logging ────────────────────────────────────────────────────────────────

def test_log_written_on_evaluate(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    evaluate(pdb, run_id="run-log-test")
    log_file = tmp_logs_critic / "run-log-test.jsonl"
    assert log_file.exists()
    assert log_file.stat().st_size > 0


def test_log_has_prd_fields(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    evaluate(pdb, run_id="run-prd-fields")
    log_file = tmp_logs_critic / "run-prd-fields.jsonl"
    entry = json.loads(log_file.read_text().strip().splitlines()[-1])
    for field in ("timestamp", "agent", "event", "level", "message"):
        assert field in entry, f"Missing log field: {field}"
    assert entry["agent"] == "critic"


def test_no_log_without_run_id(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    evaluate(pdb)  # no run_id
    assert list(tmp_logs_critic.iterdir()) == []


# ── E. Regression ─────────────────────────────────────────────────────────────

def test_empty_pdb_does_not_raise(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, "END\n")
    result = evaluate(pdb)
    assert result["pass"] is False
    assert len(result["failure_reasons"]) > 0


def test_design_id_none_when_no_run_id(tmp_path, tmp_logs_critic):
    pdb = _write_pdb(tmp_path, PASSING_PDB)
    result = evaluate(pdb)
    assert result["design_id"] is None
