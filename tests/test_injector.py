"""Phase 4 tests: seeded bug injector and axe-core baseline on fixtures/clean.html."""

from __future__ import annotations

from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from blindspot.axe_runner import run_axe
from blindspot.browser import launch_browser
from blindspot.checks import run_checks
from blindspot.decide import decide_findings
from blindspot.injector import BUG_TO_CHECK, BUG_TYPES, inject, manifest_sha256, write_manifest
from blindspot.runner import run_keyboard

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"
CLEAN_URI = (FIXTURES / "clean.html").as_uri()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = launch_browser(p, headless=True)
        yield b
        b.close()


@pytest.mark.parametrize("bug_type", BUG_TYPES)
def test_injector_triggers_confirmed_finding_on_clean_html(browser, tmp_path, bug_type):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    page.goto(CLEAN_URI)

    manifest = inject(page, bug_type, seed=42)
    assert manifest["bug_type"] == bug_type
    assert manifest["seed"] == 42
    assert manifest["target_selector"]
    assert page.locator(f"[data-bs-target='{bug_type}']").count() == 1

    run = run_keyboard(page, tmp_path)
    axe_res = run_axe(page)
    context.close()

    checks = run_checks(run)
    dec = decide_findings(run, checks)
    confirmed_checks = {f["check"] for f in dec["confirmed"]}
    expected_check = BUG_TO_CHECK[bug_type]
    assert expected_check in confirmed_checks, f"{bug_type} not confirmed: {dec['confirmed']}"

    # Verify axe-core honesty per SPEC section 8:
    # axe catches positive_tabindex (tabindex) and label_mismatch (label-content-name-mismatch),
    # and misses hide_focus, keyboard_trap, and covering_banner by design.
    assert "error" not in axe_res, axe_res
    if bug_type in ("positive_tabindex", "label_mismatch"):
        assert bug_type in axe_res["mapped_bugs"], axe_res
    else:
        assert bug_type not in axe_res["mapped_bugs"], axe_res


def test_injector_random_and_seed_reproducibility(browser, tmp_path):
    manifests = []
    for _ in range(2):
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()
        page.goto(CLEAN_URI)
        manifests.append(inject(page, "random", seed=12345))
        context.close()

    assert manifests[0]["bug_type"] == manifests[1]["bug_type"]
    assert manifests[0]["target_selector"] == manifests[1]["target_selector"]

    m_path = tmp_path / "manifest.json"
    digest = write_manifest(manifests[0], m_path)
    assert len(digest) == 64
    assert digest == manifest_sha256(m_path)
