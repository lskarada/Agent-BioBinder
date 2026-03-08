"""
Tamarind async client — implements the correct 4-step protocol per job:
  Upload File → Submit Job → Poll by jobName → Get Result URL → Download.

Env vars:
  TAMARIND_API_KEY          — x-api-key header value
  TAMARIND_BASE_URL         — default https://api.tamarind.bio/v1
  TAMARIND_TIMEOUT_SECONDS  — per-step poll timeout, default 300
  LIVE_API                  — "true" / "false"
  ALLOW_FALLBACK            — "true" / "false"
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE_DIR = Path(__file__).parent.parent
OUTPUTS_DIR = BASE_DIR / "outputs"
PDBS_DIR = OUTPUTS_DIR / "pdbs"
MOCK_FALLBACKS_DIR = OUTPUTS_DIR / "mock_fallbacks"
LOGS_DIR = OUTPUTS_DIR / "logs"

# Default poll timeout per job step (RFdiffusion can take several minutes)
DEFAULT_TIMEOUT_S = 300
# Exponential-capped poll backoff
_POLL_MIN_S = 5
_POLL_MAX_S = 30


class TamarindTimeoutError(Exception):
    pass


class TamarindFailedError(Exception):
    pass


# ── Logging ────────────────────────────────────────────────────────────────────

def _append_log(run_id: str, message: str, event: str, level: str = "info") -> None:
    log_file = LOGS_DIR / f"{run_id}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "tamarind",
        "event": event,
        "level": level,
        "message": message,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Config helpers ─────────────────────────────────────────────────────────────

def _base_url() -> str:
    return os.environ.get("TAMARIND_BASE_URL", "https://api.tamarind.bio/v1").rstrip("/")


def _headers() -> dict[str, str]:
    """Tamarind uses x-api-key, NOT Authorization: Bearer."""
    return {"x-api-key": os.environ.get("TAMARIND_API_KEY", "")}


def _timeout_s() -> int:
    return int(os.environ.get("TAMARIND_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_S)))


def _allow_fallback() -> bool:
    return os.environ.get("ALLOW_FALLBACK", "true").lower() == "true"


# ── Fallback ───────────────────────────────────────────────────────────────────

def _fallback_pdb(run_id: str, iteration: int) -> str:
    """Copy mock fallback PDB to outputs/pdbs/ and return its path."""
    src = MOCK_FALLBACKS_DIR / "cxcl12_success.pdb"
    if not src.exists():
        raise FileNotFoundError(
            f"Fallback PDB not found at {src}. "
            "Place a valid binder PDB at outputs/mock_fallbacks/cxcl12_success.pdb"
        )
    dest = PDBS_DIR / f"{run_id}_iter_{iteration}.pdb"
    shutil.copy2(src, dest)
    _append_log(run_id, f"Using fallback PDB: {dest}", event="fallback_activated", level="warning")
    return str(dest)


# ── Low-level primitives ───────────────────────────────────────────────────────

async def upload_file(
    client: httpx.AsyncClient,
    filename: str,
    file_bytes: bytes,
) -> str:
    """
    PUT /upload/{filename} — uploads a file to Tamarind storage.
    Returns the filename string to reference in subsequent job payloads.
    """
    headers = {**_headers(), "Content-Type": "application/octet-stream"}
    response = await client.put(
        f"{_base_url()}/upload/{filename}",
        content=file_bytes,
        headers=headers,
        follow_redirects=True,  # Tamarind 308-redirects PUT to CloudFront/S3
    )
    response.raise_for_status()
    return filename


async def submit_job(
    client: httpx.AsyncClient,
    job_name: str,
    job_type: str,
    settings: dict,
) -> None:
    """
    POST /submit-job — submits a job by name.
    Tamarind does NOT return a job ID; polling is by jobName.
    """
    payload = {"jobName": job_name, "type": job_type, "settings": settings}
    response = await client.post(
        f"{_base_url()}/submit-job",
        json=payload,
        headers=_headers(),
    )
    response.raise_for_status()


async def poll_until_complete(
    client: httpx.AsyncClient,
    job_name: str,
    run_id: str,
    timeout_s: int | None = None,
) -> dict | None:
    """
    GET /jobs?jobName={name} — polls until JobStatus == "Complete".
    Returns the Score dict from the job object when Complete (contains iptm, etc.),
    or None if no Score field is present.
    Raises TamarindTimeoutError or TamarindFailedError on terminal bad states.
    """
    timeout_s = timeout_s or _timeout_s()
    elapsed = 0
    attempt = 1

    while elapsed < timeout_s:
        interval = min(_POLL_MIN_S * attempt, _POLL_MAX_S)
        await asyncio.sleep(interval)
        elapsed += interval

        response = await client.get(
            f"{_base_url()}/jobs",
            params={"jobName": job_name},
            headers=_headers(),
        )
        response.raise_for_status()
        data = response.json()

        # Tamarind response format when querying by jobName:
        #   {"0": {"JobName": "...", "JobStatus": "In Queue", "Score": {...}}, "statuses": {...}}
        # Numeric string keys hold job objects; "statuses" and "jobs" are metadata.
        # JobName uses capital N; JobStatus uses capital S.
        status = "UNKNOWN"
        job_obj: dict | None = None
        if isinstance(data, dict):
            for val in data.values():
                if isinstance(val, dict) and val.get("JobName") == job_name:
                    status = val.get("JobStatus", "UNKNOWN")
                    job_obj = val
                    break
        elif isinstance(data, list):
            job_obj = next((j for j in data if j.get("JobName") == job_name), None)
            status = job_obj.get("JobStatus", "UNKNOWN") if job_obj else "UNKNOWN"

        _append_log(
            run_id,
            f"[{job_name}] status={status} elapsed={elapsed}s",
            event="poll",
        )

        if status == "Complete":
            score = job_obj.get("Score") if job_obj else None
            if isinstance(score, str):
                try:
                    score = json.loads(score)
                except (json.JSONDecodeError, ValueError):
                    score = None
            return score if isinstance(score, dict) else None
        if status in ("Stopped", "Deleted", "Failed"):
            raise TamarindFailedError(f"Job '{job_name}' terminal status: {status}")
        attempt += 1

    raise TamarindTimeoutError(f"Job '{job_name}' timed out after {timeout_s}s")


async def get_result_url(
    client: httpx.AsyncClient,
    job_name: str,
) -> str:
    """
    POST /result with {"jobName": name} — returns the S3 download URL string.
    """
    response = await client.post(
        f"{_base_url()}/result",
        json={"jobName": job_name},
        headers=_headers(),
    )
    response.raise_for_status()
    # Tamarind returns a bare string (the S3 URL)
    body = response.json()
    if isinstance(body, str):
        return body
    # In case it's wrapped in an object
    if isinstance(body, dict):
        for key in ("url", "downloadUrl", "result"):
            if key in body:
                return body[key]
    raise TamarindFailedError(f"Unexpected result response format: {body!r}")


async def download_from_url(url: str) -> bytes:
    """Download raw bytes from a URL (S3 — no auth required)."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        return response.content


