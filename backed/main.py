"""
ReachFlow — FastAPI Backend
============================
Exposes the 3-stage outreach pipeline as REST + Server-Sent Events endpoints.

Endpoints:
  POST /api/run          — start a pipeline run (returns run_id)
  GET  /api/run/{id}     — get run status + results
  GET  /api/stream/{id}  — SSE stream of live stage logs
  POST /api/send/{id}    — confirm send (safety checkpoint)
  POST /api/cancel/{id}  — cancel a pending run
  GET  /api/runs         — list all past runs
  GET  /api/health       — health check / API key status

Run:
  uvicorn api:app --reload --port 8000
"""

import asyncio
import json
import time
import uuid
import logging
import os
import sys
from datetime import datetime
from typing import AsyncGenerator
from pathlib import Path

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# ── Add pipeline root to path ─────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "outreach_pipeline"))

from stages.stage1_apollo import find_lookalikes
from stages.stage2_prospeo import find_decision_makers
from stages.stage4_brevo import send_outreach
from utils.config import load_config

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ReachFlow API",
    description="Automated cold-outreach pipeline: Apollo → Prospeo → Brevo",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory run store (replace with DB in production) ──────────────────────
runs: dict[str, dict] = {}

# SSE event queues per run_id
sse_queues: dict[str, asyncio.Queue] = {}


# ── Pydantic models ───────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    domain: str = Field(..., example="stripe.com", description="Seed company domain")
    limit: int | None = Field(None, ge=1, le=50, description="Cap contacts (testing)")
    dry_run: bool = Field(False, description="Preview emails, don't send")

class RunStatus(BaseModel):
    run_id: str
    domain: str
    status: str          # pending | stage1 | stage2 | checkpoint | stage3 | done | failed | cancelled
    dry_run: bool
    created_at: str
    updated_at: str
    lookalikes: list[str]
    contacts: list[dict]
    send_results: list[dict]
    logs: list[dict]
    error: str | None

class SendConfirm(BaseModel):
    run_id: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.utcnow().isoformat() + "Z"

def _make_run(domain: str, dry_run: bool) -> dict:
    run_id = str(uuid.uuid4())[:8]
    return {
        "run_id": run_id,
        "domain": domain,
        "dry_run": dry_run,
        "status": "pending",
        "created_at": _now(),
        "updated_at": _now(),
        "lookalikes": [],
        "contacts": [],
        "send_results": [],
        "logs": [],
        "error": None,
        "_confirm_event": asyncio.Event(),
        "_cancel_flag": False,
    }

def _log(run: dict, stage: str, msg: str, level: str = "info"):
    entry = {"ts": _now(), "stage": stage, "msg": msg, "level": level}
    run["logs"].append(entry)
    run["updated_at"] = _now()
    # Push to SSE queue if exists
    q = sse_queues.get(run["run_id"])
    if q:
        q.put_nowait({"type": "log", **entry})

def _push_event(run_id: str, event: dict):
    q = sse_queues.get(run_id)
    if q:
        q.put_nowait(event)


# ── Stream logger adapter ──────────────────────────────────────────────────────

class RunLogger(logging.Logger):
    """Bridges Python logging into the run log + SSE queue."""
    def __init__(self, run: dict):
        super().__init__("reachflow")
        self.run = run
        self.setLevel(logging.DEBUG)

    def _emit(self, level: str, msg: str, *args):
        if args:
            try:
                msg = msg % args
            except Exception:
                pass
        _log(self.run, self.run.get("status", "?"), msg, level)

    def info(self, msg, *args, **kw):    self._emit("info",    msg, *args)
    def warning(self, msg, *args, **kw): self._emit("warning", msg, *args)
    def error(self, msg, *args, **kw):   self._emit("error",   msg, *args)
    def debug(self, msg, *args, **kw):   self._emit("debug",   msg, *args)
    def exception(self, msg, *args, **kw): self._emit("error", msg, *args)


# ── Pipeline runner (runs in background task) ─────────────────────────────────

