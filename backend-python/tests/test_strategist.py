"""
Test suite for agents/strategist.py — PRD §13.2 contract.

Groups:
  A. Unit — _build_user_prompt          (2 tests)
  B. Unit — _append_log                 (2 tests)
  C. Mock async — run_strategist        (4 tests)
  D. PRD §13.2 contract (mocked)        (5 tests)
  E. Regression                         (1 test)
  F. Live smoke test                    (1 test)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agents.strategist import (
    StrategistOutput,
    _append_log,
    _build_user_prompt,
    _load_literature,
    run_strategist,
)
from tests.conftest import PRD_COMPLIANT_OUTPUT


# ── A. Unit — _load_literature ───────────────────────────────────────────────


def test_load_literature_empty_dir(tmp_path, monkeypatch):
    import agents.strategist as strategist_mod
    # Point __file__ so that parent.parent / "literature" does not exist
    fake_file = tmp_path / "agents" / "strategist.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.touch()
    monkeypatch.setattr(strategist_mod, "__file__", str(fake_file))
    result = _load_literature()
    assert result == ""


def test_load_literature_reads_txt_files(tmp_path, monkeypatch):
    import agents.strategist as strategist_mod
    # Point __file__ so that parent.parent == tmp_path
    fake_file = tmp_path / "agents" / "strategist.py"
    fake_file.parent.mkdir(parents=True)
    fake_file.touch()
    monkeypatch.setattr(strategist_mod, "__file__", str(fake_file))
    # Create literature dir with two txt files
    lit_dir = tmp_path / "literature"
    lit_dir.mkdir()
    (lit_dir / "aa_first.txt").write_text("content alpha")
    (lit_dir / "bb_second.txt").write_text("content beta")
    result = _load_literature()
    assert "aa_first.txt" in result
    assert "content alpha" in result
    assert "bb_second.txt" in result
    assert "content beta" in result


# ── B. Unit — _build_user_prompt ─────────────────────────────────────────────


def test_prompt_iteration_number():
    prompt = _build_user_prompt(1, feedback=None)
    assert "Iteration 1" in prompt
    assert "Critic feedback" not in prompt


def test_prompt_includes_feedback():
    feedback = "Increase hydrophobic contacts near Val18."
    prompt = _build_user_prompt(2, feedback=feedback)
    assert feedback in prompt


# ── B. Unit — _append_log ────────────────────────────────────────────────────


def test_log_creates_jsonl_file(tmp_logs: Path):
    _append_log("run-001", "test message")
    log_file = tmp_logs / "run-001.jsonl"
    assert log_file.exists()
    line = json.loads(log_file.read_text().strip())
    assert line["message"] == "test message"


def test_log_has_all_prd_fields(tmp_logs: Path):
    _append_log("run-002", "prd field check", event="start")
    log_file = tmp_logs / "run-002.jsonl"
    entry = json.loads(log_file.read_text().strip())
    assert "timestamp" in entry
    assert entry["agent"] == "strategist"
    assert "event" in entry
    assert entry["level"] == "info"
    assert "message" in entry


# ── C. Mock async — run_strategist behavior ───────────────────────────────────


async def test_run_strategist_returns_strategist_output(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = await run_strategist("run-100", iteration=1)
    assert isinstance(result, StrategistOutput)


async def test_run_strategist_writes_two_log_entries(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    await run_strategist("run-101", iteration=1)
    log_file = tmp_logs / "run-101.jsonl"
    lines = [l for l in log_file.read_text().strip().splitlines() if l]
    assert len(lines) == 2


async def test_run_strategist_start_log_event(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    await run_strategist("run-102", iteration=1)
    log_file = tmp_logs / "run-102.jsonl"
    first_entry = json.loads(log_file.read_text().splitlines()[0])
    assert first_entry["event"] == "start"


async def test_run_strategist_with_feedback_in_prompt(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    feedback_text = "Reduce steric clash near Arg47."
    await run_strategist("run-103", iteration=2, previous_feedback=feedback_text)

    # Inspect the call that was made to the mocked client
    import agents.strategist as strategist_mod
    mock_client_instance = strategist_mod.AsyncOpenAI.return_value
    call_kwargs = mock_client_instance.beta.chat.completions.parse.call_args
    messages = call_kwargs.kwargs.get("messages") or call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs["messages"]
    # Find the user message
    user_message = next(m for m in messages if m["role"] == "user")
    assert feedback_text in user_message["content"]


# ── D. PRD §13.2 contract (mocked) ───────────────────────────────────────────


async def test_contract_target_id_is_cxcl12(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = await run_strategist("run-200", iteration=1)
    assert result.target_id == "CXCL12"


async def test_contract_primary_anchor_zone(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = await run_strategist("run-201", iteration=1)
    zone = [r.upper() for r in result.binding_hypothesis.primary_anchor_zone]
    assert "VAL18" in zone
    assert "ARG47" in zone
    assert "VAL49" in zone


async def test_contract_secondary_extension_zone(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = await run_strategist("run-202", iteration=1)
    zone = [r.upper() for r in result.binding_hypothesis.secondary_extension_zone]
    assert "PRO10" in zone
    assert "LEU29" in zone
    assert "VAL39" in zone


async def test_contract_length_bounds(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = await run_strategist("run-203", iteration=1)
    assert result.design_constraints.min_length >= 8
    assert result.design_constraints.max_length <= 18


async def test_contract_rationale_nonempty(tmp_logs, mock_openai, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    result = await run_strategist("run-204", iteration=1)
    assert isinstance(result.rationale, str) and len(result.rationale) > 0


# ── E. Regression ────────────────────────────────────────────────────────────


async def test_missing_api_key_raises_key_error(tmp_logs, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(KeyError):
        await run_strategist("run-300", iteration=1)


# ── F. Live smoke test ────────────────────────────────────────────────────────


@pytest.mark.live
async def test_live_run_strategist_full_prd_contract(tmp_logs):
    """
    Calls real OpenAI. Requires OPENAI_API_KEY in environment or .env file.
    Run with: pytest -m live
    """
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).parent.parent / ".env")

    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set — skipping live test")

    result = await run_strategist("run-live-001", iteration=1)

    # PRD §13.2 contract assertions
    assert isinstance(result, StrategistOutput)
    assert result.target_id == "CXCL12"

    primary = [r.upper() for r in result.binding_hypothesis.primary_anchor_zone]
    assert any("VAL18" in r or "18" in r for r in primary), f"VAL18 not in primary_anchor_zone: {primary}"
    assert any("ARG47" in r or "47" in r for r in primary), f"ARG47 not in primary_anchor_zone: {primary}"
    assert any("VAL49" in r or "49" in r for r in primary), f"VAL49 not in primary_anchor_zone: {primary}"

    secondary = [r.upper() for r in result.binding_hypothesis.secondary_extension_zone]
    assert any("PRO10" in r or "10" in r for r in secondary), f"PRO10 not in secondary_extension_zone: {secondary}"
    assert any("LEU29" in r or "29" in r for r in secondary), f"LEU29 not in secondary_extension_zone: {secondary}"
    assert any("VAL39" in r or "39" in r for r in secondary), f"VAL39 not in secondary_extension_zone: {secondary}"

    assert result.design_constraints.min_length >= 8
    assert result.design_constraints.max_length <= 18
    assert isinstance(result.rationale, str) and len(result.rationale) > 0

    # Log file written with correct PRD §15.2 fields
    log_file = tmp_logs / "run-live-001.jsonl"
    assert log_file.exists()
    lines = [json.loads(l) for l in log_file.read_text().splitlines() if l]
    assert len(lines) == 2
    for entry in lines:
        assert "timestamp" in entry
        assert entry["agent"] == "strategist"
        assert "event" in entry
        assert entry["level"] == "info"
        assert "message" in entry