# ── Result parsers ─────────────────────────────────────────────────────────────

def _extract_pdb_from_bytes(raw: bytes, label: str = "output") -> bytes:
    """
    Given raw bytes that may be a zip archive or a bare PDB, return PDB bytes.
    Prefers the first .pdb file found inside a zip.
    """
    if raw[:2] == b"PK":  # zip magic bytes
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            pdb_names = [n for n in zf.namelist() if n.endswith(".pdb")]
            if not pdb_names:
                raise TamarindFailedError(f"No .pdb file in {label} zip")
            return zf.read(pdb_names[0])
    # Bare PDB text
    return raw


def _extract_sequence_from_bytes(raw: bytes) -> str:
    """
    Parse the first amino-acid sequence from ProteinMPNN output.
    Handles zip-containing-FASTA or bare FASTA/text.
    Returns the sequence string (uppercase letters only).
    """
    if raw[:2] == b"PK":  # zip
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            # Prefer .fasta / .fa / .seq files
            candidates = [
                n for n in zf.namelist()
                if any(n.endswith(ext) for ext in (".fasta", ".fa", ".seq", ".txt"))
            ]
            if not candidates:
                candidates = zf.namelist()
            content = zf.read(candidates[0]).decode("utf-8", errors="ignore")
    else:
        content = raw.decode("utf-8", errors="ignore")

    # Parse FASTA — grab the first non-header line(s)
    sequence_lines: list[str] = []
    in_seq = False
    for line in content.splitlines():
        line = line.strip()
        if line.startswith(">"):
            if in_seq and sequence_lines:
                break  # already captured first sequence
            in_seq = True
            continue
        if in_seq and line:
            sequence_lines.append(line.upper())

    if sequence_lines:
        return "".join(sequence_lines)

    raise TamarindFailedError("Could not parse a sequence from ProteinMPNN output")


