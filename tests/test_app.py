"""Phase 0 tests: the app serves its pages and records submissions."""

from fastapi.testclient import TestClient

import app.main as main


def test_pages_and_submit(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "SUBMISSIONS", tmp_path / "submissions.jsonl")
    client = TestClient(main.app)
    assert client.get("/").status_code == 200
    assert client.get("/submit").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}

    bad = client.post("/api/submit", json={"url": "not a url"})
    assert bad.status_code == 400

    ok = client.post("/api/submit", json={"url": "https://example.com", "note": "hi"})
    assert ok.status_code == 200 and ok.json()["count"] == 1
    assert client.get("/api/submissions/count").json()["count"] == 1
