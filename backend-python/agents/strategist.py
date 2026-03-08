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

class BindingHypothesis(BaseModel):
    primary_anchor_zone: list[str]
    secondary_extension_zone: list[str]
    mode: str


class DesignConstraints(BaseModel):
    min_length: int
    max_length: int
    desired_flexibility: str
    topology_hint: str
    avoid_excess_bulk_near: str


class StrategistOutput(BaseModel):
    target_id: str
    binding_hypothesis: BindingHypothesis
    design_constraints: DesignConstraints
    rationale: str


BASE_SYSTEM_PROMPT = """You are a structural biology expert designing peptide binders.
You will be given published literature about the target protein. Read it carefully and
use it — not prior assumptions — to derive the binding site, anchor residues, and design
constraints. Design goal: a compact peptide that engages the receptor-recognition surface.
Not a validated therapeutic."""


def _load_literature() -> str:
    lit_dir = Path(__file__).parent.parent / "literature"
    if not lit_dir.exists():
        return ""
    texts = []
    for path in sorted(lit_dir.glob("*.txt")):
        texts.append(f"=== {path.name} ===\n{path.read_text().strip()}")
    return "\n\n".join(texts)


def _build_system_prompt() -> str:
    literature = _load_literature()
    if not literature:
        return BASE_SYSTEM_PROMPT
    return BASE_SYSTEM_PROMPT + "\n\n## Literature\n" + literature


def _build_user_prompt(iteration: int, feedback: str | None) -> str:
    feedback_section = ""
    if feedback:
        feedback_section = f"\nCritic feedback from previous iteration: {feedback}\n"
    return (
        f"Iteration {iteration}.{feedback_section}\n"
        "Generate binding design constraints as JSON matching the StrategistOutput schema."
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
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": _build_system_prompt()},
            {"role": "user", "content": _build_user_prompt(iteration, previous_feedback)},
        ],
        response_format=StrategistOutput,
    )

    result: StrategistOutput = response.choices[0].message.parsed

    _append_log(
        run_id,
        f"Constraints generated. "
        f"Binder length {result.design_constraints.min_length}–"
        f"{result.design_constraints.max_length}. "
        f"Rationale: {result.rationale}",
    )

    return result
