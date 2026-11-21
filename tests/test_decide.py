"""Phase 3 tests: Decisions API parser, decide.py rules, overlay gating, and SSE stream."""

from __future__ import annotations

import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from blindspot.decide import (
    decide_findings,
    decide_one,
    failing_probability,
    filter_checks_for_scoring,
    is_under_overlay,
)
from blindspot.gemini import make_boxed_crop, parse_decisions_response

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE_JSON = ROOT / "docs" / "decisions_response_example.json"
FIXTURES = ROOT / "fixtures"


def test_parse_decisions_response_from_saved_example():
    saved = json.loads(EXAMPLE_JSON.read_text(encoding="utf-8"))
    parsed = parse_decisions_response(saved["response"])

    assert parsed["usage"] == {
        "text_input_tokens": 443,
        "image_input_tokens": 1092,
        "total_input_tokens": 1535,
        "total_output_tokens": 0,
        "total_tokens": 1535,
    }
    ps = parsed["answers"]["page_state"]
    assert ps["type"] == "choice"
    assert ps["choice"] == "normal"
    assert ps["confidence"] == pytest.approx(0.9976, abs=1e-3)

    hvf = parsed["answers"]["has_visible_focus"]
    assert hvf["type"] == "noul"
    assert hvf["noul"] == pytest.approx(0.16878, abs=1e-4)
    assert hvf["p_false"] == pytest.approx(1.0 - 0.16878, abs=1e-4)


def test_failing_probability_orientation():
    # focus_visible: failing when False -> 1 - noul
    assert failing_probability("focus_visible", {"type": "noul", "noul": 0.10, "confidence": 0.90}) == 0.90
    # focus_covered: failing when True -> noul
    assert failing_probability("focus_covered", {"type": "noul", "noul": 0.85, "confidence": 0.85}) == 0.85
    # label_matches: failing when False -> 1 - noul
    assert failing_probability("label_matches", {"type": "noul", "noul": 0.05, "confidence": 0.95}) == 0.95
    # indicator_faint: failing when True -> noul
    assert failing_probability("indicator_faint", {"type": "noul", "noul": 0.20, "confidence": 0.80}) == 0.20


def test_decide_one_all_branches():
    # Proven by code -> always confirmed (unless replay fails)
    assert decide_one(proven=True, suspect=False, fail_p=None)[0] == "confirmed"
    assert decide_one(proven=True, suspect=False, fail_p=0.10)[0] == "confirmed"
    assert decide_one(proven=True, suspect=False, fail_p=0.95, replayed=False)[0] == "dropped"

    # Code suspect + high scorer (>= 0.80) -> confirmed
    assert decide_one(proven=False, suspect=True, fail_p=0.80)[0] == "confirmed"
    assert decide_one(proven=False, suspect=True, fail_p=0.93)[0] == "confirmed"

    # Code suspect + mid/low/missing scorer -> needs_human (never guess pass on a code flag)
    assert decide_one(proven=False, suspect=True, fail_p=0.65)[0] == "needs_human"
    assert decide_one(proven=False, suspect=True, fail_p=0.10)[0] == "needs_human"
    assert decide_one(proven=False, suspect=True, fail_p=None)[0] == "needs_human"

    # No code flag + scorer >= 0.80 -> needs_human (scorer alone never confirms)
    assert decide_one(proven=False, suspect=False, fail_p=0.92)[0] == "needs_human"
    # No code flag + scorer between 0.40 and 0.80 -> needs_human
    assert decide_one(proven=False, suspect=False, fail_p=0.55)[0] == "needs_human"
    # No code flag + scorer < 0.40 -> dropped
    assert decide_one(proven=False, suspect=False, fail_p=0.12)[0] == "dropped"


def test_overlay_suppresses_indicator_contrast_suspects():
    steps = {
        1: {"index": 1, "in_overlay": False, "obscured": {"sampled": 5, "covered": 3, "fixed_covers": 0}},
        2: {"index": 2, "in_overlay": False, "obscured": {"sampled": 5, "covered": 0, "fixed_covers": 0}},
    }
    assert is_under_overlay(steps[1]) is True
    assert is_under_overlay(steps[2]) is False
    checks = [
        {"check": "indicator_contrast", "wcag": "1.4.11", "proven": False, "suspect": True, "evidence": {"step": 1, "selector": "#a"}, "detail": "dimmed"},
        {"check": "indicator_contrast", "wcag": "1.4.11", "proven": False, "suspect": True, "evidence": {"step": 2, "selector": "#b"}, "detail": "faint"},
    ]
    kept = filter_checks_for_scoring(checks, steps)
    assert [c["evidence"]["selector"] for c in kept] == ["#b"]


