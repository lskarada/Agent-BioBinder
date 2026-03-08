"""
Architect agent — uses Claude claude-sonnet-4-6 to translate Strategist constraints
into a Tamarind RFDiffusion job payload, then submits the job via tools/tamarind.py.
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from agents.strategist import StrategistOutput
from tools.tamarind import TamarindFailedError, TamarindTimeoutError, submit_and_retrieve

LOGS_DIR = Path(__file__).parent.parent / "outputs" / "logs"
TARGET_PDBS_DIR = Path(__file__).parent.parent / "target_pdbs"

SYSTEM_PROMPT = """You are a structural design engineer. Your job is to translate design constraints into a Tamarind RFDiffusion job payload and summarize what you submitted.
Target PDB file is: cxcl12.pdb (chain A).
Primary hotspots for Tamarind: A18, A47, A49.

Respond with a JSON block (fenced with ```json ... ```) containing the Tamarind job payload, followed by a brief summary.

The JSON must match this exact schema:
{
  "jobName": "<run_id>_iter_<n>",
  "type": "rfdiffusion",
  "settings": {
    "pdbFile": "cxcl12.pdb",
    "targetChains": ["A"],
    "binderLength": "<min>-<max>",
    "hotspots": ["A18", "A47", "A49"],
    "numDesigns": 1,
    "verify": true,
    "mpnnModelType": "SolubleMPNN"
  }
}"""


def _append_log(run_id: str, message: str, event: str = "payload_built", level: str = "info") -> None:
    log_file = LOGS_DIR / f"{run_id}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "architect",
        "event": event,
        "level": level,
        "message": message,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _extract_json_block(text: str) -> dict:
    """Extract JSON from a fenced code block or raw JSON in Claude's response."""
    match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))
    # Fallback: try to find raw JSON object
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise ValueError("No JSON block found in Claude response")


async def run_architect(run_id: str, iteration: int, strategy: StrategistOutput) -> str:
    """
    1. Ask Claude to format a Tamarind payload from Strategist constraints.
    2. Parse the payload from Claude's response.
    3. Submit to Tamarind (or trigger fallback on failure).
    Returns the local path to the downloaded PDB file.
    """
    client = anthropic.AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    constraints = strategy.design_constraints
    min_len = constraints.get("min_length", 10)
    max_len = constraints.get("max_length", 15)
    job_name = f"{run_id}_iter_{iteration}"

    user_message = (
        f"Design constraints from Strategist:\n"
        f"{json.dumps({'binding_hypothesis': strategy.binding_hypothesis, 'design_constraints': constraints}, indent=2)}\n\n"
        f"Job name: {job_name}\n"
        f"Binder length range: {min_len}–{max_len}\n\n"
        "Generate the Tamarind RFDiffusion payload JSON and summarize your design decision."
    )

    _append_log(run_id, f"Calling Claude to format Tamarind payload for {job_name}", event="start")

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    claude_text = response.content[0].text
    _append_log(run_id, f"Claude response received. Parsing payload.", event="claude_response")

    try:
        payload = _extract_json_block(claude_text)
    except (ValueError, json.JSONDecodeError) as e:
        # Fallback payload if Claude doesn't produce clean JSON
        _append_log(run_id, f"Could not parse Claude JSON: {e}. Using default payload.", event="parse_fallback", level="warning")
        payload = {
            "jobName": job_name,
            "type": "rfdiffusion",
            "settings": {
                "pdbFile": "cxcl12.pdb",
                "targetChains": ["A"],
                "binderLength": f"{min_len}-{max_len}",
                "hotspots": ["A18", "A47", "A49"],
                "numDesigns": 1,
                "verify": True,
                "mpnnModelType": "SolubleMPNN",
            },
        }

    _append_log(
        run_id,
        f"Submitting Tamarind job '{job_name}' with binderLength={payload['settings'].get('binderLength')}",
        event="tamarind_submit",
    )

    pdb_path = await submit_and_retrieve(
        payload=payload,
        run_id=run_id,
        iteration=iteration,
        pdb_file_path=str(TARGET_PDBS_DIR / "cxcl12.pdb"),
    )

    _append_log(run_id, f"PDB retrieved: {pdb_path}", event="pdb_retrieved")
    return pdb_path