async def _run_pipeline(run_id: str, limit: int | None):
    run = runs[run_id]
    logger = RunLogger(run)
    config = load_config()

    try:
        # ── Stage 1: Apollo ──────────────────────────────────────────────
        run["status"] = "stage1"
        _push_event(run_id, {"type": "status", "status": "stage1"})
        _log(run, "stage1", f"Apollo.io: finding lookalikes for {run['domain']}")

        lookalikes = await asyncio.get_event_loop().run_in_executor(
            None, find_lookalikes, run["domain"], config, logger
        )

        if run["_cancel_flag"]:
            run["status"] = "cancelled"
            _push_event(run_id, {"type": "status", "status": "cancelled"})
            return

        if not lookalikes:
            raise RuntimeError("Stage 1 returned no lookalike domains.")

        run["lookalikes"] = lookalikes
        _log(run, "stage1", f"Found {len(lookalikes)} lookalike domains", "success")
        _push_event(run_id, {"type": "stage1_done", "lookalikes": lookalikes})

        # ── Stage 2: Prospeo ─────────────────────────────────────────────
        run["status"] = "stage2"
        _push_event(run_id, {"type": "status", "status": "stage2"})
        _log(run, "stage2", f"Prospeo: searching {len(lookalikes)} domains for decision-makers")

        contacts = await asyncio.get_event_loop().run_in_executor(
            None, find_decision_makers, lookalikes, config, logger
        )

        if run["_cancel_flag"]:
            run["status"] = "cancelled"
            _push_event(run_id, {"type": "status", "status": "cancelled"})
            return

        if not contacts:
            raise RuntimeError("Stage 2 returned no contacts with emails.")

        if limit:
            contacts = contacts[:limit]
            _log(run, "stage2", f"Limit applied: capped at {limit} contacts")

        run["contacts"] = contacts
        _log(run, "stage2", f"Found {len(contacts)} decision-makers with emails", "success")
        _push_event(run_id, {"type": "stage2_done", "contacts": contacts})

        # ── Safety checkpoint ─────────────────────────────────────────────
        if not run["dry_run"]:
            run["status"] = "checkpoint"
            _push_event(run_id, {"type": "status", "status": "checkpoint"})
            _log(run, "checkpoint", f"Waiting for confirmation to send {len(contacts)} emails")

            # Wait for /api/send or /api/cancel — timeout 10 minutes
            try:
                await asyncio.wait_for(run["_confirm_event"].wait(), timeout=600)
            except asyncio.TimeoutError:
                run["status"] = "cancelled"
                _log(run, "checkpoint", "Checkpoint timed out (10 min). Run cancelled.", "warning")
                _push_event(run_id, {"type": "status", "status": "cancelled"})
                return

            if run["_cancel_flag"]:
                run["status"] = "cancelled"
                _push_event(run_id, {"type": "status", "status": "cancelled"})
                return

        # ── Stage 3: Brevo ────────────────────────────────────────────────
        run["status"] = "stage3"
        _push_event(run_id, {"type": "status", "status": "stage3"})
        _log(run, "stage3", f"Brevo: sending {len(contacts)} emails (dry_run={run['dry_run']})")

        results = await asyncio.get_event_loop().run_in_executor(
            None, send_outreach, contacts, config, logger, run["dry_run"]
        )

        run["send_results"] = results
        sent    = sum(1 for r in results if r["status"] == "sent")
        dry     = sum(1 for r in results if r["status"] == "dry_run")
        failed  = sum(1 for r in results if r["status"] == "failed")

        if run["dry_run"]:
            _log(run, "stage3", f"Dry run: {dry} emails previewed (not sent)", "success")
        else:
            _log(run, "stage3", f"Done — sent: {sent}, failed: {failed}", "success")

        run["status"] = "done"
        _push_event(run_id, {
            "type": "done",
            "status": "done",
            "send_results": results,
            "summary": {"sent": sent, "failed": failed, "dry": dry},
        })

    except Exception as e:
        run["status"] = "failed"
        run["error"] = str(e)
        _log(run, "error", f"Pipeline failed: {e}", "error")
        _push_event(run_id, {"type": "status", "status": "failed", "error": str(e)})

    finally:
        # Signal SSE stream to close
        await asyncio.sleep(1)
        q = sse_queues.get(run_id)
        if q:
            q.put_nowait({"type": "close"})


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    """Check API keys are loaded."""
    config = load_config()
    return {
        "status": "ok",
        "keys": {
            "apollo":  bool(config.get("APOLLO_API_KEY")),
            "prospeo": bool(config.get("PROSPEO_API_KEY")),
            "brevo":   bool(config.get("BREVO_API_KEY")),
        },
        "time": _now(),
    }


