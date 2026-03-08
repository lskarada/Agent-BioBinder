"""
Tests for agents/architect.py — the Architect builder agent.

Coverage map (keyed to PRD requirements):
  PRD §13.3 — Architect Input: validated Strategist output, run_id, iteration, mode
  PRD §13.4 — Architect Output: design_id, tamarind_mode, output_pdb_path
  PRD §15   — Logging rules: required fields, event types
  PRD §16   — Live vs Fallback mode
  PRD §18   — File contract: {run_id}_iter_{n}.pdb
  PRD §8.2  — Engineering interpretation: hotspots anchored to Val18/Arg47/Val49
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import agents.architect as A

BACKEND_DIR = Path(__file__).parent.parent
MOCK_PDB = BACKEND_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"


# ── Minimal Strategist output for testing ──────────────────────────────────────

def make_strategy(min_length: int = 10, max_length: int = 15):
    from agents.strategist import StrategistOutput
    return StrategistOutput(
        target_id="CXCL12",
        binding_hypothesis={
            "primary_anchor_zone": ["VAL18", "ARG47", "VAL49"],
            "secondary_extension_zone": ["PRO10", "LEU29", "VAL39"],
            "mode": "receptor_recognition_surface_hypothesis",
        },
        design_constraints={
            "min_length": min_length,
            "max_length": max_length,
            "desired_flexibility": "moderate",
            "topology_hint": "compact_turn_or_helical_motif",
            "avoid_excess_bulk_near": "ARG47",
        },
        rationale="Anchor in the validated receptor-recognition cleft.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 1. LITERATURE PARSING  (sequence and hotspots read from literature/, not hardcoded)
# ═══════════════════════════════════════════════════════════════════════════════

_MOCK_LITERATURE = """
=== 03_cxcl12_sequence_and_structure.txt ===
Local file : cxcl12.pdb

CANONICAL SEQUENCE (mature form, 68 residues)
----------------------------------------------
KPVSLSYRCPCRFFESHVARANTSGRKTSIINLTTLHQLSRKALNCRITEELIQKLESDGPHQVLDYVQEG

Default primary hotspots  : "18 47 49"
Default secondary hotspots: "10 29 39"
"""

class TestLiteratureParsing:
    def test_extract_target_sequence_from_literature(self):
        seq = A._extract_target_sequence(_MOCK_LITERATURE)
        assert seq == "KPVSLSYRCPCRFFESHVARANTSGRKTSIINLTTLHQLSRKALNCRITEELIQKLESDGPHQVLDYVQEG"

    def test_sequence_reasonable_length(self):
        seq = A._extract_target_sequence(_MOCK_LITERATURE)
        assert 50 <= len(seq) <= 100

    def test_sequence_uppercase_amino_acids_only(self):
        seq = A._extract_target_sequence(_MOCK_LITERATURE)
        valid_aa = set("ACDEFGHIKLMNPQRSTVWY")
        assert not (set(seq) - valid_aa)

    def test_sequence_contains_key_residues(self):
        seq = A._extract_target_sequence(_MOCK_LITERATURE)
        assert "V" in seq and "R" in seq

    def test_extract_pdb_filename(self):
        assert A._extract_pdb_filename(_MOCK_LITERATURE) == "cxcl12.pdb"

    def test_extract_default_hotspots(self):
        assert A._extract_default_hotspots(_MOCK_LITERATURE) == "18 47 49"

    def test_returns_none_when_no_sequence(self):
        assert A._extract_target_sequence("no sequence here") is None


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RFD SETTINGS PARSER  (architect internal)
# ═══════════════════════════════════════════════════════════════════════════════

class TestParseRfdSettings:
    def test_parses_clean_json_from_claude(self):
        json_str = json.dumps({
            "task": "Binder Design",
            "targetChains": ["A"],
            "binderLength": "10-15",
            "binderHotspots": {"A": "18 47 49"},
            "numDesigns": 1,
        })
        result = A._parse_rfd_settings(json_str, 10, 15, "18 47 49")
        assert result["binderLength"] == "10-15"
        assert result["binderHotspots"]["A"] == "18 47 49"

    def test_parses_fenced_json_block(self):
        text = """