def _extract_affinity_and_pdb(raw: bytes) -> tuple[bytes, float | None]:
    """
    Parse Boltz result bytes → (pdb_bytes, affinity_pred_value | None).
    Boltz zips typically contain a PDB and a JSON with affinity_pred_value.
    """
    pdb_bytes: bytes | None = None
    affinity: float | None = None

    if raw[:2] == b"PK":  # zip
        with zipfile.ZipFile(io.BytesIO(raw)) as zf:
            for name in zf.namelist():
                if name.endswith(".pdb") and pdb_bytes is None:
                    pdb_bytes = zf.read(name)
                if name.endswith(".json") and affinity is None:
                    try:
                        data = json.loads(zf.read(name))
                        # Try common key names
                        for key in ("affinity_pred_value", "affinity", "predicted_affinity"):
                            if key in data:
                                affinity = float(data[key])
                                break
                    except (json.JSONDecodeError, ValueError, TypeError):
                        pass
    else:
        # Could be bare PDB
        pdb_bytes = raw

    if pdb_bytes is None:
        raise TamarindFailedError("No .pdb file found in Boltz result")

    return pdb_bytes, affinity


# ── High-level job runners ─────────────────────────────────────────────────────

async def run_rfdiffusion(
    run_id: str,
    iteration: int,
    target_pdb_bytes: bytes,
    target_filename: str,
    settings: dict,
) -> bytes:
    """
    Upload target PDB → Submit RFdiffusion → Poll → Retrieve → return backbone PDB bytes.
    """
    job_name = f"{run_id}_rfd_iter{iteration}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        _append_log(run_id, f"Uploading {target_filename} for RFdiffusion", event="rfd_upload")
        await upload_file(client, target_filename, target_pdb_bytes)

        _append_log(run_id, f"Submitting RFdiffusion job '{job_name}'", event="rfd_submit")
        await submit_job(client, job_name, "rfdiffusion", {**settings, "pdbFile": target_filename})

    _append_log(run_id, f"Polling RFdiffusion job '{job_name}'", event="rfd_poll")
    async with httpx.AsyncClient(timeout=60.0) as client:
        await poll_until_complete(client, job_name, run_id, timeout_s=300)  # RFdiffusion: up to 5 min

        _append_log(run_id, f"Retrieving RFdiffusion result for '{job_name}'", event="rfd_result")
        result_url = await get_result_url(client, job_name)

    raw = await download_from_url(result_url)
    pdb_bytes = _extract_pdb_from_bytes(raw, label="RFdiffusion")
    _append_log(run_id, f"RFdiffusion backbone PDB downloaded ({len(pdb_bytes)} bytes)", event="rfd_done")
    return pdb_bytes


async def run_proteinmpnn(
    run_id: str,
    iteration: int,
    backbone_pdb_bytes: bytes,
    backbone_filename: str,
    num_sequences: int = 5,
) -> str:
    """
    Upload backbone PDB → Submit ProteinMPNN → Poll → Retrieve → return best sequence string.
    Designed chain is assumed to be B (RFdiffusion binder convention).
    """
    job_name = f"{run_id}_mpnn_iter{iteration}"

    async with httpx.AsyncClient(timeout=60.0) as client:
        _append_log(run_id, f"Uploading {backbone_filename} for ProteinMPNN", event="mpnn_upload")
        await upload_file(client, backbone_filename, backbone_pdb_bytes)

        settings = {
            "pdbFile": backbone_filename,
            "designedChains": ["B"],
            "modelType": "solublempnn",
            "numSequences": num_sequences,
        }
        _append_log(run_id, f"Submitting ProteinMPNN job '{job_name}'", event="mpnn_submit")
        await submit_job(client, job_name, "proteinmpnn", settings)

    _append_log(run_id, f"Polling ProteinMPNN job '{job_name}'", event="mpnn_poll")
    async with httpx.AsyncClient(timeout=60.0) as client:
        await poll_until_complete(client, job_name, run_id, timeout_s=180)  # ProteinMPNN: up to 3 min

        _append_log(run_id, f"Retrieving ProteinMPNN result for '{job_name}'", event="mpnn_result")
        result_url = await get_result_url(client, job_name)

    raw = await download_from_url(result_url)
    sequence = _extract_sequence_from_bytes(raw)
    _append_log(run_id, f"ProteinMPNN best sequence: {sequence[:30]}... (len={len(sequence)})", event="mpnn_done")
    return sequence


