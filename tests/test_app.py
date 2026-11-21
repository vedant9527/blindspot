"""App tests: pages, submission form, SSRF URL validation, and single-run concurrency guard."""

from __future__ import annotations

import socket
import threading

import pytest
from fastapi.testclient import TestClient

import app.main as main


def _fake_getaddrinfo(mapping: dict[str, list[str]]):
    def _resolver(host, port, *args, **kwargs):
        ips = mapping.get(host.lower().rstrip("."))
        if ips is None:
            raise socket.gaierror(8, "nodename nor servname provided")
        out = []
        for ip in ips:
            fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
            sockaddr = (ip, 0, 0, 0) if fam == socket.AF_INET6 else (ip, 0)
            out.append((fam, socket.SOCK_STREAM, 6, "", sockaddr))
        return out

    return _resolver


def test_pages_and_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "SUBMISSIONS", tmp_path / "submissions.jsonl")
    monkeypatch.setattr(main.socket, "getaddrinfo", _fake_getaddrinfo({"example.com": ["93.184.216.34"]}))
    client = TestClient(main.app)
    assert client.get("/").status_code == 200
    assert client.get("/submit").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}

    bad = client.post("/api/submit", json={"url": "not a url"})
    assert bad.status_code == 400

    ok = client.post("/api/submit", json={"url": "https://example.com", "note": "hi"})
    assert ok.status_code == 200 and ok.json()["count"] == 1
    assert client.get("/api/submissions/count").json()["count"] == 1


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "http://localhost:8000/",
        "http://sub.localhost/",
        "http://127.0.0.1/",
        "http://127.42.0.1:8080/admin",
        "http://0.0.0.0:8000/",
        "http://[::1]:8000/",
        "http://printer.local/",
        "https://my-mac.LOCAL/path",
        "http://10.0.0.1/",
        "http://172.16.0.5/",
        "http://172.31.255.254/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://rebind-private.test/",
        "http://rebind-loopback.test/",
        "http://unresolvable.invalid/",
    ],
)
def test_valid_url_rejects_local_private_and_file(monkeypatch, bad_url):
    monkeypatch.setattr(
        main.socket,
        "getaddrinfo",
        _fake_getaddrinfo(
            {
                "rebind-private.test": ["10.20.30.40"],
                "rebind-loopback.test": ["127.0.0.1"],
                "medlineplus.gov": ["130.14.29.110"],
            }
        ),
    )
    assert main._valid_url(bad_url) is False
    client = TestClient(main.app)
    resp = client.post("/api/run", json={"url": bad_url})
    assert resp.status_code == 400


def test_valid_url_accepts_public_hostname(monkeypatch):
    monkeypatch.setattr(main.socket, "getaddrinfo", _fake_getaddrinfo({"medlineplus.gov": ["130.14.29.110"]}))
    assert main._valid_url("https://medlineplus.gov/") is True


def test_only_one_run_at_a_time_returns_409(monkeypatch):
    monkeypatch.setattr(main.socket, "getaddrinfo", _fake_getaddrinfo({"medlineplus.gov": ["130.14.29.110"]}))
    monkeypatch.setattr(main, "_ACTIVE_RUNS", {})

    started = threading.Event()
    release = threading.Event()

    def _fake_run_audit(url, *, run_id, emit=None, **kwargs):
        started.set()
        release.wait(timeout=5.0)
        if emit:
            emit("done", {"run_id": run_id, "status": "ok"})
        return {"run_id": run_id}

    monkeypatch.setattr(main, "run_audit", _fake_run_audit)
    client = TestClient(main.app)

    r1 = client.post("/api/run", json={"url": "https://medlineplus.gov/", "headless": True, "use_gemini": False})
    assert r1.status_code == 200
    assert started.wait(timeout=2.0)

    r2 = client.post("/api/run", json={"url": "https://medlineplus.gov/", "headless": True, "use_gemini": False})
    assert r2.status_code == 409
    assert r2.json()["detail"] == "A run is already in progress"

    release.set()
    # Wait briefly for worker thread to mark the first run finished
    run1_id = r1.json()["run_id"]
    for _ in range(50):
        if main._ACTIVE_RUNS[run1_id].finished:
            break
        threading.Event().wait(0.02)

    r3 = client.post("/api/run", json={"url": "https://medlineplus.gov/", "headless": True, "use_gemini": False})
    assert r3.status_code == 200
