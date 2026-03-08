"""
Tamarind async client — submit RFDiffusion jobs, poll for completion, retrieve PDB.

Env vars:
  TAMARIND_API_KEY          — Bearer token
  TAMARIND_BASE_URL         — default https://api.tamarind.bio
  TAMARIND_TIMEOUT_SECONDS  — default 45
  LIVE_API                  — "true" / "false"
  ALLOW_FALLBACK            — "true" / "false"
"""
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


class TamarindTimeoutError(Exception):
    pass


class TamarindFailedError(Exception):
    pass


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


async def submit_and_retrieve(
    payload: dict,
    run_id: str,
    iteration: int,
    pdb_file_path: str,
    timeout_s: int | None = None,
) -> str:
    """
    Submit a Tamarind job, poll until COMPLETED/FAILED, retrieve the PDB.
    Falls back to mock PDB if LIVE_API=false or on repeated failure.

    Returns the local filesystem path to the PDB file.
    """
    live_api = os.environ.get("LIVE_API", "false").lower() == "true"
    allow_fallback = os.environ.get("ALLOW_FALLBACK", "true").lower() == "true"

    if not live_api:
        _append_log(run_id, "LIVE_API=false — skipping Tamarind, using fallback.", event="fallback_mode")
        if not allow_fallback:
            raise TamarindFailedError("LIVE_API=false and ALLOW_FALLBACK=false")
        return _fallback_pdb(run_id, iteration)

    timeout_s = timeout_s or int(os.environ.get("TAMARIND_TIMEOUT_SECONDS", "45"))
    api_key = os.environ.get("TAMARIND_API_KEY", "")
    base_url = os.environ.get("TAMARIND_BASE_URL", "https://api.tamarind.bio").rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # ── Step 1: Submit job ─────────────────────────────────────────────
            pdb_bytes = Path(pdb_file_path).read_bytes()
            submit_response = await client.post(
                f"{base_url}/submit-job",
                headers=headers,
                data={"payload": json.dumps(payload)},
                files={"pdbFile": ("cxcl12.pdb", pdb_bytes, "chemical/x-pdb")},
            )
            submit_response.raise_for_status()
            job_data = submit_response.json()
            job_id = job_data.get("jobId") or job_data.get("id")
            if not job_id:
                raise TamarindFailedError(f"No jobId in submit response: {job_data}")

            _append_log(run_id, f"Job submitted: {job_id}", event="job_submitted")

            # ── Step 2: Poll for completion ────────────────────────────────────
            import asyncio
            poll_interval = 3
            elapsed = 0
            while elapsed < timeout_s:
                await asyncio.sleep(poll_interval)
                elapsed += poll_interval

                status_response = await client.get(
                    f"{base_url}/jobs",
                    headers=headers,
                    params={"jobId": job_id},
                )
                status_response.raise_for_status()
                status_data = status_response.json()
                job_status = status_data.get("status", "UNKNOWN")

                _append_log(run_id, f"Job {job_id} status: {job_status} ({elapsed}s elapsed)", event="poll")

                if job_status == "COMPLETED":
                    break
                elif job_status == "FAILED":
                    raise TamarindFailedError(f"Tamarind job {job_id} failed: {status_data}")
            else:
                raise TamarindTimeoutError(f"Tamarind job {job_id} timed out after {timeout_s}s")

            # ── Step 3: Retrieve result ────────────────────────────────────────
            result_response = await client.post(
                f"{base_url}/result",
                headers=headers,
                json={"jobId": job_id},
            )
            result_response.raise_for_status()

            # Extract PDB from zip
            zip_bytes = result_response.content
            dest_path = PDBS_DIR / f"{run_id}_iter_{iteration}.pdb"
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                pdb_names = [n for n in zf.namelist() if n.endswith(".pdb")]
                if not pdb_names:
                    raise TamarindFailedError("No PDB file found in result zip")
                pdb_content = zf.read(pdb_names[0])
                dest_path.write_bytes(pdb_content)

            _append_log(run_id, f"PDB saved: {dest_path}", event="pdb_saved")
            return str(dest_path)

    except (TamarindTimeoutError, TamarindFailedError) as e:
        _append_log(run_id, str(e), event="tamarind_error", level="error")
        if allow_fallback:
            _append_log(run_id, "Activating fallback PDB.", event="fallback_triggered", level="warning")
            return _fallback_pdb(run_id, iteration)
        raise

    except Exception as e:
        _append_log(run_id, f"Unexpected error: {e}", event="tamarind_error", level="error")
        if allow_fallback:
            return _fallback_pdb(run_id, iteration)
        raise TamarindFailedError(str(e)) from e
