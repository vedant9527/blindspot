"""Phase 1 spike: one Decisions API call on a real page screenshot.

Usage:  python scripts/spike_decisions.py --url https://www.medicare.gov/
        python scripts/spike_decisions.py --image path/to/screenshot.png

Prints the raw response and saves it to docs/decisions_response_example.json,
which Phase 3 uses to write the parser.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from blindspot.gemini import decide, image_block  # noqa: E402

QUESTIONS = {
    "page_state": {
        "type": "choice",
        "instructions": "What kind of page is shown in this screenshot?",
        "criteria": {
            "normal": "A normal, usable web page.",
            "bot_check": "A bot check or CAPTCHA, such as 'verify you are human'.",
            "login_wall": "A login or sign-in page blocking the content.",
            "error_page": "An error page, such as access denied or not found.",
            "cookie_banner": "A cookie or consent banner covering most of the page.",
        },
    },
    "has_visible_focus": {"type": "noul", "instructions": "Does any element on the page show a visible keyboard focus indicator, such as an outline or highlight ring?"},
    "has_cookie_banner": {"type": "noul", "instructions": "Is a cookie or consent banner visible?"},
    "has_main_navigation": {"type": "noul", "instructions": "Is a main navigation menu visible?"},
    "has_search_box": {"type": "noul", "instructions": "Is a search box visible?"},
    "has_sticky_header": {"type": "noul", "instructions": "Does the page appear to have a header or banner fixed to the top of the screen?"},
}


def screenshot(url: str) -> bytes:
    from playwright.sync_api import sync_playwright

    from blindspot.browser import launch_browser
    from blindspot.preflight import run_preflight

    with sync_playwright() as p:
        browser = launch_browser(p, headless=False)
        page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
        r = run_preflight(page, url)
        print(f"Preflight: {r.status} {r.reason} (focusable: {r.tabbable}, banner: {r.banner_action})")
        png = page.screenshot()
        browser.close()
    return png


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url")
    ap.add_argument("--image")
    args = ap.parse_args()
    if not args.url and not args.image:
        ap.error("give --url or --image")
    png = Path(args.image).read_bytes() if args.image else screenshot(args.url)

    inputs = [
        image_block(png),
        {"type": "text", "text": "This is a screenshot of a web page, taken by an accessibility testing agent."},
    ]
    resp, latency = decide(inputs, QUESTIONS)
    raw = resp.model_dump(mode="json") if hasattr(resp, "model_dump") else json.loads(json.dumps(resp, default=str))
    print(json.dumps(raw, indent=2))
    print(f"\nLatency: {latency:.3f}s for {len(QUESTIONS)} questions")

    out = ROOT / "docs" / "decisions_response_example.json"
    out.write_text(json.dumps({"latency_s": latency, "questions": QUESTIONS, "response": raw}, indent=2), encoding="utf-8")
    print(f"Saved to {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