Here is the payload:
```json
{"task": "Binder Design", "targetChains": ["A"], "binderLength": "8-12",
 "binderHotspots": {"A": "18 47 49"}, "numDesigns": 1}
```
I chose these hotspots because...
"""
        result = A._parse_rfd_settings(text, 8, 12, "18 47 49")
        assert result["binderLength"] == "8-12"

    def test_fallback_defaults_on_invalid_json(self):
        """If Claude returns garbage, architect must fall back to sensible defaults."""
        result = A._parse_rfd_settings("sorry I cannot help with that", 10, 15, "18 47 49")
        assert "binderLength" in result
        assert result["binderLength"] == "10-15"
        assert "binderHotspots" in result

    def test_fallback_uses_primary_hotspots(self):
        """PRD §8.3: fallback hotspots must include the primary anchor residues."""
        result = A._parse_rfd_settings("not json", 10, 15, "18 47 49")
        hotspot_str = str(result.get("binderHotspots", ""))
        # At minimum, residues 18, 47, 49 must be represented
        assert "18" in hotspot_str and "47" in hotspot_str and "49" in hotspot_str

    def test_binder_length_encodes_strategy_constraints(self):
        """binderLength must reflect min/max from Strategist output."""
        result = A._parse_rfd_settings("garbage json", 8, 18, "18 47 49")
        assert result["binderLength"] == "8-18"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. run_architect — FALLBACK MODE  (PRD §16.3)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestRunArchitectFallback:
    async def test_returns_pdb_path_string(self, tmp_path, env_fallback, mock_claude):
        strategy = make_strategy()
        with patch("tools.tamarind.PDBS_DIR", tmp_path), \
             patch("tools.tamarind.LOGS_DIR", tmp_path), \
             patch.object(A, "LOGS_DIR", tmp_path):
            path = await A.run_architect("run_f01", 1, strategy)
        assert isinstance(path, str)

    async def test_returned_pdb_exists_on_disk(self, tmp_path, env_fallback, mock_claude):
        """PRD §18: file must exist at the returned path."""
        strategy = make_strategy()
        with patch("tools.tamarind.PDBS_DIR", tmp_path), \
             patch("tools.tamarind.LOGS_DIR", tmp_path), \
             patch.object(A, "LOGS_DIR", tmp_path):
            path = await A.run_architect("run_f02", 1, strategy)
        assert Path(path).exists()

    async def test_output_filename_matches_prd_contract(self, tmp_path, env_fallback, mock_claude):
        """PRD §18: filename must be {run_id}_iter_{n}.pdb."""
        strategy = make_strategy()
        with patch("tools.tamarind.PDBS_DIR", tmp_path), \
             patch("tools.tamarind.LOGS_DIR", tmp_path), \
             patch.object(A, "LOGS_DIR", tmp_path):
            path = await A.run_architect("run_f03", 2, strategy)
        assert Path(path).name == "run_f03_iter_2.pdb"

    async def test_writes_log_entries(self, tmp_path, env_fallback, mock_claude):
        """PRD §15: architect must write log entries during execution."""
        strategy = make_strategy()
        with patch("tools.tamarind.PDBS_DIR", tmp_path), \
             patch("tools.tamarind.LOGS_DIR", tmp_path), \
             patch.object(A, "LOGS_DIR", tmp_path):
            await A.run_architect("run_f04", 1, strategy)

        log_file = tmp_path / "run_f04.jsonl"
        assert log_file.exists(), "Log file must be created"
        entries = [json.loads(line) for line in log_file.read_text().splitlines() if line]
        assert len(entries) >= 1

    async def test_log_entries_have_required_fields(self, tmp_path, env_fallback, mock_claude):
        """PRD §15.2: timestamp, agent, event, level, message all required."""
        strategy = make_strategy()
        with patch("tools.tamarind.PDBS_DIR", tmp_path), \
             patch("tools.tamarind.LOGS_DIR", tmp_path), \
             patch.object(A, "LOGS_DIR", tmp_path):
            await A.run_architect("run_f05", 1, strategy)

        log_file = tmp_path / "run_f05.jsonl"
        for line in log_file.read_text().splitlines():
            if not line:
                continue
            entry = json.loads(line)
            for field in ("timestamp", "agent", "event", "level", "message"):
                assert field in entry, f"Log entry missing field: {field}"

    async def test_log_agent_is_architect(self, tmp_path, env_fallback, mock_claude):
        strategy = make_strategy()
        with patch("tools.tamarind.PDBS_DIR", tmp_path), \
             patch("tools.tamarind.LOGS_DIR", tmp_path), \
             patch.object(A, "LOGS_DIR", tmp_path):
            await A.run_architect("run_f06", 1, strategy)

        entries = [
            json.loads(line)
            for line in (tmp_path / "run_f06.jsonl").read_text().splitlines()
            if line
        ]
        architect_entries = [e for e in entries if e["agent"] == "architect"]
        assert len(architect_entries) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 4. run_architect — LIVE MODE  (PRD §16.2, §13.3, §13.4)
# ═══════════════════════════════════════════════════════════════════════════════

def _mock_claude_response(text: str) -> MagicMock:
    content_block = MagicMock()
    content_block.text = text
    response = MagicMock()
    response.content = [content_block]
    return response


VALID_RFD_JSON = json.dumps({
    "task": "Binder Design",
    "targetChains": ["A"],
    "binderLength": "10-15",
    "binderHotspots": {"A": "18 47 49"},
    "numDesigns": 1,
})


@pytest.mark.asyncio
class TestRunArchitectLive:
    async def test_calls_claude_for_rfd_settings(self, tmp_path, env_live, mock_pdb_bytes):
        """Architect must consult Claude to translate Strategist constraints → RFd settings."""
        strategy = make_strategy()
        mock_create = AsyncMock(return_value=_mock_claude_response(VALID_RFD_JSON))
        mock_pipeline = AsyncMock(return_value=(str(tmp_path / "run_l01_iter_1.pdb"), None, {"iptm": 0.946}))
        (tmp_path / "run_l01_iter_1.pdb").write_bytes(mock_pdb_bytes)

        with patch("anthropic.AsyncAnthropic") as MockAnthropic, \
             patch("agents.architect.run_pipeline", new=mock_pipeline), \
             patch.object(A, "LOGS_DIR", tmp_path):
            MockAnthropic.return_value.messages.create = mock_create
            await A.run_architect("run_l01", 1, strategy)

        mock_create.assert_called_once()

    async def test_claude_called_with_sonnet_model(self, tmp_path, env_live, mock_pdb_bytes):
        """Architect must use claude-sonnet-4-6 per project architecture spec."""
        strategy = make_strategy()
        mock_create = AsyncMock(return_value=_mock_claude_response(VALID_RFD_JSON))
        mock_pipeline = AsyncMock(return_value=(str(tmp_path / "run_l02_iter_1.pdb"), None, None))
        (tmp_path / "run_l02_iter_1.pdb").write_bytes(mock_pdb_bytes)

        with patch("anthropic.AsyncAnthropic") as MockAnthropic, \
             patch("agents.architect.run_pipeline", new=mock_pipeline), \
             patch.object(A, "LOGS_DIR", tmp_path):
            MockAnthropic.return_value.messages.create = mock_create
            await A.run_architect("run_l02", 1, strategy)

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs.get("model") == "claude-sonnet-4-6"

    async def test_passes_target_sequence_to_pipeline(self, tmp_path, env_live, mock_pdb_bytes):
        """Boltz needs the target sequence — architect must read it from literature."""
        strategy = make_strategy()
        mock_create = AsyncMock(return_value=_mock_claude_response(VALID_RFD_JSON))
        mock_pipeline = AsyncMock(return_value=(str(tmp_path / "run_l03_iter_1.pdb"), None, None))
        (tmp_path / "run_l03_iter_1.pdb").write_bytes(mock_pdb_bytes)

        with patch("anthropic.AsyncAnthropic") as MockAnthropic, \
             patch("agents.architect.run_pipeline", new=mock_pipeline), \
             patch.object(A, "LOGS_DIR", tmp_path):
            MockAnthropic.return_value.messages.create = mock_create
            await A.run_architect("run_l03", 1, strategy)

        pipeline_kwargs = mock_pipeline.call_args[1]
        seq = pipeline_kwargs.get("target_sequence")
        # Sequence must be a non-empty uppercase amino-acid string from literature
        assert seq and len(seq) >= 20
        assert seq == seq.upper()
        assert all(c in "ACDEFGHIKLMNPQRSTVWY" for c in seq)

    async def test_returns_pdb_path_from_pipeline(self, tmp_path, env_live, mock_pdb_bytes):
        """PRD §13.4: output_pdb_path must be the path returned from pipeline."""
        expected = str(tmp_path / "run_l04_iter_1.pdb")
        (tmp_path / "run_l04_iter_1.pdb").write_bytes(mock_pdb_bytes)
        strategy = make_strategy()
        mock_create = AsyncMock(return_value=_mock_claude_response(VALID_RFD_JSON))
        mock_pipeline = AsyncMock(return_value=(expected, None, {"iptm": 0.946}))

        with patch("anthropic.AsyncAnthropic") as MockAnthropic, \
             patch("agents.architect.run_pipeline", new=mock_pipeline), \
             patch.object(A, "LOGS_DIR", tmp_path):
            MockAnthropic.return_value.messages.create = mock_create
            result = await A.run_architect("run_l04", 1, strategy)

        assert result == expected

    async def test_handles_claude_garbage_json_gracefully(self, tmp_path, env_live, mock_pdb_bytes):
        """If Claude returns invalid JSON, architect must fall back to default settings."""
        strategy = make_strategy()
        mock_create = AsyncMock(return_value=_mock_claude_response("I cannot help with that."))
        expected = str(tmp_path / "run_l05_iter_1.pdb")
        (tmp_path / "run_l05_iter_1.pdb").write_bytes(mock_pdb_bytes)
        mock_pipeline = AsyncMock(return_value=(expected, None, None))

        with patch("anthropic.AsyncAnthropic") as MockAnthropic, \
             patch("agents.architect.run_pipeline", new=mock_pipeline), \
             patch.object(A, "LOGS_DIR", tmp_path):
            MockAnthropic.return_value.messages.create = mock_create
            result = await A.run_architect("run_l05", 1, strategy)

        assert result == expected  # must not raise

    async def test_strategy_constraints_propagate_to_pipeline(self, tmp_path, env_live, mock_pdb_bytes):
        """Binder length from Strategist must reach the RFdiffusion settings."""
        strategy = make_strategy(min_length=8, max_length=18)
        mock_create = AsyncMock(return_value=_mock_claude_response("bad json"))  # force fallback
        expected = str(tmp_path / "run_l06_iter_1.pdb")
        (tmp_path / "run_l06_iter_1.pdb").write_bytes(mock_pdb_bytes)
        mock_pipeline = AsyncMock(return_value=(expected, None, None))

        with patch("anthropic.AsyncAnthropic") as MockAnthropic, \
             patch("agents.architect.run_pipeline", new=mock_pipeline), \
             patch.object(A, "LOGS_DIR", tmp_path):
            MockAnthropic.return_value.messages.create = mock_create
            await A.run_architect("run_l06", 1, strategy)

        rfd_settings = mock_pipeline.call_args[1].get("rfd_settings", {})
        assert rfd_settings.get("binderLength") == "8-18"

    async def test_logs_pipeline_completion(self, tmp_path, env_live, mock_pdb_bytes):
        """PRD §15: pipeline_done event must be logged on success."""
        strategy = make_strategy()
        mock_create = AsyncMock(return_value=_mock_claude_response(VALID_RFD_JSON))
        expected = str(tmp_path / "run_l07_iter_1.pdb")
        (tmp_path / "run_l07_iter_1.pdb").write_bytes(mock_pdb_bytes)
        mock_pipeline = AsyncMock(return_value=(expected, None, {"iptm": 0.92, "confidence_score": 0.71}))

        with patch("anthropic.AsyncAnthropic") as MockAnthropic, \
             patch("agents.architect.run_pipeline", new=mock_pipeline), \
             patch.object(A, "LOGS_DIR", tmp_path):
            MockAnthropic.return_value.messages.create = mock_create
            await A.run_architect("run_l07", 1, strategy)

        entries = [
            json.loads(line)
            for line in (tmp_path / "run_l07.jsonl").read_text().splitlines()
            if line
        ]
        events = [e["event"] for e in entries]
        assert "pipeline_done" in events


# ═══════════════════════════════════════════════════════════════════════════════
# 5. ITERATION BOUNDARY TESTS  (PRD §11 — Iteration Logic)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestIterationBoundaries:
    async def test_iteration_number_reflected_in_output_path(self, tmp_path, env_fallback, mock_claude):
        """Each iteration must produce a distinct output file."""
        strategy = make_strategy()
        paths = []
        for iteration in (1, 2, 3):
            with patch("tools.tamarind.PDBS_DIR", tmp_path), \
                 patch("tools.tamarind.LOGS_DIR", tmp_path), \
                 patch.object(A, "LOGS_DIR", tmp_path):
                path = await A.run_architect(f"run_iter_{iteration}", iteration, strategy)
            paths.append(Path(path).name)

        # All three must be distinct filenames
        assert len(set(paths)) == 3

    async def test_accepts_all_valid_iterations(self, tmp_path, env_fallback, mock_claude):
        """PRD §5.1: up to 3 iterations — architect must accept iterations 1, 2, 3."""
        strategy = make_strategy()
        for i in (1, 2, 3):
            with patch("tools.tamarind.PDBS_DIR", tmp_path), \
                 patch("tools.tamarind.LOGS_DIR", tmp_path), \
                 patch.object(A, "LOGS_DIR", tmp_path):
                path = await A.run_architect(f"run_boundary_{i}", i, strategy)
            assert Path(path).exists()
