"""Shared fixtures for the Strategist test suite."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.strategist import BindingHypothesis, DesignConstraints, StrategistOutput

# ── PRD §13.2 compliant output ────────────────────────────────────────────────

PRD_COMPLIANT_OUTPUT = StrategistOutput(
    target_id="CXCL12",
    binding_hypothesis=BindingHypothesis(
        primary_anchor_zone=["VAL18", "ARG47", "VAL49"],
        secondary_extension_zone=["PRO10", "LEU29", "VAL39"],
        mode="competitive_displacement",
    ),
    design_constraints=DesignConstraints(
        min_length=8,
        max_length=18,
        desired_flexibility="moderate",
        topology_hint="compact_turn_or_helical_motif",
        avoid_excess_bulk_near="ARG47",
    ),
    rationale="Engages the sTyr21-recognition cleft of CXCL12 to block CXCR4 binding.",
)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def tmp_logs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect LOGS_DIR to a temporary directory so tests never touch outputs/."""
    import agents.strategist as strategist_mod

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    monkeypatch.setattr(strategist_mod, "LOGS_DIR", logs_dir)
    return logs_dir


@pytest.fixture()
def mock_openai(monkeypatch: pytest.MonkeyPatch):
    """
    Patch AsyncOpenAI so run_strategist returns PRD_COMPLIANT_OUTPUT without
    making any network calls.
    """
    import agents.strategist as strategist_mod

    parsed_response = MagicMock()
    parsed_response.choices[0].message.parsed = PRD_COMPLIANT_OUTPUT

    async_client = MagicMock()
    async_client.beta.chat.completions.parse = AsyncMock(return_value=parsed_response)

    mock_cls = MagicMock(return_value=async_client)
    monkeypatch.setattr(strategist_mod, "AsyncOpenAI", mock_cls)
    return mock_cls
