"""Blindspot web app.

Phase 0: serves the one-page app placeholder and the QR submission form that
collects stranger URLs for the held-out test set. The run API arrives in later
phases (see docs/PLAN.md).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
SUBMISSIONS = ROOT / "eval" / "submissions.jsonl"

app = FastAPI(title="Blindspot")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class Submission(BaseModel):
    url: str
    note: str | None = None


def _valid_url(url: str) -> bool:
    parsed = urlparse(url.strip())
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/submit")
def submit_page() -> FileResponse:
    return FileResponse(STATIC / "submit.html")


@app.post("/api/submit")
def submit(sub: Submission) -> dict:
    """Append a stranger-submitted URL to eval/submissions.jsonl."""
    url = sub.url.strip()
    if not _valid_url(url):
        raise HTTPException(status_code=400, detail="Please enter a full URL starting with http:// or https://")
    record = {
        "url": url,
        "note": (sub.note or "").strip()[:200],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    SUBMISSIONS.parent.mkdir(parents=True, exist_ok=True)
    with SUBMISSIONS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")
    return {"ok": True, "count": _count_submissions()}


def _count_submissions() -> int:
    if not SUBMISSIONS.exists():
        return 0
    return sum(1 for line in SUBMISSIONS.read_text(encoding="utf-8").splitlines() if line.strip())


@app.get("/api/submissions/count")
def submissions_count() -> dict:
    return {"count": _count_submissions()}


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}
