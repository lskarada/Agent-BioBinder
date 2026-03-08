import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import aiofiles
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

app = FastAPI(title="Agent Binder API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
OUTPUTS_DIR = BASE_DIR / "outputs"
LOGS_DIR = OUTPUTS_DIR / "logs"
PDBS_DIR = OUTPUTS_DIR / "pdbs"
STATE_FILE = BASE_DIR / "state.json"

OUTPUTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)
PDBS_DIR.mkdir(exist_ok=True)

app.mount("/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")


# ── State helpers ──────────────────────────────────────────────────────────────

def read_state() -> dict:
    if not STATE_FILE.exists():
        return {"status": "idle"}
    with open(STATE_FILE) as f:
        return json.load(f)


def write_state(state: dict) -> None:
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def initial_state(run_id: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    return {
        "run_id": run_id,
        "status": "started",
        "iteration": 0,
        "mode": "live",
        "target_id": "CXCL12",
        "metrics": {"plddt_mean": None, "steric_clashes": None},
        "final_pdb_url": None,
        "created_at": now,
        "updated_at": now,
    }


# ── Request/response models ────────────────────────────────────────────────────

class StartLoopRequest(BaseModel):
    target_id: str = "CXCL12"


class StartLoopResponse(BaseModel):
    run_id: str
    status: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.post("/api/start-loop", response_model=StartLoopResponse)
async def start_loop(req: StartLoopRequest, background_tasks: BackgroundTasks):
    if req.target_id.upper() != "CXCL12":
        raise HTTPException(status_code=400, detail="Only CXCL12 target is supported")

    current = read_state()
    if current.get("status", "idle") not in ("idle", "completed_success_live", "completed_success_fallback", "completed_failure", "error"):
        raise HTTPException(status_code=409, detail="A run is already in progress")

    run_id = "run_" + uuid.uuid4().hex[:8]
    state = initial_state(run_id)
    write_state(state)

    from agents.loop import run_loop
    background_tasks.add_task(run_loop, run_id)

    return StartLoopResponse(run_id=run_id, status="started")


@app.get("/api/status")
async def get_status(run_id: str):
    state = read_state()
    if state.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": state["run_id"],
        "status": state["status"],
        "iteration": state.get("iteration", 0),
        "mode": state.get("mode", "live"),
        "metrics": state.get("metrics", {}),
    }


@app.get("/api/logs")
async def get_logs(run_id: str):
    log_file = LOGS_DIR / f"{run_id}.jsonl"
    if not log_file.exists():
        return []
    entries = []
    async with aiofiles.open(log_file) as f:
        async for line in f:
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return entries


@app.get("/api/result")
async def get_result(run_id: str):
    state = read_state()
    if state.get("run_id") != run_id:
        raise HTTPException(status_code=404, detail="Run not found")
    return {
        "run_id": state["run_id"],
        "status": state["status"],
        "final_pdb_url": state.get("final_pdb_url"),
        "metrics": state.get("metrics", {}),
        "mode": state.get("mode", "live"),
    }