def test_decide_findings_deduplicates_and_keeps_highest_evidence():
    # Two steps hit the same selector `#btn`: step 1 is needs_human (fail_p=0.55), step 2 has code suspect + fail_p=0.88 -> confirmed
    run = {
        "page": {"tabbable": 12, "positive_tabindex": []},
        "steps": [
            {
                "index": 1,
                "selector": "#btn",
                "tag": "button",
                "role": "button",
                "ax_ok": True,
                "accessible_name": "Book",
                "label_text": "Book",
                "rect": {"x": 20, "y": 20, "width": 80, "height": 32},
                "scroll_y": 0,
                "pixels": {"changed_px": 120, "changed_elsewhere": 0, "mean_diff": 8.0, "contrast": 5.0, "crop_px": 1000},
                "obscured": {"sampled": 5, "covered": 0, "fixed_covers": 0, "covering": []},
                "scores": {
                    "answers": {
                        "focus_visible": {"type": "noul", "noul": 0.45, "confidence": 0.55},  # fail_p = 0.55 -> needs_human
                        "focus_covered": {"type": "noul", "noul": 0.05, "confidence": 0.95},  # fail_p = 0.05 -> dropped
                    }
                },
            },
            {
                "index": 2,
                "selector": "#btn",
                "tag": "button",
                "role": "button",
                "ax_ok": True,
                "accessible_name": "Book",
                "label_text": "Book",
                "rect": {"x": 20, "y": 20, "width": 80, "height": 32},
                "scroll_y": 0,
                "pixels": {"changed_px": 40, "changed_elsewhere": 0, "mean_diff": 1.5, "contrast": 5.0, "crop_px": 1000},  # faint -> code suspect!
                "obscured": {"sampled": 5, "covered": 0, "fixed_covers": 0, "covering": []},
                "scores": {
                    "answers": {
                        "focus_visible": {"type": "noul", "noul": 0.10, "confidence": 0.90},  # fail_p = 0.90 + code suspect -> confirmed!
                        "focus_covered": {"type": "noul", "noul": 0.02, "confidence": 0.98},  # dropped
                    }
                },
            },
        ],
    }
    out = decide_findings(run)
    assert len(out["confirmed"]) == 1
    assert out["confirmed"][0]["check"] == "focus_not_visible"
    assert out["confirmed"][0]["evidence"]["step"] == 2
    assert out["needs_human"] == []
    assert len(out["dropped"]) == 2


def test_make_boxed_crop_draws_red_outline():
    from PIL import Image
    import io

    img = Image.new("RGB", (400, 300), "white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    crop, boxed_full = make_boxed_crop(buf.getvalue(), {"x": 100, "y": 80, "width": 60, "height": 30}, viewport_width=400)
    assert crop is not None and len(crop) > 100
    assert len(boxed_full) > 100


def test_api_run_and_sse_events_end_to_end(monkeypatch):
    import app.main as main_mod

    # Allow local fixture file:// URI in offline test while keeping production strict http/https
    assert main_mod._valid_url("file:///etc/passwd") is False
    monkeypatch.setattr(main_mod, "_valid_url", lambda u: u.startswith(("http://", "https://", "file://")))

    client = TestClient(app)
    resp = client.post(
        "/api/run",
        json={"url": (FIXTURES / "hidden_focus.html").as_uri(), "headless": True, "use_gemini": False},
    )
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    events: list[tuple[str, dict]] = []
    with client.stream("GET", f"/api/run/{run_id}/events") as sse:
        assert sse.status_code == 200
        ev_type = None
        for line in sse.iter_lines():
            if line.startswith("event: "):
                ev_type = line[len("event: "):]
            elif line.startswith("data: ") and ev_type:
                events.append((ev_type, json.loads(line[len("data: "):])))
                ev_type = None

    event_names = [e[0] for e in events]
    assert "preflight" in event_names
    assert "step" in event_names
    assert "finding" in event_names
    assert event_names[-1] == "done"
    findings = [payload for name, payload in events if name == "finding"]
    assert any(f["check"] == "focus_not_visible" and f["status"] == "confirmed" for f in findings)