@app.post("/api/run", status_code=201)
async def start_run(req: RunRequest, background_tasks: BackgroundTasks):
    """Start a new pipeline run. Returns run_id immediately."""
    domain = req.domain.strip().lower()
    # Strip protocol
    for p in ("https://", "http://", "www."):
        if domain.startswith(p):
            domain = domain[len(p):]
    domain = domain.rstrip("/")

    if not domain or "." not in domain:
        raise HTTPException(400, "Invalid domain. Example: stripe.com")

    run = _make_run(domain, req.dry_run)
    run_id = run["run_id"]
    runs[run_id] = run
    sse_queues[run_id] = asyncio.Queue()

    background_tasks.add_task(_run_pipeline, run_id, req.limit)

    return {
        "run_id": run_id,
        "domain": domain,
        "dry_run": req.dry_run,
        "status": "pending",
    }


@app.get("/api/run/{run_id}")
def get_run(run_id: str):
    """Get current state of a run."""
    run = runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    return {k: v for k, v in run.items() if not k.startswith("_")}


@app.get("/api/runs")
def list_runs():
    """List all runs (most recent first)."""
    result = []
    for run in sorted(runs.values(), key=lambda r: r["created_at"], reverse=True):
        result.append({
            "run_id":     run["run_id"],
            "domain":     run["domain"],
            "status":     run["status"],
            "dry_run":    run["dry_run"],
            "created_at": run["created_at"],
            "lookalikes": len(run["lookalikes"]),
            "contacts":   len(run["contacts"]),
            "sent":       sum(1 for r in run["send_results"] if r.get("status") == "sent"),
        })
    return result


@app.post("/api/send/{run_id}")
def confirm_send(run_id: str):
    """Safety checkpoint — confirm sending emails for this run."""
    run = runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    if run["status"] != "checkpoint":
        raise HTTPException(400, f"Run is in status '{run['status']}', not at checkpoint")
    run["_confirm_event"].set()
    _log(run, "checkpoint", "Send confirmed by user", "success")
    _push_event(run_id, {"type": "confirmed"})
    return {"ok": True, "message": "Send confirmed"}


@app.post("/api/cancel/{run_id}")
def cancel_run(run_id: str):
    """Cancel a run (at checkpoint or during execution)."""
    run = runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")
    run["_cancel_flag"] = True
    run["_confirm_event"].set()   # unblock checkpoint wait if active
    run["status"] = "cancelled"
    _log(run, "cancel", "Run cancelled by user", "warning")
    _push_event(run_id, {"type": "status", "status": "cancelled"})
    return {"ok": True}


@app.get("/api/stream/{run_id}")
async def stream_run(run_id: str):
    """
    Server-Sent Events stream for live pipeline logs.
    Connect with EventSource('/api/stream/{run_id}').
    """
    run = runs.get(run_id)
    if not run:
        raise HTTPException(404, f"Run {run_id} not found")

    # Ensure queue exists
    if run_id not in sse_queues:
        sse_queues[run_id] = asyncio.Queue()

    async def event_generator() -> AsyncGenerator[str, None]:
        q = sse_queues[run_id]

        # Replay existing logs for reconnects
        for log_entry in run.get("logs", []):
            yield f"data: {json.dumps({'type': 'log', **log_entry})}\n\n"

        # Stream new events
        while True:
            try:
                event = await asyncio.wait_for(q.get(), timeout=30)
                yield f"data: {json.dumps(event)}\n\n"
                if event.get("type") == "close":
                    break
            except asyncio.TimeoutError:
                yield "data: {\"type\":\"ping\"}\n\n"
            except asyncio.CancelledError:
                # Generator was cancelled during server shutdown/reload — exit cleanly
                break

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )