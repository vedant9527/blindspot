"""Phase 2 tests: each fixture triggers exactly its own proven check; clean.html triggers none."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright

from blindspot.browser import launch_browser
from blindspot.checks import contrast_ratio, normalize_label, pixel_stats, run_checks
from blindspot.preflight import dismiss_banner
from blindspot.runner import run_keyboard

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = launch_browser(p, headless=True)
        yield b
        b.close()


def run_fixture(browser, name: str, out_dir: Path) -> dict:
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.goto((FIXTURES / name).as_uri())
    run = run_keyboard(page, out_dir)
    context.close()
    return run


@pytest.mark.parametrize("fixture,expected", [
    ("clean.html", set()),
    ("trap.html", {"keyboard_trap"}),
    ("hidden_focus.html", {"focus_not_visible"}),
    ("covered.html", {"focus_obscured"}),
    ("tabindex.html", {"focus_order"}),
    ("label_mismatch.html", {"label_in_name"}),
])
def test_fixture_triggers_exactly_its_check(browser, tmp_path, fixture, expected):
    run = run_fixture(browser, fixture, tmp_path)
    proven = [r for r in run_checks(run) if r["proven"]]
    assert {r["check"] for r in proven} == expected, proven
    assert len(proven) == len(expected), "one proven finding per bug"


def test_clean_run_visits_every_element_and_stops_on_cycle(browser, tmp_path):
    run = run_fixture(browser, "clean.html", tmp_path)
    selectors = {s["selector"] for s in run["steps"] if s["selector"]}
    assert len(selectors) == 12
    assert run["stop_reason"] == "cycle"
    assert all(Path(s["full_screenshot"]).exists() for s in run["steps"])


def test_trap_stops_run_and_escape_fails(browser, tmp_path):
    run = run_fixture(browser, "trap.html", tmp_path)
    assert run["stop_reason"] == "trap_suspected"
    assert run["trap_test"]["shift_tab_escaped"] is False
    assert run["trap_test"]["escape_key_escaped"] is False
    assert run["trap_test"]["selectors"] == ["#trap"]


def test_findings_point_at_the_right_element(browser, tmp_path):
    hidden = run_checks(run_fixture(browser, "hidden_focus.html", tmp_path / "h"))
    assert any(r["proven"] and "telehealth" in r["evidence"]["visible_text"].lower() for r in hidden)
    label = run_checks(run_fixture(browser, "label_mismatch.html", tmp_path / "l"))
    hit = next(r for r in label if r["check"] == "label_in_name")
    assert hit["evidence"]["accessible_name"] == "Menu item"
    assert hit["evidence"]["label_text"] == "Search"


def _png(draw_box: bool) -> bytes:
    img = Image.new("RGB", (200, 100), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 40), "Button", fill="black")
    if draw_box:
        d.rectangle([40, 30, 160, 70], outline=(26, 95, 180), width=3)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def test_pixel_stats():
    rect = {"x": 45, "y": 35, "width": 110, "height": 30}
    same = pixel_stats(_png(False), _png(False), rect, 200)
    assert same["changed_px"] == 0 and same["changed_elsewhere"] == 0
    ring = pixel_stats(_png(True), _png(False), rect, 200)
    assert ring["changed_px"] > 100 and ring["contrast"] > 3
    assert pixel_stats(_png(True), _png(False), {"x": -500, "y": -500, "width": 10, "height": 10}, 200) is None


def test_helpers():
    assert normalize_label("  Log in! ") == normalize_label("Login")
    assert normalize_label("Cambiar a español") == "cambiaraespañol"
    assert round(contrast_ratio((0, 0, 0), (255, 255, 255)), 1) == 21.0


def test_late_popup_is_closed_and_page_is_tested(browser, tmp_path):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.goto((FIXTURES / "popup.html").as_uri())
    run = run_keyboard(page, tmp_path, dismiss_popup=dismiss_banner)
    context.close()

    assert len(run["popups"]) == 1, run["popups"]
    assert run["popups"][0]["action"] == "close"
    assert run["stop_reason"] == "cycle"
    page_selectors = {s["selector"] for s in run["steps"] if s["selector"] and not s.get("in_overlay")}
    assert len(page_selectors) == 12
    proven = [r for r in run_checks(run) if r["proven"]]
    assert proven == [], proven
