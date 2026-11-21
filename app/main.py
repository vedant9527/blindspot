"""Blindspot web app: run API, Server-Sent Events stream, QR submission form, static files.

See docs/SPEC.md section 1.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from blindspot.runner import run_audit

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "app" / "static"
RUNS_DIR = ROOT / "runs"
SUBMISSIONS = ROOT / "eval" / "submissions.jsonl"
VETTED_OK = ROOT / "eval" / "pages_ok.txt"

RUNS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Blindspot")
app.mount("/static", StaticFiles(directory=STATIC), name="static")
app.mount("/runs", StaticFiles(directory=RUNS_DIR), name="runs")


@dataclass
class RunStreamState:
    """Thread-safe event log + subscriber notification for one active/completed run."""

    run_id: str
    url: str
    events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    finished: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    subscribers: list[tuple[asyncio.AbstractEventLoop, asyncio.Event]] = field(default_factory=list)

    def push(self, event: str, data: dict[str, Any]) -> None:
        with self.lock:
            self.events.append((event, data))
            if event in ("done", "error"):
                self.finished = True
            subs = list(self.subscribers)
        for loop, wake in subs:
            try:
                loop.call_soon_threadsafe(wake.set)
            except RuntimeError:
                pass


_ACTIVE_RUNS: dict[str, RunStreamState] = {}
_RUNS_LOCK = threading.Lock()


class Submission(BaseModel):
    url: str
    note: str | None = None


class RunRequest(BaseModel):
    url: str
    inject: str | None = None
    seed: int | None = None
    headless: bool = False
    use_gemini: bool = True


def _is_blocked_ip(ip_str: str) -> bool:
    """True for loopback, private, link-local, unspecified, reserved, or multicast IPs."""
    clean = ip_str.split("%", 1)[0]  # strip IPv6 zone ID if present
    ip = ipaddress.ip_address(clean)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_reserved
        or ip.is_multicast
    )


def _valid_url(url: str) -> bool:
    """Allow only public http(s) URLs; reject file://, localhost, .local, and private/loopback IPs."""
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        return False
    try:
        return not _is_blocked_ip(host)
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    ips = {info[4][0] for info in infos if info and info[4]}
    if not ips:
        return False
    for ip_str in ips:
        try:
            if _is_blocked_ip(ip_str):
                return False
        except ValueError:
            return False
    return True


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/submit")
def submit_page() -> FileResponse:
    return FileResponse(STATIC / "submit.html")


@app.post("/api/submit")
def submit(sub: Submission) -> dict[str, Any]:
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
def submissions_count() -> dict[str, int]:
    return {"count": _count_submissions()}


@app.get("/api/vetted")
def vetted_pages() -> dict[str, list[str]]:
    """Return vetted public healthcare URLs from eval/pages_ok.txt."""
    if not VETTED_OK.exists():
        return {"urls": []}
    urls = [ln.strip() for ln in VETTED_OK.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.startswith("#")]
    return {"urls": urls}


@app.post("/api/run")
def start_run(req: RunRequest) -> dict[str, str]:
    """Start an accessibility run in a background worker and return its `run_id`."""
    url = req.url.strip()
    if not _valid_url(url):
        raise HTTPException(status_code=400, detail="Please enter a valid public URL starting with http:// or https://")
    host = urlparse(url).netloc.replace("www.", "") or "page"
    short = uuid.uuid4().hex[:6]
    run_id = f"{datetime.now():%Y%m%d-%H%M%S}-{host}-{short}"
    state = RunStreamState(run_id=run_id, url=url)
    with _RUNS_LOCK:
        if any(not s.finished for s in _ACTIVE_RUNS.values()):
            raise HTTPException(status_code=409, detail="A run is already in progress")
        _ACTIVE_RUNS[run_id] = state

    def _worker() -> None:
        try:
            run_audit(
                url,
                run_id=run_id,
                out_dir=RUNS_DIR / run_id,
                headless=req.headless,
                inject=req.inject,
                seed=req.seed,
                use_gemini=req.use_gemini,
                emit=state.push,
            )
        except Exception as exc:
            state.push("error", {"run_id": run_id, "message": str(exc)})
        finally:
            with state.lock:
                state.finished = True

    threading.Thread(target=_worker, name=f"blindspot-{run_id}", daemon=True).start()
    return {"run_id": run_id}


@app.get("/api/run/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    """Return saved findings and metadata for a run once available."""
    run_dir = RUNS_DIR / run_id
    findings_file = run_dir / "findings.json"
    if findings_file.exists():
        return json.loads(findings_file.read_text(encoding="utf-8"))
    with _RUNS_LOCK:
        state = _ACTIVE_RUNS.get(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Unknown run_id")
    return {"run_id": run_id, "url": state.url, "status": "running", "events_emitted": len(state.events)}


@app.get("/api/run/{run_id}/events")
async def stream_run_events(run_id: str) -> StreamingResponse:
    """Stream Server-Sent Events (`preflight`, `step`, `finding`, `axe`, `ticket`, `done`, `error`)."""
    with _RUNS_LOCK:
        state = _ACTIVE_RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Unknown run_id")

    async def _event_gen() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        wake = asyncio.Event()
        sub = (loop, wake)
        with state.lock:
            state.subscribers.append(sub)
        cursor = 0
        try:
            while True:
                with state.lock:
                    batch = state.events[cursor:]
                    cursor = len(state.events)
                    done = state.finished
                for ev_name, payload in batch:
                    yield f"event: {ev_name}\ndata: {json.dumps(payload)}\n\n"
                if done and cursor >= len(state.events):
                    break
                wake.clear()
                try:
                    await asyncio.wait_for(wake.wait(), timeout=10.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            with state.lock:
                if sub in state.subscribers:
                    state.subscribers.remove(sub)

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