async def run_boltz(
    run_id: str,
    iteration: int,
    target_sequence: str,
    binder_sequence: str,
) -> tuple[bytes, float | None, dict | None]:
    """
    Submit Boltz co-folding → Poll → Retrieve → return (complex_pdb_bytes, affinity, score_dict).

    score_dict contains Boltz 2.2.0 structural quality metrics from the poll response:
      iptm, confidence_score, complex_plddt, ipSAE_AB, pDockQ2_AB (available when Complete).
    affinity_pred_value is always None for protein-protein — Boltz-2's affinity head is for
    protein-ligand (small molecule) only. Use iptm > 0.8 as the quality gate instead.
    """
    job_name = f"{run_id}_boltz_iter{iteration}"
    settings = {
        "inputFormat": "list",
        "proteins": [target_sequence, binder_sequence],
        "predictAffinity": True,
        "numSamples": 1,
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        _append_log(run_id, f"Submitting Boltz job '{job_name}'", event="boltz_submit")
        await submit_job(client, job_name, "boltz", settings)

    _append_log(run_id, f"Polling Boltz job '{job_name}'", event="boltz_poll")
    async with httpx.AsyncClient(timeout=60.0) as client:
        score_dict = await poll_until_complete(client, job_name, run_id, timeout_s=360)  # Boltz: up to 6 min

        _append_log(run_id, f"Retrieving Boltz result for '{job_name}'", event="boltz_result")
        result_url = await get_result_url(client, job_name)

    raw = await download_from_url(result_url)
    pdb_bytes, affinity = _extract_affinity_and_pdb(raw)

    iptm = score_dict.get("iptm") if score_dict else None
    _append_log(
        run_id,
        f"Boltz done. affinity_pred_value={affinity}, iptm={iptm}, PDB size={len(pdb_bytes)} bytes",
        event="boltz_done",
    )
    return pdb_bytes, affinity, score_dict


# ── Public entry point (used by architect) ─────────────────────────────────────

async def run_pipeline(
    run_id: str,
    iteration: int,
    target_pdb_path: str,
    target_sequence: str,
    rfd_settings: dict,
) -> tuple[str, float | None, dict | None]:
    """
    Full RFdiffusion → ProteinMPNN → Boltz pipeline.

    Returns:
        (local_pdb_path, affinity_pred_value | None, boltz_scores | None)

    boltz_scores dict (when available) contains:
        iptm, confidence_score, complex_plddt, ipSAE_AB, pDockQ2_AB
    Use iptm > 0.8 as the Critic quality gate for protein-protein binders.

    If LIVE_API=false or ALLOW_FALLBACK=true and any step fails,
    falls back to the mock PDB and returns (path, None, None).
    """
    live_api = os.environ.get("LIVE_API", "false").lower() == "true"

    if not live_api:
        _append_log(run_id, "LIVE_API=false — skipping Tamarind pipeline, using fallback.", event="fallback_mode")
        if not _allow_fallback():
            raise TamarindFailedError("LIVE_API=false and ALLOW_FALLBACK=false")
        return _fallback_pdb(run_id, iteration), None, None

    target_pdb_bytes = Path(target_pdb_path).read_bytes()
    target_filename = Path(target_pdb_path).name

    try:
        # ── Step 1: RFdiffusion ────────────────────────────────────────────────
        backbone_pdb_bytes = await run_rfdiffusion(
            run_id, iteration, target_pdb_bytes, target_filename, rfd_settings
        )
        backbone_filename = f"{run_id}_iter{iteration}_backbone.pdb"
        backbone_local = PDBS_DIR / backbone_filename
        backbone_local.write_bytes(backbone_pdb_bytes)

        # ── Step 2: ProteinMPNN ────────────────────────────────────────────────
        binder_sequence = await run_proteinmpnn(
            run_id, iteration, backbone_pdb_bytes, backbone_filename
        )

        # ── Step 3: Boltz ──────────────────────────────────────────────────────
        complex_pdb_bytes, affinity, boltz_scores = await run_boltz(
            run_id, iteration, target_sequence, binder_sequence
        )

        # Save final complex PDB (this is what the Critic will evaluate)
        dest = PDBS_DIR / f"{run_id}_iter_{iteration}.pdb"
        dest.write_bytes(complex_pdb_bytes)

        # Save sidecar with all scoring data for the Critic
        sidecar = PDBS_DIR / f"{run_id}_iter_{iteration}_affinity.json"
        sidecar_data: dict = {
            "affinity_pred_value": affinity,
            "binder_sequence": binder_sequence,
            "target_sequence": target_sequence,
        }
        if boltz_scores:
            # Surface iptm and companion metrics for Critic quality gate (iptm > 0.8)
            sidecar_data["boltz_scores"] = boltz_scores
            for key in ("iptm", "confidence_score", "complex_plddt", "ipSAE_AB", "pDockQ2_AB"):
                if key in boltz_scores:
                    sidecar_data[key] = boltz_scores[key]
        sidecar.write_text(json.dumps(sidecar_data))

        return str(dest), affinity, boltz_scores

    except (TamarindTimeoutError, TamarindFailedError) as e:
        _append_log(run_id, str(e), event="pipeline_error", level="error")
        if _allow_fallback():
            _append_log(run_id, "Activating fallback PDB.", event="fallback_triggered", level="warning")
            return _fallback_pdb(run_id, iteration), None, None
        raise

    except Exception as e:
        _append_log(run_id, f"Unexpected pipeline error: {e}", event="pipeline_error", level="error")
        if _allow_fallback():
            return _fallback_pdb(run_id, iteration), None, None
        raise TamarindFailedError(str(e)) from e
