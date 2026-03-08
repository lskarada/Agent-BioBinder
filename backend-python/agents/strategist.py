"""
Strategist agent — uses OpenAI gpt-4.1 with structured output to generate
peptide binder design constraints for CXCL12.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from openai import AsyncOpenAI
from pydantic import BaseModel

LOGS_DIR = Path(__file__).parent.parent / "outputs" / "logs"

# ── Output schema ──────────────────────────────────────────────────────────────

class StrategistOutput(BaseModel):
    target_id: str
    binding_hypothesis: dict  # primary_anchor_zone, secondary_extension_zone, mode
    design_constraints: dict  # min_length, max_length, desired_flexibility, topology_hint, avoid_excess_bulk_near
    rationale: str


SYSTEM_PROMPT = """You are a structural biology expert designing peptide binders.
Target: CXCL12 — a small chemokine (8.5 kDa) central to CXCL12–CXCR4 signaling implicated in tumor metastasis.
Primary anchor zone: Val18, Arg47, Val49 (sTyr21-recognition cleft).
Secondary extension zone: Pro10, Leu29, Val39 (adjacent hydrophobic surface).
Design goal: A peptide that engages the receptor-recognition surface as a structural hypothesis. Not a validated therapeutic."""


def _build_user_prompt(iteration: int, feedback: str | None) -> str:
    feedback_section = ""
    if feedback:
        feedback_section = f"\nCritic feedback from previous iteration: {feedback}\n"
    return (
        f"Iteration {iteration}.{feedback_section}\n"
        "Generate binding design constraints as JSON matching the StrategistOutput schema.\n"
        "Prefer compact_turn_or_helical_motif. Binder length 8–18 residues.\n"
        "Avoid excess bulk near Arg47."
    )


def _append_log(run_id: str, message: str, event: str = "constraint_generated") -> None:
    log_file = LOGS_DIR / f"{run_id}.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": "strategist",
        "event": event,
        "level": "info",
        "message": message,
    }
    with open(log_file, "a") as f:
        f.write(json.dumps(entry) + "\n")


async def run_strategist(run_id: str, iteration: int, previous_feedback: str | None = None) -> StrategistOutput:
    """
    Call OpenAI gpt-4.1 with structured output to get design constraints.
    Returns a StrategistOutput Pydantic model.
    """
    client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    _append_log(run_id, f"Strategist starting iteration {iteration}", event="start")

    response = await client.beta.chat.completions.parse(
        model="gpt-4o",  # use gpt-4o as gpt-4.1 may not be available; swap to "gpt-4.1" when accessible
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _build_user_prompt(iteration, previous_feedback)},
        ],
        response_format=StrategistOutput,
    )

    result: StrategistOutput = response.choices[0].message.parsed

    _append_log(
        run_id,
        f"Anchoring design around sTyr21-recognition cleft. "
        f"Binder length {result.design_constraints.get('min_length', '?')}–"
        f"{result.design_constraints.get('max_length', '?')}. "
        f"Rationale: {result.rationale}",
    )

    return result
