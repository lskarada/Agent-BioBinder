"""
Shared fixtures for all agent test suites (Strategist, Architect, Tamarind).
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / ".env"))

BACKEND_DIR = Path(__file__).parent.parent
MOCK_PDB_SRC = BACKEND_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"

# ── Strategist fixtures ────────────────────────────────────────────────────────

from agents.strategist import BindingHypothesis, DesignConstraints, StrategistOutput

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


# ── Architect / Tamarind raw data fixtures ─────────────────────────────────────

@pytest.fixture()
def mock_pdb_bytes() -> bytes:
    return MOCK_PDB_SRC.read_bytes()


@pytest.fixture()
def mock_pdb_zip(mock_pdb_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("result/binder.pdb", mock_pdb_bytes)
    return buf.getvalue()


@pytest.fixture()
def mock_fasta_bytes() -> bytes:
    return b">designed_binder score=1.23\nACDEFGHIKLMN\n"


@pytest.fixture()
def mock_fasta_zip(mock_fasta_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("sequences/binder_0.fasta", mock_fasta_bytes)
    return buf.getvalue()


@pytest.fixture()
def mock_boltz_zip(mock_pdb_bytes: bytes) -> bytes:
    """Zip with PDB + affinity JSON (Boltz output shape)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("predictions/complex.pdb", mock_pdb_bytes)
        zf.writestr("affinity.json", json.dumps({"affinity_pred_value": -9.42}))
    return buf.getvalue()


@pytest.fixture()
def mock_boltz_zip_no_affinity(mock_pdb_bytes: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("predictions/complex.pdb", mock_pdb_bytes)
    return buf.getvalue()


# ── Environment fixtures ───────────────────────────────────────────────────────

@pytest.fixture()
def env_fallback(monkeypatch: pytest.MonkeyPatch):
    """LIVE_API=false — Tamarind calls skipped, fallback PDB used."""
    monkeypatch.setenv("LIVE_API", "false")
    monkeypatch.setenv("ALLOW_FALLBACK", "true")
    monkeypatch.setenv("TAMARIND_API_KEY", "test-key")


@pytest.fixture()
def env_live(monkeypatch: pytest.MonkeyPatch):
    """LIVE_API=true — httpx calls must be mocked."""
    monkeypatch.setenv("LIVE_API", "true")
    monkeypatch.setenv("ALLOW_FALLBACK", "true")
    monkeypatch.setenv("TAMARIND_API_KEY", "test-key")
    monkeypatch.setenv("TAMARIND_BASE_URL", "https://app.tamarind.bio/api")
    monkeypatch.setenv("TAMARIND_TIMEOUT_SECONDS", "30")


@pytest.fixture()
def env_live_no_fallback(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LIVE_API", "true")
    monkeypatch.setenv("ALLOW_FALLBACK", "false")
    monkeypatch.setenv("TAMARIND_API_KEY", "test-key")
    monkeypatch.setenv("TAMARIND_BASE_URL", "https://app.tamarind.bio/api")
    monkeypatch.setenv("TAMARIND_TIMEOUT_SECONDS", "30")


# ── Claude mock fixture ────────────────────────────────────────────────────────

@pytest.fixture()
def mock_claude():
    """
    Patches anthropic.AsyncAnthropic so no real API calls are made.
    Returns the mock client so tests can inspect calls made to it.
    """
    rfd_json = json.dumps({
        "task": "Binder Design", "targetChains": ["A"],
        "binderLength": "10-15", "binderHotspots": {"A": "18 47 49"}, "numDesigns": 1,
    })
    content_block = MagicMock()
    content_block.text = rfd_json
    response = MagicMock()
    response.content = [content_block]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=response)

    with patch("anthropic.AsyncAnthropic", return_value=mock_client):
        yield mock_client


# ── httpx mock helpers ─────────────────────────────────────────────────────────

def make_response(status_code: int = 200, json_body=None, content: bytes = b"") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.content = content
    resp.json = MagicMock(return_value=json_body if json_body is not None else {})
    resp.raise_for_status = MagicMock()
    return resp


def make_async_client(**method_returns) -> AsyncMock:
    """
    Build an AsyncMock httpx client usable as `async with httpx.AsyncClient() as c`.
    Pass keyword args like put=..., post=..., get=... as AsyncMock return values.
    """
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    for method, return_value in method_returns.items():
        setattr(client, method, AsyncMock(return_value=return_value))
    return client
