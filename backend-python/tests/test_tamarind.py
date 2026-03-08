"""
Tests for tools/tamarind.py — the Tamarind API client layer.

Coverage map (keyed to PRD requirements):
  PRD §16   — Live vs Fallback mode (LIVE_API env var)
  PRD §18   — File contract: outputs/pdbs/{run_id}_iter_{n}.pdb
  PRD §9.2  — Architect must handle API failure and switch to fallback
  PRD §11.4 — Retry rules
  Architecture doc — correct 4-step protocol:
    Upload (PUT /upload/{filename}) → Submit (POST /submit-job) →
    Poll by jobName (GET /jobs?jobName=) → Result URL (POST /result)
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.conftest import make_async_client, make_response

# Module under test
import tools.tamarind as T

BACKEND_DIR = Path(__file__).parent.parent


# ═══════════════════════════════════════════════════════════════════════════════
# 1. PARSER UNIT TESTS  (pure — no network, no filesystem)
# ═══════════════════════════════════════════════════════════════════════════════

class TestExtractPdbFromBytes:
    def test_extracts_pdb_from_zip(self, mock_pdb_zip, mock_pdb_bytes):
        result = T._extract_pdb_from_bytes(mock_pdb_zip)
        assert result == mock_pdb_bytes

    def test_returns_bare_pdb_unchanged(self, mock_pdb_bytes):
        result = T._extract_pdb_from_bytes(mock_pdb_bytes)
        assert result == mock_pdb_bytes

    def test_raises_if_zip_has_no_pdb(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("result.txt", "not a pdb")
        with pytest.raises(T.TamarindFailedError, match="No .pdb file"):
            T._extract_pdb_from_bytes(buf.getvalue())


class TestExtractSequenceFromBytes:
    def test_parses_sequence_from_bare_fasta(self, mock_fasta_bytes):
        seq = T._extract_sequence_from_bytes(mock_fasta_bytes)
        assert seq == "ACDEFGHIKLMN"

    def test_parses_sequence_from_fasta_zip(self, mock_fasta_zip):
        seq = T._extract_sequence_from_bytes(mock_fasta_zip)
        assert seq == "ACDEFGHIKLMN"

    def test_sequence_is_uppercase(self):
        fasta = b">binder\nAcDeF\n"
        seq = T._extract_sequence_from_bytes(fasta)
        assert seq == seq.upper()

    def test_multiline_fasta_joined(self):
        fasta = b">binder\nACDE\nFGHI\n"
        seq = T._extract_sequence_from_bytes(fasta)
        assert seq == "ACDEFGHI"

    def test_raises_if_no_sequence_found(self):
        with pytest.raises(T.TamarindFailedError, match="Could not parse"):
            T._extract_sequence_from_bytes(b"no sequence here at all")

    def test_only_first_sequence_returned(self):
        fasta = b">binder_1\nAAAA\n>binder_2\nCCCC\n"
        seq = T._extract_sequence_from_bytes(fasta)
        assert seq == "AAAA"


class TestExtractAffinityAndPdb:
    def test_extracts_pdb_and_affinity_from_zip(self, mock_boltz_zip, mock_pdb_bytes):
        pdb, affinity = T._extract_affinity_and_pdb(mock_boltz_zip)
        assert pdb == mock_pdb_bytes
        assert affinity == pytest.approx(-9.42)

    def test_affinity_is_none_when_no_json(self, mock_boltz_zip_no_affinity, mock_pdb_bytes):
        pdb, affinity = T._extract_affinity_and_pdb(mock_boltz_zip_no_affinity)
        assert pdb == mock_pdb_bytes
        assert affinity is None

    def test_raises_if_no_pdb_in_zip(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("affinity.json", json.dumps({"affinity_pred_value": -5.0}))
        with pytest.raises(T.TamarindFailedError, match="No .pdb file"):
            T._extract_affinity_and_pdb(buf.getvalue())

    def test_handles_alternative_affinity_key_names(self, mock_pdb_bytes):
        """PRD does not prescribe exact JSON key — must handle common variants."""
        for key in ("affinity", "predicted_affinity"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                zf.writestr("complex.pdb", mock_pdb_bytes)
                zf.writestr("result.json", json.dumps({key: -7.0}))
            _, affinity = T._extract_affinity_and_pdb(buf.getvalue())
            assert affinity == pytest.approx(-7.0), f"Failed for key={key}"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. FALLBACK BEHAVIOUR  (PRD §16 — Live vs Fallback Mode)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFallbackPdb:
    def test_copies_mock_pdb_to_pdbs_dir(self, tmp_path, env_fallback):
        """_fallback_pdb must copy the source to outputs/pdbs/{run_id}_iter_{n}.pdb."""
        with patch.object(T, "PDBS_DIR", tmp_path), \
             patch.object(T, "LOGS_DIR", tmp_path):
            path = T._fallback_pdb("run_test", 1)

        result = Path(path)
        assert result.exists()
        assert result.name == "run_test_iter_1.pdb"
        # Content matches the real mock fallback
        assert result.read_bytes() == (
            BACKEND_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"
        ).read_bytes()

    def test_raises_if_mock_file_missing(self, tmp_path):
        with patch.object(T, "PDBS_DIR", tmp_path), \
             patch.object(T, "MOCK_FALLBACKS_DIR", tmp_path), \
             patch.object(T, "LOGS_DIR", tmp_path):
            with pytest.raises(FileNotFoundError, match="Fallback PDB not found"):
                T._fallback_pdb("run_test", 1)


@pytest.mark.asyncio
class TestRunPipelineFallbackMode:
    async def test_returns_fallback_when_live_api_false(self, tmp_path, env_fallback):
        """PRD §16.3: fallback activates when LIVE_API=false."""
        with patch.object(T, "PDBS_DIR", tmp_path), \
             patch.object(T, "LOGS_DIR", tmp_path):
            path, affinity, scores = await T.run_pipeline(
                run_id="run_t01",
                iteration=1,
                target_pdb_path=str(BACKEND_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"),
                target_sequence="KPVSLSYRC",
                rfd_settings={},
            )

        assert Path(path).exists()
        assert affinity is None  # fallback never has affinity
        assert scores is None

    async def test_raises_when_live_false_and_no_fallback(self, tmp_path, env_live_no_fallback,
                                                           monkeypatch):
        """LIVE_API=false + ALLOW_FALLBACK=false must raise, not silently succeed."""
        monkeypatch.setenv("LIVE_API", "false")
        with patch.object(T, "PDBS_DIR", tmp_path), \
             patch.object(T, "LOGS_DIR", tmp_path):
            with pytest.raises(T.TamarindFailedError, match="ALLOW_FALLBACK=false"):
                await T.run_pipeline(
                    run_id="run_t02",
                    iteration=1,
                    target_pdb_path=str(BACKEND_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"),
                    target_sequence="KPVSLSYRC",
                    rfd_settings={},
                )

    async def test_fallback_on_pipeline_exception(self, tmp_path, env_live):
        """PRD §9.2: on Tamarind failure with ALLOW_FALLBACK=true → use fallback."""
        with patch.object(T, "PDBS_DIR", tmp_path), \
             patch.object(T, "LOGS_DIR", tmp_path), \
             patch("tools.tamarind.run_rfdiffusion", side_effect=T.TamarindFailedError("boom")):
            path, affinity, scores = await T.run_pipeline(
                run_id="run_t03",
                iteration=1,
                target_pdb_path=str(BACKEND_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"),
                target_sequence="KPVSLSYRC",
                rfd_settings={},
            )
        assert Path(path).exists()
        assert affinity is None
        assert scores is None

    async def test_pipeline_saves_affinity_sidecar(self, tmp_path, env_live, mock_pdb_bytes):
        """PRD §13.4 — Architect output must include pdb_path; sidecar saves sequence+affinity."""
        mock_scores = {"iptm": 0.946, "confidence_score": 0.745}
        with patch.object(T, "PDBS_DIR", tmp_path), \
             patch.object(T, "LOGS_DIR", tmp_path), \
             patch("tools.tamarind.run_rfdiffusion", new=AsyncMock(return_value=mock_pdb_bytes)), \
             patch("tools.tamarind.run_proteinmpnn", new=AsyncMock(return_value="ACDEFGHIKLMN")), \
             patch("tools.tamarind.run_boltz", new=AsyncMock(return_value=(mock_pdb_bytes, None, mock_scores))):
            path, affinity, scores = await T.run_pipeline(
                run_id="run_t04",
                iteration=1,
                target_pdb_path=str(BACKEND_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"),
                target_sequence="KPVSLSYRC",
                rfd_settings={},
            )

        sidecar = tmp_path / "run_t04_iter_1_affinity.json"
        assert sidecar.exists(), "Affinity sidecar JSON must be written"
        data = json.loads(sidecar.read_text())
        assert data["affinity_pred_value"] is None
        assert data["binder_sequence"] == "ACDEFGHIKLMN"
        assert data["target_sequence"] == "KPVSLSYRC"
        assert data["iptm"] == pytest.approx(0.946)
        assert data["boltz_scores"] == mock_scores

    async def test_pipeline_output_pdb_at_correct_path(self, tmp_path, env_live, mock_pdb_bytes):
        """PRD §18: output PDB must be at outputs/pdbs/{run_id}_iter_{n}.pdb."""
        with patch.object(T, "PDBS_DIR", tmp_path), \
             patch.object(T, "LOGS_DIR", tmp_path), \
             patch("tools.tamarind.run_rfdiffusion", new=AsyncMock(return_value=mock_pdb_bytes)), \
             patch("tools.tamarind.run_proteinmpnn", new=AsyncMock(return_value="ACDEFGHIKLMN")), \
             patch("tools.tamarind.run_boltz", new=AsyncMock(return_value=(mock_pdb_bytes, None, None))):
            path, _, __ = await T.run_pipeline(
                run_id="run_t05",
                iteration=2,
                target_pdb_path=str(BACKEND_DIR / "outputs" / "mock_fallbacks" / "cxcl12_success.pdb"),
                target_sequence="KPVSLSYRC",
                rfd_settings={},
            )

        assert Path(path).name == "run_t05_iter_2.pdb"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. API PROTOCOL TESTS  (correct 4-step: Upload → Submit → Poll → Result)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
class TestUploadFile:
    async def test_uses_put_method(self, env_live):
        """Step 1: must be PUT /upload/{filename}, not POST."""
        resp = make_response(200)
        client = make_async_client(put=resp)
        result = await T.upload_file(client, "cxcl12.pdb", b"ATOM 1...")
        client.put.assert_called_once()
        call_url = client.put.call_args[0][0]
        assert call_url.endswith("/upload/cxcl12.pdb")

    async def test_uses_x_api_key_header(self, env_live):
        """Authentication: must use x-api-key, NOT Authorization: Bearer."""
        resp = make_response(200)
        client = make_async_client(put=resp)
        await T.upload_file(client, "cxcl12.pdb", b"ATOM 1...")
        headers = client.put.call_args[1].get("headers", {})
        assert "x-api-key" in headers, "Must use x-api-key header"
        assert "Authorization" not in headers, "Must NOT use Authorization: Bearer"

    async def test_returns_filename(self, env_live):
        resp = make_response(200)
        client = make_async_client(put=resp)
        result = await T.upload_file(client, "cxcl12.pdb", b"ATOM 1...")
        assert result == "cxcl12.pdb"

    async def test_sends_file_bytes_as_content(self, env_live):
        resp = make_response(200)
        client = make_async_client(put=resp)
        payload = b"ATOM  1  N   ALA"
        await T.upload_file(client, "cxcl12.pdb", payload)
        kwargs = client.put.call_args[1]
        assert kwargs.get("content") == payload


@pytest.mark.asyncio
class TestSubmitJob:
    async def test_posts_to_submit_job_endpoint(self, env_live):
        resp = make_response(200)
        client = make_async_client(post=resp)
        await T.submit_job(client, "run_001_rfd_iter1", "rfdiffusion", {"binderLength": "10-15"})
        call_url = client.post.call_args[0][0]
        assert call_url.endswith("/submit-job")

    async def test_payload_contains_jobName(self, env_live):
        """Polling is by jobName — must be present in submit payload."""
        resp = make_response(200)
        client = make_async_client(post=resp)
        await T.submit_job(client, "my_job_name", "rfdiffusion", {})
        json_body = client.post.call_args[1].get("json", {})
        assert json_body.get("jobName") == "my_job_name"

    async def test_payload_contains_type_and_settings(self, env_live):
        resp = make_response(200)
        client = make_async_client(post=resp)
        settings = {"binderLength": "10-15", "numDesigns": 1}
        await T.submit_job(client, "job1", "rfdiffusion", settings)
        json_body = client.post.call_args[1].get("json", {})
        assert json_body.get("type") == "rfdiffusion"
        assert json_body.get("settings") == settings


@pytest.mark.asyncio
class TestPollUntilComplete:
    async def test_polls_by_jobName_not_jobId(self, tmp_path, env_live):
        """PRD architecture: poll GET /jobs?jobName=..., NOT by jobId."""
        # Real Tamarind format: {"0": {"JobName": "...", "JobStatus": "..."}, "statuses": {}}
        complete_resp = make_response(200, json_body={"0": {"JobName": "my_job", "JobStatus": "Complete"}, "statuses": {}})
        client = make_async_client(get=complete_resp)
        with patch.object(T, "LOGS_DIR", tmp_path):
            await T.poll_until_complete(client, "my_job", "run_x", timeout_s=60)
        call_params = client.get.call_args[1].get("params", {})
        assert "jobName" in call_params, "Must poll by jobName"
        assert call_params["jobName"] == "my_job"

    async def test_returns_when_status_complete(self, tmp_path, env_live):
        complete_resp = make_response(200, json_body={"0": {"JobName": "job1", "JobStatus": "Complete"}, "statuses": {}})
        client = make_async_client(get=complete_resp)
        with patch.object(T, "LOGS_DIR", tmp_path):
            # Should not raise
            result = await T.poll_until_complete(client, "job1", "run_x", timeout_s=60)
        assert result is None  # no Score field in this response

    async def test_returns_score_dict_when_complete(self, tmp_path, env_live):
        """When Complete, score metrics from the job object must be returned."""
        score = {"iptm": 0.946, "confidence_score": 0.745, "complex_plddt": 0.695}
        complete_resp = make_response(200, json_body={
            "0": {"JobName": "job_sc", "JobStatus": "Complete", "Score": score},
            "statuses": {},
        })
        client = make_async_client(get=complete_resp)
        with patch.object(T, "LOGS_DIR", tmp_path):
            result = await T.poll_until_complete(client, "job_sc", "run_x", timeout_s=60)
        assert result == score
        assert result["iptm"] == pytest.approx(0.946)

    async def test_raises_on_stopped(self, tmp_path, env_live):
        stopped_resp = make_response(200, json_body={"0": {"JobName": "job1", "JobStatus": "Stopped"}, "statuses": {}})
        client = make_async_client(get=stopped_resp)
        with patch.object(T, "LOGS_DIR", tmp_path):
            with pytest.raises(T.TamarindFailedError, match="Stopped"):
                await T.poll_until_complete(client, "job1", "run_x", timeout_s=60)

    async def test_raises_on_deleted(self, tmp_path, env_live):
        resp = make_response(200, json_body={"0": {"JobName": "job1", "JobStatus": "Deleted"}, "statuses": {}})
        client = make_async_client(get=resp)
        with patch.object(T, "LOGS_DIR", tmp_path):
            with pytest.raises(T.TamarindFailedError):
                await T.poll_until_complete(client, "job1", "run_x", timeout_s=60)

    async def test_raises_timeout_when_exhausted(self, tmp_path, env_live):
        """PRD §11.4 — must raise TamarindTimeoutError after timeout, not loop forever."""
        pending_resp = make_response(200, json_body={"0": {"JobName": "job1", "JobStatus": "Running"}, "statuses": {}})
        client = make_async_client(get=pending_resp)
        with patch.object(T, "LOGS_DIR", tmp_path), \
             patch("tools.tamarind.asyncio.sleep", new=AsyncMock()):
            with pytest.raises(T.TamarindTimeoutError):
                await T.poll_until_complete(client, "job1", "run_x", timeout_s=1)

    async def test_handles_list_response_format(self, tmp_path, env_live):
        """Tamarind /jobs may return a list — must find the matching jobName entry."""
        resp = make_response(200, json_body=[
            {"JobName": "other_job", "JobStatus": "Running"},
            {"JobName": "my_job", "JobStatus": "Complete"},
        ])
        client = make_async_client(get=resp)
        with patch.object(T, "LOGS_DIR", tmp_path):
            await T.poll_until_complete(client, "my_job", "run_x", timeout_s=60)


@pytest.mark.asyncio
class TestGetResultUrl:
    async def test_posts_to_result_endpoint_with_jobName(self, env_live):
        resp = make_response(200, json_body="https://s3.amazonaws.com/result.zip")
        client = make_async_client(post=resp)
        url = await T.get_result_url(client, "my_job")
        call_url = client.post.call_args[0][0]
        assert call_url.endswith("/result")
        json_body = client.post.call_args[1].get("json", {})
        assert json_body.get("jobName") == "my_job"

    async def test_returns_bare_string_url(self, env_live):
        """Tamarind spec: POST /result returns a plain string S3 URL."""
        s3_url = "https://s3.amazonaws.com/bucket/result.zip"
        resp = make_response(200, json_body=s3_url)
        client = make_async_client(post=resp)
        result = await T.get_result_url(client, "job1")
        assert result == s3_url

    async def test_handles_wrapped_url_dict(self, env_live):
        """Defensive: also handle {"url": "..."} response shape."""
        s3_url = "https://s3.amazonaws.com/bucket/result.zip"
        for key in ("url", "downloadUrl", "result"):
            resp = make_response(200, json_body={key: s3_url})
            client = make_async_client(post=resp)
            result = await T.get_result_url(client, "job1")
            assert result == s3_url, f"Failed for key={key}"

    async def test_raises_on_unknown_format(self, env_live):
        resp = make_response(200, json_body={"unexpected": 123})
        client = make_async_client(post=resp)
        with pytest.raises(T.TamarindFailedError, match="Unexpected result"):
            await T.get_result_url(client, "job1")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. LOG FORMAT TESTS  (PRD §15 — Logging Rules)
# ═══════════════════════════════════════════════════════════════════════════════

class TestLogFormat:
    def test_log_entry_has_required_fields(self, tmp_path):
        """PRD §15.2: every log entry needs timestamp, agent, event, level, message."""
        log_file = tmp_path / "run_log01.jsonl"
        with patch.object(T, "LOGS_DIR", tmp_path):
            T._append_log("run_log01", "Test message", event="fallback_triggered")

        entries = [json.loads(line) for line in log_file.read_text().splitlines()]
        assert len(entries) == 1
        entry = entries[0]
        for field in ("timestamp", "agent", "event", "level", "message"):
            assert field in entry, f"Missing required log field: {field}"

    def test_log_agent_is_tamarind(self, tmp_path):
        with patch.object(T, "LOGS_DIR", tmp_path):
            T._append_log("run_log02", "msg", event="design_submitted")
        entry = json.loads((tmp_path / "run_log02.jsonl").read_text())
        assert entry["agent"] == "tamarind"

    def test_log_event_types_match_prd(self, tmp_path):
        """PRD §15.3 allowed event types used by Tamarind."""
        allowed = {
            "fallback_triggered", "fallback_activated", "fallback_mode",
            "rfd_upload", "rfd_submit", "rfd_poll", "rfd_result", "rfd_done",
            "mpnn_upload", "mpnn_submit", "mpnn_poll", "mpnn_result", "mpnn_done",
            "boltz_submit", "boltz_poll", "boltz_result", "boltz_done",
            "pipeline_start", "pipeline_error", "pipeline_done",
            "poll",
        }
        with patch.object(T, "LOGS_DIR", tmp_path):
            for event in ["fallback_triggered", "rfd_submit", "boltz_done"]:
                T._append_log(f"run_ev_{event}", "msg", event=event)
