"""Check that each page in eval/pages_vetted.txt loads cleanly three times.

Usage:  python scripts/check_pages.py [--headless] [--file eval/pages_vetted.txt]

Writes eval/pages_check.json and eval/pages_ok.txt (pages that passed all three
loads). Use pages_ok.txt as the vetted list judges pick from.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from blindspot.browser import launch_browser  # noqa: E402
from blindspot.preflight import run_preflight  # noqa: E402


def read_urls(path: Path) -> list[str]:
    urls = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(ROOT / "eval" / "pages_vetted.txt"))
    ap.add_argument("--headless", action="store_true", help="Run without a visible window (more likely to be blocked)")
    ap.add_argument("--tries", type=int, default=3)
    args = ap.parse_args()

    urls = read_urls(Path(args.file))
    if not urls:
        print(f"No URLs in {args.file}. Add one public page per line.")
        return

    results = []
    with sync_playwright() as p:
        browser = launch_browser(p, headless=args.headless)
        for url in urls:
            outcomes = []
            for _ in range(args.tries):
                context = browser.new_context(viewport={"width": 1280, "height": 800})
                page = context.new_page()
                r = run_preflight(page, url)
                outcomes.append({"status": r.status, "reason": r.reason, "http": r.http_status,
                                 "tabbable": r.tabbable, "banner": r.banner_action})
                context.close()
            passed = all(o["status"] == "ok" for o in outcomes)
            reason = next((o["reason"] for o in outcomes if o["status"] != "ok"), "")
            print(f"{'OK     ' if passed else 'BLOCKED'}  {url}  {reason}  "
                  f"(focusable: {outcomes[-1]['tabbable']}, banner: {outcomes[-1]['banner']})")
            results.append({"url": url, "passed": passed, "reason": reason, "tries": outcomes})
        browser.close()

    (ROOT / "eval" / "pages_check.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    ok = [r["url"] for r in results if r["passed"]]
    (ROOT / "eval" / "pages_ok.txt").write_text("\n".join(ok) + ("\n" if ok else ""), encoding="utf-8")
    print(f"\n{len(ok)} of {len(results)} pages passed all {args.tries} loads. Saved to eval/pages_ok.txt")


if __name__ == "__main__":
    main()
