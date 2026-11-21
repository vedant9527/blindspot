"""Phase 6 tests: Carbon ticket generation, red-box evidence crops, vetted order, and Proof API."""

from __future__ import annotations

import io
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import app.main as main
from blindspot.tickets import generate_tickets, save_evidence_crop


def _dummy_png(w: int = 400, h: int = 300) -> bytes:
    img = Image.new("RGB", (w, h), "white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_generate_tickets_writes_markdown_and_red_box_crop(tmp_path):
    shot = tmp_path / "07.png"
    shot.write_bytes(_dummy_png())
    finding = {
        "check": "focus_not_visible",
        "wcag": "2.4.7",
        "status": "confirmed",
        "proven": True,
        "scorer_fail_p": 0.93,
        "detail": "No visible focus indicator: 0 pixels change around the element",
        "evidence": {
            "step": 7,
            "selector": "a.nofocus",
            "visible_text": "Telehealth",
            "accessible_name": "Telehealth",
            "rect": {"x": 80, "y": 90, "width": 100, "height": 34},
            "full_screenshot": str(shot),
        },
    }
    run = {"run_id": "test-run", "page": {"url": "https://example.org/", "viewport": {"width": 400, "height": 300}}}

    emitted = []
    tickets = generate_tickets(
        run,
        [finding],
        tmp_path,
        use_gemini=False,
        on_ticket=emitted.append,
    )
    assert len(tickets) == 1
    assert len(emitted) == 1
    t = tickets[0]
    assert Path(t["ticket_path"]).exists()
    assert Path(t["crop_path"]).exists()
    md = Path(t["ticket_path"]).read_text(encoding="utf-8")
    assert "2.4.7" in md
    assert "a.nofocus" in md
    assert "Step `7`" in md
    assert "1_evidence.png" in md


def test_save_evidence_crop_fallback_without_rect(tmp_path):
    crop_path, data = save_evidence_crop({"check": "focus_order", "evidence": {}}, tmp_path, 1)
    assert crop_path is None and data is None


def test_vetted_puts_three_stable_demo_pages_first():
    client = TestClient(main.app)
    res = client.get("/api/vetted")
    assert res.status_code == 200
    data = res.json()
    assert data["urls"][:3] == [
        "https://nyulangone.org/doctors",
        "https://www.va.gov/find-locations/",
        "https://medlineplus.gov/",
    ]
    assert len(data["urls"]) >= 3


def test_proof_endpoint_placeholder_and_rendered_md(tmp_path, monkeypatch):
    client = TestClient(main.app)
    monkeypatch.setattr(main, "RESULTS_MD", tmp_path / "missing.md")
    monkeypatch.setattr(main, "HELDOUT_MANIFEST", tmp_path / "missing_manifest.json")
    r1 = client.get("/api/proof")
    assert r1.status_code == 200
    assert r1.json()["ready"] is False
    assert "after the held-out run" in r1.json()["message"].lower()

    md_file = tmp_path / "results.md"
    md_file.write_text("# Results\n\n| System | Score |\n| --- | --- |\n| blindspot | 10/10 |\n", encoding="utf-8")
    monkeypatch.setattr(main, "RESULTS_MD", md_file)
    r2 = client.get("/api/proof")
    assert r2.status_code == 200
    assert r2.json()["ready"] is True
    assert "blindspot" in r2.json()["markdown"]
