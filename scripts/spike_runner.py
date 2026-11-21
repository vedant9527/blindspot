"""Phase 1 spike: tab through a page in a visible browser and print what has focus.

Usage:  python scripts/spike_runner.py --url https://www.medicare.gov/ [--tabs 10]

No API key needed. Saves a screenshot per step to runs/spike/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from blindspot import config  # noqa: E402
from blindspot.browser import focus_info, launch_browser  # noqa: E402
from blindspot.preflight import run_preflight  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--tabs", type=int, default=10)
    args = ap.parse_args()

    out_dir = ROOT / "runs" / "spike"
    out_dir.mkdir(parents=True, exist_ok=True)
    steps = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=False)
        page = browser.new_context(viewport={"width": 1280, "height": 800}).new_page()
        r = run_preflight(page, args.url)
        print(f"Preflight: {r.status} {r.reason} (focusable: {r.tabbable}, banner: {r.banner_action})")
        if r.status != "ok":
            browser.close()
            return
        page.mouse.click(5, 5)  # put keyboard focus in the document
        for i in range(1, args.tabs + 1):
            page.keyboard.press("Tab")
            page.wait_for_timeout(config.STEP_WAIT_MS)
            info = focus_info(page)
            page.screenshot(path=str(out_dir / f"step_{i:02d}.png"))
            if info is None:
                print(f"{i:2d}. (focus on page body)")
                continue
            rect = info["rect"]
            print(f"{i:2d}. <{info['tag']}> role={info['role']!r} name={info['accessible_name']!r} "
                  f"visible={info['visible_text'][:40]!r} at ({rect['x']:.0f},{rect['y']:.0f}) {info['selector'][:60]}")
            steps.append({"index": i, **info})
        browser.close()
    (out_dir / "steps.json").write_text(json.dumps(steps, indent=2), encoding="utf-8")
    print(f"\nSaved {len(steps)} steps to runs/spike/steps.json")


if __name__ == "__main__":
    main()
